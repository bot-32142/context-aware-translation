"""Tests for EngineCore config snapshot capture/refresh logic."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest

from context_aware_translation.storage.task_store import TaskRecord, TaskStore
from context_aware_translation.workflow.tasks.engine_core import EngineCore
from context_aware_translation.workflow.tasks.models import (
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_QUEUED,
    TaskAction,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    status: str = STATUS_QUEUED,
    task_id: str = "task-1",
    book_id: str = "book-1",
    task_type: str = "batch_translation",
    config_snapshot_json: str | None = None,
) -> TaskRecord:
    now = time.time()
    return TaskRecord(
        task_id=task_id,
        book_id=book_id,
        task_type=task_type,
        status=status,
        phase=None,
        document_ids_json=None,
        payload_json=None,
        config_snapshot_json=config_snapshot_json,
        cancel_requested=False,
        total_items=0,
        completed_items=0,
        failed_items=0,
        last_error=None,
        created_at=now,
        updated_at=now,
    )


def _make_engine(tmp_path) -> tuple[EngineCore, MagicMock]:
    """Return (engine, mock_deps) with a real TaskStore and mocked WorkerDeps."""
    store = TaskStore(tmp_path / "tasks.db")
    # Use plain MagicMock (not spec=WorkerDeps) because from __future__ import annotations
    # makes dataclass field annotations string-based, breaking spec-based attribute lookup.
    deps = MagicMock()
    engine = EngineCore(store=store, deps=deps)
    return engine, deps


def _make_handler(allowed: bool = True, task_type: str = "batch_translation") -> MagicMock:
    handler = MagicMock()
    handler.task_type = task_type
    handler.validate_submit.return_value = MagicMock(allowed=allowed, reason="")
    handler.validate_run.return_value = MagicMock(allowed=True)
    handler.decode_payload.return_value = {}
    handler.can.return_value = MagicMock(allowed=True)
    handler.claims.return_value = frozenset()
    return handler


_VALID_SNAPSHOT = json.dumps({"snapshot_version": 1, "config": {"key": "value"}})


# ---------------------------------------------------------------------------
# submit() — config snapshot capture
# ---------------------------------------------------------------------------


class TestSubmitConfigSnapshot:
    def test_submit_captures_config_snapshot(self, tmp_path):
        """submit() should store a config snapshot on the created task record."""
        engine, deps = _make_engine(tmp_path)
        handler = _make_handler()
        engine.register_handler(handler)

        # Simulate book_manager providing config that serialises to snapshot JSON
        deps.book_manager.get_config_snapshot_json.return_value = _VALID_SNAPSHOT

        record = engine.submit("batch_translation", "book-1")

        assert record.config_snapshot_json == _VALID_SNAPSHOT
        engine.close()

    def test_submit_raises_and_does_not_create_row_when_snapshot_fails(self, tmp_path):
        """submit() must raise ValueError and NOT persist any row when snapshot capture fails."""
        engine, deps = _make_engine(tmp_path)
        handler = _make_handler()
        engine.register_handler(handler)

        deps.book_manager.get_config_snapshot_json.side_effect = RuntimeError("config missing")

        with pytest.raises(ValueError, match="config"):
            engine.submit("batch_translation", "book-1")

        # The task must not have been persisted
        tasks = engine._store.list_tasks(book_id="book-1")
        assert tasks == []
        engine.close()


# ---------------------------------------------------------------------------
# preflight() — snapshot probe
# ---------------------------------------------------------------------------


class TestPreflightSnapshotProbe:
    def test_preflight_returns_denied_when_snapshot_probe_fails(self, tmp_path):
        """preflight() should return denied Decision when snapshot capture raises."""
        engine, deps = _make_engine(tmp_path)
        handler = _make_handler()
        engine.register_handler(handler)

        deps.book_manager.get_config_snapshot_json.side_effect = RuntimeError("no config")

        decision = engine.preflight("batch_translation", "book-1", {}, TaskAction.RUN)

        assert decision.allowed is False
        engine.close()

    def test_preflight_allowed_when_snapshot_probe_succeeds(self, tmp_path):
        """preflight() should return allowed when snapshot capture succeeds."""
        engine, deps = _make_engine(tmp_path)
        handler = _make_handler()
        engine.register_handler(handler)

        deps.book_manager.get_config_snapshot_json.return_value = _VALID_SNAPSHOT

        decision = engine.preflight("batch_translation", "book-1", {}, TaskAction.RUN)

        assert decision.allowed is True
        engine.close()


# ---------------------------------------------------------------------------
# ensure_runnable() — re-capture snapshot for terminal tasks
# ---------------------------------------------------------------------------


class TestEnsureRunnableSnapshot:
    def test_ensure_runnable_recaptures_snapshot_for_terminal_task(self, tmp_path):
        """ensure_runnable() should update config_snapshot_json for a terminal task."""
        engine, deps = _make_engine(tmp_path)
        handler = _make_handler()
        engine.register_handler(handler)

        new_snapshot = json.dumps({"snapshot_version": 1, "config": {"updated": True}})
        deps.book_manager.get_config_snapshot_json.return_value = new_snapshot

        # Create a failed task (terminal)
        record = engine._store.create(
            book_id="book-1",
            task_type="batch_translation",
            status=STATUS_FAILED,
            config_snapshot_json=_VALID_SNAPSHOT,
        )

        result = engine.ensure_runnable(record.task_id)

        assert result.status == STATUS_QUEUED
        assert result.config_snapshot_json == new_snapshot
        engine.close()

    def test_ensure_runnable_raises_and_leaves_status_unchanged_when_capture_fails(self, tmp_path):
        """ensure_runnable() must raise ValueError and not change status when capture fails."""
        engine, deps = _make_engine(tmp_path)
        handler = _make_handler()
        engine.register_handler(handler)

        deps.book_manager.get_config_snapshot_json.side_effect = RuntimeError("config error")

        record = engine._store.create(
            book_id="book-1",
            task_type="batch_translation",
            status=STATUS_FAILED,
            config_snapshot_json=_VALID_SNAPSHOT,
        )
        original_status = record.status

        with pytest.raises(ValueError):
            engine.ensure_runnable(record.task_id)

        # Status must remain unchanged
        fetched = engine._store.get(record.task_id)
        assert fetched is not None
        assert fetched.status == original_status
        engine.close()

    def test_ensure_runnable_nonterminal_task_returned_as_is(self, tmp_path):
        """ensure_runnable() should return non-terminal tasks without touching snapshot."""
        engine, deps = _make_engine(tmp_path)
        handler = _make_handler()
        engine.register_handler(handler)

        deps.book_manager.get_config_snapshot_json.return_value = _VALID_SNAPSHOT

        record = engine._store.create(
            book_id="book-1",
            task_type="batch_translation",
            status=STATUS_QUEUED,
        )

        result = engine.ensure_runnable(record.task_id)

        assert result.status == STATUS_QUEUED
        engine.close()


# ---------------------------------------------------------------------------
# rerun() — re-capture snapshot for terminal tasks
# ---------------------------------------------------------------------------


class TestRerunSnapshot:
    def test_rerun_recaptures_snapshot_for_terminal_task(self, tmp_path):
        """rerun() should update config_snapshot_json when re-queuing a terminal task."""
        engine, deps = _make_engine(tmp_path)
        handler = _make_handler()
        engine.register_handler(handler)

        new_snapshot = json.dumps({"snapshot_version": 1, "config": {"rerun": True}})
        deps.book_manager.get_config_snapshot_json.return_value = new_snapshot

        record = engine._store.create(
            book_id="book-1",
            task_type="batch_translation",
            status=STATUS_CANCELLED,
            config_snapshot_json=_VALID_SNAPSHOT,
        )

        result = engine.rerun(record.task_id)

        assert result.status == STATUS_QUEUED
        assert result.config_snapshot_json == new_snapshot
        engine.close()

    def test_rerun_raises_when_capture_fails(self, tmp_path):
        """rerun() must raise ValueError when config snapshot capture fails."""
        engine, deps = _make_engine(tmp_path)
        handler = _make_handler()
        engine.register_handler(handler)

        deps.book_manager.get_config_snapshot_json.side_effect = RuntimeError("no config")

        record = engine._store.create(
            book_id="book-1",
            task_type="batch_translation",
            status=STATUS_CANCELLED,
        )

        with pytest.raises(ValueError):
            engine.rerun(record.task_id)

        engine.close()

    def test_rerun_enforces_handler_can_run_policy_for_completed(self, tmp_path):
        """rerun() should raise for completed non-rerunnable tasks."""
        engine, deps = _make_engine(tmp_path)
        handler = _make_handler()
        # completed is non-rerunnable for batch_translation
        handler.can.return_value = MagicMock(allowed=False, reason="Task already completed")
        engine.register_handler(handler)

        deps.book_manager.get_config_snapshot_json.return_value = _VALID_SNAPSHOT

        record = engine._store.create(
            book_id="book-1",
            task_type="batch_translation",
            status=STATUS_COMPLETED,
        )

        with pytest.raises(ValueError):
            engine.rerun(record.task_id)

        engine.close()
