"""Worker for async image reembedding task run/cancel operations."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from context_aware_translation.core.cancellation import OperationCancelledError
from context_aware_translation.core.progress import ProgressUpdate
from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.task_store import TaskStore
from context_aware_translation.workflow.ops import bootstrap_ops, export_ops
from context_aware_translation.workflow.runtime import WorkflowContext
from context_aware_translation.workflow.session import WorkflowSession

from .base_worker import BaseWorker

logger = logging.getLogger(__name__)


class ImageReembeddingTaskWorker(BaseWorker):
    """Worker to run/cancel persistent image-reembedding tasks."""

    def __init__(
        self,
        book_manager: BookManager,
        book_id: str,
        *,
        action: str,
        task_id: str | None = None,
        document_ids: list[int] | None = None,
        source_ids: list[int] | None = None,
        force: bool = False,
        task_store: TaskStore | None = None,
        notify_task_changed: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self._book_manager = book_manager
        self._book_id = book_id
        self._action = action
        self._task_id = task_id
        self._document_ids = document_ids
        self._source_ids = source_ids
        self._force = force
        self._task_store = task_store
        self._notify_task_changed = notify_task_changed

    def _execute(self) -> None:
        if self._action == "run":
            self._run_reembedding()
            return
        if self._action == "cancel":
            self._run_cancel()
            return
        raise ValueError(f"Unknown action: {self._action!r}")

    def _run_reembedding(self) -> None:
        if self._task_store is not None and self._task_id is not None:
            self._task_store.update(self._task_id, status="running")
        self._notify()
        try:
            session_ctx = WorkflowSession.from_book(self._book_manager, self._book_id)
            with session_ctx as svc:
                asyncio.run(self._do_reembedding(svc))
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

    async def _do_reembedding(self, context: WorkflowContext) -> None:
        docs = bootstrap_ops.load_documents(context, self._document_ids)
        for doc in docs:
            await export_ops.materialize_document_translation_state(
                context,
                doc,
                allow_original_fallback=True,
                cancel_check=self._is_cancelled,
                progress_callback=self._on_progress,
            )
            await doc.reembed(
                context.config.image_reembedding_config,
                force=self._force,
                source_ids=self._source_ids,
                cancel_check=self._is_cancelled,
                progress_callback=self._on_progress,
            )

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
