"""Tests for TranslationTextTaskWorker run/cancel/progress behavior."""

from __future__ import annotations

from pathlib import Path
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


class _WorkflowSessionContext:
    def __init__(self, session, exit_error: Exception | None = None) -> None:
        self._session = session
        self._exit_error = exit_error

    def __enter__(self):
        return self._session

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._exit_error is not None:
            raise self._exit_error
        return False


def _capture_signals(worker):
    success: list[object] = []
    cancelled: list[bool] = []
    errors: list[str] = []
    worker.finished_success.connect(lambda value: success.append(value))
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.error.connect(lambda message: errors.append(message))
    return success, cancelled, errors


def _book_manager_with_db(tmp_path: Path) -> MagicMock:
    manager = MagicMock()
    manager.get_book_db_path.return_value = tmp_path / "book.db"
    return manager


# --- run action ---


def test_run_action_calls_session_translate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Test that run action calls session.translate with correct parameters."""
    from context_aware_translation.ui.workers.translation_text_task_worker import TranslationTextTaskWorker

    task_store = MagicMock()
    worker = TranslationTextTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-1",
        task_store=task_store,
        force=False,
        skip_context=False,
    )

    mock_session = MagicMock()
    mock_session.translate = MagicMock(return_value=_async_noop())

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.translation_text_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowSessionContext(mock_session),
    )

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert errors == []
    assert cancelled == []
    assert success[0]["action"] == "run"
    assert success[0]["task_id"] == "task-1"


def test_run_action_updates_task_store_running_then_completed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """run action must update task status to running, then completed."""
    from context_aware_translation.ui.workers.translation_text_task_worker import TranslationTextTaskWorker

    task_store = MagicMock()
    worker = TranslationTextTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-1",
        task_store=task_store,
    )

    mock_session = MagicMock()
    mock_session.translate = MagicMock(return_value=_async_noop())

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.translation_text_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowSessionContext(mock_session),
    )

    worker.run()

    task_store.update.assert_any_call("task-1", status="running")
    task_store.update.assert_any_call("task-1", status="completed")


def test_run_action_on_cancel_sets_cancelled_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Cancellation during run sets cancelled status."""
    from context_aware_translation.core.cancellation import OperationCancelledError
    from context_aware_translation.ui.workers.translation_text_task_worker import TranslationTextTaskWorker

    task_store = MagicMock()
    worker = TranslationTextTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-cancel",
        task_store=task_store,
    )

    mock_session = MagicMock()
    mock_session.translate = MagicMock(return_value=_async_raise(OperationCancelledError("cancelled")))

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.translation_text_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowSessionContext(mock_session),
    )

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert success == []
    assert cancelled == [True]
    assert errors == []
    task_store.update.assert_any_call("task-cancel", status="cancelled", cancel_requested=False)


