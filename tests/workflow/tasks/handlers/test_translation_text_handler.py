from __future__ import annotations

import json
import time

from context_aware_translation.storage.repositories.task_store import TaskRecord
from context_aware_translation.workflow.tasks.claims import (
    AllDocuments,
    ClaimMode,
    ResourceClaim,
    SomeDocuments,
)
from context_aware_translation.workflow.tasks.handlers.translation_text import TranslationTextHandler
from context_aware_translation.workflow.tasks.models import (
    STATUS_CANCEL_REQUESTED,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PAUSED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    ActionSnapshot,
    TaskAction,
)


def _make_record(
    status: str = STATUS_QUEUED,
    document_ids_json: str | None = None,
    payload_json: str | None = None,
    task_id: str = "task-text",
    book_id: str = "book-1",
    config_snapshot_json: str | None = None,
) -> TaskRecord:
    now = time.time()
    return TaskRecord(
        task_id=task_id,
        book_id=book_id,
        task_type="translation_text",
        status=status,
        phase=None,
        document_ids_json=document_ids_json,
        payload_json=payload_json,
        config_snapshot_json=config_snapshot_json,
        cancel_requested=False,
        total_items=0,
        completed_items=0,
        failed_items=0,
        last_error=None,
        created_at=now,
        updated_at=now,
    )


def _make_snapshot(
    running_task_ids: frozenset[str] | None = None,
    active_claims: frozenset[ResourceClaim] | None = None,
) -> ActionSnapshot:
    return ActionSnapshot(
        running_task_ids=running_task_ids or frozenset(),
        active_claims=active_claims or frozenset(),
        now_monotonic=time.monotonic(),
        retry_after_by_book={},
    )


handler = TranslationTextHandler()


def test_task_type():
    assert handler.task_type == "translation_text"


def test_decode_payload_empty():
    record = _make_record(payload_json=None)
    assert handler.decode_payload(record) == {}


def test_decode_payload_valid():
    record = _make_record(payload_json='{"force": true, "skip_context": false}')
    payload = handler.decode_payload(record)
    assert payload["force"] is True
    assert payload["skip_context"] is False


def test_scope_all_documents_when_no_ids():
    record = _make_record(document_ids_json=None)
    scope = handler.scope(record, {})
    assert isinstance(scope, AllDocuments)
    assert scope.book_id == "book-1"


def test_scope_some_documents_when_ids_provided():
    record = _make_record(document_ids_json=json.dumps([1, 2, 3]))
    scope = handler.scope(record, {})
    assert isinstance(scope, SomeDocuments)
    assert scope.doc_ids == frozenset({1, 2, 3})


def test_scope_all_documents_when_empty_list():
    record = _make_record(document_ids_json=json.dumps([]))
    scope = handler.scope(record, {})
    assert isinstance(scope, AllDocuments)


def test_scope_all_documents_on_invalid_json():
    record = _make_record(document_ids_json="not-json")
    scope = handler.scope(record, {})
    assert isinstance(scope, AllDocuments)


def test_claims_all_docs_when_scope_is_all():
    record = _make_record(document_ids_json=None)
    claims = handler.claims(record, {})
    assert ResourceClaim("doc", "book-1", "*") in claims
    assert ResourceClaim("glossary_state", "book-1", "*", ClaimMode.READ_SHARED) in claims
    assert ResourceClaim("context_tree", "book-1", "*", ClaimMode.WRITE_COOPERATIVE) in claims


def test_claims_specific_docs_when_scope_is_some():
    record = _make_record(document_ids_json=json.dumps([5, 6]))
    claims = handler.claims(record, {})
    assert ResourceClaim("doc", "book-1", "5") in claims
    assert ResourceClaim("doc", "book-1", "6") in claims
    assert ResourceClaim("doc", "book-1", "*") not in claims


# --- can() tests ---


def test_can_run_queued():
    record = _make_record(status=STATUS_QUEUED)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert result.allowed


def test_can_run_paused():
    record = _make_record(status=STATUS_PAUSED)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert result.allowed


def test_can_run_cancelled():
    record = _make_record(status=STATUS_CANCELLED)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert result.allowed


def test_can_run_failed():
    record = _make_record(status=STATUS_FAILED)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert result.allowed


def test_cannot_run_already_running():
    record = _make_record(status=STATUS_RUNNING)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert not result.allowed


