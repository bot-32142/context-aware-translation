"""Worker for async translation batch-task run/cancel operations."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.task_store import TaskStore
from context_aware_translation.workflow.session import WorkflowSession
from context_aware_translation.workflow.tasks.execution.batch_translation_executor import BatchTranslationExecutor

from .base_worker import BaseWorker
from .batch_task_overlap_guard import has_any_batch_task_overlap
from .operation_tracker import DocumentOperationTracker

logger = logging.getLogger(__name__)


class BatchTranslationTaskWorker(BaseWorker):
    """Worker to run/cancel persistent translation batch tasks."""

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
    ) -> None:
        super().__init__()
        self.book_manager = book_manager
        self.book_id = book_id
        self.action = action
        self.task_id = task_id
        self.document_ids = document_ids
        self.force = force
        self.skip_context = skip_context
        self.task_store = task_store
        self.notify_task_changed = notify_task_changed
        self.config_snapshot_json = config_snapshot_json

    @classmethod
    def is_run_active_for_book(cls, book_id: str) -> bool:
        return DocumentOperationTracker.is_any_active_for_book(book_id)

    def _resolve_run_document_ids(self) -> list[int] | None:
        """Resolve document IDs for a 'run' action from the task record."""
        if self.document_ids is not None:
            return self.document_ids
        if self.task_id and self.task_store is not None:
            task = self.task_store.get(self.task_id)
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
        if self.action in {"run"}:
            doc_ids = self._resolve_run_document_ids()
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
                if self.task_store is not None and has_any_batch_task_overlap(
                    self.task_store,
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

    def _should_fallback_to_live_config_on_snapshot_error(self) -> bool:
        """Allow live-config fallback only for cancellation flows."""
        if self.action == "cancel":
            return True
        if self.action != "run" or self.task_store is None or not self.task_id:
            return False
        try:
            task = self.task_store.get(self.task_id)
        except Exception:
            logger.warning("Could not load task %s to evaluate snapshot fallback policy", self.task_id, exc_info=True)
            return False
        if task is None:
            return False
        return getattr(task, "cancel_requested", False) is True

    def _execute(self) -> None:
        self._raise_if_cancelled()
        if self.config_snapshot_json:
            try:
                session_manager = WorkflowSession.from_snapshot(self.config_snapshot_json, self.book_id)
            except Exception as snap_exc:
                if self._should_fallback_to_live_config_on_snapshot_error():
                    logger.warning(
                        "Config snapshot restore failed for task %s (%s action); "
                        "falling back to live config: %s",
                        self.task_id,
                        self.action,
                        snap_exc,
                    )
                    session_manager = WorkflowSession.from_book(self.book_manager, self.book_id)
                else:
                    if self.task_store is not None and self.task_id:
                        try:
                            self.task_store.update(
                                self.task_id,
                                status="failed",
                                last_error=f"Config snapshot restore failed: {snap_exc}",
                            )
                        except Exception:
                            logger.exception(
                                "Failed to mark task %s as failed after snapshot restore error",
                                self.task_id,
                            )
                    raise
        else:
            session_manager = WorkflowSession.from_book(self.book_manager, self.book_id)
        with session_manager as session:
            executor = BatchTranslationExecutor.from_workflow(
                session,
                task_store=self.task_store,
                notify_task_changed=self.notify_task_changed,
            )
            try:
                if self.action == "run":
                    if not self.task_id:
                        raise ValueError("task_id is required for action='run'.")
                    record = asyncio.run(
                        executor.run_task(
                            self.task_id,
                            cancel_check=self._is_cancelled,
                            progress_callback=self._emit_progress,
                        )
                    )
                    # Persist remote_submission_state into payload_json so
                    # cancel_dispatch_policy can inspect it later.
                    if self.task_store is not None and self.task_id:
                        try:
                            current = self.task_store.get(self.task_id)
                            if current is not None:
                                try:
                                    existing_payload = json.loads(current.payload_json or "{}")
                                except (json.JSONDecodeError, TypeError):
                                    existing_payload = {}
                                existing_payload["remote_submission_state"] = "submitted"
                                self.task_store.update(
                                    self.task_id,
                                    payload_json=json.dumps(existing_payload),
                                )
                        except Exception:
                            pass  # Non-fatal: state persistence best-effort
                    self.finished_success.emit({"action": "run", "task": self._record_to_payload(record)})
                    return

                if self.action == "cancel":
                    if not self.task_id:
                        raise ValueError("task_id is required for action='cancel'.")
                    record = asyncio.run(executor.request_cancel(self.task_id))
                    self.finished_success.emit({"action": "cancel", "task": self._record_to_payload(record)})
                    return

                raise ValueError(f"Unsupported batch task worker action: {self.action}")
            finally:
                executor.close()
