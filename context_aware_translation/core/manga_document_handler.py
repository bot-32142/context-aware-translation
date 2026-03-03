from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from context_aware_translation.core.cancellation import raise_if_cancelled
from context_aware_translation.core.context_manager import (
    _dedup_batch_terms,
    _select_final_exception,
)
from context_aware_translation.core.progress import ProgressCallback, ProgressUpdate, WorkflowStep
from context_aware_translation.core.translation_strategies import (
    ImageFetcher,
    MangaPageTranslationStrategy,
)

if TYPE_CHECKING:
    from context_aware_translation.core.context_manager import TranslationContextManager

logger = logging.getLogger(__name__)

# Very large token limit so each page's OCR text becomes exactly one chunk.
# Manga OCR text per page is typically a few hundred tokens at most.
# This constant prevents the semantic chunker from splitting a page into
# multiple chunks, which would break the chunk-to-source mapping.
_MANGA_CHUNK_TOKEN_LIMIT = 100_000


class MangaDocumentHandler:
    """DocumentTypeHandler for manga documents.

    Implements the three dispatch points that vary by document type:
    add_text, translate_chunks, and get_translated_lines.

    No inheritance from TranslationContextManager — all manga-specific
    logic is contained here and the shared manager is passed as a parameter.
    """

    def __init__(
        self,
        manga_page_translator: MangaPageTranslationStrategy,
        image_fetcher: ImageFetcher,
        concurrency: int = 5,
    ) -> None:
        self._manga_page_translator = manga_page_translator
        self._image_fetcher = image_fetcher
        self._concurrency = concurrency

    def add_text(
        self,
        text: str,
        max_token_size_per_chunk: int,  # noqa: ARG002
        document_id: int,
        manager: TranslationContextManager,
    ) -> int:
        """Split text by newline, create one chunk per non-empty page.

        Each page's OCR text becomes exactly one chunk via
        _MANGA_CHUNK_TOKEN_LIMIT.  No source mapping is stored here;
        the chunk-to-source mapping is derived at translation time.
        """
        page_texts = text.split("\n")
        last_chunk_id = 0
        for page_text in page_texts:
            if not page_text.strip():
                continue
            last_chunk_id = manager.add_text(
                page_text,
                max_token_size_per_chunk=_MANGA_CHUNK_TOKEN_LIMIT,
                document_id=document_id,
            )
        return last_chunk_id

    async def translate_chunks(
        self,
        document_ids: list[int],
        manager: TranslationContextManager,
        force: bool = False,
        source_ids: list[int] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        """Translate manga pages using vision LLM.

        For each document:
        1. Get ALL chunks (sorted by chunk_id) to derive positional mapping
        2. Get source_ids with non-empty OCR text via image_fetcher
        3. Positionally zip chunks ↔ source_ids
        4. Filter to untranslated, send one page per translation call
        """
        raise_if_cancelled(cancel_check)
        source_language = manager.term_repo.get_source_language()
        if not source_language:
            raise ValueError("Source language not found")

        all_terms = [t for t in manager.term_repo.list_keyed_context() if not t.ignored]

        for doc_id in document_ids:
            raise_if_cancelled(cancel_check)
            # All chunks for this document, sorted by chunk_id
            all_chunks = sorted(
                manager.term_repo.list_chunks(document_id=doc_id),
                key=lambda c: c.chunk_id,
            )
            if not all_chunks:
                continue

            # Source IDs with non-empty OCR text, matching add_text() filtering
            doc_source_ids = self._image_fetcher.list_page_source_ids(doc_id)
            if len(doc_source_ids) != len(all_chunks):
                raise ValueError(
                    f"Manga source/chunk alignment mismatch for document {doc_id}: "
                    f"{len(doc_source_ids)} non-empty OCR pages vs {len(all_chunks)} chunks. "
                    "Rebuild glossary after OCR edits."
                )

            # Derive positional mapping: chunk_to_source using chunk_id as key
            chunk_to_source: dict[int, int] = {}
            for chunk, sid in zip(all_chunks, doc_source_ids, strict=True):
                chunk_to_source[chunk.chunk_id] = sid

            # Filter to untranslated chunks that have source mappings
            untranslated = sorted(
                [
                    c
                    for c in manager.term_repo.get_chunks_to_translate([doc_id], force=force)
                    if c.chunk_id in chunk_to_source
                ],
                key=lambda c: c.chunk_id,
            )
            if source_ids is not None:
                source_id_set = {int(source_id) for source_id in source_ids}
                untranslated = [c for c in untranslated if chunk_to_source.get(c.chunk_id) in source_id_set]
            if not untranslated:
                continue

            # Send one page per LLM call to avoid multi-page response coupling.
            batches = [[chunk] for chunk in untranslated]

            total_batches = len(batches)
            completed = 0
            progress_lock = asyncio.Lock()
            failure_order: list[BaseException] = []
            failure_lock = asyncio.Lock()

            semaphore = asyncio.Semaphore(self._concurrency)

            async def process_batch(
                batch: list,
                _chunk_to_source: dict[int, int] = chunk_to_source,
                _semaphore: asyncio.Semaphore = semaphore,
                _total_batches: int = total_batches,
                _progress_lock: asyncio.Lock = progress_lock,
                _failure_lock: asyncio.Lock = failure_lock,
                _failure_order: list[BaseException] = failure_order,
            ) -> None:
                try:
                    raise_if_cancelled(cancel_check)
                    async with _semaphore:
                        raise_if_cancelled(cancel_check)
                        # Fetch images
                        page_images = []
                        extracted_texts = []
                        for chunk in batch:
                            source_id = _chunk_to_source[chunk.chunk_id]
                            image_bytes, mime_type = self._image_fetcher.fetch_source_image(source_id)
                            page_images.append((image_bytes, mime_type))
                            extracted_texts.append(self._image_fetcher.fetch_source_ocr_text(source_id))

                        # Collect relevant terms
                        batch_texts = [chunk.text for chunk in batch]
                        max_chunk_id = max(c.chunk_id for c in batch)
                        batch_terms = _dedup_batch_terms(
                            [
                                (
                                    t.key,
                                    t.translated_name or "",
                                    manager.get_term_description_for_query(t, max_chunk_id),
                                )
                                for t in all_terms
                                if any(t.key in text for text in batch_texts)
                            ]
                        )

                        # Call vision translator
                        translations = await self._manga_page_translator.translate(
                            page_images,
                            batch_terms,
                            source_language,
                            extracted_texts=extracted_texts,
                        )

                        # Store translations (persist before cancel check to avoid losing work)
                        for chunk, translation in zip(batch, translations, strict=True):
                            chunk.translation = translation
                            chunk.is_translated = True
                        manager._state_update([], batch)
                        raise_if_cancelled(cancel_check)

                        nonlocal completed
                        async with _progress_lock:
                            completed += 1
                            if progress_callback:
                                progress_callback(
                                    ProgressUpdate(
                                        step=WorkflowStep.TRANSLATE_CHUNKS,
                                        current=completed,
                                        total=_total_batches,
                                        message=f"Translating manga batch {completed}/{_total_batches}",
                                    )
                                )
                except BaseException as exc:
                    async with _failure_lock:
                        _failure_order.append(exc)
                    raise

            results = await asyncio.gather(*[process_batch(b) for b in batches], return_exceptions=True)
            raise_if_cancelled(cancel_check)
            exceptions = [e for e in results if isinstance(e, BaseException)]
            if exceptions:
                for e in exceptions:
                    logger.error("Error translating manga batch for document %s: %s", doc_id, e, exc_info=True)
                raise _select_final_exception(exceptions, failure_order=failure_order)

    def get_translated_lines(
        self,
        document_id: int,
        manager: TranslationContextManager,
    ) -> list[str]:
        """Return per-chunk translations as a list (one entry per chunk).

        Preserves multi-line dialogue per page, unlike the base manager's
        export() which concatenates and then splits by newline.
        """
        chunks = manager.term_repo.list_chunks(document_id=document_id)
        if not chunks:
            raise ValueError("No chunks found in the database")

        sorted_chunks = sorted(chunks, key=lambda c: c.chunk_id)

        untranslated = [c for c in sorted_chunks if not c.is_translated or c.translation is None]
        if untranslated:
            untranslated_ids = [c.chunk_id for c in untranslated]
            raise ValueError(f"Cannot export: chunks {untranslated_ids} are not translated yet")

        return [c.translation for c in sorted_chunks if c.translation is not None]