def test_cannot_run_completed():
    record = _make_record(status=STATUS_COMPLETED)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert not result.allowed


def test_cannot_run_cancel_requested():
    record = _make_record(status=STATUS_CANCEL_REQUESTED)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert not result.allowed


def test_can_cancel_running():
    record = _make_record(status=STATUS_RUNNING)
    result = handler.can(TaskAction.CANCEL, record, {}, _make_snapshot())
    assert result.allowed


def test_cannot_cancel_completed():
    record = _make_record(status=STATUS_COMPLETED)
    result = handler.can(TaskAction.CANCEL, record, {}, _make_snapshot())
    assert not result.allowed


def test_can_delete_queued():
    record = _make_record(status=STATUS_QUEUED)
    result = handler.can(TaskAction.DELETE, record, {}, _make_snapshot())
    assert result.allowed


def test_cannot_delete_running():
    record = _make_record(status=STATUS_RUNNING)
    result = handler.can(TaskAction.DELETE, record, {}, _make_snapshot())
    assert not result.allowed


def test_cannot_delete_cancel_requested():
    record = _make_record(status=STATUS_CANCEL_REQUESTED)
    result = handler.can(TaskAction.DELETE, record, {}, _make_snapshot())
    assert not result.allowed


# --- can_autorun() tests ---


def test_can_autorun_queued_no_conflicts():
    record = _make_record(status=STATUS_QUEUED)
    result = handler.can_autorun(record, {}, _make_snapshot())
    assert result.allowed


def test_cannot_autorun_running():
    record = _make_record(status=STATUS_RUNNING)
    result = handler.can_autorun(record, {}, _make_snapshot())
    assert not result.allowed


def test_cannot_autorun_already_in_running_set():
    record = _make_record(status=STATUS_QUEUED, task_id="task-text")
    result = handler.can_autorun(record, {}, _make_snapshot(running_task_ids=frozenset({"task-text"})))
    assert not result.allowed


def test_cannot_autorun_with_claim_conflict():
    record = _make_record(status=STATUS_QUEUED, document_ids_json=None)
    active_claim = ResourceClaim("doc", "book-1", "*")
    result = handler.can_autorun(record, {}, _make_snapshot(active_claims=frozenset({active_claim})))
    assert not result.allowed


# --- validate_submit() tests ---


def _deps_with_documents(tmp_path, documents, ocr_sources_by_doc_id: dict | None = None):
    """Create WorkerDeps mock with a fake book DB returning *documents*."""
    from unittest.mock import MagicMock, patch

    ocr_sources_by_doc_id = ocr_sources_by_doc_id or {}

    deps = MagicMock()
    deps.book_manager.get_book_db_path.return_value = tmp_path / "book.db"
    fake_db = MagicMock()
    fake_repo = MagicMock()
    fake_repo.list_documents.return_value = documents
    fake_repo.get_document_sources_needing_ocr.side_effect = lambda doc_id: ocr_sources_by_doc_id.get(doc_id, [])
    fake_repo.get_document_by_id.side_effect = lambda doc_id: next(
        (d for d in documents if d["document_id"] == doc_id), None
    )
    deps._patches = (
        patch("context_aware_translation.storage.schema.book_db.SQLiteBookDB", return_value=fake_db),
        patch(
            "context_aware_translation.storage.repositories.document_repository.DocumentRepository",
            return_value=fake_repo,
        ),
    )
    return deps


def test_validate_submit_with_text_documents(tmp_path):
    deps = _deps_with_documents(tmp_path, [{"document_id": 1, "document_type": "text"}])
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_submit("book-1", {}, deps)
    assert result.allowed


def test_validate_submit_rejects_empty_book(tmp_path):
    deps = _deps_with_documents(tmp_path, [])
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_submit("book-1", {}, deps)
    assert not result.allowed
    assert "no documents" in result.reason.lower()


def test_validate_submit_rejects_manga_documents(tmp_path):
    """TranslationTextHandler must reject manga document types."""
    deps = _deps_with_documents(tmp_path, [{"document_id": 1, "document_type": "manga"}])
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_submit("book-1", {}, deps)
    assert not result.allowed
    assert "manga" in result.reason.lower()


