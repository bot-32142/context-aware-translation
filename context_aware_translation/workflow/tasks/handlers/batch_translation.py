from __future__ import annotations

import json
import logging
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Any

import context_aware_translation.storage.repositories.document_repository as document_repository
import context_aware_translation.storage.schema.book_db as book_db
from context_aware_translation.adapters.qt.workers.batch_translation_task_worker import BatchTranslationTaskWorker
from context_aware_translation.config import (
    Config,
    infer_polish_batch_provider,
    infer_translator_batch_provider,
    resolve_polish_config,
)
from context_aware_translation.workflow.session import WorkflowSession
from context_aware_translation.workflow.tasks.claims import (
    AllDocuments,
    ClaimArbiter,
    ClaimMode,
    DocumentScope,
    ResourceClaim,
    SomeDocuments,
)
from context_aware_translation.workflow.tasks.execution.batch_translation_executor import BatchTranslationExecutor
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

logger = logging.getLogger(__name__)

_RERUNNABLE_TERMINAL_STATUSES = frozenset({STATUS_CANCELLED, STATUS_FAILED, STATUS_COMPLETED_WITH_ERRORS})
_NON_DELETABLE_STATUSES = frozenset({STATUS_RUNNING, STATUS_CANCEL_REQUESTED, STATUS_CANCELLING})
_AUTORUN_STATUSES = frozenset(
    {STATUS_QUEUED, STATUS_RUNNING, STATUS_PAUSED, STATUS_CANCEL_REQUESTED, STATUS_CANCELLING}
)


