import threading
from collections.abc import Callable
from pathlib import Path

from context_aware_translation.config import Config
from context_aware_translation.core.cancellation import raise_if_cancelled
from context_aware_translation.core.context_manager import TranslationContextManagerAdapter
from context_aware_translation.core.context_tree import ContextTree
from context_aware_translation.core.progress import ProgressCallback, ProgressUpdate, WorkflowStep
from context_aware_translation.documents.base import Document, is_ocr_required_for_type
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.storage.book_db import SQLiteBookDB
from context_aware_translation.storage.document_repository import DocumentRepository


class WorkflowService:
    """Application workflow orchestrator for translation use-cases."""

    # Per-book bootstrap lock: serializes _prepare_llm_prerequisites for the same book_id
    _bootstrap_registry_lock = threading.Lock()
    _bootstrap_locks: dict[str, threading.Lock] = {}

    @classmethod
    def _get_bootstrap_lock(cls, book_id: str | None) -> threading.Lock:
        """Return a per-book lock for serializing bootstrap operations."""
        key = book_id or "__unknown__"
        with cls._bootstrap_registry_lock:
            if key not in cls._bootstrap_locks:
                cls._bootstrap_locks[key] = threading.Lock()
            return cls._bootstrap_locks[key]

    def __init__(
        self,
        *,
        config: Config,
        llm_client: LLMClient,
        context_tree: ContextTree,
        manager: TranslationContextManagerAdapter,
        db: SQLiteBookDB,
        document_repo: DocumentRepository,
        book_id: str | None = None,
    ) -> None:
        self.config = config
        self.llm_client = llm_client
        self.context_tree = context_tree
        self.manager = manager
        self.db = db
        self.document_repo = document_repo
        self.book_id = book_id

    def _load_documents(self, document_ids: list[int] | None = None) -> list[Document]:
        """Load documents by IDs, or all documents if None."""
        if document_ids is None:
            return Document.load_all(self.document_repo, self.config.ocr_config)
        return Document.load_by_ids(self.document_repo, document_ids, self.config.ocr_config)

    @staticmethod
    def _check_cancel(cancel_check: Callable[[], bool] | None) -> None:
        """Raise cancellation if requested."""
        raise_if_cancelled(cancel_check)

    async def _ensure_source_language(
        self,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        """Ensure source language is available for LLM-dependent glossary/translation steps."""
        self._check_cancel(cancel_check)
        await self.manager.detect_language(cancel_check=cancel_check)

    async def _prepare_llm_prerequisites(
        self,
        document_ids: list[int] | None,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        """Prepare document text/chunks and source language for LLM-driven steps."""
        lock = self._get_bootstrap_lock(self.book_id)
        with lock:
            self._check_cancel(cancel_check)
            await self._process_document(document_ids, cancel_check=cancel_check)
            self._check_cancel(cancel_check)
            await self._ensure_source_language(cancel_check=cancel_check)

    async def _ensure_glossary_source_language(
        self,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        """Ensure source language for glossary-only operations without document preflight.

        This keeps glossary table operations available even when some documents are
        OCR-blocked, by deriving language from existing term data when needed.
        """
        self._check_cancel(cancel_check)
        source_language = self.db.get_source_language()
        if source_language:
            return

        # Hidden best-effort prep: add text from docs that are already ready.
        # OCR-blocked document types are skipped rather than failing.
        documents = sorted(self._load_documents(None), key=lambda doc: int(doc.document_id))
        translator_config = self.config.translator_config
        assert translator_config is not None
        for document in documents:
            self._check_cancel(cancel_check)
            if document.is_text_added():
                continue
            if document.ocr_required_for_translation and not document.is_ocr_completed():
                continue
            text_content = document.get_text()
            self.manager.add_text(
                text=text_content,
                max_token_size_per_chunk=translator_config.chunk_size,
                document_id=document.document_id,
                document_type=document.document_type,
            )
            document.mark_text_added()

        # First try standard chunk-based detection (if any chunks now exist).
        try:
            await self._ensure_source_language(cancel_check=cancel_check)
            return
        except ValueError as exc:
            if not self._is_missing_source_language_error(exc):
                raise

        # Fallback to glossary table text (imported terms, etc.).
        terms = self.db.list_terms(limit=80)
        sample_parts: list[str] = []
        for term in terms:
            self._check_cancel(cancel_check)
            key = (term.key or "").strip()
            if key:
                sample_parts.append(key)
            descriptions = term.descriptions or {}
            for desc in descriptions.values():
                if isinstance(desc, str) and desc.strip():
                    sample_parts.append(desc.strip())
                    break
            if len(sample_parts) >= 120:
                break

        sample_text = "\n".join(sample_parts).strip()
        if not sample_text:
            raise ValueError("Source language not found. Build/import glossary terms with source text first.")

        detected = await self.manager.source_language_detector.detect(sample_text, cancel_check=cancel_check)
        self.db.set_source_language(detected)

    @staticmethod
    def _is_missing_source_language_error(exc: BaseException) -> bool:
        message = str(exc).lower()
        return ("source language not found" in message) or ("no text chunks found" in message)

    async def run_ocr(
        self,
        progress_callback: ProgressCallback | None = None,
        source_ids: list[int] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> int:
        """
        Run OCR on documents that need it.
        Returns count of pages processed.

        This allows users to review/edit OCR results before building glossary.

        Args:
            progress_callback: Optional callback for progress updates
            source_ids: Optional list of source IDs to process. If None, process all.
        """
        total_processed = 0
        self._check_cancel(cancel_check)
        documents = Document.load_all(self.document_repo, self.config.ocr_config)

        if not documents:
            return 0

        # Count total sources needing OCR (filtered if source_ids provided)
        all_sources = []
        for doc in documents:
            if self.config.ocr_config is not None:
                sources = self.document_repo.get_document_sources_needing_ocr(doc.document_id)
                if source_ids is not None:
                    sources = [s for s in sources if s["source_id"] in source_ids]
                all_sources.extend(sources)

        total_sources = len(all_sources)

        self._check_cancel(cancel_check)
        if progress_callback and total_sources > 0:
            progress_callback(
                ProgressUpdate(
                    step=WorkflowStep.OCR,
                    current=0,
                    total=total_sources,
                    message="Starting OCR...",
                )
            )

        current = 0
        for document in documents:
            self._check_cancel(cancel_check)
            if self.config.ocr_config is not None:
                if cancel_check is None:
                    processed = await document.process_ocr(self.llm_client, source_ids)
                else:
                    processed = await document.process_ocr(self.llm_client, source_ids, cancel_check=cancel_check)
                if processed > 0:
                    current += processed
                    total_processed += processed

                    if progress_callback:
                        progress_callback(
                            ProgressUpdate(
                                step=WorkflowStep.OCR,
                                current=current,
                                total=total_sources,
                                message=f"OCR page {current}/{total_sources}",
                            )
                        )

        return total_processed

    async def _process_document(
        self,
        document_ids: list[int] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        """Process documents, adding their text to the context manager with document_id.

        Args:
            document_ids: Specific document IDs to process, or None for all

        Raises:
            ValueError: If no documents found or if OCR is not complete for a document
        """
        documents = self._load_documents(document_ids)
        if not documents:
            raise ValueError("No documents found in database")

        for document in documents:
            self._check_cancel(cancel_check)
            if not document.is_ocr_completed() and document.ocr_required_for_translation:
                raise ValueError(
                    f"Document {document.document_id} has not completed OCR. "
                    "Please run OCR from the OCR Review tab before translation or glossary build."
                )

            if not document.is_text_added():
                text_content = document.get_text()
                translator_config = self.config.translator_config
                assert translator_config is not None

                self.manager.add_text(
                    text=text_content,
                    max_token_size_per_chunk=translator_config.chunk_size,
                    document_id=document.document_id,
                    document_type=document.document_type,
                )
                document.mark_text_added()

    def _resolve_preflight_document_ids(self, document_ids: list[int] | None) -> list[int] | None:
        """Resolve document IDs to preflight before translation.

        Translation context/chunk IDs are stack-ordered. When translating a selected
        document N, we preflight all earlier documents (<= N) first so context and
        chunk ordering remain consistent with glossary workflows.
        """
        all_documents = sorted(self.document_repo.list_documents(), key=lambda d: int(d["document_id"]))
        if not all_documents:
            return None
        if document_ids is None:
            return [int(doc["document_id"]) for doc in all_documents]

        if not document_ids:
            return []

        selected_ids = {int(doc_id) for doc_id in document_ids}
        selected_docs = [doc for doc in all_documents if int(doc["document_id"]) in selected_ids]
        if selected_docs and all(
            not is_ocr_required_for_type(str(doc.get("document_type", ""))) for doc in selected_docs
        ):
            return [int(doc["document_id"]) for doc in selected_docs]

        cutoff = max(selected_ids)
        return [int(doc["document_id"]) for doc in all_documents if int(doc["document_id"]) <= cutoff]

    # ------------------------------------------------------------------
    # Public wrappers for cross-module callers (batch_translation_task_ops)
    # ------------------------------------------------------------------

    def resolve_preflight_document_ids(self, document_ids: list[int] | None) -> list[int] | None:
        """Public wrapper for ``_resolve_preflight_document_ids``."""
        return self._resolve_preflight_document_ids(document_ids)

    async def prepare_llm_prerequisites(
        self,
        document_ids: list[int] | None,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        """Public wrapper for ``_prepare_llm_prerequisites``."""
        await self._prepare_llm_prerequisites(document_ids, cancel_check=cancel_check)

    @staticmethod
    def check_cancel(cancel_check: Callable[[], bool] | None) -> None:
        """Public wrapper for ``_check_cancel``."""
        raise_if_cancelled(cancel_check)

    def update_chunk_records(self, chunk_records: list) -> None:
        """Persist translated chunk records via the context manager."""
        self.manager._state_update([], chunk_records)

    def _build_doc_type_by_id(self, document_ids: list[int] | None) -> dict[int, str]:
        """Build document_id -> document_type mapping for selected translation targets."""
        all_docs = self.document_repo.list_documents()
        if document_ids is None:
            return {int(doc["document_id"]): str(doc["document_type"]) for doc in all_docs}
        id_set = {int(doc_id) for doc_id in document_ids}
        return {
            int(doc["document_id"]): str(doc["document_type"]) for doc in all_docs if int(doc["document_id"]) in id_set
        }

    def _resolve_export_lines(
        self,
        document: Document,
        *,
        allow_original_fallback: bool,
    ) -> list[str]:
        """Resolve text lines to apply to a document during export."""
        try:
            return self.manager.get_translated_lines(document.document_id, document.document_type)
        except ValueError:
            if not allow_original_fallback:
                raise
            return self._get_lines_with_original_fallback(document)

    async def materialize_document_translation_state(
        self,
        document: Document,
        *,
        allow_original_fallback: bool = False,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        """Apply translated lines to a document so it is ready for export or reembedding.

        Sets EPUB target language metadata if applicable. Does NOT trigger image
        reembedding — that is handled separately via document.reembed().

        Args:
            document: The document instance to populate.
            allow_original_fallback: If True, untranslated chunks fall back to
                original text.
            cancel_check: Optional cooperative cancellation callback.
            progress_callback: Optional callback for progress updates.
        """
        all_lines = self._resolve_export_lines(
            document,
            allow_original_fallback=allow_original_fallback,
        )
        if document.document_type == "epub":
            from context_aware_translation.documents.epub import EPUBDocument

            if isinstance(document, EPUBDocument):
                document.set_translation_target_language(self.config.translation_target_language)

        await document.set_text(
            all_lines,
            image_reembedding_config=None,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )
        self._check_cancel(cancel_check)

    async def _apply_export_text(
        self,
        document: Document,
        *,
        allow_original_fallback: bool,
        cancel_check: Callable[[], bool] | None,
        progress_callback: ProgressCallback | None,
    ) -> None:
        """Apply export text lines to a document, with fallback semantics."""
        await self.materialize_document_translation_state(
            document,
            allow_original_fallback=allow_original_fallback,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )

    def _resolve_import_class(
        self,
        classes: list[type[Document]],
        path: Path,
        *,
        document_type: str | None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> type[Document]:
        """Resolve target document class for import request."""
        if document_type:
            for cls in classes:
                self._check_cancel(cancel_check)
                if cls.document_type != document_type:
                    continue
                if cls.can_import(path):
                    return cls
                raise ValueError(f"Path cannot be imported as {document_type}")
            raise ValueError(f"Unknown document type: {document_type}")

        matches = []
        for cls in classes:
            self._check_cancel(cancel_check)
            if cls.can_import(path):
                matches.append(cls)
        if len(matches) > 1:
            names = [cls.__name__.replace("Document", "").lower() for cls in matches]
            raise ValueError(f"Path can be imported as: {', '.join(names)}. Please specify document_type.")
        if len(matches) == 0:
            raise ValueError("Cannot import path: no supported document type matches.")
        return matches[0]

    def _import_with_class(
        self,
        document_class: type[Document],
        path: Path,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, int | None]:
        """Import a path with a resolved document class and return standardized result."""
        existing_document_ids = {int(doc["document_id"]) for doc in self.document_repo.list_documents()}
        self._check_cancel(cancel_check)
        result = document_class.do_import(self.document_repo, path, cancel_check=cancel_check)
        document_id = self._resolve_imported_document_id(existing_document_ids, int(result["imported"]))
        return {
            "imported": int(result["imported"]),
            "skipped": int(result["skipped"]),
            "document_id": document_id,
        }

    async def build_glossary(
        self,
        document_ids: list[int] | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        """
        Build glossary: extract terms and occurrence mapping.

        Note: OCR must be run separately before calling this method.
        Use run_ocr() or the OCR Review UI to process images first.

        Args:
            document_ids: Specific document IDs to process, or None for all
            progress_callback: Optional callback for progress updates
        """
        extractor_config = self.config.extractor_config
        assert extractor_config is not None

        await self._prepare_llm_prerequisites(document_ids, cancel_check=cancel_check)

        self._check_cancel(cancel_check)
        await self.manager.extract_keyed_context(
            concurrency=extractor_config.concurrency,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )
        await self.manager.build_occurrence_mapping(cancel_check=cancel_check)

    async def translate_glossary(
        self,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        """Translate glossary terms using glossary-table-only prerequisites."""
        glossary_config = self.config.glossary_config
        assert glossary_config is not None

        try:
            self._check_cancel(cancel_check)
            await self.manager.translate_terms(
                translation_name_similarity_threshold=0.7,
                concurrency=glossary_config.concurrency or self.config.llm_concurrency,
                cancel_check=cancel_check,
                progress_callback=progress_callback,
            )
        except ValueError as exc:
            if not self._is_missing_source_language_error(exc):
                raise
            await self._ensure_glossary_source_language(cancel_check=cancel_check)
            self._check_cancel(cancel_check)
            await self.manager.translate_terms(
                translation_name_similarity_threshold=0.7,
                concurrency=glossary_config.concurrency or self.config.llm_concurrency,
                cancel_check=cancel_check,
                progress_callback=progress_callback,
            )

    async def review_terms(
        self,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        """Review unreviewed terms using glossary-table-only prerequisites."""
        review_config = self.config.review_config
        if review_config is None:
            raise ValueError("Review config not set. Please configure review settings.")

        try:
            self._check_cancel(cancel_check)
            await self.manager.review_terms(
                concurrency=review_config.concurrency,
                cancel_check=cancel_check,
                progress_callback=progress_callback,
            )
        except ValueError as exc:
            if not self._is_missing_source_language_error(exc):
                raise
            await self._ensure_glossary_source_language(cancel_check=cancel_check)
            self._check_cancel(cancel_check)
            await self.manager.review_terms(
                concurrency=review_config.concurrency,
                cancel_check=cancel_check,
                progress_callback=progress_callback,
            )

    async def translate(
        self,
        document_ids: list[int] | None = None,
        progress_callback: ProgressCallback | None = None,
        force: bool = False,
        skip_context: bool = False,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        """
        Translate documents using the glossary.

        The manager handles manga/text dispatch internally via translate_chunks().

        Args:
            document_ids: Specific document IDs to translate, or None for all
            progress_callback: Optional callback for progress updates
            skip_context: If True, use only each term's earliest description instead of
                chunk-indexed context summaries when preparing translation prompts.
        """
        translator_config = self.config.translator_config
        assert translator_config is not None

        preflight_document_ids = self._resolve_preflight_document_ids(document_ids)
        await self._prepare_llm_prerequisites(preflight_document_ids, cancel_check=cancel_check)

        if not skip_context:
            self._check_cancel(cancel_check)
            self.manager.build_context_tree(cancel_check=cancel_check)

        self._check_cancel(cancel_check)
        doc_type_by_id = self._build_doc_type_by_id(document_ids)

        await self.manager.translate_chunks(
            doc_type_by_id=doc_type_by_id,
            concurrency=translator_config.concurrency,
            batch_size=translator_config.num_of_chunks_per_llm_call,
            force=force,
            skip_context=skip_context,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )

    async def retranslate_chunk(
        self,
        chunk_id: int,
        document_id: int,
        skip_context: bool = False,
        cancel_check: Callable[[], bool] | None = None,
    ) -> str:
        """Retranslate a single chunk by ID using the LLM.

        Args:
            chunk_id: The chunk to retranslate.
            document_id: The document the chunk belongs to.
            skip_context: If True, use only earliest description per term.
            cancel_check: Optional cancellation callback.

        Returns:
            The new translation text.
        """
        translator_config = self.config.translator_config
        assert translator_config is not None

        # Ensure prerequisites (text added, source language detected)
        preflight_document_ids = self._resolve_preflight_document_ids([document_id])
        await self._prepare_llm_prerequisites(preflight_document_ids, cancel_check=cancel_check)

        if not skip_context:
            self._check_cancel(cancel_check)
            self.manager.build_context_tree(cancel_check=cancel_check)

        self._check_cancel(cancel_check)

        # Fetch the chunk record
        chunk = self.db.get_chunk_by_id(chunk_id)
        if chunk is None:
            raise ValueError(f"Chunk {chunk_id} not found")

        source_language = self.db.get_source_language()
        if not source_language:
            raise ValueError("Source language not found in the database")

        # Build terms for this single chunk
        all_terms = [term for term in self.manager.term_repo.list_keyed_context() if not term.ignored]
        _, batch_terms = self.manager.build_batch_request_payload(
            [chunk],
            all_terms,
            skip_context=skip_context,
        )

        self._check_cancel(cancel_check)

        # Translate the single chunk
        translated_texts = await self.manager.chunk_translator.translate(
            [chunk.text], batch_terms, source_language, cancel_check=cancel_check
        )

        new_translation: str = translated_texts[0]
        chunk.translation = new_translation
        chunk.is_translated = True

        # Persist
        self.manager._state_update([], [chunk])

        return new_translation

    async def export(
        self,
        file_path: Path,
        export_format: str | None = None,
        document_ids: list[int] | None = None,
        allow_original_fallback: bool = False,
        progress_callback: ProgressCallback | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        """Export translated content to file.

        Args:
            file_path: Output file path
            export_format: Output format (txt, epub, md). Auto-detected from extension if None.
            document_ids: Specific document IDs to export, or None for all
            allow_original_fallback: If True, allow untranslated chunks to fall back
                to original text while preserving translated chunks.
            progress_callback: Optional callback for progress updates
        """
        self._check_cancel(cancel_check)
        documents = self._load_documents(document_ids)
        if not documents:
            raise ValueError("No documents to export")

        doc_types = {d.document_type for d in documents}
        if len(doc_types) > 1:
            raise ValueError(f"Cannot export mixed document types: {doc_types}. All documents must be the same type.")

        if export_format is None:
            ext = file_path.suffix.lower()
            export_format = ext[1:] if ext else "txt"

        if not documents[0].can_export(export_format):
            supported = ", ".join(documents[0].supported_export_formats)
            raise ValueError(f"Format '{export_format}' not supported. Supported: {supported}")

        total_docs = len(documents)
        for idx, doc in enumerate(documents):
            self._check_cancel(cancel_check)
            if progress_callback:
                progress_callback(
                    ProgressUpdate(
                        step=WorkflowStep.EXPORT,
                        current=idx + 1,
                        total=total_docs,
                        message=f"Exporting document {idx + 1}/{total_docs}",
                    )
                )
            await self._apply_export_text(
                doc,
                allow_original_fallback=allow_original_fallback,
                cancel_check=cancel_check,
                progress_callback=progress_callback,
            )

        self._check_cancel(cancel_check)
        doc_class = type(documents[0])
        doc_class.export_merged(documents, export_format, file_path)

    async def export_preserve_structure(
        self,
        output_folder: Path,
        document_ids: list[int] | None = None,
        allow_original_fallback: bool = False,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self._check_cancel(cancel_check)
        documents = self._load_documents(document_ids)
        if not documents:
            raise ValueError("No documents to export")

        for document in documents:
            if not document.supports_preserve_structure:
                raise NotImplementedError(
                    f"{type(document).__name__} documents do not support structure-preserving export"
                )

        for document in documents:
            self._check_cancel(cancel_check)
            await self._apply_export_text(
                document,
                allow_original_fallback=allow_original_fallback,
                cancel_check=cancel_check,
                progress_callback=progress_callback,
            )
            document.export_preserve_structure(output_folder / str(document.document_id))

    def _get_lines_with_original_fallback(self, document: Document) -> list[str]:
        """Return export lines with per-chunk fallback for untranslated chunks.

        For manga, untranslated chunks fallback to empty translations so reembedding
        is skipped and original page images are preserved.
        """
        chunks = sorted(self.db.list_chunks(document_id=document.document_id), key=lambda chunk: chunk.chunk_id)
        if not chunks:
            if document.document_type == "manga":
                return []
            return document.get_text().splitlines()

        if document.document_type == "manga":
            return [
                chunk.translation if chunk.is_translated and chunk.translation is not None else "" for chunk in chunks
            ]

        merged_chunks = [
            chunk.translation if chunk.is_translated and chunk.translation is not None else chunk.text
            for chunk in chunks
        ]
        return "".join(merged_chunks).splitlines()

    def _resolve_imported_document_id(
        self,
        existing_document_ids: set[int],
        imported_count: int,
    ) -> int | None:
        """Resolve the newly created document_id after an import operation."""
        if imported_count <= 0:
            return None

        after_documents = self.document_repo.list_documents()
        new_ids = sorted(
            int(doc["document_id"]) for doc in after_documents if int(doc["document_id"]) not in existing_document_ids
        )
        if not new_ids:
            return None
        return new_ids[-1]

    def import_path(
        self,
        path: Path,
        document_type: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, int | None]:
        from context_aware_translation.documents.base import get_document_classes

        self._check_cancel(cancel_check)
        if not path.exists():
            raise ValueError(f"Path does not exist: {path}")

        self._check_cancel(cancel_check)
        if path.is_dir() and not any(path.iterdir()):
            raise ValueError(f"Cannot import empty folder: {path}")

        classes = get_document_classes()
        target_class = self._resolve_import_class(
            classes,
            path,
            document_type=document_type,
            cancel_check=cancel_check,
        )
        return self._import_with_class(target_class, path, cancel_check=cancel_check)