def test_validate_submit_rejects_selected_manga_document(tmp_path):
    """When specific IDs are requested, only selected docs are checked."""
    docs = [
        {"document_id": 1, "document_type": "text"},
        {"document_id": 2, "document_type": "manga"},
    ]
    deps = _deps_with_documents(tmp_path, docs)
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_submit("book-1", {"document_ids": [2]}, deps)
    assert not result.allowed
    assert "manga" in result.reason.lower()


def test_validate_submit_allows_non_selected_manga(tmp_path):
    """Manga docs not in the selection must not block submission."""
    docs = [
        {"document_id": 1, "document_type": "text"},
        {"document_id": 2, "document_type": "manga"},
    ]
    deps = _deps_with_documents(tmp_path, docs)
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_submit("book-1", {"document_ids": [1]}, deps)
    assert result.allowed


def test_validate_submit_rejects_ocr_blocker(tmp_path):
    """validate_submit must reject if a selected doc has pending OCR sources."""
    docs = [{"document_id": 3, "document_type": "scanned_book"}]
    deps = _deps_with_documents(tmp_path, docs, ocr_sources_by_doc_id={3: [{"source_id": 10}]})
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_submit("book-1", {}, deps)
    assert not result.allowed
    assert "ocr" in result.reason.lower()


def test_validate_submit_allows_completed_ocr(tmp_path):
    """validate_submit passes when OCR is complete (no pending sources)."""
    docs = [{"document_id": 3, "document_type": "scanned_book"}]
    deps = _deps_with_documents(tmp_path, docs, ocr_sources_by_doc_id={3: []})
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_submit("book-1", {}, deps)
    assert result.allowed


def test_validate_run_always_allowed():
    from unittest.mock import MagicMock

    record = _make_record()
    result = handler.validate_run(record, {}, MagicMock())
    assert result.allowed


# --- build_worker() tests ---


def test_build_worker_run_returns_translation_text_task_worker():
    from unittest.mock import MagicMock

    deps = MagicMock()
    record = _make_record(
        status=STATUS_QUEUED,
        document_ids_json=json.dumps([1, 2]),
        payload_json=json.dumps({"force": True, "skip_context": False}),
    )
    payload = handler.decode_payload(record)
    worker = handler.build_worker(TaskAction.RUN, record, payload, deps)
    from context_aware_translation.adapters.qt.workers.translation_text_task_worker import TranslationTextTaskWorker

    assert isinstance(worker, TranslationTextTaskWorker)


def test_build_worker_run_filters_to_non_manga_document_ids():
    """build_worker passes document_ids as-is; worker filters manga at runtime."""
    from unittest.mock import MagicMock

    deps = MagicMock()
    doc_ids = [1, 2, 3]
    record = _make_record(
        status=STATUS_QUEUED,
        document_ids_json=json.dumps(doc_ids),
        payload_json=json.dumps({"force": False, "skip_context": False}),
    )
    payload = handler.decode_payload(record)
    worker = handler.build_worker(TaskAction.RUN, record, payload, deps)
    assert worker._document_ids == doc_ids


def test_build_worker_cancel_returns_translation_text_task_worker():
    from unittest.mock import MagicMock

    deps = MagicMock()
    record = _make_record(status=STATUS_RUNNING)
    worker = handler.build_worker(TaskAction.CANCEL, record, {}, deps)
    from context_aware_translation.adapters.qt.workers.translation_text_task_worker import TranslationTextTaskWorker

    assert isinstance(worker, TranslationTextTaskWorker)


def test_pre_delete_returns_empty_list():
    from unittest.mock import MagicMock

    record = _make_record()
    assert handler.pre_delete(record, {}, MagicMock()) == []


def test_build_worker_run_passes_config_snapshot_to_worker():
    """build_worker(RUN) must forward config_snapshot_json from record to the worker."""
    import json
    from unittest.mock import MagicMock

    snapshot = json.dumps({"snapshot_version": 1, "config": {"key": "val"}})
    deps = MagicMock()
    record = _make_record(
        status=STATUS_QUEUED,
        payload_json=json.dumps({"force": False, "skip_context": False}),
        config_snapshot_json=snapshot,
    )
    payload = handler.decode_payload(record)
    worker = handler.build_worker(TaskAction.RUN, record, payload, deps)

    from context_aware_translation.adapters.qt.workers.translation_text_task_worker import TranslationTextTaskWorker

    assert isinstance(worker, TranslationTextTaskWorker)
    assert worker._config_snapshot_json == snapshot
