from __future__ import annotations

from typing import TYPE_CHECKING, Any

from context_aware_translation.workflow.tasks.claims import (
    ClaimArbiter,
    ClaimMode,
    DocumentScope,
    NoDocuments,
    ResourceClaim,
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
    from context_aware_translation.workflow.tasks.models import ActionSnapshot
    from context_aware_translation.workflow.tasks.worker_deps import WorkerDeps


_RERUNNABLE_TERMINAL_STATUSES = frozenset({STATUS_CANCELLED, STATUS_FAILED, STATUS_COMPLETED_WITH_ERRORS})
_NON_DELETABLE_STATUSES = frozenset({STATUS_RUNNING, STATUS_CANCEL_REQUESTED, STATUS_CANCELLING})
_AUTORUN_STATUSES = frozenset({STATUS_QUEUED, STATUS_PAUSED})


class GlossaryTranslationHandler:
    task_type = "glossary_translation"

    def decode_payload(self, record: TaskRecord) -> dict[str, Any]:
        return decode_task_payload(record)

    def scope(self, record: TaskRecord, payload: Any) -> DocumentScope:
        return NoDocuments(record.book_id)

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
        from context_aware_translation.storage.book_db import SQLiteBookDB
        from context_aware_translation.storage.term_repository import TermRepository

        book = deps.book_manager.get_book(book_id)
        if book is None:
            return Decision(allowed=False, reason=f"Book not found: {book_id}")

        db_path = deps.book_manager.get_book_db_path(book_id)
        db = SQLiteBookDB(db_path)
        try:
            term_repo = TermRepository(db)
            to_translate = term_repo.get_terms_to_translate()
            if not to_translate:
                return Decision(
                    allowed=False,
                    code="no_untranslated_terms",
                    reason="No untranslated terms found.",
                )
        finally:
            db.close()

        return Decision(allowed=True)

    def validate_run(self, record: TaskRecord, payload: Any, deps: WorkerDeps) -> Decision:
        from context_aware_translation.storage.book_db import SQLiteBookDB
        from context_aware_translation.storage.term_repository import TermRepository

        book_id = record.book_id

        book = deps.book_manager.get_book(book_id)
        if book is None:
            return Decision(allowed=False, reason=f"Book not found: {book_id}")

        db_path = deps.book_manager.get_book_db_path(book_id)
        db = SQLiteBookDB(db_path)
        try:
            term_repo = TermRepository(db)
            to_translate = term_repo.get_terms_to_translate()
            if not to_translate:
                return Decision(
                    allowed=False,
                    code="no_untranslated_terms",
                    reason="No untranslated terms found.",
                )
        finally:
            db.close()

        return Decision(allowed=True)

    def build_worker(self, action: TaskAction, record: TaskRecord, payload: Any, deps: WorkerDeps):
        from context_aware_translation.ui.workers.glossary_translation_task_worker import GlossaryTranslationTaskWorker

        if action == TaskAction.RUN:
            return GlossaryTranslationTaskWorker(
                deps.book_manager,
                record.book_id,
                action="run",
                task_id=record.task_id,
                task_store=deps.task_store,
                notify_task_changed=deps.notify_task_changed,
                config_snapshot_json=record.config_snapshot_json,
            )

        if action == TaskAction.CANCEL:
            return GlossaryTranslationTaskWorker(
                deps.book_manager,
                record.book_id,
                action="cancel",
                task_id=record.task_id,
                task_store=deps.task_store,
                notify_task_changed=deps.notify_task_changed,
            )

        raise ValueError(f"Unsupported action for GlossaryTranslationHandler: {action!r}")

    def cancel_dispatch_policy(self, record: TaskRecord, payload: Any):
        from context_aware_translation.workflow.tasks.handlers.base import CancelDispatchPolicy
        return CancelDispatchPolicy.LOCAL_TERMINALIZE

    def classify_cancel_outcome(self, record: TaskRecord, payload: Any, provider_result: Any):
        from context_aware_translation.workflow.tasks.handlers.base import CancelOutcome
        return CancelOutcome.CONFIRMED_CANCELLED

    def pre_delete(self, record: TaskRecord, payload: Any, deps: WorkerDeps) -> list[str]:
        return []
