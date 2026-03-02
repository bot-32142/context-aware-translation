"""Worker for async manga translation task run/cancel operations."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from context_aware_translation.core.cancellation import OperationCancelledError
from context_aware_translation.core.progress import ProgressUpdate
from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.task_store import TaskStore
from context_aware_translation.ui.workers.base_worker import BaseWorker
from context_aware_translation.workflow.ops import translation_ops
from context_aware_translation.workflow.session import WorkflowSession

logger = logging.getLogger(__name__)


class TranslationMangaTaskWorker(BaseWorker):
    """Worker to run/cancel persistent manga translation tasks."""

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
        enable_polish: bool = True,
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
        self._enable_polish = enable_polish
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

    def _run_translation(self) -> None:
        if self._task_store is not None and self._task_id is not None:
            self._task_store.update(self._task_id, status="running")
        self._notify()
        try:
            if self._config_snapshot_json:
                session_ctx = WorkflowSession.from_snapshot(self._config_snapshot_json, self._book_id)
            else:
                session_ctx = WorkflowSession.from_book(self._book_manager, self._book_id)
            with session_ctx as context:
                translator_config = context.config.translator_config
                if translator_config is not None:
                    translator_config.enable_polish = self._enable_polish
                asyncio.run(
                    translation_ops.translate(
                        context,
                        document_ids=self._document_ids,
                        progress_callback=self._on_progress,
                        force=self._force,
                        skip_context=self._skip_context,
                        cancel_check=self._is_cancelled,
                    )
                )
            if self._task_store is not None and self._task_id is not None:
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
