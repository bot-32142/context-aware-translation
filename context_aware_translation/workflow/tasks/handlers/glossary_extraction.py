from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from context_aware_translation.workflow.tasks.claims import (
    AllDocuments,
    ClaimArbiter,
    ClaimMode,
    DocumentScope,
    ResourceClaim,
    SomeDocuments,
)
from context_aware_translation.workflow.tasks.execution.batch_translation_ops import decode_task_payload
from context_aware_translation.workflow.tasks.glossary_preflight import (
    compute_glossary_preflight,
    resolve_effective_pending_ids,
)
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
    from context_aware_translation.workflow.tasks.models import ActionSnapshot
    from context_aware_translation.workflow.tasks.worker_deps import WorkerDeps


_RERUNNABLE_TERMINAL_STATUSES = frozenset({STATUS_CANCELLED, STATUS_FAILED, STATUS_COMPLETED_WITH_ERRORS})
_NON_DELETABLE_STATUSES = frozenset({STATUS_RUNNING, STATUS_CANCEL_REQUESTED, STATUS_CANCELLING})
_AUTORUN_STATUSES = frozenset({STATUS_QUEUED, STATUS_PAUSED})


def _open_doc_repo(deps: WorkerDeps, book_id: str):
    from context_aware_translation.storage.book_db import SQLiteBookDB
    from context_aware_translation.storage.document_repository import DocumentRepository

    db = SQLiteBookDB(deps.book_manager.get_book_db_path(book_id))
    doc_repo = DocumentRepository(db)
    return db, doc_repo


class GlossaryExtractionHandler:
    task_type = "glossary_extraction"

    def decode_payload(self, record: TaskRecord) -> dict[str, Any]:
        return decode_task_payload(record)

    def scope(self, record: TaskRecord, payload: Any) -> DocumentScope:
        if not record.document_ids_json:
            return AllDocuments(record.book_id)
        try:
            ids = json.loads(record.document_ids_json)
        except (json.JSONDecodeError, TypeError):
            return AllDocuments(record.book_id)
        if not isinstance(ids, list) or not ids:
            return AllDocuments(record.book_id)
        return SomeDocuments(record.book_id, frozenset(int(i) for i in ids))

    def claims(self, record: TaskRecord, payload: Any) -> frozenset[ResourceClaim]:
        book_id = record.book_id
        return frozenset({
            ResourceClaim("glossary_state", book_id, "*", ClaimMode.WRITE_EXCLUSIVE),
        })

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
        if record.status not in _AUTORUN_STATUSES:
            return Decision(allowed=False, reason=f"Status {record.status!r} is not autorunnable")
        if record.task_id in snapshot.running_task_ids:
            return Decision(allowed=False, reason="Already running")
        wanted = self.claims(record, payload)
        arbiter = ClaimArbiter()
        if arbiter.conflicts(wanted, snapshot.active_claims):
            return Decision(allowed=False, reason="Claims conflict with active tasks")
        return Decision(allowed=True)

    def validate_submit(self, book_id: str, params: dict, deps: WorkerDeps) -> Decision:
        db, doc_repo = _open_doc_repo(deps, book_id)
        try:
            requested_ids: list[int] | None = params.get("document_ids")
            effective_ids, stale_ids = resolve_effective_pending_ids(requested_ids, doc_repo)

            if stale_ids:
                return Decision(
                    allowed=False,
                    code="stale_selection",
                    reason=f"Selected document(s) are no longer pending: {stale_ids}",
                )

            if not effective_ids:
                return Decision(
                    allowed=False,
                    code="no_pending_documents",
                    reason="No documents are pending glossary build.",
                )

            selected_cutoff: int | None = params.get("cutoff_doc_id")
            preflight = compute_glossary_preflight(effective_ids, selected_cutoff, doc_repo)

            if preflight.is_blocked:
                joined = ", ".join(str(d) for d in preflight.blocking_ocr_doc_ids)
                return Decision(
                    allowed=False,
                    code="blocked_ocr_pending",
                    reason=(
                        f"Cannot build glossary because earlier OCR-required document(s) are still "
                        f"pending OCR: {joined}."
                    ),
                )
        finally:
            db.close()

        return Decision(allowed=True)

    def validate_run(self, record: TaskRecord, payload: Any, deps: WorkerDeps) -> Decision:
        book_id = record.book_id
        db, doc_repo = _open_doc_repo(deps, book_id)
        try:
            requested_ids: list[int] | None = None
            if record.document_ids_json:
                try:
                    parsed = json.loads(record.document_ids_json)
                    if isinstance(parsed, list):
                        requested_ids = [int(i) for i in parsed]
                except (json.JSONDecodeError, TypeError, ValueError):
                    requested_ids = None

            effective_ids, stale_ids = resolve_effective_pending_ids(requested_ids, doc_repo)

            if stale_ids:
                return Decision(
                    allowed=False,
                    code="stale_selection",
                    reason=f"Selected document(s) are no longer pending: {stale_ids}",
                )

            if not effective_ids:
                return Decision(
                    allowed=False,
                    code="no_pending_documents",
                    reason="No documents are pending glossary build.",
                )

            selected_cutoff: int | None = (payload or {}).get("cutoff_doc_id")
            preflight = compute_glossary_preflight(effective_ids, selected_cutoff, doc_repo)

            if preflight.is_blocked:
                joined = ", ".join(str(d) for d in preflight.blocking_ocr_doc_ids)
                return Decision(
                    allowed=False,
                    code="blocked_ocr_pending",
                    reason=(
                        f"Cannot build glossary because earlier OCR-required document(s) are still "
                        f"pending OCR: {joined}."
                    ),
                )
        finally:
            db.close()

        return Decision(allowed=True)

    def build_worker(self, action: TaskAction, record: TaskRecord, payload: Any, deps: WorkerDeps):
        from context_aware_translation.ui.workers.glossary_extraction_task_worker import GlossaryExtractionTaskWorker

        doc_ids: list[int] | None = None
        if record.document_ids_json:
            try:
                parsed = json.loads(record.document_ids_json)
                if isinstance(parsed, list):
                    doc_ids = [int(i) for i in parsed]
            except (json.JSONDecodeError, TypeError, ValueError):
                doc_ids = None

        if action == TaskAction.RUN:
            return GlossaryExtractionTaskWorker(
                deps.book_manager,
                record.book_id,
                action="run",
                task_id=record.task_id,
                document_ids=doc_ids,
                task_store=deps.task_store,
                notify_task_changed=deps.notify_task_changed,
                config_snapshot_json=record.config_snapshot_json,
            )

        if action == TaskAction.CANCEL:
            return GlossaryExtractionTaskWorker(
                deps.book_manager,
                record.book_id,
                action="cancel",
                task_id=record.task_id,
                task_store=deps.task_store,
                notify_task_changed=deps.notify_task_changed,
            )

        raise ValueError(f"Unsupported action for GlossaryExtractionHandler: {action!r}")

    def cancel_dispatch_policy(self, record: TaskRecord, payload: Any):
        from context_aware_translation.workflow.tasks.handlers.base import CancelDispatchPolicy
        return CancelDispatchPolicy.LOCAL_TERMINALIZE

    def classify_cancel_outcome(self, record: TaskRecord, payload: Any, provider_result: Any):
        from context_aware_translation.workflow.tasks.handlers.base import CancelOutcome
        return CancelOutcome.CONFIRMED_CANCELLED

    def pre_delete(self, record: TaskRecord, payload: Any, deps: WorkerDeps) -> list[str]:
        return []
