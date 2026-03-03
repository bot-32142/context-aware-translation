"""Tests for GlossaryExportTaskWorker run/cancel/progress behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, Mock

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


def test_run_action_calls_build_fully_summarized_descriptions_and_export(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Test that run action calls build_fully_summarized_descriptions and export_glossary."""
    from context_aware_translation.ui.workers.glossary_export_task_worker import GlossaryExportTaskWorker

    task_store = MagicMock()
    task_store.get.return_value = Mock(total_items=10)
    output_path = tmp_path / "glossary.csv"
    worker = GlossaryExportTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-1",
        task_store=task_store,
        output_path=output_path,
    )

    mock_db = MagicMock()
    mock_manager = MagicMock()
    mock_manager.build_fully_summarized_descriptions.return_value = {"term1": "desc1"}

    class _Session:
        db = mock_db
        manager = mock_manager

    mock_export_glossary = MagicMock(return_value=42)
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.glossary_export_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowSessionContext(_Session()),
    )
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.glossary_export_task_worker.export_glossary",
        mock_export_glossary,
    )

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    mock_manager.build_fully_summarized_descriptions.assert_called_once()
    call_kwargs = mock_manager.build_fully_summarized_descriptions.call_args[1]
    assert "cancel_check" in call_kwargs
    assert "progress_callback" in call_kwargs

    mock_export_glossary.assert_called_once()
    call_args = mock_export_glossary.call_args
    assert call_args[0][0] == mock_db
    assert call_args[0][1] == output_path
    assert call_args[1]["summarized_descriptions"] == {"term1": "desc1"}

    assert cancelled == []
    assert errors == []
    assert success[0]["action"] == "run"
    assert success[0]["count"] == 42
    assert success[0]["task_id"] == "task-1"


def test_run_action_updates_task_store_status_running_then_completed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Test that run action updates task status to running, then completed."""
    from context_aware_translation.ui.workers.glossary_export_task_worker import GlossaryExportTaskWorker

    task_store = MagicMock()
    task_store.get.return_value = Mock(total_items=10)
    output_path = tmp_path / "glossary.csv"
    worker = GlossaryExportTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-1",
        task_store=task_store,
        output_path=output_path,
    )

    # Mock session and manager
    mock_db = MagicMock()
    mock_manager = MagicMock()
    mock_manager.build_fully_summarized_descriptions.return_value = {}

    class _Session:
        db = mock_db
        manager = mock_manager

    mock_export_glossary = MagicMock(return_value=15)
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.glossary_export_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowSessionContext(_Session()),
    )
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.glossary_export_task_worker.export_glossary",
        mock_export_glossary,
    )

    worker.run()

    task_store.update.assert_any_call("task-1", status="running")
    task_store.update.assert_any_call(
        "task-1",
        status="completed",
        completed_items=15,
        total_items=15,  # max(10, 15)
    )


def test_run_action_on_cancel_sets_cancelled_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Test that cancellation during run sets cancelled status."""
    from context_aware_translation.core.cancellation import OperationCancelledError
    from context_aware_translation.ui.workers.glossary_export_task_worker import GlossaryExportTaskWorker

    task_store = MagicMock()
    output_path = tmp_path / "glossary.csv"
    worker = GlossaryExportTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-cancel",
        task_store=task_store,
        output_path=output_path,
    )

    # Mock session and manager that raises OperationCancelledError
    mock_manager = MagicMock()
    mock_manager.build_fully_summarized_descriptions.side_effect = OperationCancelledError("cancelled")

    class _Session:
        db = MagicMock()
        manager = mock_manager

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.glossary_export_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowSessionContext(_Session()),
    )

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert success == []
    assert cancelled == [True]
    assert errors == []
    task_store.update.assert_any_call("task-cancel", status="cancelled", cancel_requested=False)


