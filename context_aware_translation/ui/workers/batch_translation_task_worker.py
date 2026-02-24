"""Worker for async translation batch-task operations."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from typing import Any

from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.translation_batch_task_store import TranslationBatchTaskStore
from context_aware_translation.workflow.batch_translation_task_service import BatchTranslationTaskService
from context_aware_translation.workflow.session import WorkflowSession

from .base_worker import BaseWorker
from .batch_task_overlap_guard import has_any_batch_task_overlap
from .operation_tracker import DocumentOperationTracker

logger = logging.getLogger(__name__)


class BatchTranslationTaskWorker(BaseWorker):
    """Worker to create/list/run/cancel/delete persistent translation batch tasks."""

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
    ) -> None:
        super().__init__()
        self.book_manager = book_manager
        self.book_id = book_id
        self.action = action
        self.task_id = task_id
        self.document_ids = document_ids
        self.force = force
        self.skip_context = skip_context

    @classmethod
    def is_run_active_for_book(cls, book_id: str) -> bool:
        return DocumentOperationTracker.is_any_active_for_book(book_id)

    def _resolve_run_document_ids(self) -> list[int] | None:
        """Resolve document IDs for a 'run' action from the task record."""
        if self.document_ids is not None:
            return self.document_ids
        if self.task_id:
            store_path = self.book_manager.get_book_db_path(self.book_id).parent / "translation_batch_tasks.db"
            store = TranslationBatchTaskStore(store_path)
            try:
                task = store.get(self.task_id)
            finally:
                store.close()
            if task and task.document_ids_json:
                try:
                    parsed = json.loads(task.document_ids_json)
                    if isinstance(parsed, list):
                        return [int(doc_id) for doc_id in parsed]
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
        return None  # fallback: assume all docs (conservative)

    def run(self) -> None:
        op_id = None
        doc_ids = None
        if self.action in {"create", "run"}:
            doc_ids = self.document_ids if self.action == "create" else self._resolve_run_document_ids()
            op_id = DocumentOperationTracker.try_start_operation(self.book_id, doc_ids)
            if op_id is None:
                logger.info(
                    "Skipping batch %s for %s due to active selected-doc overlap",
                    self.action,
                    self.book_id,
                )
                self.error.emit("Selected documents have active operations. Please wait for them to complete.")
                return
        try:
            if op_id is not None:
                exclude = {self.task_id} if self.action == "run" and self.task_id else set()
                if has_any_batch_task_overlap(
                    self.book_manager,
                    self.book_id,
                    doc_ids,
                    exclude_task_ids=exclude or None,
                ):
                    logger.info(
                        "Skipping batch %s for %s due to existing batch-task reservation",
                        self.action,
                        self.book_id,
                    )
                    self.error.emit(
                        "Selected documents are reserved by existing batch tasks. Delete overlapping task(s) first."
                    )
                    return
            super().run()
        finally:
            if op_id is not None:
                DocumentOperationTracker.finish_operation(self.book_id, op_id)

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
