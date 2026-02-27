from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from context_aware_translation.config import Config
from context_aware_translation.core.cancellation import raise_if_cancelled
from context_aware_translation.core.context_manager import TranslationContextManagerAdapter
from context_aware_translation.core.context_tree import ContextTree
from context_aware_translation.core.progress import ProgressCallback
from context_aware_translation.documents.base import Document
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.storage.book_db import SQLiteBookDB
from context_aware_translation.storage.document_repository import DocumentRepository
from context_aware_translation.workflow.services import (
    bootstrap_ops,
    export_ops,
    glossary_ops,
    import_ops,
    ocr_ops,
    translation_ops,
)


class WorkflowService:
    """Application workflow orchestrator for translation use-cases."""

    # Backward-compatible class attributes for tests/introspection.
    _bootstrap_registry_lock = bootstrap_ops.BOOTSTRAP_REGISTRY_LOCK
    _bootstrap_locks = bootstrap_ops.BOOTSTRAP_LOCKS

    @classmethod
    def _get_bootstrap_lock(cls, book_id: str | None):
        """Return a per-book lock for serializing bootstrap operations."""
        return bootstrap_ops.get_bootstrap_lock(
            book_id,
            registry_lock=cls._bootstrap_registry_lock,
            locks=cls._bootstrap_locks,
        )

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
        await bootstrap_ops.ensure_source_language(self, cancel_check=cancel_check)

    async def _prepare_llm_prerequisites(
        self,
        document_ids: list[int] | None,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        await bootstrap_ops.prepare_llm_prerequisites(self, document_ids, cancel_check=cancel_check)

    async def _ensure_glossary_source_language(
        self,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        await bootstrap_ops.ensure_glossary_source_language(self, cancel_check=cancel_check)

    @staticmethod
    def _is_missing_source_language_error(exc: BaseException) -> bool:
        return bootstrap_ops.is_missing_source_language_error(exc)

    async def run_ocr(
        self,
        progress_callback: ProgressCallback | None = None,
        source_ids: list[int] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> int:
        return await ocr_ops.run_ocr(
            self,
            document_loader=Document.load_all,
            progress_callback=progress_callback,
            source_ids=source_ids,
            cancel_check=cancel_check,
        )

    async def _process_document(
        self,
        document_ids: list[int] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        await bootstrap_ops.process_document(self, document_ids, cancel_check=cancel_check)

    def _resolve_preflight_document_ids(self, document_ids: list[int] | None) -> list[int] | None:
        return bootstrap_ops.resolve_preflight_document_ids(self, document_ids)

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
        translation_ops.update_chunk_records(self, chunk_records)

    def _build_doc_type_by_id(self, document_ids: list[int] | None) -> dict[int, str]:
        return translation_ops.build_doc_type_by_id(self, document_ids)

    def _resolve_export_lines(
        self,
        document: Document,
        *,
        allow_original_fallback: bool,
    ) -> list[str]:
        return export_ops.resolve_export_lines(self, document, allow_original_fallback=allow_original_fallback)

    async def materialize_document_translation_state(
        self,
        document: Document,
        *,
        allow_original_fallback: bool = False,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        await export_ops.materialize_document_translation_state(
            self,
            document,
            allow_original_fallback=allow_original_fallback,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )

    async def _apply_export_text(
        self,
        document: Document,
        *,
        allow_original_fallback: bool,
        cancel_check: Callable[[], bool] | None,
        progress_callback: ProgressCallback | None,
    ) -> None:
        await export_ops.apply_export_text(
            self,
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
        return import_ops.resolve_import_class(
            self,
            classes,
            path,
            document_type=document_type,
            cancel_check=cancel_check,
        )

    def _import_with_class(
        self,
        document_class: type[Document],
        path: Path,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, int | None]:
        return import_ops.import_with_class(self, document_class, path, cancel_check=cancel_check)

    async def build_glossary(
        self,
        document_ids: list[int] | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        await glossary_ops.build_glossary(
            self,
            document_ids=document_ids,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )

    async def translate_glossary(
        self,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        await glossary_ops.translate_glossary(
            self,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )

    async def review_terms(
        self,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        await glossary_ops.review_terms(
            self,
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
        await translation_ops.translate(
            self,
            document_ids=document_ids,
            progress_callback=progress_callback,
            force=force,
            skip_context=skip_context,
            cancel_check=cancel_check,
        )

    async def retranslate_chunk(
        self,
        chunk_id: int,
        document_id: int,
        skip_context: bool = False,
        cancel_check: Callable[[], bool] | None = None,
    ) -> str:
        return await translation_ops.retranslate_chunk(
            self,
            chunk_id=chunk_id,
            document_id=document_id,
            skip_context=skip_context,
            cancel_check=cancel_check,
        )

    async def export(
        self,
        file_path: Path,
        export_format: str | None = None,
        document_ids: list[int] | None = None,
        allow_original_fallback: bool = False,
        progress_callback: ProgressCallback | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        await export_ops.export(
            self,
            file_path=file_path,
            export_format=export_format,
            document_ids=document_ids,
            allow_original_fallback=allow_original_fallback,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )

    async def export_preserve_structure(
        self,
        output_folder: Path,
        document_ids: list[int] | None = None,
        allow_original_fallback: bool = False,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        await export_ops.export_preserve_structure(
            self,
            output_folder=output_folder,
            document_ids=document_ids,
            allow_original_fallback=allow_original_fallback,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )

    def _get_lines_with_original_fallback(self, document: Document) -> list[str]:
        return export_ops.get_lines_with_original_fallback(self, document)

    def _resolve_imported_document_id(
        self,
        existing_document_ids: set[int],
        imported_count: int,
    ) -> int | None:
        return import_ops.resolve_imported_document_id(self, existing_document_ids, imported_count)

    def import_path(
        self,
        path: Path,
        document_type: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, int | None]:
        return import_ops.import_path(
            self,
            path=path,
            document_type=document_type,
            cancel_check=cancel_check,
        )
