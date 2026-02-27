"""Worker for async OCR task run/cancel operations."""

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
from context_aware_translation.workflow.session import WorkflowSession

from .base_worker import BaseWorker

logger = logging.getLogger(__name__)


class OCRTaskWorker(BaseWorker):
    """Worker to run/cancel persistent OCR tasks for a single document."""

    def __init__(
        self,
        book_manager: BookManager,
        book_id: str,
        *,
        action: str,
        task_id: str | None = None,
        document_id: int | None = None,
        source_ids: list[int] | None = None,
        task_store: TaskStore | None = None,
        notify_task_changed: Callable[[str], None] | None = None,
        config_snapshot_json: str | None = None,
    ) -> None:
        super().__init__()
        self._book_manager = book_manager
        self._book_id = book_id
        self._action = action
        self._task_id = task_id
        self._document_id = document_id
        self._source_ids = source_ids
        self._task_store = task_store
        self._notify_task_changed = notify_task_changed
        self._config_snapshot_json = config_snapshot_json

    def _execute(self) -> None:
        if self._action == "run":
            self._run_ocr()
            return
        if self._action == "cancel":
            self._run_cancel()
            return
        raise ValueError(f"Unknown action: {self._action!r}")

    def _resolve_source_ids_for_document(self) -> list[int]:
        """Resolve which source IDs to OCR for this document.

        Returns only pending (needs-OCR) source IDs that belong to document_id.
        If source_ids is None, returns all pending sources for the document.
        If source_ids is explicit, validates they belong to this document and
        intersects with the pending set.
        """
        db_path = self._book_manager.get_book_db_path(self._book_id)
        db = SQLiteBookDB(db_path)
        try:
            repo = DocumentRepository(db)
            pending_rows = repo.get_document_sources_needing_ocr(self._document_id)
            pending_ids = {row["source_id"] for row in pending_rows}

            if self._source_ids is None:
                return list(pending_ids)

            # Explicit source_ids: validate they belong to this document by
            # intersecting with the pending set (cross-document IDs are excluded).
            return [sid for sid in self._source_ids if sid in pending_ids]
        finally:
            db.close()

    def _run_ocr(self) -> None:
        if self._task_store is not None and self._task_id is not None:
            self._task_store.update(self._task_id, status="running")
        self._notify()
        try:
            resolved_ids = self._resolve_source_ids_for_document()

            if self._config_snapshot_json:
                session_ctx = WorkflowSession.from_snapshot(self._config_snapshot_json, self._book_id)
            else:
                session_ctx = WorkflowSession.from_book(self._book_manager, self._book_id)
            with session_ctx as session:
                asyncio.run(
                    session.run_ocr(
                        progress_callback=self._on_progress,
                        source_ids=resolved_ids,
                        cancel_check=self._is_cancelled,
                    )
                )
            if self._task_store is not None and self._task_id is not None:
                self._task_store.update(self._task_id, status="completed")
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
