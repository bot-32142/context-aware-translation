from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from context_aware_translation.workflow.tasks.claims import (
    AllDocuments,
    ClaimMode,
    DocumentScope,
    ResourceClaim,
    SomeDocuments,
)
from context_aware_translation.workflow.tasks.execution.batch_translation_ops import decode_task_payload
from context_aware_translation.workflow.tasks.models import (
    STATUS_CANCEL_REQUESTED,
    STATUS_CANCELLED,
    STATUS_CANCELLING,
    STATUS_COMPLETED,
    STATUS_COMPLETED_WITH_ERRORS,
    STATUS_FAILED,
    STATUS_PAUSED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    TERMINAL_TASK_STATUSES,
    Decision,
    TaskAction,
)

if TYPE_CHECKING:
    from context_aware_translation.storage.task_store import TaskRecord
    from context_aware_translation.workflow.tasks.handlers.base import CancelDispatchPolicy, CancelOutcome
    from context_aware_translation.workflow.tasks.models import ActionSnapshot
    from context_aware_translation.workflow.tasks.worker_deps import WorkerDeps


_RERUNNABLE_TERMINAL_STATUSES = frozenset({STATUS_CANCELLED, STATUS_FAILED, STATUS_COMPLETED_WITH_ERRORS})
_NON_DELETABLE_STATUSES = frozenset({STATUS_RUNNING, STATUS_CANCEL_REQUESTED, STATUS_CANCELLING})


