from __future__ import annotations

import json
import time

from context_aware_translation.storage.repositories.task_store import TaskRecord
from context_aware_translation.workflow.tasks.claims import (
    ClaimMode,
    ResourceClaim,
    SomeDocuments,
)
from context_aware_translation.workflow.tasks.handlers.chunk_retranslation import ChunkRetranslationHandler
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
    task_id: str = "task-chunk",
    book_id: str = "book-1",
) -> TaskRecord:
    now = time.time()
    return TaskRecord(
        task_id=task_id,
        book_id=book_id,
        task_type="chunk_retranslation",
        status=status,
        phase=None,
        document_ids_json=document_ids_json,
        payload_json=payload_json,
        config_snapshot_json=None,
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


handler = ChunkRetranslationHandler()


def test_task_type():
    assert handler.task_type == "chunk_retranslation"


def test_decode_payload_empty():
    record = _make_record(payload_json=None)
    assert handler.decode_payload(record) == {}


def test_decode_payload_valid():
    record = _make_record(payload_json='{"chunk_id": 7, "document_id": 3, "skip_context": true}')
    payload = handler.decode_payload(record)
    assert payload["chunk_id"] == 7
    assert payload["document_id"] == 3
    assert payload["skip_context"] is True


def test_scope_from_payload_document_id():
    record = _make_record()
    payload = {"chunk_id": 1, "document_id": 5}
    scope = handler.scope(record, payload)
    assert isinstance(scope, SomeDocuments)
    assert scope.doc_ids == frozenset({5})


def test_scope_from_document_ids_json_fallback():
    record = _make_record(document_ids_json=json.dumps([9]))
    scope = handler.scope(record, {})
    assert isinstance(scope, SomeDocuments)
    assert scope.doc_ids == frozenset({9})


def test_scope_all_documents_when_no_info():
    from context_aware_translation.workflow.tasks.claims import AllDocuments

    record = _make_record(document_ids_json=None)
    scope = handler.scope(record, {})
    assert isinstance(scope, AllDocuments)


def test_claims_specific_doc():
    record = _make_record()
    payload = {"chunk_id": 1, "document_id": 4}
    claims = handler.claims(record, payload)
    assert ResourceClaim("doc", "book-1", "4", ClaimMode.WRITE_COOPERATIVE) in claims
    assert ResourceClaim("chunk", "book-1", "1") in claims
    assert ResourceClaim("glossary_state", "book-1", "*", ClaimMode.READ_SHARED) in claims
    assert ResourceClaim("context_tree", "book-1", "*", ClaimMode.WRITE_COOPERATIVE) in claims
    assert ResourceClaim("doc", "book-1", "*") not in claims


def test_claims_all_docs_when_no_doc_id():
    record = _make_record()
    claims = handler.claims(record, {})
    assert ResourceClaim("doc", "book-1", "*") in claims


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


def test_cannot_run_running():
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


def test_can_autorun_always_denied():
    """Chunk retranslation is interactive-only — autorun is always denied."""
    record = _make_record(status=STATUS_QUEUED)
    payload = {"chunk_id": 1, "document_id": 2}
    result = handler.can_autorun(record, payload, _make_snapshot())
    assert not result.allowed


def test_cannot_autorun_running():
    record = _make_record(status=STATUS_RUNNING)
    result = handler.can_autorun(record, {}, _make_snapshot())
    assert not result.allowed


def test_cannot_autorun_already_in_running_set():
    """Even queued with no conflicts — still denied for chunk retranslation."""
    record = _make_record(status=STATUS_QUEUED, task_id="task-chunk")
    result = handler.can_autorun(record, {}, _make_snapshot(running_task_ids=frozenset({"task-chunk"})))
    assert not result.allowed


def test_cannot_autorun_with_claim_conflict():
    record = _make_record(status=STATUS_QUEUED)
    payload = {"chunk_id": 1, "document_id": 3}
    active_claim = ResourceClaim("doc", "book-1", "3")
    result = handler.can_autorun(record, payload, _make_snapshot(active_claims=frozenset({active_claim})))
    assert not result.allowed


# --- validate_submit() tests ---


def test_validate_submit_requires_chunk_id():
    from unittest.mock import MagicMock

    deps = MagicMock()
    result = handler.validate_submit("book-1", {"document_id": 1}, deps)
    assert not result.allowed
    assert "chunk_id" in result.reason


def test_validate_submit_requires_document_id():
    from unittest.mock import MagicMock

    deps = MagicMock()
    result = handler.validate_submit("book-1", {"chunk_id": 1}, deps)
    assert not result.allowed
    assert "document_id" in result.reason


def test_validate_submit_allowed_with_both(tmp_path):
    from unittest.mock import MagicMock, patch

    deps = MagicMock()
    deps.book_manager.get_book_db_path.return_value = tmp_path / "book.db"
    fake_db = MagicMock()
    fake_chunk = MagicMock()
    fake_chunk.document_id = 2
    fake_db.get_chunk_by_id.return_value = fake_chunk
    with patch("context_aware_translation.storage.schema.book_db.SQLiteBookDB", return_value=fake_db):
        result = handler.validate_submit("book-1", {"chunk_id": 1, "document_id": 2}, deps)
    assert result.allowed


def test_validate_submit_rejects_missing_chunk(tmp_path):
    from unittest.mock import MagicMock, patch

    deps = MagicMock()
    deps.book_manager.get_book_db_path.return_value = tmp_path / "book.db"
    fake_db = MagicMock()
    fake_db.get_chunk_by_id.return_value = None
    with patch("context_aware_translation.storage.schema.book_db.SQLiteBookDB", return_value=fake_db):
        result = handler.validate_submit("book-1", {"chunk_id": 999, "document_id": 2}, deps)
    assert not result.allowed
    assert "not found" in result.reason.lower()


def test_validate_submit_rejects_wrong_document(tmp_path):
    from unittest.mock import MagicMock, patch

    deps = MagicMock()
    deps.book_manager.get_book_db_path.return_value = tmp_path / "book.db"
    fake_db = MagicMock()
    fake_chunk = MagicMock()
    fake_chunk.document_id = 5  # chunk belongs to doc 5, not doc 2
    fake_db.get_chunk_by_id.return_value = fake_chunk
    with patch("context_aware_translation.storage.schema.book_db.SQLiteBookDB", return_value=fake_db):
        result = handler.validate_submit("book-1", {"chunk_id": 1, "document_id": 2}, deps)
    assert not result.allowed
    assert "belongs to document 5" in result.reason


def test_validate_run_requires_chunk_id():
    from unittest.mock import MagicMock

    record = _make_record(payload_json='{"document_id": 1}')
    payload = handler.decode_payload(record)
    result = handler.validate_run(record, payload, MagicMock())
    assert not result.allowed
    assert "chunk_id" in result.reason


def test_validate_run_requires_document_id():
    from unittest.mock import MagicMock

    record = _make_record(payload_json='{"chunk_id": 1}')
    payload = handler.decode_payload(record)
    result = handler.validate_run(record, payload, MagicMock())
    assert not result.allowed
    assert "document_id" in result.reason


def test_validate_run_allowed_with_both():
    from unittest.mock import MagicMock

    record = _make_record(payload_json='{"chunk_id": 1, "document_id": 2}')
    payload = handler.decode_payload(record)
    result = handler.validate_run(record, payload, MagicMock())
    assert result.allowed


# --- build_worker() tests ---


def test_build_worker_run_returns_chunk_retranslation_task_worker():
    from unittest.mock import MagicMock

    deps = MagicMock()
    record = _make_record(
        status=STATUS_QUEUED,
        payload_json=json.dumps({"chunk_id": 3, "document_id": 7, "skip_context": False}),
    )
    payload = handler.decode_payload(record)
    worker = handler.build_worker(TaskAction.RUN, record, payload, deps)
    from context_aware_translation.adapters.qt.workers.chunk_retranslation_task_worker import (
        ChunkRetranslationTaskWorker,
    )

    assert isinstance(worker, ChunkRetranslationTaskWorker)


def test_build_worker_cancel_returns_chunk_retranslation_task_worker():
    from unittest.mock import MagicMock

    deps = MagicMock()
    record = _make_record(
        status=STATUS_RUNNING,
        payload_json=json.dumps({"chunk_id": 3, "document_id": 7}),
    )
    payload = handler.decode_payload(record)
    worker = handler.build_worker(TaskAction.CANCEL, record, payload, deps)
    from context_aware_translation.adapters.qt.workers.chunk_retranslation_task_worker import (
        ChunkRetranslationTaskWorker,
    )

    assert isinstance(worker, ChunkRetranslationTaskWorker)


def test_pre_delete_returns_empty_list():
    from unittest.mock import MagicMock

    record = _make_record()
    assert handler.pre_delete(record, {}, MagicMock()) == []