def test_run_action_on_error_sets_failed_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Error during run sets failed status."""
    from context_aware_translation.ui.workers.translation_text_task_worker import TranslationTextTaskWorker

    task_store = MagicMock()
    worker = TranslationTextTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-fail",
        task_store=task_store,
    )

    mock_session = MagicMock()
    mock_session.translate = MagicMock(return_value=_async_raise(RuntimeError("translation failed")))

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.translation_text_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowSessionContext(mock_session),
    )

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert success == []
    assert cancelled == []
    assert len(errors) == 1
    assert "translation failed" in errors[0]
    task_store.update.assert_any_call("task-fail", status="failed", last_error="translation failed")


# --- cancel action ---


def test_cancel_action_sets_cancelled_status(tmp_path: Path):
    """cancel action sets cancelled status in task store."""
    from context_aware_translation.ui.workers.translation_text_task_worker import TranslationTextTaskWorker

    task_store = MagicMock()
    worker = TranslationTextTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="cancel",
        task_id="task-cancel",
        task_store=task_store,
    )

    worker.run()

    task_store.update.assert_called_once_with("task-cancel", status="cancelled", cancel_requested=False)


def test_cancel_action_calls_notify_task_changed(tmp_path: Path):
    """cancel action calls notify_task_changed callback."""
    from context_aware_translation.ui.workers.translation_text_task_worker import TranslationTextTaskWorker

    task_store = MagicMock()
    notify = MagicMock()
    worker = TranslationTextTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="cancel",
        task_id="task-cancel",
        task_store=task_store,
        notify_task_changed=notify,
    )

    worker.run()

    notify.assert_called_with("book-id")


# --- document filtering ---


def test_worker_filters_manga_document_ids(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Worker filters out manga document IDs before calling translate."""
    from context_aware_translation.ui.workers.translation_text_task_worker import TranslationTextTaskWorker

    # Simulate DB with mixed doc types
    mock_db = MagicMock()
    mock_repo = MagicMock()
    mock_repo.get_document_by_id.side_effect = lambda doc_id: {
        1: {"document_id": 1, "document_type": "text"},
        2: {"document_id": 2, "document_type": "manga"},
        3: {"document_id": 3, "document_type": "pdf"},
    }.get(doc_id)

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.translation_text_task_worker.SQLiteBookDB",
        lambda *_args, **_kwargs: mock_db,
    )
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.translation_text_task_worker.DocumentRepository",
        lambda *_args, **_kwargs: mock_repo,
    )

    task_store = MagicMock()
    worker = TranslationTextTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-filter",
        task_store=task_store,
        document_ids=[1, 2, 3],
    )

    captured_doc_ids: list = []
    mock_session = MagicMock()

    async def _capture_translate(**kwargs):
        captured_doc_ids.extend(kwargs.get("document_ids") or [])

    mock_session.translate = _capture_translate

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.translation_text_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowSessionContext(mock_session),
    )

    worker.run()

    # manga doc id=2 must be filtered out
    assert 2 not in captured_doc_ids
    assert 1 in captured_doc_ids
    assert 3 in captured_doc_ids


def test_worker_passes_none_document_ids_when_unset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """When document_ids is None (all docs), no filtering is applied."""
    from context_aware_translation.ui.workers.translation_text_task_worker import TranslationTextTaskWorker

    task_store = MagicMock()
    worker = TranslationTextTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-all",
        task_store=task_store,
        document_ids=None,
    )

    captured_doc_ids: list = ["sentinel"]  # sentinel to detect not overwritten

    mock_session = MagicMock()

    async def _capture_translate(**kwargs):
        captured_doc_ids.clear()
        captured_doc_ids.append(kwargs.get("document_ids"))

    mock_session.translate = _capture_translate

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.translation_text_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowSessionContext(mock_session),
    )

    worker.run()

    assert captured_doc_ids == [None]


# --- config snapshot ---


def test_run_uses_config_snapshot_when_provided(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """When config_snapshot_json is set, WorkflowSession.from_snapshot is used."""
    import json as _json

    from context_aware_translation.ui.workers.translation_text_task_worker import TranslationTextTaskWorker

    snapshot = _json.dumps({"snapshot_version": 1})
    task_store = MagicMock()
    worker = TranslationTextTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-snap",
        task_store=task_store,
        config_snapshot_json=snapshot,
    )

    mock_session = MagicMock()
    mock_session.translate = MagicMock(return_value=_async_noop())
    from_snapshot_calls: list = []

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.translation_text_task_worker.WorkflowSession.from_snapshot",
        lambda snap, book_id: (from_snapshot_calls.append((snap, book_id)) or _WorkflowSessionContext(mock_session)),
    )

    worker.run()

    assert len(from_snapshot_calls) == 1
    assert from_snapshot_calls[0][0] == snapshot
    assert from_snapshot_calls[0][1] == "book-id"


# --- unknown action ---


def test_unknown_action_raises(tmp_path: Path):
    """Unknown action raises an error signal."""
    from context_aware_translation.ui.workers.translation_text_task_worker import TranslationTextTaskWorker

    worker = TranslationTextTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="unknown_action",
        task_id="task-x",
    )

    errors: list[str] = []
    worker.error.connect(lambda msg: errors.append(msg))
    worker.run()

    assert len(errors) == 1
    assert "unknown_action" in errors[0]


# --- helpers ---


async def _async_noop(**kwargs):
    pass


async def _async_raise(exc: Exception, **_kwargs):
    raise exc
