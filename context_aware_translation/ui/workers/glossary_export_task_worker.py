"""Worker for async glossary export task run/cancel operations."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from pathlib import Path

from context_aware_translation.core.cancellation import OperationCancelledError
from context_aware_translation.glossary_io import export_glossary
from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.task_store import TaskStore
from context_aware_translation.workflow.session import WorkflowSession

from .base_worker import BaseWorker

logger = logging.getLogger(__name__)


class GlossaryExportTaskWorker(BaseWorker):
    """Worker to run/cancel persistent glossary export tasks."""

    def __init__(
        self,
        book_manager: BookManager,
        book_id: str,
        *,
        action: str,
        task_id: str | None = None,
        task_store: TaskStore | None = None,
        notify_task_changed: Callable[[str], None] | None = None,
        output_path: str | Path,
        skip_context: bool = False,
        config_snapshot_json: str | None = None,
    ) -> None:
        super().__init__()
        self._book_manager = book_manager
        self._book_id = book_id
        self._action = action
        self._task_id = task_id
        self._task_store = task_store
        self._notify_task_changed = notify_task_changed
        self._output_path = Path(output_path) if isinstance(output_path, str) else output_path
        self._skip_context = skip_context
        self._config_snapshot_json = config_snapshot_json

    def _execute(self) -> None:
        if self._action == "run":
            self._run_export()
            return
        if self._action == "cancel":
            self._run_cancel()
            return
        raise ValueError(f"Unknown action: {self._action!r}")

    def _run_export(self) -> None:
        if self._task_store is not None and self._task_id is not None:
            self._task_store.update(self._task_id, status="running")
        self._notify()
        try:
            # Always use live config — glossary export validates against live state
            # at run time, so execution must also use live config (no snapshot fallback).
            session_ctx = WorkflowSession.from_book(self._book_manager, self._book_id)
            with session_ctx as session:
                session.db.refresh()
                summarized_descriptions = self._build_summaries_with_compatible_kwargs(
                    session.manager.build_fully_summarized_descriptions
                )
                self._raise_if_cancelled()
                count = export_glossary(
                    session.db,
                    self._output_path,
                    summarized_descriptions=summarized_descriptions,
                )
            if self._task_store is not None and self._task_id is not None:
                # Get current total_items and ensure it's at least as large as count
                task = self._task_store.get(self._task_id)
                total_items = max(task.total_items if task else 0, count)
                self._task_store.update(
                    self._task_id,
                    status="completed",
                    completed_items=count,
                    total_items=total_items,
                )
            self.finished_success.emit(
                {
                    "count": count,
                    "path": str(self._output_path),
                    "task_id": self._task_id,
                    "action": "run",
                }
            )
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

    def _build_summaries_with_compatible_kwargs(self, build_fn: Callable):
        """Call build_fully_summarized_descriptions with compatible kwarg names.

        Supports both current (`cancel_check`, `progress_callback`, `skip_context`)
        and legacy/underscore-style test doubles.
        """
        try:
            params = inspect.signature(build_fn).parameters
        except (TypeError, ValueError):
            # Unknown callable signature: fall back to positional ordering.
            return build_fn(self._is_cancelled, self._on_progress, self._skip_context)

        has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        kwargs: dict[str, object] = {}

        def put(canonical: str, legacy: str, value: object) -> None:
            if canonical in params or has_varkw:
                kwargs[canonical] = value
            elif legacy in params:
                kwargs[legacy] = value

        put("cancel_check", "_cancel_check", self._is_cancelled)
        put("progress_callback", "_progress_callback", self._on_progress)
        put("skip_context", "_skip_context", self._skip_context)

        if kwargs:
            return build_fn(**kwargs)
        return build_fn(self._is_cancelled, self._on_progress, self._skip_context)
