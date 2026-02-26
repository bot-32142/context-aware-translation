"""Tests for GlossaryReviewTaskWorker run/cancel/progress/failure/snapshot behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

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


class _TranslatorContext:
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

def test_run_emits_success_on_completion(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from context_aware_translation.ui.workers.glossary_review_task_worker import GlossaryReviewTaskWorker

    task_store = MagicMock()
    worker = GlossaryReviewTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-1",
        task_store=task_store,
    )

    class _Session:
        async def review_terms(self, **kwargs) -> None:
            pass

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.glossary_review_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _TranslatorContext(_Session()),
    )

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert cancelled == []
    assert errors == []
    assert success[0]["action"] == "run"
    assert success[0]["task_id"] == "task-1"


def test_run_marks_task_running_then_completed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from context_aware_translation.ui.workers.glossary_review_task_worker import GlossaryReviewTaskWorker

    task_store = MagicMock()
    worker = GlossaryReviewTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-1",
        task_store=task_store,
    )

    class _Session:
        async def review_terms(self, **kwargs) -> None:
            pass

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.glossary_review_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _TranslatorContext(_Session()),
    )

    worker.run()

    task_store.update.assert_any_call("task-1", status="running")
    task_store.update.assert_any_call("task-1", status="completed")


def test_run_emits_error_on_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from context_aware_translation.ui.workers.glossary_review_task_worker import GlossaryReviewTaskWorker

    task_store = MagicMock()
    worker = GlossaryReviewTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-fail",
        task_store=task_store,
    )

    class _Session:
        async def review_terms(self, **kwargs) -> None:
            raise RuntimeError("review failed")

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.glossary_review_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _TranslatorContext(_Session()),
    )

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert success == []
    assert cancelled == []
    assert len(errors) == 1
    assert "RuntimeError: review failed" in errors[0]
    task_store.update.assert_any_call("task-fail", status="failed", last_error="review failed")


def test_run_emits_error_when_session_exit_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from context_aware_translation.ui.workers.glossary_review_task_worker import GlossaryReviewTaskWorker

    task_store = MagicMock()
    worker = GlossaryReviewTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-exit-fail",
        task_store=task_store,
    )

    class _Session:
        async def review_terms(self, **kwargs) -> None:
            pass

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.glossary_review_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _TranslatorContext(_Session(), exit_error=RuntimeError("close failed")),
    )

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert success == []
    assert cancelled == []
    assert len(errors) == 1
    assert "RuntimeError: close failed" in errors[0]


# --- cancel action ---

def test_cancel_marks_task_cancelled(tmp_path: Path):
    from context_aware_translation.ui.workers.glossary_review_task_worker import GlossaryReviewTaskWorker

    task_store = MagicMock()
    worker = GlossaryReviewTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="cancel",
        task_id="task-cancel",
        task_store=task_store,
    )

    worker.run()

    task_store.update.assert_called_once_with("task-cancel", status="cancelled", cancel_requested=False)


def test_cancel_calls_notify_task_changed(tmp_path: Path):
    from context_aware_translation.ui.workers.glossary_review_task_worker import GlossaryReviewTaskWorker

    task_store = MagicMock()
    notify = MagicMock()
    worker = GlossaryReviewTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="cancel",
        task_id="task-cancel",
        task_store=task_store,
        notify_task_changed=notify,
    )

    worker.run()

    notify.assert_called_with("book-id")


# --- progress ---

def test_run_forwards_progress_updates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from context_aware_translation.core.progress import ProgressUpdate, WorkflowStep
    from context_aware_translation.ui.workers.glossary_review_task_worker import GlossaryReviewTaskWorker

    task_store = MagicMock()
    worker = GlossaryReviewTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-progress",
        task_store=task_store,
    )

    class _Session:
        async def review_terms(self, progress_callback=None, **kwargs) -> None:
            if progress_callback:
                progress_callback(ProgressUpdate(step=WorkflowStep.EXPORT, current=1, total=5, message="reviewing"))

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.glossary_review_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _TranslatorContext(_Session()),
    )

    worker.run()

    task_store.update.assert_any_call("task-progress", completed_items=1, total_items=5)


# --- live config (no snapshot fallback) ---

def test_run_always_uses_live_config_even_when_snapshot_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Glossary review always uses live config, never snapshot — per spec."""
    from context_aware_translation.ui.workers.glossary_review_task_worker import GlossaryReviewTaskWorker

    task_store = MagicMock()
    worker = GlossaryReviewTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-snapshot",
        task_store=task_store,
        config_snapshot_json='{"snapshot": true}',
    )

    class _Session:
        async def review_terms(self, **kwargs) -> None:
            pass

    from_book_calls: list[bool] = []

    def fake_from_book(*_args, **_kwargs):
        from_book_calls.append(True)
        return _TranslatorContext(_Session())

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.glossary_review_task_worker.WorkflowSession.from_book",
        fake_from_book,
    )

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert from_book_calls == [True], "Must use from_book (live config), not from_snapshot"
    assert success[0]["action"] == "run"


# --- notify_task_changed ---

def test_run_calls_notify_task_changed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from context_aware_translation.ui.workers.glossary_review_task_worker import GlossaryReviewTaskWorker

    task_store = MagicMock()
    notify = MagicMock()
    worker = GlossaryReviewTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-notify",
        task_store=task_store,
        notify_task_changed=notify,
    )

    class _Session:
        async def review_terms(self, **kwargs) -> None:
            pass

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.glossary_review_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _TranslatorContext(_Session()),
    )

    worker.run()

    notify.assert_called_with("book-id")


# --- unknown action ---

def test_unknown_action_raises(tmp_path: Path):
    from context_aware_translation.ui.workers.glossary_review_task_worker import GlossaryReviewTaskWorker

    worker = GlossaryReviewTaskWorker(
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
