from __future__ import annotations

import json
import time

import pytest

from context_aware_translation.storage.repositories.task_store import TaskRecord
from context_aware_translation.workflow.tasks.claims import (
    ClaimMode,
    NoDocuments,
    ResourceClaim,
    SomeDocuments,
)
from context_aware_translation.workflow.tasks.handlers.ocr import OCRHandler
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
    ActionSnapshot,
    TaskAction,
)


def _make_record(
    status: str = STATUS_QUEUED,
    document_ids_json: str | None = None,
    payload_json: str | None = None,
    task_id: str = "task-ocr",
    book_id: str = "book-1",
    config_snapshot_json: str | None = None,
) -> TaskRecord:
    now = time.time()
    return TaskRecord(
        task_id=task_id,
        book_id=book_id,
        task_type="ocr",
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


handler = OCRHandler()


# ---------------------------------------------------------------------------
# task_type
# ---------------------------------------------------------------------------


def test_task_type():
    assert handler.task_type == "ocr"


# ---------------------------------------------------------------------------
# decode_payload
# ---------------------------------------------------------------------------


def test_decode_payload_empty():
    record = _make_record(payload_json=None)
    assert handler.decode_payload(record) == {}


def test_decode_payload_valid():
    record = _make_record(payload_json='{"source_ids": [1, 2, 3]}')
    payload = handler.decode_payload(record)
    assert payload["source_ids"] == [1, 2, 3]


def test_decode_payload_invalid_json():
    record = _make_record(payload_json="not-json")
    assert handler.decode_payload(record) == {}


def test_decode_payload_non_dict_json():
    record = _make_record(payload_json="[1, 2, 3]")
    assert handler.decode_payload(record) == {}


# ---------------------------------------------------------------------------
# scope
# ---------------------------------------------------------------------------


def test_scope_some_documents_with_single_id():
    record = _make_record(document_ids_json=json.dumps([42]))
    scope = handler.scope(record, {})
    assert isinstance(scope, SomeDocuments)
    assert scope.doc_ids == frozenset({42})
    assert scope.book_id == "book-1"


def test_scope_no_documents_when_no_ids():
    record = _make_record(document_ids_json=None)
    scope = handler.scope(record, {})
    assert isinstance(scope, NoDocuments)


def test_scope_no_documents_on_invalid_json():
    record = _make_record(document_ids_json="not-json")
    scope = handler.scope(record, {})
    assert isinstance(scope, NoDocuments)


def test_scope_no_documents_when_multiple_ids():
    record = _make_record(document_ids_json=json.dumps([1, 2]))
    scope = handler.scope(record, {})
    assert isinstance(scope, NoDocuments)


def test_scope_no_documents_when_empty_list():
    record = _make_record(document_ids_json=json.dumps([]))
    scope = handler.scope(record, {})
    assert isinstance(scope, NoDocuments)


# ---------------------------------------------------------------------------
# claims
# ---------------------------------------------------------------------------


def test_claims_with_valid_single_document():
    record = _make_record(document_ids_json=json.dumps([5]))
    claims = handler.claims(record, {})
    assert ResourceClaim("ocr", "book-1", "5", ClaimMode.WRITE_EXCLUSIVE) in claims
    assert ResourceClaim("doc", "book-1", "5", ClaimMode.WRITE_EXCLUSIVE) in claims
    assert len(claims) == 2


def test_claims_empty_when_no_document_id():
    record = _make_record(document_ids_json=None)
    claims = handler.claims(record, {})
    assert claims == frozenset()


def test_claims_empty_when_multiple_ids():
    record = _make_record(document_ids_json=json.dumps([1, 2]))
    claims = handler.claims(record, {})
    assert claims == frozenset()


# ---------------------------------------------------------------------------
# can()
# ---------------------------------------------------------------------------


def test_can_run_queued():
    record = _make_record(status=STATUS_QUEUED)
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


def test_can_run_completed_with_errors():
    record = _make_record(status=STATUS_COMPLETED_WITH_ERRORS)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert result.allowed


def test_cannot_run_already_running():
    record = _make_record(status=STATUS_RUNNING)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert not result.allowed
    assert "already running" in result.reason.lower()


def test_cannot_run_completed():
    record = _make_record(status=STATUS_COMPLETED)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert not result.allowed
    assert "completed" in result.reason.lower()


def test_cannot_run_cancel_requested():
    record = _make_record(status=STATUS_CANCEL_REQUESTED)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert not result.allowed
    assert "cancel" in result.reason.lower()


def test_cannot_run_cancelling():
    record = _make_record(status=STATUS_CANCELLING)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert not result.allowed
    assert "cancel" in result.reason.lower()


def test_cannot_run_paused():
    record = _make_record(status=STATUS_PAUSED)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert not result.allowed


def test_can_cancel_running():
    record = _make_record(status=STATUS_RUNNING)
    result = handler.can(TaskAction.CANCEL, record, {}, _make_snapshot())
    assert result.allowed


def test_can_cancel_queued():
    record = _make_record(status=STATUS_QUEUED)
    result = handler.can(TaskAction.CANCEL, record, {}, _make_snapshot())
    assert result.allowed


def test_cannot_cancel_completed():
    record = _make_record(status=STATUS_COMPLETED)
    result = handler.can(TaskAction.CANCEL, record, {}, _make_snapshot())
    assert not result.allowed


def test_cannot_cancel_cancelled():
    record = _make_record(status=STATUS_CANCELLED)
    result = handler.can(TaskAction.CANCEL, record, {}, _make_snapshot())
    assert not result.allowed


def test_can_delete_queued():
    record = _make_record(status=STATUS_QUEUED)
    result = handler.can(TaskAction.DELETE, record, {}, _make_snapshot())
    assert result.allowed


def test_can_delete_cancelled():
    record = _make_record(status=STATUS_CANCELLED)
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


def test_cannot_delete_cancelling():
    record = _make_record(status=STATUS_CANCELLING)
    result = handler.can(TaskAction.DELETE, record, {}, _make_snapshot())
    assert not result.allowed


def test_can_unknown_action_raises():
    record = _make_record(status=STATUS_QUEUED)
    with pytest.raises(ValueError, match="Unknown action"):
        handler.can("unknown_action", record, {}, _make_snapshot())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# can_autorun()
# ---------------------------------------------------------------------------


def test_can_autorun_always_denied():
    record = _make_record(status=STATUS_QUEUED)
    result = handler.can_autorun(record, {}, _make_snapshot())
    assert not result.allowed
    assert "user" in result.reason.lower() or "explicit" in result.reason.lower()


def test_can_autorun_denied_regardless_of_status():
    for status in [STATUS_QUEUED, STATUS_PAUSED, STATUS_RUNNING, STATUS_CANCELLED]:
        record = _make_record(status=status)
        result = handler.can_autorun(record, {}, _make_snapshot())
        assert not result.allowed


# ---------------------------------------------------------------------------
# validate_submit() helpers
# ---------------------------------------------------------------------------


_SENTINEL = object()


def _make_deps_for_submit(
    tmp_path,
    *,
    doc: dict | None = None,
    ocr_sources: list[dict] | None = None,
    all_sources: list[dict] | None = None,
    book_config: dict | None | object = _SENTINEL,
):
    """Build a mock WorkerDeps for validate_submit tests."""
    from unittest.mock import MagicMock, patch

    deps = MagicMock()
    deps.book_manager.get_book_db_path.return_value = tmp_path / "book.db"

    # Default: book config with ocr_config
    if book_config is _SENTINEL:
        book_config = {"ocr_config": {"endpoint_profile": "test"}}
    deps.book_manager.get_book_config.return_value = book_config

    fake_db = MagicMock()
    fake_repo = MagicMock()

    fake_repo.get_document_by_id.return_value = doc
    fake_repo.get_document_sources_needing_ocr.return_value = ocr_sources or []
    fake_repo.get_document_sources_metadata.return_value = all_sources or []

    deps._patches = (
        patch("context_aware_translation.storage.schema.book_db.SQLiteBookDB", return_value=fake_db),
        patch(
            "context_aware_translation.storage.repositories.document_repository.DocumentRepository",
            return_value=fake_repo,
        ),
    )
    return deps


# ---------------------------------------------------------------------------
# validate_submit() tests
# ---------------------------------------------------------------------------


def test_validate_submit_rejects_missing_document_ids(tmp_path):
    deps = _make_deps_for_submit(tmp_path)
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_submit("book-1", {}, deps)
    assert not result.allowed
    assert "document_id" in result.reason.lower()


def test_validate_submit_rejects_multiple_document_ids(tmp_path):
    deps = _make_deps_for_submit(tmp_path)
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_submit("book-1", {"document_ids": [1, 2]}, deps)
    assert not result.allowed
    assert "exactly one" in result.reason.lower()


def test_validate_submit_rejects_empty_document_ids(tmp_path):
    deps = _make_deps_for_submit(tmp_path)
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_submit("book-1", {"document_ids": []}, deps)
    assert not result.allowed


def test_validate_submit_rejects_document_not_found(tmp_path):
    deps = _make_deps_for_submit(tmp_path, doc=None)
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_submit("book-1", {"document_ids": [99]}, deps)
    assert not result.allowed
    assert "not found" in result.reason.lower()


def test_validate_submit_rejects_non_ocr_capable_document(tmp_path):
    doc = {"document_id": 1, "document_type": "text"}
    deps = _make_deps_for_submit(tmp_path, doc=doc, ocr_sources=[{"source_id": 10}])
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_submit("book-1", {"document_ids": [1]}, deps)
    assert not result.allowed
    assert "ocr" in result.reason.lower()


def test_validate_submit_rejects_missing_ocr_config(tmp_path):
    doc = {"document_id": 1, "document_type": "scanned_book"}
    deps = _make_deps_for_submit(
        tmp_path,
        doc=doc,
        ocr_sources=[{"source_id": 10}],
        book_config={},  # no ocr_config
    )
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_submit("book-1", {"document_ids": [1]}, deps)
    assert not result.allowed
    assert "ocr_config" in result.reason.lower()


def test_validate_submit_rejects_none_book_config(tmp_path):
    doc = {"document_id": 1, "document_type": "scanned_book"}
    deps = _make_deps_for_submit(
        tmp_path,
        doc=doc,
        ocr_sources=[{"source_id": 10}],
        book_config=None,
    )
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_submit("book-1", {"document_ids": [1]}, deps)
    assert not result.allowed
    assert "ocr_config" in result.reason.lower()


def test_validate_submit_rejects_no_pending_ocr_sources(tmp_path):
    doc = {"document_id": 1, "document_type": "scanned_book"}
    deps = _make_deps_for_submit(tmp_path, doc=doc, ocr_sources=[])
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_submit("book-1", {"document_ids": [1]}, deps)
    assert not result.allowed
    assert "no pending ocr" in result.reason.lower()


def test_validate_submit_allows_scanned_book_with_pending_sources(tmp_path):
    doc = {"document_id": 1, "document_type": "scanned_book"}
    deps = _make_deps_for_submit(tmp_path, doc=doc, ocr_sources=[{"source_id": 10}])
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_submit("book-1", {"document_ids": [1]}, deps)
    assert result.allowed


def test_validate_submit_allows_pdf_document(tmp_path):
    doc = {"document_id": 2, "document_type": "pdf"}
    deps = _make_deps_for_submit(tmp_path, doc=doc, ocr_sources=[{"source_id": 20}])
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_submit("book-1", {"document_ids": [2]}, deps)
    assert result.allowed


def test_validate_submit_allows_manga_document(tmp_path):
    doc = {"document_id": 3, "document_type": "manga"}
    deps = _make_deps_for_submit(tmp_path, doc=doc, ocr_sources=[{"source_id": 30}])
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_submit("book-1", {"document_ids": [3]}, deps)
    assert result.allowed


def test_validate_submit_allows_epub_document(tmp_path):
    doc = {"document_id": 4, "document_type": "epub"}
    deps = _make_deps_for_submit(tmp_path, doc=doc, ocr_sources=[{"source_id": 40}])
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_submit("book-1", {"document_ids": [4]}, deps)
    assert result.allowed


def test_validate_submit_rejects_source_id_not_belonging_to_doc(tmp_path):
    doc = {"document_id": 1, "document_type": "scanned_book"}
    all_sources = [{"source_id": 10}, {"source_id": 11}]
    deps = _make_deps_for_submit(
        tmp_path,
        doc=doc,
        ocr_sources=[{"source_id": 10}],
        all_sources=all_sources,
    )
    with deps._patches[0], deps._patches[1]:
        # source_id=99 does not belong to document
        result = handler.validate_submit("book-1", {"document_ids": [1], "source_ids": [99]}, deps)
    assert not result.allowed
    assert "99" in result.reason


def test_validate_submit_with_valid_explicit_source_ids(tmp_path):
    doc = {"document_id": 1, "document_type": "scanned_book"}
    all_sources = [{"source_id": 10}, {"source_id": 11}]
    pending_sources = [{"source_id": 10}, {"source_id": 11}]
    deps = _make_deps_for_submit(
        tmp_path,
        doc=doc,
        ocr_sources=pending_sources,
        all_sources=all_sources,
    )
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_submit("book-1", {"document_ids": [1], "source_ids": [10]}, deps)
    assert result.allowed


def test_validate_submit_allows_explicit_source_ids_even_if_already_completed(tmp_path):
    """Explicit source_ids allow rerun of already OCR-completed pages."""
    doc = {"document_id": 1, "document_type": "scanned_book"}
    all_sources = [{"source_id": 10}, {"source_id": 11}]
    pending_sources: list[dict] = []
    deps = _make_deps_for_submit(
        tmp_path,
        doc=doc,
        ocr_sources=pending_sources,
        all_sources=all_sources,
    )
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_submit("book-1", {"document_ids": [1], "source_ids": [10]}, deps)
    assert result.allowed


# ---------------------------------------------------------------------------
# validate_run() tests
# ---------------------------------------------------------------------------


def _make_deps_for_run(
    tmp_path,
    *,
    doc: dict | None = None,
    ocr_sources: list[dict] | None = None,
    all_sources: list[dict] | None = None,
    book_config: dict | None | object = _SENTINEL,
):
    from unittest.mock import MagicMock, patch

    deps = MagicMock()
    deps.book_manager.get_book_db_path.return_value = tmp_path / "book.db"

    if book_config is _SENTINEL:
        book_config = {"ocr_config": {"endpoint_profile": "test"}}
    deps.book_manager.get_book_config.return_value = book_config

    fake_db = MagicMock()
    fake_repo = MagicMock()
    fake_repo.get_document_by_id.return_value = doc
    fake_repo.get_document_sources_needing_ocr.return_value = ocr_sources or []
    fake_repo.get_document_sources_metadata.return_value = all_sources or []

    deps._patches = (
        patch("context_aware_translation.storage.schema.book_db.SQLiteBookDB", return_value=fake_db),
        patch(
            "context_aware_translation.storage.repositories.document_repository.DocumentRepository",
            return_value=fake_repo,
        ),
    )
    return deps


def test_validate_run_rejects_missing_document_id(tmp_path):
    record = _make_record(document_ids_json=None)
    deps = _make_deps_for_run(tmp_path)
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_run(record, {}, deps)
    assert not result.allowed


def test_validate_run_rejects_missing_ocr_config(tmp_path):
    record = _make_record(document_ids_json=json.dumps([1]))
    doc = {"document_id": 1, "document_type": "scanned_book"}
    deps = _make_deps_for_run(tmp_path, doc=doc, ocr_sources=[{"source_id": 10}], book_config={})
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_run(record, {}, deps)
    assert not result.allowed
    assert "ocr_config" in result.reason.lower()


def test_validate_run_rejects_document_not_found(tmp_path):
    record = _make_record(document_ids_json=json.dumps([99]))
    deps = _make_deps_for_run(tmp_path, doc=None)
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_run(record, {}, deps)
    assert not result.allowed
    assert "not found" in result.reason.lower()


def test_validate_run_rejects_non_ocr_capable_document(tmp_path):
    record = _make_record(document_ids_json=json.dumps([1]))
    doc = {"document_id": 1, "document_type": "text"}
    deps = _make_deps_for_run(tmp_path, doc=doc)
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_run(record, {}, deps)
    assert not result.allowed


def test_validate_run_rejects_no_pending_sources(tmp_path):
    record = _make_record(document_ids_json=json.dumps([1]))
    doc = {"document_id": 1, "document_type": "scanned_book"}
    deps = _make_deps_for_run(tmp_path, doc=doc, ocr_sources=[])
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_run(record, {}, deps)
    assert not result.allowed
    assert "no pending" in result.reason.lower()


def test_validate_run_allows_valid_record(tmp_path):
    record = _make_record(document_ids_json=json.dumps([1]))
    doc = {"document_id": 1, "document_type": "scanned_book"}
    deps = _make_deps_for_run(tmp_path, doc=doc, ocr_sources=[{"source_id": 10}])
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_run(record, {}, deps)
    assert result.allowed


def test_validate_run_with_valid_source_ids_in_payload(tmp_path):
    record = _make_record(document_ids_json=json.dumps([1]))
    doc = {"document_id": 1, "document_type": "pdf"}
    all_sources = [{"source_id": 10}, {"source_id": 11}]
    pending = []
    deps = _make_deps_for_run(tmp_path, doc=doc, ocr_sources=pending, all_sources=all_sources)
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_run(record, {"source_ids": [10]}, deps)
    assert result.allowed


def test_validate_run_rejects_invalid_source_id_in_payload(tmp_path):
    record = _make_record(document_ids_json=json.dumps([1]))
    doc = {"document_id": 1, "document_type": "pdf"}
    all_sources = [{"source_id": 10}]
    pending = [{"source_id": 10}]
    deps = _make_deps_for_run(tmp_path, doc=doc, ocr_sources=pending, all_sources=all_sources)
    with deps._patches[0], deps._patches[1]:
        result = handler.validate_run(record, {"source_ids": [999]}, deps)
    assert not result.allowed


# ---------------------------------------------------------------------------
# build_worker() tests
# ---------------------------------------------------------------------------


def test_build_worker_run_returns_ocr_task_worker():
    from unittest.mock import MagicMock

    deps = MagicMock()
    record = _make_record(
        status=STATUS_QUEUED,
        document_ids_json=json.dumps([1]),
        payload_json=json.dumps({"source_ids": [10]}),
    )
    payload = handler.decode_payload(record)
    try:
        worker = handler.build_worker(TaskAction.RUN, record, payload, deps)
        from context_aware_translation.adapters.qt.workers.ocr_task_worker import OCRTaskWorker

        assert isinstance(worker, OCRTaskWorker)
    except ImportError:
        pytest.skip("OCRTaskWorker not yet implemented")


def test_build_worker_cancel_returns_ocr_task_worker():
    from unittest.mock import MagicMock

    deps = MagicMock()
    record = _make_record(status=STATUS_RUNNING, document_ids_json=json.dumps([1]))
    try:
        worker = handler.build_worker(TaskAction.CANCEL, record, {}, deps)
        from context_aware_translation.adapters.qt.workers.ocr_task_worker import OCRTaskWorker

        assert isinstance(worker, OCRTaskWorker)
    except ImportError:
        pytest.skip("OCRTaskWorker not yet implemented")


def test_build_worker_unsupported_action_raises():
    from unittest.mock import MagicMock

    deps = MagicMock()
    record = _make_record(status=STATUS_QUEUED, document_ids_json=json.dumps([1]))
    with pytest.raises((ValueError, ImportError)):
        handler.build_worker(TaskAction.DELETE, record, {}, deps)


# ---------------------------------------------------------------------------
# cancel_dispatch_policy() and classify_cancel_outcome()
# ---------------------------------------------------------------------------


def test_cancel_dispatch_policy_is_local_terminalize():
    from context_aware_translation.workflow.tasks.handlers.base import CancelDispatchPolicy

    record = _make_record()
    policy = handler.cancel_dispatch_policy(record, {})
    assert policy == CancelDispatchPolicy.LOCAL_TERMINALIZE


def test_classify_cancel_outcome_is_confirmed_cancelled():
    from context_aware_translation.workflow.tasks.handlers.base import CancelOutcome

    record = _make_record()
    outcome = handler.classify_cancel_outcome(record, {}, None)
    assert outcome == CancelOutcome.CONFIRMED_CANCELLED


# ---------------------------------------------------------------------------
# pre_delete()
# ---------------------------------------------------------------------------


def test_pre_delete_returns_empty_list():
    from unittest.mock import MagicMock

    record = _make_record()
    assert handler.pre_delete(record, {}, MagicMock()) == []