class BatchTranslationHandler:
    task_type = "batch_translation"

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
        claims = set()
        if isinstance(doc_scope, AllDocuments):
            claims.add(ResourceClaim("doc", book_id, "*"))
        elif isinstance(doc_scope, SomeDocuments):
            claims.update(ResourceClaim("doc", book_id, str(doc_id)) for doc_id in doc_scope.doc_ids)
        # Shared-resource claims for glossary state and term memory
        claims.add(ResourceClaim("glossary_state", book_id, "*", ClaimMode.READ_SHARED))
        claims.add(ResourceClaim("term_memory", book_id, "*", ClaimMode.WRITE_COOPERATIVE))
        return frozenset(claims)

    def validate_run(self, record: TaskRecord, payload: Any, deps: WorkerDeps) -> Decision:
        return Decision(allowed=True)

    def cancel_dispatch_policy(self, record: TaskRecord, payload: Any) -> CancelDispatchPolicy:
        remote_state = (payload or {}).get("remote_submission_state", "none")
        if remote_state == "submitted":
            return CancelDispatchPolicy.REQUIRE_REMOTE_CONFIRMATION
        return CancelDispatchPolicy.LOCAL_TERMINALIZE

    def classify_cancel_outcome(self, record: TaskRecord, payload: Any, provider_result: Any) -> CancelOutcome:
        return CancelOutcome.CONFIRMED_CANCELLED

    def can(self, action: TaskAction, record: TaskRecord, payload: Any, snapshot: ActionSnapshot) -> Decision:
        status = record.status
        if action == TaskAction.RUN:
            if status in _RERUNNABLE_TERMINAL_STATUSES:
                return Decision(allowed=True)
            if status in {STATUS_QUEUED, STATUS_PAUSED, STATUS_RUNNING, STATUS_CANCEL_REQUESTED, STATUS_CANCELLING}:
                return Decision(allowed=True)
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
        db = book_db.SQLiteBookDB(db_path)
        try:
            doc_repo = document_repository.DocumentRepository(db)
            documents = doc_repo.list_documents()
            doc_ids = params.get("document_ids")
            if doc_ids is not None:
                id_set = set(doc_ids)
                documents = [d for d in documents if d["document_id"] in id_set]
            if any(d.get("document_type") == "manga" for d in documents):
                return Decision(allowed=False, reason="Batch translation does not support manga documents.")
        finally:
            db.close()
        book = deps.book_manager.get_book(book_id)
        if book is None:
            return Decision(allowed=False, reason=f"Book not found: {book_id}")
        config = Config.from_book(book, deps.book_manager.library_root, deps.book_manager.registry)
        translator_batch_provider = infer_translator_batch_provider(config.translator_config)
        if translator_batch_provider is None:
            return Decision(
                allowed=False,
                reason="Async batch translation requires a batch-capable Translator connection.",
            )
        enable_polish = bool(params.get("enable_polish", True))
        if enable_polish:
            polish_config = resolve_polish_config(config.polish_config, config.translator_config)
            polish_batch_provider = infer_polish_batch_provider(polish_config)
            if polish_batch_provider is None or polish_batch_provider != translator_batch_provider:
                return Decision(
                    allowed=False,
                    reason=(
                        "Async batch translation requires Translator and Polish to use the same batch-capable provider."
                    ),
                )
        return Decision(allowed=True)

    def pre_delete(self, record: TaskRecord, payload: Any, deps: WorkerDeps) -> list[str]:
        warnings: list[str] = []
        snapshot_exc: Exception | None = None

        def _cleanup_with_session_ctx(session_ctx: AbstractContextManager[Any]) -> None:
            with session_ctx as session:
                executor = BatchTranslationExecutor.from_workflow(session, task_store=deps.task_store)
                try:
                    result = executor.cleanup_remote_artifacts(record.task_id)
                    cleanup_warnings = result.get("cleanup_warnings", [])
                    if isinstance(cleanup_warnings, list):
                        warnings.extend(str(w) for w in cleanup_warnings)
                finally:
                    executor.close()

        if record.config_snapshot_json:
            try:
                snapshot_ctx = WorkflowSession.from_snapshot(record.config_snapshot_json, record.book_id)
                _cleanup_with_session_ctx(snapshot_ctx)
                return warnings
            except Exception as exc:  # noqa: BLE001
                snapshot_exc = exc
                logger.warning(
                    "pre_delete: snapshot cleanup failed for task %s; retrying with live config: %s",
                    record.task_id,
                    exc,
                    exc_info=True,
                )

        try:
            _cleanup_with_session_ctx(deps.create_workflow_session(record.book_id))
        except Exception as live_exc:
            if snapshot_exc is not None:
                warnings.append(
                    f"pre_delete cleanup error for task {record.task_id}: "
                    f"snapshot path failed ({type(snapshot_exc).__name__}: {snapshot_exc}); "
                    f"live-config fallback failed ({type(live_exc).__name__}: {live_exc})"
                )
            else:
                warnings.append(
                    f"pre_delete cleanup error for task {record.task_id}: {type(live_exc).__name__}: {live_exc}"
                )
        return warnings

    def build_worker(self, action: TaskAction, record: TaskRecord, payload: Any, deps: WorkerDeps) -> object:
        doc_ids: list[int] | None = None
        if record.document_ids_json:
            try:
                parsed = json.loads(record.document_ids_json)
                if isinstance(parsed, list):
                    doc_ids = [int(i) for i in parsed]
            except (json.JSONDecodeError, TypeError, ValueError):
                doc_ids = None

        if action == TaskAction.RUN:
            enable_polish: bool = bool((payload or {}).get("enable_polish", True))
            return BatchTranslationTaskWorker(
                deps.book_manager,
                record.book_id,
                action="run",
                task_id=record.task_id,
                document_ids=doc_ids,
                enable_polish=enable_polish,
                task_store=deps.task_store,
                notify_task_changed=deps.notify_task_changed,
                config_snapshot_json=record.config_snapshot_json,
            )
        if action == TaskAction.CANCEL:
            return BatchTranslationTaskWorker(
                deps.book_manager,
                record.book_id,
                action="cancel",
                task_id=record.task_id,
                task_store=deps.task_store,
                notify_task_changed=deps.notify_task_changed,
                config_snapshot_json=record.config_snapshot_json,
            )
        raise ValueError(f"Unsupported action for BatchTranslationHandler: {action}")
