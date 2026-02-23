from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from transformers import PreTrainedTokenizer

from context_aware_translation.core.cancellation import raise_if_cancelled
from context_aware_translation.core.context_extractor import ContextExtractor
from context_aware_translation.core.context_tree import ContextTree
from context_aware_translation.core.models import KeyedContext, Term
from context_aware_translation.core.progress import ProgressCallback, ProgressUpdate, WorkflowStep
from context_aware_translation.core.translation_strategies import (
    ChunkTranslationStrategy,
    DocumentTypeHandler,
    GlossaryTranslationStrategy,
    SourceLanguageDetector,
    TermReviewer,
)
from context_aware_translation.storage.book_db import (
    ChunkRecord,
    TermRecord,
    TranslationChunkRecord,
)
from context_aware_translation.storage.term_repository import (
    BatchUpdate,
    TermRepository,
)
from context_aware_translation.utils.cjk_normalize import normalize_for_matching
from context_aware_translation.utils.hashing import compute_chunk_hash
from context_aware_translation.utils.semantic_chunker import (
    line_batched_semantic_chunker,
)
from context_aware_translation.utils.string_similarity import string_similarity
from context_aware_translation.utils.symbol_check import symbol_only

logger = logging.getLogger(__name__)


def _dedup_batch_terms(
    terms: list[tuple[str, str, str]],
) -> list[tuple[str, str, str]]:
    """Remove duplicate batch terms that share the same normalized key and translation.

    When two terms have the same ``normalize_for_matching(key)`` **and** the same
    translated name, keep the shorter one (by ``len(key) + len(description)``).
    """
    seen: dict[tuple[str, str], int] = {}
    for idx, (key, translated_name, description) in enumerate(terms):
        dedup_key = (normalize_for_matching(key), translated_name)
        if dedup_key in seen:
            prev_idx = seen[dedup_key]
            prev_key, _, prev_desc = terms[prev_idx]
            if len(key) + len(description) < len(prev_key) + len(prev_desc):
                seen[dedup_key] = idx
        else:
            seen[dedup_key] = idx
    kept = set(seen.values())
    return [t for i, t in enumerate(terms) if i in kept]


def _select_final_exception(
    exceptions: Sequence[BaseException],
    *,
    failure_order: Sequence[BaseException] | None = None,
) -> BaseException:
    """Return the latest observed task failure for concurrent workers."""
    if not exceptions:
        raise ValueError("exceptions cannot be empty")
    if failure_order:
        return failure_order[-1]
    return exceptions[-1]


class _TermLike(Protocol):
    """Protocol for term-like objects with key and votes attributes."""

    key: str
    votes: int


_TL = TypeVar("_TL", bound=_TermLike)


@dataclass(frozen=True)
class ChunkTranslationInputs:
    source_language: str
    all_terms: list[Term]
    batches: list[list[TranslationChunkRecord]]


