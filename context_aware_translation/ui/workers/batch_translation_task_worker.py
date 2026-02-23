"""Worker for async translation batch-task operations."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import asdict
from typing import Any

from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.workflow.batch_translation_task_service import BatchTranslationTaskService
from context_aware_translation.workflow.session import WorkflowSession

from .base_worker import BaseWorker


class BatchTranslationTaskWorker(BaseWorker):
    """Worker to create/list/run/cancel/delete persistent translation batch tasks."""

    # Class-level shared state: intentionally shared across all instances so the
    # application can globally track which books have an active "run" worker,
    # preventing duplicate concurrent runs for the same book.
    _run_lock = threading.Lock()
    _active_run_counts: dict[str, int] = {}

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
        auto_run_after_create: bool = False,
    ) -> None:
        super().__init__()
        self.book_manager = book_manager
        self.book_id = book_id
        self.action = action
        self.task_id = task_id
        self.document_ids = document_ids
        self.force = force
        self.skip_context = skip_context
        self.auto_run_after_create = auto_run_after_create

    @classmethod
    def _mark_run_started(cls, book_id: str) -> None:
        with cls._run_lock:
            cls._active_run_counts[book_id] = cls._active_run_counts.get(book_id, 0) + 1

    @classmethod
    def _mark_run_finished(cls, book_id: str) -> None:
        with cls._run_lock:
            count = cls._active_run_counts.get(book_id, 0) - 1
            if count > 0:
                cls._active_run_counts[book_id] = count
            else:
                cls._active_run_counts.pop(book_id, None)

    @classmethod
    def is_run_active_for_book(cls, book_id: str) -> bool:
        with cls._run_lock:
            return cls._active_run_counts.get(book_id, 0) > 0

    def run(self) -> None:
        is_run_action = self.action == "run"
        if is_run_action:
            self._mark_run_started(self.book_id)
        try:
            super().run()
        finally:
            if is_run_action:
                self._mark_run_finished(self.book_id)

    @staticmethod
    def _record_to_payload(record: Any) -> dict[str, Any]:
        if hasattr(record, "__dataclass_fields__"):
            return asdict(record)
        if isinstance(record, dict):
            return record
        return {"value": record}

    def _execute(self) -> None:
        self._raise_if_cancelled()
        session_manager = WorkflowSession.from_book(self.book_manager, self.book_id)
        with session_manager as session:
            service = BatchTranslationTaskService.from_workflow(session)
            try:
                if self.action == "list":
                    records = service.list_tasks()
                    payload = [self._record_to_payload(record) for record in records]
                    self.finished_success.emit({"action": "list", "tasks": payload})
                    return

                if self.action == "create":
                    record = service.create_task(
                        document_ids=self.document_ids,
                        force=self.force,
                        skip_context=self.skip_context,
                    )
                    if self.auto_run_after_create:
                        record = asyncio.run(
                            service.run_task(
                                record.task_id,
                                cancel_check=self._is_cancelled,
                                progress_callback=self._emit_progress,
                            )
                        )
                    self.finished_success.emit({"action": "create", "task": self._record_to_payload(record)})
                    return

                if self.action == "run":
                    if not self.task_id:
                        raise ValueError("task_id is required for action='run'.")
                    record = asyncio.run(
                        service.run_task(
                            self.task_id,
                            cancel_check=self._is_cancelled,
                            progress_callback=self._emit_progress,
                        )
                    )
                    self.finished_success.emit({"action": "run", "task": self._record_to_payload(record)})
                    return

                if self.action == "cancel":
                    if not self.task_id:
                        raise ValueError("task_id is required for action='cancel'.")
                    record = asyncio.run(service.request_cancel(self.task_id))
                    self.finished_success.emit({"action": "cancel", "task": self._record_to_payload(record)})
                    return

                if self.action == "delete":
                    if not self.task_id:
                        raise ValueError("task_id is required for action='delete'.")
                    result = service.delete_task(self.task_id)
                    payload = {"action": "delete", "task_id": self.task_id}
                    if isinstance(result, dict):
                        payload.update(result)
                    self.finished_success.emit(payload)
                    return

                raise ValueError(f"Unsupported batch task worker action: {self.action}")
            finally:
                service.close()
