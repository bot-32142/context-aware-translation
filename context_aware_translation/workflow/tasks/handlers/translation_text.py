from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import context_aware_translation.storage.repositories.document_repository as document_repository
import context_aware_translation.storage.schema.book_db as book_db
from context_aware_translation.adapters.qt.workers.translation_text_task_worker import TranslationTextTaskWorker
from context_aware_translation.workflow.tasks.claims import (
    AllDocuments,
    ClaimArbiter,
    ClaimMode,
    DocumentScope,
    ResourceClaim,
    SomeDocuments,
)
from context_aware_translation.workflow.tasks.execution.batch_translation_ops import decode_task_payload
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

if TYPE_CHECKING:
    from context_aware_translation.storage.repositories.task_store import TaskRecord
    from context_aware_translation.workflow.tasks.models import ActionSnapshot
    from context_aware_translation.workflow.tasks.worker_deps import WorkerDeps


_RERUNNABLE_TERMINAL_STATUSES = frozenset({STATUS_CANCELLED, STATUS_FAILED, STATUS_COMPLETED_WITH_ERRORS})
_NON_DELETABLE_STATUSES = frozenset({STATUS_RUNNING, STATUS_CANCEL_REQUESTED, STATUS_CANCELLING})
_AUTORUN_STATUSES = frozenset({STATUS_QUEUED, STATUS_PAUSED})

_MANGA_DOCUMENT_TYPE = "manga"


class TranslationTextHandler:
    task_type = "translation_text"

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
        doc_scope = self.scope(record, payload)
        book_id = record.book_id
        claims: set[ResourceClaim] = set()
        if isinstance(doc_scope, AllDocuments):
            claims.add(ResourceClaim("doc", book_id, "*"))
        elif isinstance(doc_scope, SomeDocuments):
            claims.update(ResourceClaim("doc", book_id, str(doc_id)) for doc_id in doc_scope.doc_ids)
        claims.add(ResourceClaim("glossary_state", book_id, "*", ClaimMode.READ_SHARED))
        claims.add(ResourceClaim("term_memory", book_id, "*", ClaimMode.WRITE_COOPERATIVE))
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
        db_path = deps.book_manager.get_book_db_path(book_id)
        try:
            db = book_db.SQLiteBookDB(db_path)
        except Exception:
            return Decision(allowed=False, reason="Cannot open book database.")
        try:
            doc_repo = document_repository.DocumentRepository(db)
            documents = doc_repo.list_documents()
            if not documents:
                return Decision(allowed=False, reason="Book has no documents to translate.")

            # Filter to requested doc IDs if specified
            requested_ids: set[int] | None = None
            raw_ids = params.get("document_ids")
            if isinstance(raw_ids, list) and raw_ids:
                requested_ids = {int(i) for i in raw_ids}

            target_docs = [doc for doc in documents if requested_ids is None or doc["document_id"] in requested_ids]

            # Reject if any selected doc is manga type
            manga_docs = [doc for doc in target_docs if doc.get("document_type") == _MANGA_DOCUMENT_TYPE]
            if manga_docs:
                return Decision(
                    allowed=False,
                    reason="Selected documents include manga type(s). Use translation_manga task instead.",
                )

            # Reject if any selected doc has pending OCR blockers
            for doc in target_docs:
                sources_needing_ocr = doc_repo.get_document_sources_needing_ocr(doc["document_id"])
                if sources_needing_ocr:
                    return Decision(
                        allowed=False,
                        reason=f"Document {doc['document_id']} has pending OCR. Complete OCR before translating.",
                    )
        finally:
            db.close()
        return Decision(allowed=True)

    def validate_run(self, record: TaskRecord, payload: Any, deps: WorkerDeps) -> Decision:
        return Decision(allowed=True)

    def build_worker(self, action: TaskAction, record: TaskRecord, payload: Any, deps: WorkerDeps) -> object:
        doc_ids: list[int] | None = None
        if record.document_ids_json:
            try:
                parsed = json.loads(record.document_ids_json)
                if isinstance(parsed, list):
                    doc_ids = [int(i) for i in parsed]
            except (json.JSONDecodeError, TypeError, ValueError):
                doc_ids = None

        force: bool = bool((payload or {}).get("force", False))
        enable_polish: bool = bool((payload or {}).get("enable_polish", True))

        if action == TaskAction.RUN:
            return TranslationTextTaskWorker(
                deps.book_manager,
                record.book_id,
                action="run",
                task_id=record.task_id,
                document_ids=doc_ids,
                force=force,
                enable_polish=enable_polish,
                task_store=deps.task_store,
                notify_task_changed=deps.notify_task_changed,
                config_snapshot_json=record.config_snapshot_json,
                enqueue_followup=deps.enqueue_followup,
            )

        if action == TaskAction.CANCEL:
            return TranslationTextTaskWorker(
                deps.book_manager,
                record.book_id,
                action="cancel",
                task_id=record.task_id,
                task_store=deps.task_store,
                notify_task_changed=deps.notify_task_changed,
            )

        raise ValueError(f"Unsupported action for TranslationTextHandler: {action!r}")

    def cancel_dispatch_policy(self, record: TaskRecord, payload: Any) -> CancelDispatchPolicy:
        return CancelDispatchPolicy.LOCAL_TERMINALIZE

    def classify_cancel_outcome(self, record: TaskRecord, payload: Any, provider_result: Any) -> CancelOutcome:
        return CancelOutcome.CONFIRMED_CANCELLED

    def pre_delete(self, record: TaskRecord, payload: Any, deps: WorkerDeps) -> list[str]:
        return []