class ContextManager:
    def __init__(
        self,
        context_extractor: ContextExtractor,
        term_repo: TermRepository,
        context_tree: ContextTree,
        tokenizer: PreTrainedTokenizer,
    ) -> None:
        # Initialize storage manager
        self.term_repo: TermRepository = term_repo
        self.tokenizer = tokenizer
        self.context_extractor = context_extractor
        # Lock for thread-safe merge operations
        self._merge_lock = threading.Lock()
        self.context_tree = context_tree

    def close(self) -> None:
        """
        Close all services. Should only be called during application shutdown.
        """
        if hasattr(self.context_tree, "close"):
            self.context_tree.close()
        if hasattr(self.term_repo, "close"):
            self.term_repo.close()

    def add_text(
        self,
        text: str,
        max_token_size_per_chunk: int = 1000,
        document_id: int | None = None,
    ) -> int:
        chunk_generator = line_batched_semantic_chunker(
            text,
            self.tokenizer,
            chunk_size=max_token_size_per_chunk,
        )
        chunk_records = []
        chunk_id = self.term_repo.get_next_chunk_id()
        for chunk_text, _, _ in chunk_generator:
            chunk_records.append(
                ChunkRecord(
                    chunk_id=chunk_id,
                    hash=compute_chunk_hash(chunk_text, document_id=document_id),
                    text=chunk_text,
                    document_id=document_id,
                    is_extracted=False,
                    is_summarized=False,
                )
            )
            chunk_id += 1
        new_chunk_records = [
            chunk_record for chunk_record in chunk_records if not self.term_repo.chunk_exists_by_hash(chunk_record.hash)
        ]
        if new_chunk_records:
            self._state_update([], new_chunk_records)
        return chunk_id - 1

    def build_context_tree(self, cancel_check: Callable[[], bool] | None = None) -> None:
        """
        Build context tree from chunks that are not summarized yet.
        Context tree is shared across all documents.
        """
        terms_data = {
            term.key: {
                idx: description
                for chunk_id, description in term.descriptions.items()
                if (idx := self._description_index(chunk_id)) is not None
            }
            for term in self.term_repo.list_keyed_context()
            if not term.ignored and term.descriptions
        }
        terms_data = {k: v for k, v in terms_data.items() if v}
        if terms_data:
            self.context_tree.add_chunks(terms_data, cancel_check=cancel_check)

    @staticmethod
    def _description_index(key: object) -> int | None:
        if key == "imported":
            return -1
        if isinstance(key, int):
            return key
        raw = str(key).strip()
        if raw == "imported":
            return -1
        if raw.lstrip("-").isdigit():
            return int(raw)
        return None

    @classmethod
    def _description_query_index(cls, descriptions: dict[str, str]) -> int:
        numeric_keys = [idx for key in descriptions if (idx := cls._description_index(key)) is not None]
        if not numeric_keys:
            return 0
        return max(numeric_keys) + 1

    @classmethod
    def _ordered_description_values(cls, descriptions: dict[str, str]) -> list[str]:
        def _sort_key(raw_key: object) -> tuple[int, int | str]:
            idx = cls._description_index(raw_key)
            if idx is None:
                return (2, str(raw_key))
            if idx == -1:
                return (0, -1)
            return (1, idx)

        values: list[str] = []
        for key in sorted(descriptions.keys(), key=_sort_key):
            value = descriptions[key]
            if value and value.strip():
                values.append(value)
        return values

    @classmethod
    def _first_description_value(cls, descriptions: dict[str, str]) -> str:
        values = cls._ordered_description_values(descriptions)
        return values[0] if values else ""

    def _build_export_description_for_term(
        self,
        term: Term,
        *,
        skip_context: bool,
        cancel_check: Callable[[], bool] | None,
    ) -> str:
        if not term.descriptions:
            return ""

        description_values = self._ordered_description_values(term.descriptions)
        if not description_values:
            return ""
        if skip_context:
            return description_values[0]
        if term.ignored:
            return " ".join(description_values).strip()

        query_index = self._description_query_index(term.descriptions)
        summary = self.context_tree.summarize_term_fully(term.key, query_index, cancel_check=cancel_check)
        if summary.strip():
            return summary

        raise ValueError(
            f"Failed to summarize glossary term '{term.key}' for export. "
            "All non-ignored terms must have a context-tree summary when skip_context=False."
        )

    @staticmethod
    def _export_term_progress_message(*, skip_context: bool, current: int, total: int) -> str:
        if skip_context:
            return f"Collecting glossary term {current}/{total}"
        return f"Summarizing glossary term {current}/{total}"

    def build_fully_summarized_descriptions(
        self,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
        skip_context: bool = False,
    ) -> dict[str, str]:
        """Build one export description for every glossary term.

        When ``skip_context`` is False, descriptions are fully summarized via
        context-tree nodes (persisted for future reuse). When True, export uses
        only each term's earliest description without context summarization.
        """
        if not skip_context:
            self.build_context_tree(cancel_check=cancel_check)
        terms = self.term_repo.list_keyed_context()
        progress_total = max(1, len(terms))
        if progress_callback:
            progress_callback(
                ProgressUpdate(
                    step=WorkflowStep.EXPORT,
                    current=0,
                    total=progress_total,
                    message="Preparing glossary export...",
                )
            )

        summaries: dict[str, str] = {}
        for idx, term in enumerate(terms, start=1):
            raise_if_cancelled(cancel_check)
            summaries[term.key] = self._build_export_description_for_term(
                term,
                skip_context=skip_context,
                cancel_check=cancel_check,
            )

            if progress_callback:
                progress_callback(
                    ProgressUpdate(
                        step=WorkflowStep.EXPORT,
                        current=idx,
                        total=progress_total,
                        message=self._export_term_progress_message(
                            skip_context=skip_context,
                            current=idx,
                            total=progress_total,
                        ),
                    )
                )
        return summaries

    def get_term_description_for_query(self, term: Term, query_index: int, *, skip_context: bool = False) -> str:
        """Return the term description text used for chunk translation prompts."""
        if skip_context:
            return self._first_description_value(term.descriptions)
        return "\n".join(self.context_tree.get_context(term.key, query_index))

    async def extract_keyed_context(
        self,
        concurrency: int = 20,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        """
        Extract keyed context from chunks that are not extracted yet, and save to DB.
        """
        raise_if_cancelled(cancel_check)
        chunk_records = self.term_repo.get_chunks_to_extract()
        if not chunk_records:
            return

        source_language = self.term_repo.get_source_language()
        if not source_language:
            raise ValueError("Source language not found in the database")

        # Use semaphore to limit concurrent processing
        semaphore = asyncio.Semaphore(concurrency)
        total = len(chunk_records)
        completed = 0
        progress_lock = asyncio.Lock()
        failure_order: list[BaseException] = []
        failure_lock = asyncio.Lock()

        async def process_chunk(chunk_record: ChunkRecord) -> None:
            nonlocal completed
            try:
                raise_if_cancelled(cancel_check)
                async with semaphore:
                    raise_if_cancelled(cancel_check)
                    # Extract keyed context from chunk
                    extracted_keyed_context = await self.context_extractor.extract_keyed_context(
                        chunk_record, source_language
                    )
                    # Mark chunk as extracted
                    chunk_record.is_extracted = True
                    # Update storage: merge and write atomically (thread-safe)
                    self._state_update(extracted_keyed_context, [chunk_record])
                    raise_if_cancelled(cancel_check)

                    # Update progress after work completes
                    async with progress_lock:
                        completed += 1
                        if progress_callback:
                            progress_callback(
                                ProgressUpdate(
                                    step=WorkflowStep.EXTRACT_TERMS,
                                    current=completed,
                                    total=total,
                                    message=f"Extracting terms from chunk {completed}/{total}",
                                )
                            )
            except BaseException as exc:
                async with failure_lock:
                    failure_order.append(exc)
                raise

        # Process all chunks concurrently
        results = await asyncio.gather(
            *[process_chunk(chunk_record) for chunk_record in chunk_records],
            return_exceptions=True,
        )
        raise_if_cancelled(cancel_check)
        exceptions = [e for e in results if isinstance(e, BaseException)]
        if exceptions:
            for e in exceptions:
                logger.error("Error extracting keyed context: %s", e, exc_info=True)
            raise _select_final_exception(exceptions, failure_order=failure_order)

    def _state_update(
        self,
        extracted_keyed_context: Sequence[KeyedContext],
        chunk_records: Sequence[ChunkRecord],
    ) -> None:
        keyed_contexts: list[Term] = []

        with self._merge_lock:
            for keyed_context in extracted_keyed_context:
                key = keyed_context.get_key()
                existing_keyed_context = self.term_repo.get_keyed_context(key)

                if existing_keyed_context:
                    existing_keyed_context.merge(keyed_context)
                    if isinstance(existing_keyed_context, Term):
                        keyed_contexts.append(existing_keyed_context)
                else:
                    if isinstance(keyed_context, Term):
                        keyed_contexts.append(keyed_context)

            update = BatchUpdate(
                keyed_context=keyed_contexts,
                chunk_records=chunk_records,
            )

            self.term_repo.apply_batch(update)


class TranslationContextManager(ContextManager):
    """
    A specialized ContextManager for translation workflows.

    This class extends ContextManager and provides translation-specific
    functionality while maintaining all the base context management capabilities.
    """

    def __init__(
        self,
        term_repo: TermRepository,
        context_tree: ContextTree,
        context_extractor: ContextExtractor,
        tokenizer: PreTrainedTokenizer,
        *,
        source_language_detector: SourceLanguageDetector,
        glossary_translator: GlossaryTranslationStrategy,
        chunk_translator: ChunkTranslationStrategy,
        term_reviewer: TermReviewer | None = None,
    ) -> None:
        """
        Initialize the TranslationContextManager.

        Args:
            storage_manager: The storage manager for persisting terms and chunks
            context_tree: The context tree for managing context
            context_extractor: The context extractor for extracting terms from chunks
            tokenizer: Tokenizer for text processing
        """
        self.term_repo = term_repo
        self.source_language_detector: SourceLanguageDetector = source_language_detector
        self.glossary_translator: GlossaryTranslationStrategy = glossary_translator
        self.chunk_translator: ChunkTranslationStrategy = chunk_translator
        self.term_reviewer: TermReviewer | None = term_reviewer
        super().__init__(context_extractor, self.term_repo, context_tree, tokenizer)

    async def detect_language(self, cancel_check: Callable[[], bool] | None = None) -> None:
        """
        Detect language of the text.

        Samples text from multiple chunks spread across the corpus to avoid
        misdetection when the first chunk is atypical (e.g. a title page
        in a different language).
        """
        source_language = self.term_repo.get_source_language()
        if not source_language:
            chunks = self.term_repo.list_chunks()
            if not chunks:
                raise ValueError(
                    "No text chunks found. Run 'import' to import files, "
                    "then 'build_glossary' will process text and perform OCR."
                )

            # Sample from up to 5 evenly-spaced chunks for a representative sample
            num_samples = min(5, len(chunks))
            step = max(1, len(chunks) // num_samples)
            samples: list[str] = []
            for i in range(0, len(chunks), step):
                if chunks[i].text:
                    samples.append(chunks[i].text)
                if len(samples) >= num_samples:
                    break

            sample_text = "\n".join(samples)
            if not sample_text:
                raise Exception("Please import text first. No text found.")
            source_language = await self.source_language_detector.detect(sample_text, cancel_check=cancel_check)
            self.term_repo.set_source_language(source_language)

    async def build_occurrence_mapping(self, cancel_check: Callable[[], bool] | None = None) -> None:
        """Build occurrence mapping for terms by counting occurrences in chunks.

        Uses pre-computed normalized_text from the database when available,
        falling back to on-the-fly normalization for legacy chunks.
        """
        raise_if_cancelled(cancel_check)
        relevant_chunks = self.term_repo.get_chunks_to_map_occurrence()
        if not relevant_chunks:
            return

        normalized_texts: dict[str, str] = {str(c.chunk_id): c.normalized_text for c in relevant_chunks}

        occurrence_updates: list[Term] = []
        for keyed_context in self.term_repo.list_keyed_context():
            raise_if_cancelled(cancel_check)
            normalized_key = normalize_for_matching(keyed_context.key)
            occurrence_dict = {
                str(c.chunk_id): count
                for c in relevant_chunks
                if (count := normalized_texts[str(c.chunk_id)].count(normalized_key)) > 0
            }
            if occurrence_dict:
                occurrence_updates.append(
                    Term(
                        key=keyed_context.key,
                        descriptions={},
                        occurrence=occurrence_dict,
                        votes=0,
                        total_api_calls=0,
                    )
                )

        for chunk in relevant_chunks:
            chunk.is_occurrence_mapped = True
        self._state_update(occurrence_updates, relevant_chunks)

    async def build_occruance_mapping(self) -> None:
        """Backward-compatible alias for build_occurrence_mapping()."""
        await self.build_occurrence_mapping()

    async def mark_noise_terms(self, cancel_check: Callable[[], bool] | None = None) -> int:
        """
        Auto-mark obvious noise terms as ignored and reviewed before LLM review.

        Current deterministic rules:
        - Symbol-only term key.
        - Term extracted from chunk text (description key is a chunk id) but has
          zero exact occurrence matches after occurrence mapping.

        Returns:
            Number of terms auto-marked as ignored+reviewed.
        """
        raise_if_cancelled(cancel_check)
        required_methods = (
            "get_last_noise_filtered_at",
            "list_term_records",
            "update_terms_bulk",
            "set_last_noise_filtered_at",
        )
        if not all(hasattr(self.term_repo, name) for name in required_methods):
            # Backward-compatibility for lightweight test/mocks that only implement
            # the minimal review API.
            return 0

        last_checkpoint = self.term_repo.get_last_noise_filtered_at()

        def _is_chunk_id_key(raw_key: object) -> bool:
            return str(raw_key).lstrip("-").isdigit()

        def _is_noise_record(record: TermRecord) -> bool:
            if symbol_only(record.key):
                return True
            has_extracted_description = any(_is_chunk_id_key(k) for k in record.descriptions)
            has_no_exact_occurrence = len(record.occurrence) == 0
            return has_extracted_description and has_no_exact_occurrence

        all_records = self.term_repo.list_term_records()
        records_to_check = [
            record
            for record in all_records
            if not record.is_reviewed
            and not record.ignored
            and (last_checkpoint is None or (record.created_at is not None and record.created_at > last_checkpoint))
        ]
        if not records_to_check:
            return 0

        max_created_at = last_checkpoint or 0.0
        keys_to_mark: list[str] = []
        for record in records_to_check:
            raise_if_cancelled(cancel_check)
            if _is_noise_record(record):
                keys_to_mark.append(record.key)
            if record.created_at:
                max_created_at = max(max_created_at, record.created_at)

        if keys_to_mark:
            self.term_repo.update_terms_bulk(keys_to_mark, ignored=True, is_reviewed=True)

        if max_created_at > (last_checkpoint or 0.0):
            self.term_repo.set_last_noise_filtered_at(max_created_at)

        raise_if_cancelled(cancel_check)
        return len(keys_to_mark)

    async def review_terms(
        self,
        concurrency: int = 5,
        batch_size: int = 20,
        similarity_threshold: float = 0.7,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        """
        Review terms using LLM to filter out noise/hallucinations.
        Only reviews terms that have not been reviewed yet.
        """
        term_reviewer = self.term_reviewer
        if term_reviewer is None:
            raise ValueError("Term reviewer is not configured; provide term_reviewer to TranslationContextManager.")

        raise_if_cancelled(cancel_check)
        auto_marked_count = await self.mark_noise_terms(cancel_check=cancel_check)
        if auto_marked_count > 0:
            logger.info("Auto-marked %s obvious noise term(s) as ignored+reviewed.", auto_marked_count)

        # Get pending review terms
        pending_terms = self.term_repo.get_terms_pending_review()
        if not pending_terms:
            logger.info("No terms pending review.")
            return

        # Skip terms that are already ignored by heuristics?
        # Use case: We might want LLM to double check, or trust heuristics.
        # Plan says: "Review everything not yet reviewed to catch false positives/negatives."
        # But heuristic "ignored" terms are also "unreviewed".
        # Let's filter out terms that are already ignored to save cost, OR include them to see if LLM saves them.
        # The prompt says "identify which should be kept ... and which should be ignored".
        # If we send ignored terms, LLM might say "Keep".
        # Let's send ALL unreviewed terms.

        logger.info(f"Reviewing {len(pending_terms)} terms...")

        source_language = self.term_repo.get_source_language()
        if not source_language:
            raise ValueError("Source language not found in the database")

        semaphore = asyncio.Semaphore(concurrency)

        # Group similar terms into connected components using union-find,
        # then batch using nearest-neighbor clustering (same approach as translate_terms)
        components, sim_cache = self._group_by_similarity(pending_terms, similarity_threshold)
        batches: list[list[TermRecord]] = []
        small_components: list[list[TermRecord]] = []
        for component in components:
            if len(component) <= batch_size:
                small_components.append(component)
            else:
                sub_batches = self._greedy_nearest_neighbor_split(component, batch_size, sim_cache)
                batches.extend(sub_batches)
        batches.extend(self._bin_pack_components(small_components, batch_size))
        total = len(batches)
        completed = 0
        progress_lock = asyncio.Lock()
        failure_order: list[BaseException] = []
        failure_lock = asyncio.Lock()

        async def process_batch(batch: list[TermRecord]) -> None:
            nonlocal completed
            try:
                raise_if_cancelled(cancel_check)
                async with semaphore:
                    raise_if_cancelled(cancel_check)
                    result = await term_reviewer.review_batch(
                        batch,
                        source_language,
                        cancel_check=cancel_check,
                    )

                    # Prepare updates
                    ignore_set = set(result["ignore"])

                    term_records_to_update = []
                    for term_record in batch:
                        # Determine new state
                        should_ignore = term_record.key in ignore_set

                        # Update record
                        term_record.ignored = should_ignore
                        term_record.is_reviewed = True
                        term_records_to_update.append(term_record)

                    self.term_repo.upsert_terms(term_records_to_update)
                    raise_if_cancelled(cancel_check)

                    # Update progress after work completes
                    async with progress_lock:
                        completed += 1
                        if progress_callback:
                            progress_callback(
                                ProgressUpdate(
                                    step=WorkflowStep.REVIEW,
                                    current=completed,
                                    total=total,
                                    message=f"Reviewing batch {completed}/{total}",
                                )
                            )
            except BaseException as exc:
                async with failure_lock:
                    failure_order.append(exc)
                raise

        results = await asyncio.gather(*[process_batch(b) for b in batches], return_exceptions=True)
        raise_if_cancelled(cancel_check)
        exceptions = [e for e in results if isinstance(e, BaseException)]
        if exceptions:
            for e in exceptions:
                logger.error("Error reviewing batch: %s", e, exc_info=True)
            raise _select_final_exception(exceptions, failure_order=failure_order)
        logger.info("Term review completed.")

    @staticmethod
    def _get_primary_description(term: Term) -> str:
        """Get the earliest description for a term by smallest chunk_id key."""
        if not term.descriptions:
            raise ValueError(f"Term {term.key} has no descriptions")

        def _to_int_key(key: str) -> int:
            if key == "imported":
                return -1
            try:
                return int(key)
            except (TypeError, ValueError):
                return 0

        min_chunk_id_key = min(term.descriptions.keys(), key=_to_int_key)
        return term.descriptions[min_chunk_id_key]  # type: ignore[no-any-return]

    @staticmethod
    def _partition_component_terms(component: list[Term]) -> tuple[dict[str, str], list[dict[str, str]]]:
        """Split component terms into translated refs and untranslated payload."""
        translated_names: dict[str, str] = {}
        to_translate: list[dict[str, str]] = []
        for term in component:
            if term.translated_name:
                translated_names[term.key] = term.translated_name
                continue
            to_translate.append(
                {
                    "canonical_name": term.key,
                    "description": TranslationContextManager._get_primary_description(term),
                    "missing_names": term.key,
                }
            )
        return translated_names, to_translate

    @staticmethod
    def _collect_similar_terms(
        to_translate: list[dict[str, str]],
        translated_names: dict[str, str],
    ) -> dict[str, str]:
        """Collect top similar translated terms for each term to translate."""
        similar_terms: dict[str, str] = {}
        for item in to_translate:
            if not item.get("missing_names"):
                continue
            top_3 = sorted(
                [
                    (
                        string_similarity(item["canonical_name"], name),
                        name,
                    )
                    for name in translated_names
                ],
                key=lambda x: x[0],
                reverse=True,
            )[:3]
            similar_terms.update({name: translated_names[name] for _, name in top_3})
        return similar_terms

    @staticmethod
    def _build_translation_updates(translations: dict[str, str]) -> list[Term]:
        return [
            Term(
                key=k,
                descriptions={},
                occurrence={},
                votes=0,
                total_api_calls=0,
                translated_name=v,
            )
            for k, v in translations.items()
        ]

    @staticmethod
    def _greedy_nearest_neighbor_split(
        terms: list[_TL],
        max_batch_size: int,
        sim_cache: dict[tuple[str, str], float] | None = None,
    ) -> list[list[_TL]]:
        """Split terms into sub-batches using greedy nearest-neighbor clustering.

        Seeds each batch with the highest-vote remaining term, then greedily adds
        the most similar remaining term until the batch is full.  O(n²) which is
        acceptable for typical component sizes (hundreds of terms).

        Args:
            sim_cache: Optional pre-computed similarity cache mapping
                       (key_a, key_b) → similarity. Keys are stored with
                       key_a < key_b. Falls back to computing on the fly
                       for missing pairs.
        """
        if not terms:
            return []

        def _get_sim(a: str, b: str) -> float:
            if sim_cache is not None:
                pair = (a, b) if a < b else (b, a)
                cached = sim_cache.get(pair)
                if cached is not None:
                    return cached
            return string_similarity(a, b)

        remaining_indices: set[int] = set(range(len(terms)))
        batches: list[list[_TL]] = []

        while remaining_indices:
            # Seed: pick the term with the highest votes (importance first)
            seed_idx = max(remaining_indices, key=lambda i: terms[i].votes)
            remaining_indices.discard(seed_idx)
            batch_indices: list[int] = [seed_idx]

            while len(batch_indices) < max_batch_size and remaining_indices:
                best_idx = -1
                best_sim = -1.0
                for candidate in remaining_indices:
                    for member in batch_indices:
                        sim = _get_sim(terms[candidate].key, terms[member].key)
                        if sim > best_sim:
                            best_sim = sim
                            best_idx = candidate
                if best_idx < 0:
                    break
                remaining_indices.discard(best_idx)
                batch_indices.append(best_idx)

            batches.append([terms[i] for i in batch_indices])

        return batches

    @staticmethod
    def _group_by_similarity(
        terms: list[_TL],
        similarity_threshold: float,
    ) -> tuple[list[list[_TL]], dict[tuple[str, str], float]]:
        """Group terms into connected components by string similarity.

        Uses union-find to cluster terms whose keys have string similarity
        at or above the threshold.

        Returns:
            A tuple of (components, sim_cache) where sim_cache maps
            canonical (key_a, key_b) pairs (key_a < key_b) to their
            similarity score for reuse in downstream batching.
        """
        if not terms:
            return [], {}

        parent: dict[str, str] = {}
        rank: dict[str, int] = {}
        sim_cache: dict[tuple[str, str], float] = {}

        def find(x: str) -> str:
            if x not in parent:
                parent[x] = x
                rank[x] = 0
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x: str, y: str) -> None:
            px, py = find(x), find(y)
            if px == py:
                return
            if rank[px] < rank[py]:
                parent[px] = py
            elif rank[px] > rank[py]:
                parent[py] = px
            else:
                parent[py] = px
                rank[px] += 1

        for i, term in enumerate(terms):
            for other in terms[i + 1 :]:
                sim = string_similarity(term.key, other.key)
                pair = (term.key, other.key) if term.key < other.key else (other.key, term.key)
                sim_cache[pair] = sim
                if sim >= similarity_threshold:
                    union(term.key, other.key)

        components: dict[str, list[_TL]] = {}
        for term in terms:
            root = find(term.key)
            if root not in components:
                components[root] = []
            components[root].append(term)

        return list(components.values()), sim_cache

    @staticmethod
    def _bin_pack_components(
        components: list[list[_TL]],
        max_batch_size: int,
    ) -> list[list[_TL]]:
        """Bin-pack components into batches without splitting any component.

        Uses first-fit-decreasing: sorts components by size descending,
        assigns each to the first batch with room.
        Returns a flat list of batches (components in the same batch are concatenated).
        """
        if not components:
            return []

        sorted_components = sorted(components, key=len, reverse=True)
        batches: list[list[_TL]] = []
        batch_sizes: list[int] = []

        for comp in sorted_components:
            placed = False
            for i, current_size in enumerate(batch_sizes):
                if current_size + len(comp) <= max_batch_size:
                    batches[i].extend(comp)
                    batch_sizes[i] += len(comp)
                    placed = True
                    break
            if not placed:
                batches.append(list(comp))
                batch_sizes.append(len(comp))

        return batches

    @staticmethod
    def _bin_pack_small_components(
        components: list[list[Term]],
        max_batch_size: int,
    ) -> list[list[list[Term]]]:
        """Group small components into bins without splitting any component.

        Uses first-fit-decreasing bin packing: sorts components by untranslated
        count descending, then greedily assigns each to the first bin that has
        room (total untranslated ≤ max_batch_size).

        Returns a list of bins, where each bin is a list of components.
        """
        if not components:
            return []

        def _untranslated_count(comp: list[Term]) -> int:
            return sum(1 for t in comp if not t.translated_name)

        # Sort descending by untranslated count
        sorted_components = sorted(components, key=_untranslated_count, reverse=True)
        bins: list[list[list[Term]]] = []
        bin_counts: list[int] = []

        for comp in sorted_components:
            count = _untranslated_count(comp)
            placed = False
            for i, current_count in enumerate(bin_counts):
                if current_count + count <= max_batch_size:
                    bins[i].append(comp)
                    bin_counts[i] += count
                    placed = True
                    break
            if not placed:
                bins.append([comp])
                bin_counts.append(count)

        return bins

    async def translate_terms(
        self,
        translation_name_similarity_threshold: float,
        concurrency: int,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
        max_terms_per_batch: int = 20,
    ) -> None:
        """
        Translate terms that are not ignored and not translated yet, and save to DB.

        Large connected components (more untranslated terms than *max_terms_per_batch*)
        are split into sub-batches via greedy nearest-neighbor clustering and processed
        sequentially so that later sub-batches benefit from earlier translations.
        Small components are bin-packed together and processed in parallel.
        Each LLM call result is persisted immediately.
        """
        raise_if_cancelled(cancel_check)
        terms = [term for term in self.term_repo.get_terms_to_translate() if not term.ignored]
        if not terms:
            return
        source_language = self.term_repo.get_source_language()
        if not source_language:
            raise ValueError("Source language not found in the database")
        # Load all existing terms for similarity checking
        all_terms = [term for term in self.term_repo.list_keyed_context() if not term.ignored]
        component_list, sim_cache = self._union_find_with_filter(
            terms, all_terms, translation_name_similarity_threshold
        )

        # Categorize components by untranslated term count
        small_components: list[list[Term]] = []
        large_components: list[list[Term]] = []
        for component in component_list:
            untranslated_count = sum(1 for t in component if not t.translated_name)
            if untranslated_count == 0:
                continue
            if untranslated_count <= max_terms_per_batch:
                small_components.append(component)
            else:
                large_components.append(component)

        # Bin-pack small components into combined batches
        small_bins = self._bin_pack_small_components(small_components, max_terms_per_batch)

        # Count total work units for progress reporting
        large_sub_batch_count = 0
        for component in large_components:
            untranslated = [t for t in component if not t.translated_name]
            n_sub = (len(untranslated) + max_terms_per_batch - 1) // max_terms_per_batch
            large_sub_batch_count += n_sub
        total = len(small_bins) + large_sub_batch_count
        if total == 0:
            return
        completed = 0
        progress_lock = asyncio.Lock()
        semaphore = asyncio.Semaphore(concurrency)
        failure_order: list[BaseException] = []
        failure_lock = asyncio.Lock()

        # Send initial progress so the UI knows the step has started
        if progress_callback:
            progress_callback(
                ProgressUpdate(
                    step=WorkflowStep.TRANSLATE_GLOSSARY,
                    current=0,
                    total=total,
                    message=f"Translating glossary group 0/{total}",
                )
            )

        async def _report_progress() -> None:
            nonlocal completed
            async with progress_lock:
                completed += 1
                if progress_callback:
                    progress_callback(
                        ProgressUpdate(
                            step=WorkflowStep.TRANSLATE_GLOSSARY,
                            current=completed,
                            total=total,
                            message=f"Translating glossary group {completed}/{total}",
                        )
                    )

        def _is_cancelled() -> bool:
            return cancel_check is not None and cancel_check()

        async def process_small_batch(components: list[list[Term]]) -> None:
            """Process a bin of small components in a single LLM call."""
            if _is_cancelled():
                return
            try:
                async with semaphore:
                    if _is_cancelled():
                        return
                    all_bin_terms = [t for comp in components for t in comp]
                    translated_names, to_translate = self._partition_component_terms(all_bin_terms)
                    if not to_translate:
                        await _report_progress()
                        return
                    similar_terms = self._collect_similar_terms(to_translate, translated_names)
                    result = await self.glossary_translator.translate(
                        to_translate,
                        similar_terms,
                        source_language,
                        cancel_check=cancel_check,
                    )
                    if result:
                        self._state_update(self._build_translation_updates(result), [])
                    await _report_progress()
            except BaseException as exc:
                async with failure_lock:
                    failure_order.append(exc)
                raise

        async def process_large_component(component: list[Term]) -> None:
            """Process a large component sequentially in sub-batches.

            Each sub-batch persists immediately and enriches context for later
            sub-batches within the same component.
            """
            if _is_cancelled():
                return
            translated = {t.key: t.translated_name for t in component if t.translated_name}

            sub_batches = self._greedy_nearest_neighbor_split(
                [t for t in component if not t.translated_name],
                max_terms_per_batch,
                sim_cache,
            )
            try:
                for sub_batch in sub_batches:
                    if _is_cancelled():
                        break
                    async with semaphore:
                        if _is_cancelled():
                            break
                        to_translate = [
                            {
                                "canonical_name": t.key,
                                "description": self._get_primary_description(t),
                                "missing_names": t.key,
                            }
                            for t in sub_batch
                        ]
                        similar_terms = self._collect_similar_terms(to_translate, translated)
                        result = await self.glossary_translator.translate(
                            to_translate,
                            similar_terms,
                            source_language,
                            cancel_check=cancel_check,
                        )
                        if result:
                            self._state_update(self._build_translation_updates(result), [])
                            # Enrich context for subsequent sub-batches
                            translated.update(result)
                        await _report_progress()
            except BaseException as exc:
                async with failure_lock:
                    failure_order.append(exc)
                raise

        # Build task list: small bins in parallel, large components sequentially
        tasks: list[asyncio.Task[None]] = []
        for bin_components in small_bins:
            tasks.append(asyncio.ensure_future(process_small_batch(bin_components)))
        for component in large_components:
            tasks.append(asyncio.ensure_future(process_large_component(component)))

        if tasks:
            # Graceful cancellation: running LLM tasks finish and save,
            # pending tasks skip quickly via _is_cancelled() checks.
            results = await asyncio.gather(*tasks, return_exceptions=True)
            raise_if_cancelled(cancel_check)
            exceptions = [e for e in results if isinstance(e, BaseException)]
            if exceptions:
                for e in exceptions:
                    logger.error("Error translating terms: %s", e, exc_info=True)
                raise _select_final_exception(exceptions, failure_order=failure_order)

    def _union_find_with_filter(
        self, terms: list[Term], all_terms: list[Term], similarity_threshold: float
    ) -> tuple[list[list[Term]], dict[tuple[str, str], float]]:
        """Group terms into connected components, pulling in similar terms from all_terms.

        Returns:
            A tuple of (components, sim_cache) where sim_cache maps
            canonical (key_a, key_b) pairs (key_a < key_b) to their
            similarity score for reuse in downstream batching.
        """
        parent: dict[str, str] = {}
        rank: dict[str, int] = {}
        sim_cache: dict[tuple[str, str], float] = {}

        def find(x: str) -> str:
            if x not in parent:
                parent[x] = x
                rank[x] = 0
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x: str, y: str) -> None:
            px, py = find(x), find(y)
            if px == py:
                return
            if rank[px] < rank[py]:
                parent[px] = py
            elif rank[px] > rank[py]:
                parent[py] = px
            else:
                parent[py] = px
                rank[px] += 1

        queue = deque[Term](terms)
        processed = set[str](term.key for term in terms)
        # First, compare all terms in the initial list with each other
        for i, term in enumerate(terms):
            for other in terms[i + 1 :]:
                similarity = string_similarity(term.key, other.key)
                pair = (term.key, other.key) if term.key < other.key else (other.key, term.key)
                sim_cache[pair] = similarity
                if similarity >= similarity_threshold:
                    union(term.key, other.key)
        while queue:
            term = queue.popleft()
            for other in all_terms:
                if term.key == other.key or other.key in processed:
                    continue
                similarity = string_similarity(term.key, other.key)
                pair = (term.key, other.key) if term.key < other.key else (other.key, term.key)
                sim_cache[pair] = similarity
                if similarity >= similarity_threshold:
                    union(term.key, other.key)
                    processed.add(other.key)
                    # Only for untranslated terms, we look for similar terms to translate.
                    if other.translated_name is None:
                        queue.append(other)
        # Extract connected components
        components: dict[str, list[Term]] = {}
        for term in [term for term in all_terms if term.key in processed]:
            root = find(term.key)
            if root not in components:
                components[root] = []
            components[root].append(term)

        return list(components.values()), sim_cache

    @staticmethod
    def _group_consecutive_batches(
        chunks: list[TranslationChunkRecord],
        batch_size: int,
    ) -> list[list[TranslationChunkRecord]]:
        """Group chunks into consecutive chunk_id batches up to batch_size."""
        batches: list[list[TranslationChunkRecord]] = []
        current_batch: list[TranslationChunkRecord] = []
        for chunk in chunks:
            if not current_batch or (
                len(current_batch) < batch_size and chunk.chunk_id == current_batch[-1].chunk_id + 1
            ):
                current_batch.append(chunk)
            else:
                batches.append(current_batch)
                current_batch = [chunk]
        if current_batch:
            batches.append(current_batch)
        return batches

    @staticmethod
    def _term_in_batch(
        term: Term,
        batch_chunk_ids: set[str],
        batch_normalized_texts: list[str],
    ) -> bool:
        """Check whether a term should be included for a translation batch."""
        # Prefer precomputed occurrence mapping when available.
        if term.occurrence and any(chunk_id in term.occurrence for chunk_id in batch_chunk_ids):
            return True
        # Fallback: normalized substring check for terms without occurrence data.
        normalized_key = normalize_for_matching(term.key)
        return any(normalized_key in nt for nt in batch_normalized_texts)

    def _build_batch_terms(
        self,
        all_terms: list[Term],
        batch: list[TranslationChunkRecord],
        max_chunk_id: int,
        skip_context: bool = False,
    ) -> list[tuple[str, str, str]]:
        batch_chunk_ids = {str(chunk.chunk_id) for chunk in batch}
        batch_normalized_texts = [chunk.normalized_text for chunk in batch]
        raw = [
            (
                term.key,
                term.translated_name or "",
                self.get_term_description_for_query(term, max_chunk_id, skip_context=skip_context),
            )
            for term in all_terms
            if self._term_in_batch(term, batch_chunk_ids, batch_normalized_texts)
        ]
        return _dedup_batch_terms(raw)

    def collect_chunk_translation_inputs(
        self,
        *,
        batch_size: int,
        document_ids: list[int] | None,
        force: bool,
        cancel_check: Callable[[], bool] | None,
        source_language: str | None = None,
    ) -> ChunkTranslationInputs | None:
        """Collect shared chunk-translation planning inputs for translation flows."""
        raise_if_cancelled(cancel_check)
        untranslated_chunks = sorted(
            self.term_repo.get_chunks_to_translate(document_ids, force=force),
            key=lambda c: c.chunk_id,
        )
        if not untranslated_chunks:
            return None

        resolved_source_language = source_language or self.term_repo.get_source_language()
        if not resolved_source_language:
            raise ValueError("Source language not found in the database")

        all_terms = [term for term in self.term_repo.list_keyed_context() if not term.ignored]
        batches = self._group_consecutive_batches(untranslated_chunks, batch_size)
        return ChunkTranslationInputs(
            source_language=resolved_source_language,
            all_terms=all_terms,
            batches=batches,
        )

    def build_batch_request_payload(
        self,
        batch: list[TranslationChunkRecord],
        all_terms: list[Term],
        *,
        skip_context: bool = False,
    ) -> tuple[list[str], list[tuple[str, str, str]]]:
        """Build request chunk-text and glossary payload for one translation batch."""
        batch_texts = [chunk.text for chunk in batch]
        max_chunk_id = max(chunk.chunk_id for chunk in batch)
        batch_terms = self._build_batch_terms(all_terms, batch, max_chunk_id, skip_context=skip_context)
        return batch_texts, batch_terms

    async def translate_chunks(
        self,
        concurrency: int,
        batch_size: int = 5,
        document_ids: list[int] | None = None,
        force: bool = False,
        skip_context: bool = False,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        """Translate text chunks that are not translated yet, and save to DB.

        Args:
            concurrency: Number of concurrent translation tasks
            batch_size: Number of chunks per translation batch
            document_ids: Specific document IDs to translate, or None for all
        """
        inputs = self.collect_chunk_translation_inputs(
            batch_size=batch_size,
            document_ids=document_ids,
            force=force,
            cancel_check=cancel_check,
        )
        if inputs is None:
            return
        source_language = inputs.source_language
        all_terms = inputs.all_terms
        semaphore = asyncio.Semaphore(concurrency)
        batches = inputs.batches
        total = len(batches)
        completed = 0
        progress_lock = asyncio.Lock()
        failure_order: list[BaseException] = []
        failure_lock = asyncio.Lock()

        async def process_batch(batch: list[TranslationChunkRecord]) -> None:
            nonlocal completed
            try:
                raise_if_cancelled(cancel_check)
                async with semaphore:
                    raise_if_cancelled(cancel_check)
                    batch_texts, batch_terms = self.build_batch_request_payload(
                        batch,
                        all_terms,
                        skip_context=skip_context,
                    )

                    translated_texts = await self.chunk_translator.translate(
                        batch_texts, batch_terms, source_language, cancel_check=cancel_check
                    )
                    for chunk, translation in zip(batch, translated_texts, strict=True):
                        chunk.translation = translation
                        chunk.is_translated = True

                    # Use _state_update to update chunks atomically
                    self._state_update([], batch)
                    raise_if_cancelled(cancel_check)

                    # Update progress after work completes
                    async with progress_lock:
                        completed += 1
                        if progress_callback:
                            progress_callback(
                                ProgressUpdate(
                                    step=WorkflowStep.TRANSLATE_CHUNKS,
                                    current=completed,
                                    total=total,
                                    message=f"Translating batch {completed}/{total}",
                                )
                            )
            except BaseException as exc:
                async with failure_lock:
                    failure_order.append(exc)
                raise

        # Process all batches concurrently with concurrency limit.
        # Persisted successful batches should not be discarded if others fail.
        results = await asyncio.gather(*[process_batch(batch) for batch in batches], return_exceptions=True)
        raise_if_cancelled(cancel_check)
        exceptions = [e for e in results if isinstance(e, BaseException)]
        if exceptions:
            for e in exceptions:
                logger.error("Error translating chunks: %s", e, exc_info=True)
            raise _select_final_exception(exceptions, failure_order=failure_order)

    def get_translated_lines(self, document_id: int) -> list[str]:
        """Return translated text as a list of lines for a document.

        Concatenates all chunk translations in chunk_id order, then splits
        by newline.  Raises if any chunks are not yet translated.
        """
        chunks = self.term_repo.list_chunks(document_id=document_id)
        if not chunks:
            raise ValueError("No chunks found in the database")

        sorted_chunks = sorted(chunks, key=lambda c: c.chunk_id)

        untranslated = [c for c in sorted_chunks if not c.is_translated or c.translation is None]
        if untranslated:
            untranslated_ids = [c.chunk_id for c in untranslated]
            raise ValueError(f"Cannot export: chunks {untranslated_ids} are not translated yet")

        translated_text = "".join(c.translation for c in sorted_chunks if c.translation)
        return translated_text.splitlines()


class TranslationContextManagerAdapter:
    """Adapter that wraps a TranslationContextManager and dispatches by document type.

    Registered DocumentTypeHandler instances handle add_text, translate_chunks,
    and get_translated_lines for their respective document types.  All other
    attribute access is forwarded to the underlying manager.
    """

    def __init__(self, manager: TranslationContextManager) -> None:
        self._manager = manager
        self._handlers: dict[str, DocumentTypeHandler] = {}

    def register_handler(self, document_type: str, handler: DocumentTypeHandler) -> None:
        self._handlers[document_type] = handler

    # ------------------------------------------------------------------
    # Dispatch points
    # ------------------------------------------------------------------

    def add_text(
        self,
        text: str,
        max_token_size_per_chunk: int,
        document_id: int,
        document_type: str,
    ) -> int:
        handler = self._handlers.get(document_type)
        if handler is not None:
            return handler.add_text(
                text,
                max_token_size_per_chunk,
                document_id,
                self._manager,
            )
        return self._manager.add_text(text, max_token_size_per_chunk, document_id)

    async def translate_chunks(
        self,
        concurrency: int,
        batch_size: int = 5,
        doc_type_by_id: dict[int, str] | None = None,
        force: bool = False,
        skip_context: bool = False,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        if not doc_type_by_id:
            return

        # Process documents sequentially so the underlying translation
        # strategy can enforce the global concurrency budget itself.
        max_parallel = max(1, concurrency)
        for doc_id in sorted(doc_type_by_id):
            raise_if_cancelled(cancel_check)
            doc_type = doc_type_by_id[doc_id]
            handler = self._handlers.get(doc_type)
            if handler is not None:
                if cancel_check is None:
                    await handler.translate_chunks(
                        [doc_id],
                        self._manager,
                        force=force,
                        skip_context=skip_context,
                        progress_callback=progress_callback,
                    )
                else:
                    await handler.translate_chunks(
                        [doc_id],
                        self._manager,
                        force=force,
                        skip_context=skip_context,
                        cancel_check=cancel_check,
                        progress_callback=progress_callback,
                    )
            else:
                if cancel_check is None:
                    await self._manager.translate_chunks(
                        max_parallel,
                        batch_size,
                        [doc_id],
                        force=force,
                        skip_context=skip_context,
                        progress_callback=progress_callback,
                    )
                else:
                    await self._manager.translate_chunks(
                        max_parallel,
                        batch_size,
                        [doc_id],
                        force=force,
                        skip_context=skip_context,
                        cancel_check=cancel_check,
                        progress_callback=progress_callback,
                    )

    def get_translated_lines(self, document_id: int, document_type: str) -> list[str]:
        handler = self._handlers.get(document_type)
        if handler is not None:
            return handler.get_translated_lines(document_id, self._manager)
        return self._manager.get_translated_lines(document_id)

    # ------------------------------------------------------------------
    # Everything else delegates to the wrapped manager
    # ------------------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        return getattr(self._manager, name)
