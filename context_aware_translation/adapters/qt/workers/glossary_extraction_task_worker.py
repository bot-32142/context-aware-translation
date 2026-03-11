"""Worker for async glossary extraction task run/cancel operations."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from context_aware_translation.adapters.qt.workers.base_worker import BaseWorker
from context_aware_translation.core.cancellation import OperationCancelledError
from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.repositories.task_store import TaskStore
from context_aware_translation.workflow.ops import glossary_ops
from context_aware_translation.workflow.session import WorkflowSession

logger = logging.getLogger(__name__)


class GlossaryExtractionTaskWorker(BaseWorker):
    """Worker to run/cancel persistent glossary extraction tasks."""

    def __init__(
        self,
        book_manager: BookManager,
        book_id: str,
        *,
        action: str,
        task_id: str | None = None,
        document_ids: list[int] | None = None,
        task_store: TaskStore | None = None,
        notify_task_changed: Callable[[str], None] | None = None,
        config_snapshot_json: str | None = None,
    ) -> None:
        super().__init__()
        self._book_manager = book_manager
        self._book_id = book_id
        self._action = action
        self._task_id = task_id
        self._document_ids = document_ids
        self._task_store = task_store
        self._notify_task_changed = notify_task_changed
        self._config_snapshot_json = config_snapshot_json

    def _execute(self) -> None:
        if self._action == "run":
            self._run_extraction()
            return
        if self._action == "cancel":
            self._run_cancel()
            return
        raise ValueError(f"Unknown action: {self._action!r}")

    def _run_extraction(self) -> None:
        if self._task_store is not None and self._task_id is not None:
            self._task_store.update(self._task_id, status="running")
        self._notify()
        try:
            if self._config_snapshot_json:
                session_ctx = WorkflowSession.from_snapshot(self._config_snapshot_json, self._book_id)
            else:
                session_ctx = WorkflowSession.from_book(self._book_manager, self._book_id)
            with session_ctx as context:
                asyncio.run(
                    glossary_ops.build_glossary(
                        context,
                        document_ids=self._document_ids,
                        progress_callback=self._on_progress,
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

    def _on_progress(self, update) -> None:
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
