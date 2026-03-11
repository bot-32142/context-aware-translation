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
from context_aware_translation.workflow.tasks.handlers.batch_translation import BatchTranslationHandler
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
    task_id: str = "task-abc",
    book_id: str = "book-1",
    config_snapshot_json: str | None = None,
) -> TaskRecord:
    now = time.time()
    return TaskRecord(
        task_id=task_id,
        book_id=book_id,
        task_type="batch_translation",
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


handler = BatchTranslationHandler()


def test_task_type():
    assert handler.task_type == "batch_translation"


def test_decode_payload_empty():
    record = _make_record(payload_json=None)
    assert handler.decode_payload(record) == {}


def test_decode_payload_invalid_json():
    record = _make_record(payload_json="not-json{{{")
    assert handler.decode_payload(record) == {}


def test_decode_payload_valid():
    data = {"model": "gemini", "items": [1, 2, 3]}
    record = _make_record(payload_json=json.dumps(data))
    assert handler.decode_payload(record) == data


def test_scope_all_documents_when_none():
    record = _make_record(document_ids_json=None)
    scope = handler.scope(record, {})
    assert isinstance(scope, AllDocuments)
    assert scope.book_id == "book-1"


def test_scope_all_documents_when_empty_list():
    record = _make_record(document_ids_json="[]")
    scope = handler.scope(record, {})
    assert isinstance(scope, AllDocuments)


def test_scope_some_documents_with_ids():
    record = _make_record(document_ids_json="[10, 20, 30]")
    scope = handler.scope(record, {})
    assert isinstance(scope, SomeDocuments)
    assert scope.doc_ids == frozenset({10, 20, 30})
    assert scope.book_id == "book-1"


def test_claims_wildcard_for_all_documents():
    record = _make_record(document_ids_json=None)
    claims = handler.claims(record, {})
    assert claims == frozenset(
        {
            ResourceClaim("doc", "book-1", "*"),
            ResourceClaim("glossary_state", "book-1", "*", ClaimMode.READ_SHARED),
            ResourceClaim("context_tree", "book-1", "*", ClaimMode.WRITE_COOPERATIVE),
        }
    )


def test_claims_per_doc_for_some_documents():
    record = _make_record(document_ids_json="[5, 7]")
    claims = handler.claims(record, {})
    assert claims == frozenset(
        {
            ResourceClaim("doc", "book-1", "5"),
            ResourceClaim("doc", "book-1", "7"),
            ResourceClaim("glossary_state", "book-1", "*", ClaimMode.READ_SHARED),
            ResourceClaim("context_tree", "book-1", "*", ClaimMode.WRITE_COOPERATIVE),
        }
    )


# --- can(RUN) ---


def test_can_run_allows_queued():
    record = _make_record(status=STATUS_QUEUED)
    decision = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert decision.allowed is True


def test_can_run_allows_paused():
    record = _make_record(status=STATUS_PAUSED)
    decision = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert decision.allowed is True


def test_can_run_allows_failed_rerunnable():
    record = _make_record(status=STATUS_FAILED)
    decision = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert decision.allowed is True


def test_can_run_allows_cancelled_rerunnable():
    record = _make_record(status=STATUS_CANCELLED)
    decision = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert decision.allowed is True


def test_can_run_allows_completed_with_errors_rerunnable():
    record = _make_record(status=STATUS_COMPLETED_WITH_ERRORS)
    decision = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert decision.allowed is True


def test_can_run_allows_running_resume():
    record = _make_record(status=STATUS_RUNNING)
    decision = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert decision.allowed is True


def test_can_run_allows_cancel_requested_resume():
    record = _make_record(status=STATUS_CANCEL_REQUESTED)
    decision = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert decision.allowed is True


def test_can_run_allows_cancelling_resume():
    record = _make_record(status=STATUS_CANCELLING)
    decision = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert decision.allowed is True


def test_can_run_denies_completed():
    record = _make_record(status=STATUS_COMPLETED)
    decision = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert decision.allowed is False
    assert "completed" in decision.reason.lower()


# --- can(CANCEL) ---


def test_can_cancel_allows_running():
    record = _make_record(status=STATUS_RUNNING)
    decision = handler.can(TaskAction.CANCEL, record, {}, _make_snapshot())
    assert decision.allowed is True


def test_can_cancel_allows_queued():
    record = _make_record(status=STATUS_QUEUED)
    decision = handler.can(TaskAction.CANCEL, record, {}, _make_snapshot())
    assert decision.allowed is True


def test_can_cancel_denies_completed():
    record = _make_record(status=STATUS_COMPLETED)
    decision = handler.can(TaskAction.CANCEL, record, {}, _make_snapshot())
    assert decision.allowed is False
    assert "terminal" in decision.reason.lower()


def test_can_cancel_denies_cancelled():
    record = _make_record(status=STATUS_CANCELLED)
    decision = handler.can(TaskAction.CANCEL, record, {}, _make_snapshot())
    assert decision.allowed is False


def test_can_cancel_denies_failed():
    record = _make_record(status=STATUS_FAILED)
    decision = handler.can(TaskAction.CANCEL, record, {}, _make_snapshot())
    assert decision.allowed is False


# --- can(DELETE) ---


def test_can_delete_allows_completed():
    record = _make_record(status=STATUS_COMPLETED)
    decision = handler.can(TaskAction.DELETE, record, {}, _make_snapshot())
    assert decision.allowed is True


def test_can_delete_allows_queued():
    record = _make_record(status=STATUS_QUEUED)
    decision = handler.can(TaskAction.DELETE, record, {}, _make_snapshot())
    assert decision.allowed is True


def test_can_delete_denies_running():
    record = _make_record(status=STATUS_RUNNING)
    decision = handler.can(TaskAction.DELETE, record, {}, _make_snapshot())
    assert decision.allowed is False
    assert "active" in decision.reason.lower()


def test_can_delete_denies_cancel_requested():
    record = _make_record(status=STATUS_CANCEL_REQUESTED)
    decision = handler.can(TaskAction.DELETE, record, {}, _make_snapshot())
    assert decision.allowed is False


def test_can_delete_denies_cancelling():
    record = _make_record(status=STATUS_CANCELLING)
    decision = handler.can(TaskAction.DELETE, record, {}, _make_snapshot())
    assert decision.allowed is False


# --- can_autorun ---


def test_can_autorun_allows_queued_no_conflicts():
    record = _make_record(status=STATUS_QUEUED, task_id="t1")
    snapshot = _make_snapshot()
    decision = handler.can_autorun(record, {}, snapshot)
    assert decision.allowed is True


def test_can_autorun_denies_already_in_running_task_ids():
    record = _make_record(status=STATUS_QUEUED, task_id="t1")
    snapshot = _make_snapshot(running_task_ids=frozenset({"t1"}))
    decision = handler.can_autorun(record, {}, snapshot)
    assert decision.allowed is False
    assert "already running" in decision.reason.lower()


def test_can_autorun_denies_terminal_status():
    record = _make_record(status=STATUS_COMPLETED, task_id="t1")
    snapshot = _make_snapshot()
    decision = handler.can_autorun(record, {}, snapshot)
    assert decision.allowed is False


def test_can_autorun_denies_claim_conflict():
    record = _make_record(status=STATUS_QUEUED, task_id="t1", document_ids_json=None)
    # active claim with wildcard on same book
    active = frozenset({ResourceClaim("doc", "book-1", "*")})
    snapshot = _make_snapshot(active_claims=active)
    decision = handler.can_autorun(record, {}, snapshot)
    assert decision.allowed is False
    assert "conflict" in decision.reason.lower()


def test_can_autorun_allows_when_different_book_claims():
    record = _make_record(status=STATUS_QUEUED, task_id="t1", book_id="book-A", document_ids_json=None)
    # active claim on different book
    active = frozenset({ResourceClaim("doc", "book-B", "*")})
    snapshot = _make_snapshot(active_claims=active)
    decision = handler.can_autorun(record, {}, snapshot)
    assert decision.allowed is True


# ---------------------------------------------------------------------------
# config_snapshot_json tests
# ---------------------------------------------------------------------------


def test_build_worker_run_passes_config_snapshot_to_worker():
    """build_worker(RUN) must forward config_snapshot_json from record to the worker."""
    import json
    from unittest.mock import MagicMock

    snapshot = json.dumps({"snapshot_version": 1, "config": {"key": "val"}})
    deps = MagicMock()
    record = _make_record(
        status=STATUS_QUEUED,
        payload_json=None,
        config_snapshot_json=snapshot,
    )
    payload = handler.decode_payload(record)
    worker = handler.build_worker(TaskAction.RUN, record, payload, deps)

    from context_aware_translation.adapters.qt.workers.batch_translation_task_worker import BatchTranslationTaskWorker

    assert isinstance(worker, BatchTranslationTaskWorker)
    assert worker.config_snapshot_json == snapshot


def test_build_worker_cancel_passes_config_snapshot_to_worker():
    """build_worker(CANCEL) must forward config_snapshot_json to the cancel worker."""
    import json
    from unittest.mock import MagicMock

    snapshot = json.dumps({"snapshot_version": 1, "config": {"key": "val"}})
    deps = MagicMock()
    record = _make_record(
        status=STATUS_RUNNING,
        config_snapshot_json=snapshot,
    )
    worker = handler.build_worker(TaskAction.CANCEL, record, {}, deps)

    from context_aware_translation.adapters.qt.workers.batch_translation_task_worker import BatchTranslationTaskWorker

    assert isinstance(worker, BatchTranslationTaskWorker)
    assert worker.config_snapshot_json == snapshot


def test_pre_delete_uses_snapshot_when_available():
    """pre_delete() should use from_snapshot() when config_snapshot_json is set."""
    import json
    from unittest.mock import MagicMock, patch

    snapshot = json.dumps({"snapshot_version": 1, "config": {}})
    deps = MagicMock()
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=MagicMock())
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_executor = MagicMock()
    mock_executor.cleanup_remote_artifacts.return_value = {"cleanup_warnings": []}

    record = _make_record(status=STATUS_COMPLETED, config_snapshot_json=snapshot)

    with (
        patch(
            "context_aware_translation.workflow.session.WorkflowSession.from_snapshot",
            return_value=mock_session,
        ) as mock_from_snapshot,
        patch(
            "context_aware_translation.workflow.tasks.execution.batch_translation_executor.BatchTranslationExecutor.from_workflow",
            return_value=mock_executor,
        ),
    ):
        warnings = handler.pre_delete(record, {}, deps)

    mock_from_snapshot.assert_called_once_with(snapshot, record.book_id)
    assert warnings == []


def test_pre_delete_falls_back_to_live_config_when_from_snapshot_raises():
    """pre_delete() should fall back to create_workflow_session when from_snapshot fails."""
    import json
    from unittest.mock import MagicMock, patch

    snapshot = json.dumps({"snapshot_version": 1, "config": {}})
    deps = MagicMock()
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=MagicMock())
    mock_session.__exit__ = MagicMock(return_value=False)
    deps.create_workflow_session.return_value = mock_session
    mock_executor = MagicMock()
    mock_executor.cleanup_remote_artifacts.return_value = {"cleanup_warnings": []}

    record = _make_record(status=STATUS_COMPLETED, config_snapshot_json=snapshot)

    with (
        patch(
            "context_aware_translation.workflow.session.WorkflowSession.from_snapshot",
            side_effect=ValueError("bad snapshot"),
        ),
        patch(
            "context_aware_translation.workflow.tasks.execution.batch_translation_executor.BatchTranslationExecutor.from_workflow",
            return_value=mock_executor,
        ),
    ):
        warnings = handler.pre_delete(record, {}, deps)

    deps.create_workflow_session.assert_called_once_with(record.book_id)
    assert warnings == []
