from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import context_aware_translation.storage.repositories.document_repository as document_repository
import context_aware_translation.storage.schema.book_db as book_db
from context_aware_translation.adapters.qt.workers.ocr_task_worker import OCRTaskWorker
from context_aware_translation.workflow.tasks.claims import (
    ClaimMode,
    DocumentScope,
    NoDocuments,
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

# Document types that support OCR (have requires_ocr_config = True)
_OCR_CAPABLE_DOCUMENT_TYPES = frozenset({"scanned_book", "pdf", "manga", "epub"})


class OCRHandler:
    task_type = "ocr"

    def decode_payload(self, record: TaskRecord) -> dict[str, Any]:
        if not record.payload_json:
            return {}
        try:
            result = json.loads(record.payload_json)
            return result if isinstance(result, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def _get_document_id(self, record: TaskRecord) -> int:
        """Extract the single required document_id from record. Raises ValueError if not exactly 1."""
        if not record.document_ids_json:
            raise ValueError("OCR task must have exactly one document_id; none provided.")
        try:
            ids = json.loads(record.document_ids_json)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError("OCR task document_ids_json is not valid JSON.") from exc
        if not isinstance(ids, list) or len(ids) != 1:
            raise ValueError(
                f"OCR task must have exactly one document_id; got {len(ids) if isinstance(ids, list) else 'non-list'}."
            )
        return int(ids[0])

    def scope(self, record: TaskRecord, payload: Any) -> DocumentScope:
        try:
            doc_id = self._get_document_id(record)
        except ValueError:
            # Fallback: empty scope so we don't crash claim resolution
            return NoDocuments(record.book_id)
        return SomeDocuments(record.book_id, frozenset({doc_id}))

    def claims(self, record: TaskRecord, payload: Any) -> frozenset[ResourceClaim]:
        try:
            doc_id = self._get_document_id(record)
        except ValueError:
            return frozenset()
        book_id = record.book_id
        return frozenset(
            {
                ResourceClaim("ocr", book_id, str(doc_id), ClaimMode.WRITE_EXCLUSIVE),
                ResourceClaim("doc", book_id, str(doc_id), ClaimMode.WRITE_EXCLUSIVE),
            }
        )

    def can(self, action: TaskAction, record: TaskRecord, payload: Any, snapshot: ActionSnapshot) -> Decision:
        status = record.status

        if action == TaskAction.RUN:
            if status in _RERUNNABLE_TERMINAL_STATUSES:
                return Decision(allowed=True)
            if status in {STATUS_QUEUED}:
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
        # OCR is always user-triggered only
        return Decision(allowed=False, reason="OCR requires explicit user initiation")

    def validate_submit(self, book_id: str, params: dict, deps: WorkerDeps) -> Decision:
        # Must specify exactly one document_id
        raw_ids = params.get("document_ids")
        if not isinstance(raw_ids, list) or len(raw_ids) != 1:
            return Decision(
                allowed=False,
                reason="OCR task requires exactly one document_id in params.",
            )
        doc_id = int(raw_ids[0])

        # Open the book DB
        db_path = deps.book_manager.get_book_db_path(book_id)
        try:
            db = book_db.SQLiteBookDB(db_path)
        except Exception:
            return Decision(allowed=False, reason="Cannot open book database.")

        try:
            doc_repo = document_repository.DocumentRepository(db)

            # Get the document
            doc = doc_repo.get_document_by_id(doc_id)
            if doc is None:
                return Decision(allowed=False, reason=f"Document {doc_id} not found.")

            # Check document type is OCR-capable
            doc_type = doc.get("document_type", "")
            if doc_type not in _OCR_CAPABLE_DOCUMENT_TYPES:
                return Decision(
                    allowed=False,
                    reason=f"Document type '{doc_type}' does not support OCR. Supported types: {', '.join(sorted(_OCR_CAPABLE_DOCUMENT_TYPES))}.",
                )

            # Check book config has ocr_config
            book_config = deps.book_manager.get_book_config(book_id)
            if book_config is None or not book_config.get("ocr_config"):
                return Decision(
                    allowed=False,
                    reason="ocr_config is required for OCR tasks. Please configure it in your book settings.",
                )

            # Validate explicit source_ids if provided
            explicit_source_ids: list[int] | None = None
            raw_source_ids = params.get("source_ids")
            if raw_source_ids is not None:
                if not isinstance(raw_source_ids, list):
                    return Decision(allowed=False, reason="source_ids must be a list.")
                # Verify each source belongs to this document
                all_sources = doc_repo.get_document_sources_metadata(doc_id)
                all_source_ids = {s["source_id"] for s in all_sources}
                for sid in raw_source_ids:
                    if int(sid) not in all_source_ids:
                        return Decision(
                            allowed=False,
                            reason=f"source_id {sid} does not belong to document {doc_id}.",
                        )
                explicit_source_ids = [int(s) for s in raw_source_ids]

            # Resolve sources to run. Explicit source_ids allow rerun of already-
            # completed pages; default document runs remain pending-only.
            if explicit_source_ids is not None:
                resolved = explicit_source_ids
            else:
                resolved = [s["source_id"] for s in doc_repo.get_document_sources_needing_ocr(doc_id)]

            if not resolved:
                return Decision(
                    allowed=False,
                    reason="No pending OCR sources found for this document. All sources may already be OCR-completed.",
                )
        finally:
            db.close()

        return Decision(allowed=True)

    def validate_run(self, record: TaskRecord, payload: Any, deps: WorkerDeps) -> Decision:
        # Get document_id from record
        try:
            doc_id = self._get_document_id(record)
        except ValueError as exc:
            return Decision(allowed=False, reason=str(exc))

        book_id = record.book_id

        # Check ocr_config still present
        book_config = deps.book_manager.get_book_config(book_id)
        if book_config is None or not book_config.get("ocr_config"):
            return Decision(
                allowed=False,
                reason="ocr_config is required for OCR tasks. Please configure it in your book settings.",
            )

        # Open book DB
        db_path = deps.book_manager.get_book_db_path(book_id)
        try:
            db = book_db.SQLiteBookDB(db_path)
        except Exception:
            return Decision(allowed=False, reason="Cannot open book database.")

        try:
            doc_repo = document_repository.DocumentRepository(db)

            # Check document still exists and is OCR-capable
            doc = doc_repo.get_document_by_id(doc_id)
            if doc is None:
                return Decision(allowed=False, reason=f"Document {doc_id} not found.")
            doc_type = doc.get("document_type", "")
            if doc_type not in _OCR_CAPABLE_DOCUMENT_TYPES:
                return Decision(
                    allowed=False,
                    reason=f"Document type '{doc_type}' does not support OCR.",
                )

            # Validate stored source_ids if present
            source_ids: list[int] | None = None
            raw_source_ids = (payload or {}).get("source_ids")
            if raw_source_ids is not None and isinstance(raw_source_ids, list):
                source_ids = [int(s) for s in raw_source_ids]

            if source_ids is not None:
                all_sources = doc_repo.get_document_sources_metadata(doc_id)
                all_source_ids = {s["source_id"] for s in all_sources}
                for sid in source_ids:
                    if sid not in all_source_ids:
                        return Decision(
                            allowed=False,
                            reason=f"source_id {sid} does not belong to document {doc_id}.",
                        )
                resolved = source_ids
            else:
                resolved = [s["source_id"] for s in doc_repo.get_document_sources_needing_ocr(doc_id)]

            if not resolved:
                return Decision(
                    allowed=False,
                    reason="No pending OCR sources found for this document.",
                )
        finally:
            db.close()

        return Decision(allowed=True)

    def build_worker(self, action: TaskAction, record: TaskRecord, payload: Any, deps: WorkerDeps) -> object:
        try:
            doc_id = self._get_document_id(record)
        except ValueError:
            doc_id = None

        source_ids: list[int] | None = None
        if payload and isinstance((raw := payload.get("source_ids")), list):
            source_ids = [int(s) for s in raw]

        if action == TaskAction.RUN:
            return OCRTaskWorker(
                deps.book_manager,
                record.book_id,
                action="run",
                task_id=record.task_id,
                document_id=doc_id,
                source_ids=source_ids,
                task_store=deps.task_store,
                notify_task_changed=deps.notify_task_changed,
                config_snapshot_json=record.config_snapshot_json,
            )

        if action == TaskAction.CANCEL:
            return OCRTaskWorker(
                deps.book_manager,
                record.book_id,
                action="cancel",
                task_id=record.task_id,
                task_store=deps.task_store,
                notify_task_changed=deps.notify_task_changed,
            )

        raise ValueError(f"Unsupported action for OCRHandler: {action!r}")

    def cancel_dispatch_policy(self, record: TaskRecord, payload: Any) -> CancelDispatchPolicy:
        return CancelDispatchPolicy.LOCAL_TERMINALIZE

    def classify_cancel_outcome(self, record: TaskRecord, payload: Any, provider_result: Any) -> CancelOutcome:
        return CancelOutcome.CONFIRMED_CANCELLED

    def pre_delete(self, record: TaskRecord, payload: Any, deps: WorkerDeps) -> list[str]:
        return []
