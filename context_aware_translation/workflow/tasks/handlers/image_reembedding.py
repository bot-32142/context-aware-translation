from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import context_aware_translation.config as config_module
import context_aware_translation.storage.book_db as book_db
import context_aware_translation.storage.document_repository as document_repository
from context_aware_translation.ui.workers.image_reembedding_task_worker import ImageReembeddingTaskWorker
from context_aware_translation.workflow.tasks.claims import (
    AllDocuments,
    ClaimArbiter,
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
_AUTORUN_STATUSES = frozenset({STATUS_QUEUED, STATUS_PAUSED})

_REEMBEDDABLE_DOCUMENT_TYPES = frozenset({"pdf", "scanned_book", "manga", "epub"})


class ImageReembeddingHandler:
    task_type = "image_reembedding"

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
        # No glossary or context_tree claims needed for reembedding
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
        book = deps.book_manager.get_book(book_id)
        if book is None:
            return Decision(allowed=False, reason=f"Book not found: {book_id}")

        config = config_module.Config.from_book(book, deps.book_manager.library_root, deps.book_manager.registry)
        if config.image_reembedding_config is None:
            return Decision(
                allowed=False,
                reason="image_reembedding_config is required for image reembedding. Please configure it in your book settings.",
            )

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

            doc_ids_raw = params.get("document_ids")
            if doc_ids_raw is not None:
                if not isinstance(doc_ids_raw, list):
                    return Decision(allowed=False, reason="document_ids must be a list[int] or null.")
                if not doc_ids_raw:
                    return Decision(allowed=False, reason="No documents selected.")
                try:
                    id_set = {int(i) for i in doc_ids_raw}
                except (TypeError, ValueError):
                    return Decision(allowed=False, reason="document_ids must contain only integers.")
                selected_docs = [d for d in documents if int(d["document_id"]) in id_set]
                if len(selected_docs) != len(id_set):
                    return Decision(allowed=False, reason="Selected documents no longer exist.")
            else:
                selected_docs = documents

            if not selected_docs:
                return Decision(allowed=False, reason="No documents selected.")

            non_reembeddable = [d for d in selected_docs if d.get("document_type") not in _REEMBEDDABLE_DOCUMENT_TYPES]
            if non_reembeddable:
                types = {d.get("document_type") for d in non_reembeddable}
                return Decision(
                    allowed=False,
                    reason=f"Document type(s) {types} do not support image reembedding. Supported types: {_REEMBEDDABLE_DOCUMENT_TYPES}",
                )

            # Check at least one doc has translated chunks
            doc_id_set = {int(d["document_id"]) for d in selected_docs}
            chunks_by_doc = db.list_chunks_grouped_by_document()
            has_translated = any(
                any(chunk.is_translated for chunk in chunks)
                for doc_id, chunks in chunks_by_doc.items()
                if doc_id in doc_id_set
            )
            if not has_translated:
                return Decision(
                    allowed=False,
                    reason="No translated chunks found. Translate documents before running image reembedding.",
                )

            source_ids_raw = params.get("source_ids")
            if source_ids_raw is not None:
                if not isinstance(source_ids_raw, list):
                    return Decision(allowed=False, reason="source_ids must be a list[int] or null.")
                try:
                    source_id_set = {int(i) for i in source_ids_raw}
                except (TypeError, ValueError):
                    return Decision(allowed=False, reason="source_ids must contain only integers.")
                all_source_ids: set[int] = set()
                for d in selected_docs:
                    doc_sources = doc_repo.get_document_sources(int(d["document_id"]))
                    for s in doc_sources:
                        all_source_ids.add(int(s["source_id"]))
                missing = source_id_set - all_source_ids
                if missing:
                    return Decision(
                        allowed=False,
                        reason=f"source_ids not found in selected documents: {sorted(missing)}",
                    )
        finally:
            db.close()

        return Decision(allowed=True)

    def validate_run(self, record: TaskRecord, payload: Any, deps: WorkerDeps) -> Decision:
        book = deps.book_manager.get_book(record.book_id)
        if book is None:
            return Decision(allowed=False, reason=f"Book not found: {record.book_id}")

        config = config_module.Config.from_book(book, deps.book_manager.library_root, deps.book_manager.registry)
        if config.image_reembedding_config is None:
            return Decision(
                allowed=False,
                reason="image_reembedding_config is required for image reembedding.",
            )

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

            if doc_ids is not None:
                if not doc_ids:
                    return Decision(allowed=False, reason="No documents selected.")
                id_set = set(doc_ids)
                selected_docs = [d for d in documents if int(d["document_id"]) in id_set]
                if len(selected_docs) != len(id_set):
                    return Decision(allowed=False, reason="Selected documents no longer exist.")
            else:
                selected_docs = documents

            if not selected_docs:
                return Decision(allowed=False, reason="Book has no documents.")

            non_reembeddable = [d for d in selected_docs if d.get("document_type") not in _REEMBEDDABLE_DOCUMENT_TYPES]
            if non_reembeddable:
                types = {d.get("document_type") for d in non_reembeddable}
                return Decision(
                    allowed=False,
                    reason=f"Document type(s) {types} do not support image reembedding.",
                )

            doc_id_set = {int(d["document_id"]) for d in selected_docs}
            chunks_by_doc = db.list_chunks_grouped_by_document()
            has_translated = any(
                any(chunk.is_translated for chunk in chunks)
                for doc_id, chunks in chunks_by_doc.items()
                if doc_id in doc_id_set
            )
            if not has_translated:
                return Decision(
                    allowed=False,
                    reason="No translated chunks found. Translate documents before running image reembedding.",
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

        source_ids: list[int] | None = None
        force: bool = False
        if record.payload_json:
            try:
                payload_data = json.loads(record.payload_json)
                raw = payload_data.get("source_ids")
                if isinstance(raw, list):
                    source_ids = [int(i) for i in raw]
                force = bool(payload_data.get("force", False))
            except (json.JSONDecodeError, TypeError, ValueError):
                source_ids = None

        if action == TaskAction.RUN:
            return ImageReembeddingTaskWorker(
                deps.book_manager,
                record.book_id,
                action="run",
                task_id=record.task_id,
                document_ids=doc_ids,
                source_ids=source_ids,
                force=force,
                task_store=deps.task_store,
                notify_task_changed=deps.notify_task_changed,
            )

        if action == TaskAction.CANCEL:
            return ImageReembeddingTaskWorker(
                deps.book_manager,
                record.book_id,
                action="cancel",
                task_id=record.task_id,
                task_store=deps.task_store,
                notify_task_changed=deps.notify_task_changed,
            )

        raise ValueError(f"Unsupported action for ImageReembeddingHandler: {action!r}")

    def cancel_dispatch_policy(self, record: TaskRecord, payload: Any) -> CancelDispatchPolicy:
        return CancelDispatchPolicy.LOCAL_TERMINALIZE

    def classify_cancel_outcome(self, record: TaskRecord, payload: Any, provider_result: Any) -> CancelOutcome:
        return CancelOutcome.CONFIRMED_CANCELLED

    def pre_delete(self, record: TaskRecord, payload: Any, deps: WorkerDeps) -> list[str]:
        return []
