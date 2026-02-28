"""Worker for async translation-text task run/cancel operations."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from context_aware_translation.core.cancellation import OperationCancelledError
from context_aware_translation.core.progress import ProgressUpdate
from context_aware_translation.storage.book_db import SQLiteBookDB
from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.document_repository import DocumentRepository
from context_aware_translation.storage.task_store import TaskStore
from context_aware_translation.workflow.services import translation_ops
from context_aware_translation.workflow.session import WorkflowSession
from context_aware_translation.workflow.tasks.models import STATUS_COMPLETED_WITH_ERRORS

from .base_worker import BaseWorker

logger = logging.getLogger(__name__)

_MANGA_DOCUMENT_TYPE = "manga"
_REEMBEDDABLE_DOCUMENT_TYPES = frozenset({"pdf", "scanned_book", "manga", "epub"})


class TranslationTextTaskWorker(BaseWorker):
    """Worker to run/cancel persistent translation-text tasks (non-manga documents only)."""

    def __init__(
        self,
        book_manager: BookManager,
        book_id: str,
        *,
        action: str,
        task_id: str | None = None,
        document_ids: list[int] | None = None,
        force: bool = False,
        skip_context: bool = False,
        task_store: TaskStore | None = None,
        notify_task_changed: Callable[[str], None] | None = None,
        config_snapshot_json: str | None = None,
        enqueue_followup: Callable[..., None] | None = None,
    ) -> None:
        super().__init__()
        self._book_manager = book_manager
        self._book_id = book_id
        self._action = action
        self._task_id = task_id
        self._document_ids = document_ids
        self._force = force
        self._skip_context = skip_context
        self._task_store = task_store
        self._notify_task_changed = notify_task_changed
        self._config_snapshot_json = config_snapshot_json
        self._enqueue_followup = enqueue_followup

    def _execute(self) -> None:
        if self._action == "run":
            self._run_translation()
            return
        if self._action == "cancel":
            self._run_cancel()
            return
        raise ValueError(f"Unknown action: {self._action!r}")

    def _filter_non_manga_ids(self, doc_ids: list[int]) -> list[int]:
        """Return only non-manga document IDs from the given list."""
        try:
            db_path = self._book_manager.get_book_db_path(self._book_id)
            db = SQLiteBookDB(db_path)
            try:
                repo = DocumentRepository(db)
                result = []
                for doc_id in doc_ids:
                    row = repo.get_document_by_id(doc_id)
                    if row and row.get("document_type") != _MANGA_DOCUMENT_TYPE:
                        result.append(doc_id)
                return result
            finally:
                db.close()
        except Exception:
            logger.warning("Could not filter manga document IDs; using all IDs as-is", exc_info=True)
            return doc_ids

    def _resolve_reembedding_document_ids(self, doc_ids: list[int] | None) -> list[int]:
        """Return reembeddable document IDs within the provided scope."""
        try:
            db_path = self._book_manager.get_book_db_path(self._book_id)
            db = SQLiteBookDB(db_path)
            try:
                repo = DocumentRepository(db)
                documents = repo.list_documents()
                selected = set(doc_ids) if doc_ids is not None else None
                resolved: list[int] = []
                for doc in documents:
                    doc_id = int(doc["document_id"])
                    if selected is not None and doc_id not in selected:
                        continue
                    if doc.get("document_type") in _REEMBEDDABLE_DOCUMENT_TYPES:
                        resolved.append(doc_id)
                return resolved
            finally:
                db.close()
        except Exception:
            logger.warning("Could not resolve reembedding document IDs; skipping follow-up", exc_info=True)
            return []

    def _run_translation(self) -> None:
        if self._task_store is not None and self._task_id is not None:
            self._task_store.update(self._task_id, status="running")
        self._notify()
        followup_error: str | None = None
        try:
            # Filter out manga documents when specific IDs are provided
            effective_doc_ids = self._document_ids
            if effective_doc_ids is not None:
                effective_doc_ids = self._filter_non_manga_ids(effective_doc_ids)

            if self._config_snapshot_json:
                session_ctx = WorkflowSession.from_snapshot(self._config_snapshot_json, self._book_id)
            else:
                session_ctx = WorkflowSession.from_book(self._book_manager, self._book_id)
            with session_ctx as context:
                asyncio.run(
                    translation_ops.translate(
                        context,
                        document_ids=effective_doc_ids,
                        progress_callback=self._on_progress,
                        force=self._force,
                        skip_context=self._skip_context,
                        cancel_check=self._is_cancelled,
                    )
                )
            # Auto-chain: enqueue image reembedding if enabled
            if self._enqueue_followup is not None:
                try:
                    book = self._book_manager.get_book(self._book_id)
                    if book is not None:
                        from context_aware_translation.config import Config

                        config = Config.from_book(book, self._book_manager.library_root, self._book_manager.registry)
                        if (
                            config.image_reembedding_config is not None
                            and config.ocr_config is not None
                            and config.ocr_config.enable_image_reembedding
                        ):
                            reembed_doc_ids = self._resolve_reembedding_document_ids(effective_doc_ids)
                            if not reembed_doc_ids:
                                logger.debug(
                                    "Skipping auto-chain reembedding for book %s: no reembeddable documents",
                                    self._book_id,
                                )
                            else:
                                self._enqueue_followup(
                                    "image_reembedding",
                                    self._book_id,
                                    document_ids=reembed_doc_ids,
                                )
                except Exception:
                    followup_error = "Follow-up image reembedding enqueue failed. Check logs for details."
                    logger.warning("Failed to enqueue follow-up reembedding for book %s", self._book_id, exc_info=True)
            if self._task_store is not None and self._task_id is not None:
                if followup_error:
                    self._task_store.update(
                        self._task_id,
                        status=STATUS_COMPLETED_WITH_ERRORS,
                        last_error=followup_error,
                    )
                else:
                    self._task_store.update(self._task_id, status="completed")
                    self._task_store.update(self._task_id, last_error=None)
            self.finished_success.emit({"action": "run", "task_id": self._task_id})
        except OperationCancelledError:
            if self._task_store is not None and self._task_id is not None:
                self._task_store.update(self._task_id, status="cancelled", cancel_requested=False)
            raise  # Let BaseWorker.run() emit cancelled signal
        except Exception as exc:
            if self._task_store is not None and self._task_id is not None:
                self._task_store.update(self._task_id, status="failed", last_error=str(exc))
            raise  # Let BaseWorker.run() emit error signal
        finally:
            self._notify()

    def _run_cancel(self) -> None:
        if self._task_store is not None and self._task_id is not None:
            self._task_store.update(self._task_id, status="cancelled", cancel_requested=False)
        self._notify()

    def _on_progress(self, update: ProgressUpdate) -> None:
        self._raise_if_cancelled()
        if self._task_store is not None and self._task_id is not None:
            self._task_store.update(
                self._task_id,
                completed_items=update.current,
                total_items=update.total,
            )
        self._notify()

    def _notify(self) -> None:
        if self._notify_task_changed is not None:
            self._notify_task_changed(self._book_id)