class ChunkRetranslationHandler:
    task_type = "chunk_retranslation"

    def decode_payload(self, record: TaskRecord) -> dict[str, Any]:
        return decode_task_payload(record)

    def scope(self, record: TaskRecord, payload: Any) -> DocumentScope:
        doc_id: int | None = (payload or {}).get("document_id")
        if doc_id is not None:
            return SomeDocuments(record.book_id, frozenset({int(doc_id)}))
        # Fallback: parse from document_ids_json if present
        if record.document_ids_json:
            try:
                ids = json.loads(record.document_ids_json)
                if isinstance(ids, list) and ids:
                    return SomeDocuments(record.book_id, frozenset(int(i) for i in ids))
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        return AllDocuments(record.book_id)

    def claims(self, record: TaskRecord, payload: Any) -> frozenset[ResourceClaim]:
        book_id = record.book_id
        doc_id: int | None = (payload or {}).get("document_id")
        chunk_id: int | None = (payload or {}).get("chunk_id")
        claims: set[ResourceClaim] = set()
        if doc_id is not None:
            # Allow parallel chunk retranslation within the same document while still
            # conflicting with document-wide WRITE_EXCLUSIVE operations.
            claims.add(ResourceClaim("doc", book_id, str(doc_id), ClaimMode.WRITE_COOPERATIVE))
        else:
            claims.add(ResourceClaim("doc", book_id, "*"))
        if chunk_id is not None:
            # Prevent duplicate concurrent retranslation for the exact same chunk.
            claims.add(ResourceClaim("chunk", book_id, str(chunk_id)))
        claims.add(ResourceClaim("glossary_state", book_id, "*", ClaimMode.READ_SHARED))
        claims.add(ResourceClaim("context_tree", book_id, "*", ClaimMode.WRITE_COOPERATIVE))
        return frozenset(claims)

    def can(self, action: TaskAction, record: TaskRecord, payload: Any, snapshot: ActionSnapshot) -> Decision:
        status = record.status

        if action == TaskAction.RUN:
            if status in _RERUNNABLE_TERMINAL_STATUSES:
                return Decision(allowed=True)
            if status in {STATUS_QUEUED, STATUS_PAUSED}:
                return Decision(allowed=True)
            if status == STATUS_RUNNING:
                return Decision(allowed=False, reason="Task is already running")
            if status == STATUS_CANCEL_REQUESTED:
                return Decision(allowed=False, reason="Cancel requested, cannot run")
            if status == STATUS_CANCELLING:
                return Decision(allowed=False, reason="Task is being cancelled")
            if status == STATUS_COMPLETED:
                return Decision(allowed=False, reason="Task already completed")
            return Decision(allowed=False, reason=f"Cannot run task with status: {status}")

        if action == TaskAction.CANCEL:
            if status in TERMINAL_TASK_STATUSES:
                return Decision(allowed=False, reason="Task is already in terminal state")
            return Decision(allowed=True)

        if action == TaskAction.DELETE:
            if status in _NON_DELETABLE_STATUSES:
                return Decision(allowed=False, reason="Cannot delete active task")
            return Decision(allowed=True)

        raise ValueError(f"Unknown action: {action!r}")

    def can_autorun(self, record: TaskRecord, payload: Any, snapshot: ActionSnapshot) -> Decision:
        # Chunk retranslation is an interactive operation — no crash resume.
        # Uses submit_and_start() which guarantees immediate start or failure.
        return Decision(allowed=False, reason="Chunk retranslation is interactive-only")

    def validate_submit(self, book_id: str, params: dict, deps: WorkerDeps) -> Decision:
        chunk_id = params.get("chunk_id")
        document_id = params.get("document_id")
        if chunk_id is None:
            return Decision(allowed=False, reason="chunk_id is required for chunk_retranslation")
        if document_id is None:
            return Decision(allowed=False, reason="document_id is required for chunk_retranslation")
        # Verify chunk exists in DB
        from context_aware_translation.storage.book_db import SQLiteBookDB

        db_path = deps.book_manager.get_book_db_path(book_id)
        try:
            db = SQLiteBookDB(db_path)
        except Exception:
            return Decision(allowed=False, reason="Cannot open book database.")
        try:
            chunk = db.get_chunk_by_id(int(chunk_id))
            if chunk is None:
                return Decision(allowed=False, reason=f"Chunk {chunk_id} not found in database.")
            if chunk.document_id != int(document_id):
                return Decision(
                    allowed=False,
                    reason=f"Chunk {chunk_id} belongs to document {chunk.document_id}, not {document_id}.",
                )
        finally:
            db.close()
        return Decision(allowed=True)

    def validate_run(self, record: TaskRecord, payload: Any, deps: WorkerDeps) -> Decision:
        chunk_id = (payload or {}).get("chunk_id")
        document_id = (payload or {}).get("document_id")
        if chunk_id is None:
            return Decision(allowed=False, reason="chunk_id missing from task payload")
        if document_id is None:
            return Decision(allowed=False, reason="document_id missing from task payload")
        return Decision(allowed=True)

    def build_worker(self, action: TaskAction, record: TaskRecord, payload: Any, deps: WorkerDeps) -> object:
        from context_aware_translation.ui.workers.chunk_retranslation_task_worker import ChunkRetranslationTaskWorker

        p = payload or {}
        chunk_id: int = int(p["chunk_id"])
        document_id: int = int(p["document_id"])
        skip_context: bool = bool(p.get("skip_context", False))

        if action == TaskAction.RUN:
            return ChunkRetranslationTaskWorker(
                deps.book_manager,
                record.book_id,
                action="run",
                task_id=record.task_id,
                chunk_id=chunk_id,
                document_id=document_id,
                skip_context=skip_context,
                task_store=deps.task_store,
                notify_task_changed=deps.notify_task_changed,
                config_snapshot_json=record.config_snapshot_json,
            )

        if action == TaskAction.CANCEL:
            return ChunkRetranslationTaskWorker(
                deps.book_manager,
                record.book_id,
                action="cancel",
                task_id=record.task_id,
                chunk_id=chunk_id,
                document_id=document_id,
                task_store=deps.task_store,
                notify_task_changed=deps.notify_task_changed,
            )

        raise ValueError(f"Unsupported action for ChunkRetranslationHandler: {action!r}")

    def cancel_dispatch_policy(self, record: TaskRecord, payload: Any) -> CancelDispatchPolicy:
        from context_aware_translation.workflow.tasks.handlers.base import CancelDispatchPolicy

        return CancelDispatchPolicy.LOCAL_TERMINALIZE

    def classify_cancel_outcome(self, record: TaskRecord, payload: Any, provider_result: Any) -> CancelOutcome:
        from context_aware_translation.workflow.tasks.handlers.base import CancelOutcome

        return CancelOutcome.CONFIRMED_CANCELLED

    def pre_delete(self, record: TaskRecord, payload: Any, deps: WorkerDeps) -> list[str]:
        return []