def test_run_action_on_error_sets_failed_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Test that error during run sets failed status."""
    from context_aware_translation.ui.workers.glossary_export_task_worker import GlossaryExportTaskWorker

    task_store = MagicMock()
    output_path = tmp_path / "glossary.csv"
    worker = GlossaryExportTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-fail",
        task_store=task_store,
        output_path=output_path,
    )

    # Mock session and manager that raises an error
    mock_manager = MagicMock()
    mock_manager.build_fully_summarized_descriptions.side_effect = RuntimeError("export failed")

    class _Session:
        db = MagicMock()
        manager = mock_manager

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.glossary_export_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowSessionContext(_Session()),
    )

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert success == []
    assert cancelled == []
    assert len(errors) == 1
    assert "RuntimeError: export failed" in errors[0]
    task_store.update.assert_any_call("task-fail", status="failed", last_error="export failed")


# --- cancel action ---


def test_cancel_action_sets_cancelled_status(tmp_path: Path):
    """Test that cancel action sets cancelled status in task store."""
    from context_aware_translation.ui.workers.glossary_export_task_worker import GlossaryExportTaskWorker

    task_store = MagicMock()
    output_path = tmp_path / "glossary.csv"
    worker = GlossaryExportTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="cancel",
        task_id="task-cancel",
        task_store=task_store,
        output_path=output_path,
    )

    worker.run()

    task_store.update.assert_called_once_with("task-cancel", status="cancelled", cancel_requested=False)


# --- progress ---


def test_progress_updates_task_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Test that progress callbacks update task store."""
    from context_aware_translation.core.progress import ProgressUpdate, WorkflowStep
    from context_aware_translation.ui.workers.glossary_export_task_worker import GlossaryExportTaskWorker

    task_store = MagicMock()
    task_store.get.return_value = Mock(total_items=0)
    output_path = tmp_path / "glossary.csv"
    worker = GlossaryExportTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-progress",
        task_store=task_store,
        output_path=output_path,
    )

    # Mock session and manager with progress callback
    mock_db = MagicMock()
    mock_manager = MagicMock()

    def mock_build_with_progress(cancel_check=None, progress_callback=None):
        _ = cancel_check
        if progress_callback:
            progress_callback(ProgressUpdate(step=WorkflowStep.EXPORT, current=3, total=10, message="building"))
        return {}

    mock_manager.build_fully_summarized_descriptions = mock_build_with_progress

    class _Session:
        db = mock_db
        manager = mock_manager

    mock_export_glossary = MagicMock(return_value=10)
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.glossary_export_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowSessionContext(_Session()),
    )
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.glossary_export_task_worker.export_glossary",
        mock_export_glossary,
    )

    worker.run()

    task_store.update.assert_any_call("task-progress", completed_items=3, total_items=10)


# --- parameter forwarding ---


def test_output_path_used_for_export_glossary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Test that output_path parameter is used for export_glossary."""
    from context_aware_translation.ui.workers.glossary_export_task_worker import GlossaryExportTaskWorker

    task_store = MagicMock()
    output_path = tmp_path / "custom_output.csv"
    worker = GlossaryExportTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-1",
        task_store=task_store,
        output_path=str(output_path),  # Test string conversion
    )

    # Mock session and manager
    mock_db = MagicMock()
    mock_manager = MagicMock()
    mock_manager.build_fully_summarized_descriptions.return_value = {}

    class _Session:
        db = mock_db
        manager = mock_manager

    mock_export_glossary = MagicMock(return_value=5)
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.glossary_export_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowSessionContext(_Session()),
    )
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.glossary_export_task_worker.export_glossary",
        mock_export_glossary,
    )

    worker.run()

    # Verify output_path was passed to export_glossary
    call_args = mock_export_glossary.call_args
    assert call_args[0][1] == output_path


# --- notify_task_changed ---


def test_cancel_calls_notify_task_changed(tmp_path: Path):
    """Test that cancel action calls notify_task_changed callback."""
    from context_aware_translation.ui.workers.glossary_export_task_worker import GlossaryExportTaskWorker

    task_store = MagicMock()
    notify = MagicMock()
    output_path = tmp_path / "glossary.csv"
    worker = GlossaryExportTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="cancel",
        task_id="task-cancel",
        task_store=task_store,
        notify_task_changed=notify,
        output_path=output_path,
    )

    worker.run()

    notify.assert_called_with("book-id")


def test_run_calls_notify_task_changed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Test that run action calls notify_task_changed callback."""
    from context_aware_translation.ui.workers.glossary_export_task_worker import GlossaryExportTaskWorker

    task_store = MagicMock()
    task_store.get.return_value = Mock(total_items=0)
    notify = MagicMock()
    output_path = tmp_path / "glossary.csv"
    worker = GlossaryExportTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-notify",
        task_store=task_store,
        notify_task_changed=notify,
        output_path=output_path,
    )

    # Mock session and manager
    mock_db = MagicMock()
    mock_manager = MagicMock()
    mock_manager.build_fully_summarized_descriptions.return_value = {}

    class _Session:
        db = mock_db
        manager = mock_manager

    mock_export_glossary = MagicMock(return_value=5)
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.glossary_export_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowSessionContext(_Session()),
    )
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.glossary_export_task_worker.export_glossary",
        mock_export_glossary,
    )

    worker.run()

    notify.assert_called_with("book-id")


# --- unknown action ---


def test_unknown_action_raises(tmp_path: Path):
    """Test that unknown action raises an error."""
    from context_aware_translation.ui.workers.glossary_export_task_worker import GlossaryExportTaskWorker

    output_path = tmp_path / "glossary.csv"
    worker = GlossaryExportTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="unknown_action",
        task_id="task-x",
        output_path=output_path,
    )

    errors: list[str] = []
    worker.error.connect(lambda msg: errors.append(msg))
    worker.run()

    assert len(errors) == 1
    assert "unknown_action" in errors[0]
