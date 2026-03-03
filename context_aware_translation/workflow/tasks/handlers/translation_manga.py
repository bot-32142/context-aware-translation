from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import context_aware_translation.config as config_module
import context_aware_translation.storage.book_db as book_db
import context_aware_translation.storage.document_repository as document_repository
from context_aware_translation.ui.workers.translation_manga_task_worker import TranslationMangaTaskWorker
from context_aware_translation.workflow.tasks.claims import (
    AllDocuments,
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
    from context_aware_translation.storage.task_store import TaskRecord
    from context_aware_translation.workflow.tasks.models import ActionSnapshot
    from context_aware_translation.workflow.tasks.worker_deps import WorkerDeps


_RERUNNABLE_TERMINAL_STATUSES = frozenset({STATUS_CANCELLED, STATUS_FAILED, STATUS_COMPLETED_WITH_ERRORS})
_NON_DELETABLE_STATUSES = frozenset({STATUS_RUNNING, STATUS_CANCEL_REQUESTED, STATUS_CANCELLING})


class TranslationMangaHandler:
    task_type = "translation_manga"

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
        # Keep context_tree claim aligned with workflow.translate() behavior.
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
        # Manga translation always requires explicit user initiation
        return Decision(allowed=False, reason="Manga translation requires explicit user initiation")

    def validate_submit(self, book_id: str, params: dict, deps: WorkerDeps) -> Decision:
        # Check manga_translator_config exists
        book = deps.book_manager.get_book(book_id)
        if book is None:
            return Decision(allowed=False, reason=f"Book not found: {book_id}")
        config = config_module.Config.from_book(book, deps.book_manager.library_root, deps.book_manager.registry)
        if config.manga_translator_config is None:
            return Decision(
                allowed=False,
                reason="manga_translator_config is required to translate manga documents. Please configure it in your book settings.",
            )

        # Check all selected documents are manga type
        db_path = deps.book_manager.get_book_db_path(book_id)
        try:
            db = book_db.SQLiteBookDB(db_path)
        except Exception:
            return Decision(allowed=False, reason="Cannot open book database.")
        try:
            doc_repo = document_repository.DocumentRepository(db)
            documents = doc_repo.list_documents()
            if not documents:
                return Decision(allowed=False, reason="Book has no documents.")

            doc_ids = params.get("document_ids")
            if doc_ids:
                id_set = set(doc_ids)
                selected_docs = [d for d in documents if d["document_id"] in id_set]
            else:
                selected_docs = documents

            if not selected_docs:
                return Decision(allowed=False, reason="No documents selected.")

            non_manga = [d for d in selected_docs if d.get("document_type") != "manga"]
            if non_manga:
                return Decision(
                    allowed=False,
                    reason="All selected documents must be manga type for manga translation.",
                )
        finally:
            db.close()

        return Decision(allowed=True)

    def validate_run(self, record: TaskRecord, payload: Any, deps: WorkerDeps) -> Decision:
        # Re-check config
        book = deps.book_manager.get_book(record.book_id)
        if book is None:
            return Decision(allowed=False, reason=f"Book not found: {record.book_id}")
        config = config_module.Config.from_book(book, deps.book_manager.library_root, deps.book_manager.registry)
        if config.manga_translator_config is None:
            return Decision(
                allowed=False,
                reason="manga_translator_config is required to translate manga documents.",
            )

        # Re-check docs remain manga type
        db_path = deps.book_manager.get_book_db_path(record.book_id)
        try:
            db = book_db.SQLiteBookDB(db_path)
        except Exception:
            return Decision(allowed=False, reason="Cannot open book database.")
        try:
            doc_repo = document_repository.DocumentRepository(db)
            documents = doc_repo.list_documents()

            doc_ids: list[int] | None = None
            if record.document_ids_json:
                try:
                    parsed = json.loads(record.document_ids_json)
                    if isinstance(parsed, list):
                        doc_ids = [int(i) for i in parsed]
                except (json.JSONDecodeError, TypeError, ValueError):
                    doc_ids = None

            if doc_ids:
                id_set = set(doc_ids)
                selected_docs = [d for d in documents if d["document_id"] in id_set]
            else:
                selected_docs = documents

            non_manga = [d for d in selected_docs if d.get("document_type") != "manga"]
            if non_manga:
                return Decision(
                    allowed=False,
                    reason="All selected documents must be manga type for manga translation.",
                )
        finally:
            db.close()

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
        source_ids: list[int] | None = None
        parsed_source_ids = (payload or {}).get("source_ids")
        if isinstance(parsed_source_ids, list):
            source_ids = [int(i) for i in parsed_source_ids]

        if action == TaskAction.RUN:
            return TranslationMangaTaskWorker(
                deps.book_manager,
                record.book_id,
                action="run",
                task_id=record.task_id,
                document_ids=doc_ids,
                source_ids=source_ids,
                force=force,
                enable_polish=enable_polish,
                task_store=deps.task_store,
                notify_task_changed=deps.notify_task_changed,
                config_snapshot_json=record.config_snapshot_json,
                enqueue_followup=deps.enqueue_followup,
            )

        if action == TaskAction.CANCEL:
            return TranslationMangaTaskWorker(
                deps.book_manager,
                record.book_id,
                action="cancel",
                task_id=record.task_id,
                task_store=deps.task_store,
                notify_task_changed=deps.notify_task_changed,
            )

        raise ValueError(f"Unsupported action for TranslationMangaHandler: {action!r}")

    def cancel_dispatch_policy(self, record: TaskRecord, payload: Any) -> CancelDispatchPolicy:
        return CancelDispatchPolicy.LOCAL_TERMINALIZE

    def classify_cancel_outcome(self, record: TaskRecord, payload: Any, provider_result: Any) -> CancelOutcome:
        return CancelOutcome.CONFIRMED_CANCELLED

    def pre_delete(self, record: TaskRecord, payload: Any, deps: WorkerDeps) -> list[str]:
        return []
