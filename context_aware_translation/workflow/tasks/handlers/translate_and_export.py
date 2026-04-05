from __future__ import annotations

from typing import TYPE_CHECKING, Any

from context_aware_translation.adapters.qt.workers.translate_and_export_task_worker import TranslateAndExportTaskWorker
from context_aware_translation.workflow.tasks.claims import (
    ClaimArbiter,
    ClaimMode,
    DocumentScope,
    ResourceClaim,
    SomeDocuments,
)
from context_aware_translation.workflow.tasks.handlers.base import CancelDispatchPolicy, CancelOutcome
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
from context_aware_translation.workflow.tasks.translate_and_export_support import (
    decode_translate_and_export_payload,
    document_id_from_record,
    validate_translate_and_export_run,
    validate_translate_and_export_submit,
)

if TYPE_CHECKING:
    from context_aware_translation.storage.repositories.task_store import TaskRecord
    from context_aware_translation.workflow.tasks.models import ActionSnapshot
    from context_aware_translation.workflow.tasks.worker_deps import WorkerDeps


_RERUNNABLE_TERMINAL_STATUSES = frozenset({STATUS_CANCELLED, STATUS_FAILED, STATUS_COMPLETED_WITH_ERRORS})
_NON_DELETABLE_STATUSES = frozenset({STATUS_RUNNING, STATUS_CANCEL_REQUESTED, STATUS_CANCELLING})
_AUTORUN_STATUSES = frozenset({STATUS_QUEUED, STATUS_PAUSED})
_BATCH_RESUMABLE_STATUSES = frozenset({STATUS_RUNNING, STATUS_CANCEL_REQUESTED, STATUS_CANCELLING})
_REMOTE_CANCEL_PHASES = frozenset(
    {
        "translation_submit",
        "translation_poll",
        "translation_validate",
        "translation_fallback",
        "polish_submit",
        "polish_poll",
        "polish_validate",
        "polish_fallback",
        "apply",
    }
)


class TranslateAndExportHandler:
    task_type = "translate_and_export"

    @staticmethod
    def _can_resume_batch_phase(record: TaskRecord, payload: Any) -> bool:
        if not bool((payload or {}).get("use_batch", False)):
            return False
        return (record.phase or "") in _REMOTE_CANCEL_PHASES

    def decode_payload(self, record: TaskRecord) -> dict[str, Any]:
        return decode_translate_and_export_payload(record)

    def scope(self, record: TaskRecord, payload: Any) -> DocumentScope:
        return SomeDocuments(record.book_id, frozenset({document_id_from_record(record)}))

    def claims(self, record: TaskRecord, payload: Any) -> frozenset[ResourceClaim]:
        document_id = document_id_from_record(record)
        book_id = record.book_id
        return frozenset(
            {
                ResourceClaim("doc", book_id, str(document_id), ClaimMode.WRITE_EXCLUSIVE),
                ResourceClaim("glossary_state", book_id, "*", ClaimMode.WRITE_EXCLUSIVE),
                ResourceClaim("term_memory", book_id, "*", ClaimMode.WRITE_COOPERATIVE),
            }
        )

    def can(self, action: TaskAction, record: TaskRecord, payload: Any, snapshot: ActionSnapshot) -> Decision:
        status = record.status
        if action == TaskAction.RUN:
            if status in _RERUNNABLE_TERMINAL_STATUSES:
                return Decision(allowed=True)
            if status in {STATUS_QUEUED, STATUS_PAUSED}:
                return Decision(allowed=True)
            if status in _BATCH_RESUMABLE_STATUSES and self._can_resume_batch_phase(record, payload):
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
        autorun_statuses = _AUTORUN_STATUSES
        if self._can_resume_batch_phase(record, payload):
            autorun_statuses = autorun_statuses | _BATCH_RESUMABLE_STATUSES
        if record.status not in autorun_statuses:
            return Decision(allowed=False, reason=f"Status {record.status!r} is not autorunnable")
        if record.task_id in snapshot.running_task_ids:
            return Decision(allowed=False, reason="Already running")
        arbiter = ClaimArbiter()
        if arbiter.conflicts(self.claims(record, payload), snapshot.active_claims):
            return Decision(allowed=False, reason="Claims conflict with active tasks")
        return Decision(allowed=True)

    def validate_submit(self, book_id: str, params: dict, deps: WorkerDeps) -> Decision:
        return validate_translate_and_export_submit(book_id, params, deps)

    def pre_delete(self, record: TaskRecord, payload: Any, deps: WorkerDeps) -> list[str]:
        return []

    def build_worker(self, action: TaskAction, record: TaskRecord, payload: Any, deps: WorkerDeps) -> object:
        document_id = document_id_from_record(record)
        if action == TaskAction.RUN:
            return TranslateAndExportTaskWorker(
                deps.book_manager,
                record.book_id,
                action="run",
                task_id=record.task_id,
                document_id=document_id,
                format_id=str(payload.get("format_id") or ""),
                output_path=str(payload.get("output_path") or ""),
                use_batch=bool(payload.get("use_batch", False)),
                use_reembedding=bool(payload.get("use_reembedding", False)),
                enable_polish=bool(payload.get("enable_polish", True)),
                options=payload.get("options") if isinstance(payload.get("options"), dict) else {},
                task_store=deps.task_store,
                notify_task_changed=deps.notify_task_changed,
                config_snapshot_json=record.config_snapshot_json,
            )
        if action == TaskAction.CANCEL:
            return TranslateAndExportTaskWorker(
                deps.book_manager,
                record.book_id,
                action="cancel",
                task_id=record.task_id,
                document_id=document_id,
                format_id=str(payload.get("format_id") or ""),
                output_path=str(payload.get("output_path") or ""),
                use_batch=bool(payload.get("use_batch", False)),
                use_reembedding=bool(payload.get("use_reembedding", False)),
                enable_polish=bool(payload.get("enable_polish", True)),
                options=payload.get("options") if isinstance(payload.get("options"), dict) else {},
                task_store=deps.task_store,
                notify_task_changed=deps.notify_task_changed,
                config_snapshot_json=record.config_snapshot_json,
            )
        raise ValueError(f"Unsupported action for TranslateAndExportHandler: {action!r}")

    def validate_run(self, record: TaskRecord, payload: Any, deps: WorkerDeps) -> Decision:
        return validate_translate_and_export_run(record, payload, deps)

    def cancel_dispatch_policy(self, record: TaskRecord, payload: Any) -> CancelDispatchPolicy:
        if bool(payload.get("use_batch", False)) and (record.phase or "") in _REMOTE_CANCEL_PHASES:
            return CancelDispatchPolicy.REQUIRE_REMOTE_CONFIRMATION
        return CancelDispatchPolicy.LOCAL_TERMINALIZE

    def classify_cancel_outcome(self, record: TaskRecord, payload: Any, provider_result: Any) -> CancelOutcome:
        return CancelOutcome.CONFIRMED_CANCELLED
