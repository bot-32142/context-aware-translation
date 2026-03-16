"""Tests for TaskEngine core behavior."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest

try:
    from PySide6.QtWidgets import QApplication

    HAS_PYSIDE6 = True
except ImportError:
    HAS_PYSIDE6 = False

pytestmark = pytest.mark.skipif(not HAS_PYSIDE6, reason="PySide6 not available")


@pytest.fixture(autouse=True, scope="module")
def _qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def tmp_store(tmp_path):
    """Create a real TaskStore backed by a temp SQLite file."""
    from context_aware_translation.storage.repositories.task_store import TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    yield store
    store.close()


@pytest.fixture()
def mock_deps():
    """Create a mock WorkerDeps."""
    import json

    from context_aware_translation.workflow.tasks.worker_deps import WorkerDeps

    book_manager = MagicMock()
    # Provide a valid snapshot JSON so submit() / ensure_runnable() / rerun() succeed
    book_manager.get_config_snapshot_json.return_value = json.dumps(
        {"snapshot_version": 1, "config": {"translation_target_language": "en"}}
    )
    task_store = MagicMock()
    create_workflow_session = MagicMock()
    notify_task_changed = MagicMock()
    return WorkerDeps(
        book_manager=book_manager,
        task_store=task_store,
        create_workflow_session=create_workflow_session,
        notify_task_changed=notify_task_changed,
    )


def _make_handler(task_type: str = "test_task", *, can_autorun: bool = True, can_run: bool = True):
    """Build a minimal mock TaskTypeHandler."""
    from context_aware_translation.workflow.tasks.models import Decision

    handler = MagicMock()
    handler.task_type = task_type
    handler.decode_payload.return_value = {}
    handler.claims.return_value = frozenset()
    handler.can.return_value = Decision(allowed=can_run)
    handler.can_autorun.return_value = Decision(allowed=can_autorun)
    handler.validate_submit.return_value = Decision(allowed=True)
    handler.scope.return_value = MagicMock()

    # build_worker returns a mock QThread-like worker
    worker_mock = MagicMock()
    worker_mock.isRunning.return_value = False
    handler.build_worker.return_value = worker_mock

    return handler


@pytest.fixture()
def engine(tmp_store, mock_deps):
    """Create a TaskEngine with a real store and mock deps."""
    from context_aware_translation.adapters.qt.task_engine import TaskEngine

    eng = TaskEngine(store=tmp_store, deps=mock_deps)
    yield eng
    eng.stop_autorun()


# ------------------------------------------------------------------
# register_handler / _handler_or_raise
# ------------------------------------------------------------------


def test_register_handler_and_retrieve(engine):
    handler = _make_handler("my_type")
    engine.register_handler(handler)
    assert engine._core._handler_or_raise("my_type") is handler


def test_handler_or_raise_unknown_type(engine):
    with pytest.raises(RuntimeError, match="No handler registered"):
        engine._core._handler_or_raise("nonexistent_type")


# ------------------------------------------------------------------
# _build_snapshot
# ------------------------------------------------------------------


def test_build_snapshot_returns_action_snapshot(engine):
    from context_aware_translation.workflow.tasks.models import ActionSnapshot

    snap = engine._core._build_snapshot()
    assert isinstance(snap, ActionSnapshot)
    assert isinstance(snap.running_task_ids, frozenset)
    assert isinstance(snap.active_claims, frozenset)
    assert snap.now_monotonic > 0


def test_build_snapshot_reflects_active_workers(engine, tmp_store):  # noqa: ARG001
    from context_aware_translation.workflow.tasks.claims import ResourceClaim

    engine._core._active_workers["fake-task-id"] = MagicMock()
    claim = ResourceClaim(namespace="doc", book_id="book-1", key="*")
    engine._core._active_claims["fake-task-id"] = frozenset({claim})

    snap = engine._core._build_snapshot()
    assert "fake-task-id" in snap.running_task_ids
    assert claim in snap.active_claims

    # cleanup
    engine._core._active_workers.clear()
    engine._core._active_claims.clear()


# ------------------------------------------------------------------
# has_running_work
# ------------------------------------------------------------------


def test_has_running_work_initially_false(engine):
    assert engine.has_running_work() is False


def test_has_running_work_true_when_worker_active(engine):
    engine._core._active_workers["some-id"] = MagicMock()
    assert engine.has_running_work() is True
    engine._core._active_workers.clear()


# ------------------------------------------------------------------
# submit
# ------------------------------------------------------------------


def test_submit_creates_record(engine, tmp_store):  # noqa: ARG001
    handler = _make_handler("batch", can_run=False)  # can=False so worker won't start
    engine.register_handler(handler)

    record = engine.submit("batch", "book-42")
    assert record.book_id == "book-42"
    assert record.task_type == "batch"
    assert record.status == "queued"


def test_preflight_creation_returns_decision_for_batch_handler(engine, tmp_path):
    from context_aware_translation.storage.schema.book_db import SQLiteBookDB
    from context_aware_translation.workflow.tasks.handlers.batch_translation import BatchTranslationHandler
    from context_aware_translation.workflow.tasks.models import TaskAction

    # Set up a real book DB so validate_submit can open it
    book_db_path = tmp_path / "book.db"
    db = SQLiteBookDB(book_db_path)
    db.close()
    engine._core._deps.book_manager.get_book_db_path.return_value = book_db_path

    engine.register_handler(BatchTranslationHandler())
    decision = engine.preflight(
        "batch_translation",
        "book-preflight",
        {"document_ids": [1, 2], "force": False, "skip_context": False},
        TaskAction.RUN,
    )
    assert decision.allowed is True


# ------------------------------------------------------------------
# tick with unknown task_type
# ------------------------------------------------------------------


def test_tick_unknown_task_type_stops_autorun_and_emits_error(engine, tmp_store):
    # Insert a task with an unregistered type directly
    tmp_store.create(book_id="book-1", task_type="unknown_type", status="queued")

    errors = []
    engine.error_occurred.connect(errors.append)

    engine.start_autorun(interval_ms=50)

    with pytest.raises(RuntimeError, match="No handler registered"):
        engine.tick()

    assert len(errors) == 1
    assert "unknown_type" in errors[0]
    assert engine._autorun_timer is not None
    assert not engine._autorun_timer.isActive()


# ------------------------------------------------------------------
# running_work_changed signal
# ------------------------------------------------------------------


def test_running_work_changed_emits_on_state_change(engine):
    emissions: list[bool] = []
    engine.running_work_changed.connect(emissions.append)

    # Simulate going from no workers to one
    engine._core._active_workers["t1"] = MagicMock()
    engine._emit_running_work_changed_if_needed()
    assert emissions == [True]

    # Same state — no new emission
    engine._emit_running_work_changed_if_needed()
    assert emissions == [True]

    # Back to no workers
    engine._core._active_workers.clear()
    engine._emit_running_work_changed_if_needed()
    assert emissions == [True, False]


def test_submit_emits_running_work_changed_immediately_without_tick(engine):
    handler = _make_handler("immediate", can_run=True)
    worker = handler.build_worker.return_value
    worker.isRunning.return_value = True
    engine.register_handler(handler)
    emissions: list[bool] = []
    engine.running_work_changed.connect(emissions.append)

    engine.submit("immediate", "book-immediate")

    assert emissions == [True]


def test_rerun_emits_running_work_changed_immediately_without_tick(engine, tmp_store):
    handler = _make_handler("rerunnable", can_run=True)
    worker = handler.build_worker.return_value
    worker.isRunning.return_value = True
    engine.register_handler(handler)

    # rerun() requires a terminal status task
    record = tmp_store.create(book_id="book-rerun", task_type="rerunnable", status="failed")

    emissions: list[bool] = []
    engine.running_work_changed.connect(emissions.append)

    engine.rerun(record.task_id)

    assert emissions == [True]


def test_run_task_image_reembedding_forces_payload_on_terminal(engine, tmp_store):
    handler = _make_handler("image_reembedding", can_run=True)
    engine.register_handler(handler)
    record = tmp_store.create(
        book_id="book-reembed",
        task_type="image_reembedding",
        status="failed",
        payload_json=json.dumps({"source_ids": [7], "force": False}),
    )

    updated = engine.run_task(record.task_id)
    payload = json.loads(updated.payload_json or "{}")
    assert payload.get("force") is True
    assert payload.get("source_ids") == [7]


def test_cancel_emits_running_work_changed_when_cancel_worker_starts(engine, tmp_store):
    handler = _make_handler("cancelable", can_run=True)
    worker = handler.build_worker.return_value
    worker.isRunning.return_value = True
    engine.register_handler(handler)
    record = tmp_store.create(book_id="book-cancel", task_type="cancelable", status="queued")

    emissions: list[bool] = []
    engine.running_work_changed.connect(emissions.append)

    engine.cancel(record.task_id)

    assert emissions == [True]


def test_delete_does_not_emit_running_work_changed_when_state_unchanged(engine, tmp_store):
    handler = _make_handler("deletable", can_run=True)
    engine.register_handler(handler)
    record = tmp_store.create(book_id="book-delete", task_type="deletable", status="queued")

    emissions: list[bool] = []
    engine.running_work_changed.connect(emissions.append)

    engine.delete(record.task_id)

    # delete() must not emit when there was no running work transition.
    assert emissions == []


def test_cancel_running_tasks_emits_running_work_changed_when_worker_stops_immediately(engine, tmp_store):
    handler = _make_handler("cancel-now", can_run=True)
    engine.register_handler(handler)
    record = tmp_store.create(book_id="book-cancel-now", task_type="cancel-now", status="running")

    worker_mock = MagicMock()
    worker_mock.isRunning.return_value = True

    # Simulate immediate stop on interruption so running state flips in
    # cancel_running_tasks() action path without waiting for tick().
    def _stop_now():
        engine._core._active_workers.pop(record.task_id, None)
        engine._core._active_claims.pop(record.task_id, None)

    worker_mock.requestInterruption.side_effect = _stop_now
    engine._core._active_workers[record.task_id] = worker_mock
    engine._core._active_claims[record.task_id] = frozenset()
    engine._was_running = True

    emissions: list[bool] = []
    engine.running_work_changed.connect(emissions.append)

    engine.cancel_running_tasks("book-cancel-now")

    assert emissions == [False]


# ------------------------------------------------------------------
# _is_in_backoff
# ------------------------------------------------------------------


def test_is_in_backoff_respects_retry_after(engine):
    now = time.monotonic()
    engine._core._set_backoff("book-1", now)
    assert engine._core._is_in_backoff("book-1", now) is True
    assert engine._core._is_in_backoff("book-1", now + 31) is False


def test_is_in_backoff_false_when_not_set(engine):
    assert engine._core._is_in_backoff("book-99", time.monotonic()) is False


# ------------------------------------------------------------------
# close stops autorun timer
# ------------------------------------------------------------------


def test_close_stops_autorun_timer(tmp_path, mock_deps):
    from context_aware_translation.adapters.qt.task_engine import TaskEngine
    from context_aware_translation.storage.repositories.task_store import TaskStore

    store = TaskStore(tmp_path / "tasks_close.db")
    eng = TaskEngine(store=store, deps=mock_deps)
    eng.start_autorun(interval_ms=5000)
    assert eng._autorun_timer is not None and eng._autorun_timer.isActive()

    eng.close()

    assert eng._autorun_timer is None or not eng._autorun_timer.isActive()


# ------------------------------------------------------------------
# cancel_running_tasks interrupts active workers for book
# ------------------------------------------------------------------


def test_cancel_running_tasks_interrupts_workers(engine, tmp_store):
    handler = _make_handler("test_task")
    engine.register_handler(handler)
    record = tmp_store.create(book_id="book-cancel", task_type="test_task", status="running")

    worker_mock = MagicMock()
    engine._core._active_workers[record.task_id] = worker_mock

    engine.cancel_running_tasks("book-cancel")

    worker_mock.requestInterruption.assert_called_once()

    # cleanup
    engine._core._active_workers.clear()


def test_cancel_running_tasks_ignores_other_books(engine, tmp_store):
    handler = _make_handler("test_task")
    engine.register_handler(handler)
    record = tmp_store.create(book_id="book-other", task_type="test_task", status="running")

    worker_mock = MagicMock()
    engine._core._active_workers[record.task_id] = worker_mock

    engine.cancel_running_tasks("book-target")

    worker_mock.requestInterruption.assert_not_called()

    # cleanup
    engine._core._active_workers.clear()


def test_delete_allows_queued_when_handler_allows(engine, tmp_store):
    from context_aware_translation.workflow.tasks.handlers.batch_translation import BatchTranslationHandler

    handler = BatchTranslationHandler()
    # This test validates delete semantics for queued tasks, not remote cleanup.
    # Stub pre_delete to avoid opening batch cleanup stores from mock sessions.
    handler.pre_delete = MagicMock(return_value=[])
    engine.register_handler(handler)
    record = tmp_store.create(book_id="book-del", task_type="batch_translation", status="queued")

    engine.delete(record.task_id)

    assert tmp_store.get(record.task_id) is None


def test_cancel_does_not_rewrite_terminal_status(engine, tmp_store):
    from context_aware_translation.workflow.tasks.handlers.batch_translation import BatchTranslationHandler

    engine.register_handler(BatchTranslationHandler())
    record = tmp_store.create(book_id="book-cancel", task_type="batch_translation", status="completed")

    engine.cancel(record.task_id)

    updated = tmp_store.get(record.task_id)
    assert updated is not None
    assert updated.status == "completed"
    assert updated.cancel_requested is False


# ------------------------------------------------------------------
# submit_and_start: strict interactive submit for chunk_retranslation
# ------------------------------------------------------------------


def test_submit_and_start_marks_task_failed_when_start_raises(engine, tmp_store):
    """submit_and_start never strands a task in queued when the immediate start fails.

    This is the strict interactive submit contract used for chunk_retranslation.
    """
    from context_aware_translation.workflow.tasks.models import Decision

    handler = _make_handler("chunk_retranslation")
    # Simulate validate_submit allowed but build_worker raises (start will fail)
    handler.validate_submit.return_value = Decision(allowed=True)
    handler.validate_run.return_value = Decision(allowed=True)
    handler.can.return_value = Decision(allowed=True)
    handler.build_worker.side_effect = RuntimeError("worker construction failed")
    engine.register_handler(handler)

    record = engine.submit_and_start("chunk_retranslation", "book-strict", chunk_id=1, document_id=2)

    # Task must NOT be left in queued — it should be marked failed
    assert record.status == "failed"
    stored = tmp_store.get(record.task_id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.last_error is not None
    assert "strict-start failed" in stored.last_error


def test_submit_and_start_succeeds_when_worker_starts(engine, tmp_store):
    """submit_and_start returns a running/queued record when start succeeds."""
    from context_aware_translation.workflow.tasks.models import Decision

    handler = _make_handler("chunk_retranslation")
    handler.validate_submit.return_value = Decision(allowed=True)
    handler.validate_run.return_value = Decision(allowed=True)
    handler.can.return_value = Decision(allowed=True)
    worker_mock = MagicMock()
    worker_mock.isRunning.return_value = True
    handler.build_worker.return_value = worker_mock
    handler.build_worker.side_effect = None
    engine.register_handler(handler)

    record = engine.submit_and_start("chunk_retranslation", "book-strict2", chunk_id=3, document_id=4)

    # Should not be failed
    assert record.status != "failed"
    stored = tmp_store.get(record.task_id)
    assert stored is not None
    assert stored.status != "failed"

    # cleanup
    engine._core._active_workers.clear()
    engine._core._active_claims.clear()
