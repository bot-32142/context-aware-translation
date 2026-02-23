"""Tests for global async batch auto-run scheduling in MainWindow."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from context_aware_translation.storage.translation_batch_task_store import STATUS_PAUSED, TranslationBatchTaskStore

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


class _Worker:
    def __init__(self, running: bool) -> None:
        self._running = running

    def isRunning(self) -> bool:  # noqa: N802
        return self._running


def test_is_workspace_translation_worker_running_detects_interactive_translation_worker():
    from context_aware_translation.ui.main_window import MainWindow
    from context_aware_translation.ui.views.book_workspace import BookWorkspace

    translation_view = SimpleNamespace(
        worker=_Worker(True),
        retranslate_worker=None,
        batch_task_worker=_Worker(False),
    )
    workspace = MagicMock(spec=BookWorkspace)
    workspace.get_translation_view.return_value = translation_view
    fake_window = SimpleNamespace(
        _view_registry={"book_book-1": workspace},
    )

    assert MainWindow._is_workspace_translation_worker_running(fake_window, "book-1") is True


def test_global_autorun_tick_skips_book_when_interactive_translation_is_running():
    from context_aware_translation.ui.main_window import MainWindow

    fake_window = SimpleNamespace(
        _global_batch_workers={},
        _global_batch_retry_after={},
        _view_registry={},
        _sleep_inhibitor=MagicMock(),
        _update_sleep_inhibitor=MagicMock(),
        book_manager=SimpleNamespace(list_books=MagicMock(return_value=[SimpleNamespace(book_id="book-1")])),
        _cleanup_finished_global_batch_workers=MagicMock(),
        _is_workspace_translation_worker_running=MagicMock(return_value=True),
        _next_auto_batch_candidate=MagicMock(return_value=("task-1", None)),
        _start_global_batch_worker=MagicMock(),
    )

    with (
        patch(
            "context_aware_translation.ui.main_window.DocumentOperationTracker.has_document_overlap",
            return_value=False,
        ),
        patch(
            "context_aware_translation.ui.main_window.has_any_batch_task_overlap",
            return_value=False,
        ),
    ):
        MainWindow._on_global_batch_autorun_tick(fake_window)

    fake_window._start_global_batch_worker.assert_not_called()
    fake_window._next_auto_batch_candidate.assert_not_called()


def test_global_autorun_tick_respects_retry_backoff():
    from context_aware_translation.ui.main_window import MainWindow

    fake_window = SimpleNamespace(
        _global_batch_workers={},
        _global_batch_retry_after={"book-1": time.monotonic() + 60},
        _view_registry={},
        _sleep_inhibitor=MagicMock(),
        _update_sleep_inhibitor=MagicMock(),
        book_manager=SimpleNamespace(list_books=MagicMock(return_value=[SimpleNamespace(book_id="book-1")])),
        _cleanup_finished_global_batch_workers=MagicMock(),
        _is_workspace_translation_worker_running=MagicMock(return_value=False),
        _next_auto_batch_task_id=MagicMock(return_value="task-1"),
        _start_global_batch_worker=MagicMock(),
    )

    with patch(
        "context_aware_translation.ui.main_window.BatchTranslationTaskWorker.is_run_active_for_book",
        return_value=False,
    ):
        MainWindow._on_global_batch_autorun_tick(fake_window)

    fake_window._start_global_batch_worker.assert_not_called()
    fake_window._next_auto_batch_task_id.assert_not_called()


def test_global_autorun_tick_skips_book_when_any_run_worker_is_active():
    from context_aware_translation.ui.main_window import MainWindow

    fake_window = SimpleNamespace(
        _global_batch_workers={},
        _global_batch_retry_after={},
        _view_registry={},
        _sleep_inhibitor=MagicMock(),
        _update_sleep_inhibitor=MagicMock(),
        book_manager=SimpleNamespace(list_books=MagicMock(return_value=[SimpleNamespace(book_id="book-1")])),
        _cleanup_finished_global_batch_workers=MagicMock(),
        _is_workspace_translation_worker_running=MagicMock(return_value=False),
        _next_auto_batch_candidate=MagicMock(return_value=("task-1", None)),
        _start_global_batch_worker=MagicMock(),
    )

    with (
        patch(
            "context_aware_translation.ui.main_window.DocumentOperationTracker.has_document_overlap",
            return_value=True,
        ),
        patch(
            "context_aware_translation.ui.main_window.has_any_batch_task_overlap",
            return_value=False,
        ),
    ):
        MainWindow._on_global_batch_autorun_tick(fake_window)

    fake_window._start_global_batch_worker.assert_not_called()


def test_on_global_batch_worker_error_pauses_task_and_sets_backoff(tmp_path: Path):
    from context_aware_translation.ui.main_window import MainWindow

    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    task_store_path = runtime_root / "translation_batch_tasks.db"

    store = TranslationBatchTaskStore(task_store_path)
    try:
        task = store.create_task(book_id="book-1")
    finally:
        store.close()

    fake_window = SimpleNamespace(
        _global_batch_retry_after={},
        _GLOBAL_BATCH_AUTORUN_RETRY_BACKOFF_SEC=30,
        _global_batch_workers={"book-1": {task.task_id: MagicMock()}},
        book_manager=SimpleNamespace(get_book_db_path=MagicMock(return_value=runtime_root / "book.db")),
        _pause_global_task_after_worker_error=MagicMock(),
    )

    before = time.monotonic()
    MainWindow._on_global_batch_worker_error(fake_window, "book-1", task.task_id, "boom")
    retry_after = fake_window._global_batch_retry_after.get("book-1")
    assert retry_after is not None
    assert retry_after > before
    fake_window._pause_global_task_after_worker_error.assert_called_once_with("book-1", task.task_id, "boom")

    # Ensure the pause helper still persists pause status when called.
    pause_window = SimpleNamespace(
        _global_batch_workers={"book-1": {task.task_id: MagicMock()}},
        _global_batch_task_stores={},
        book_manager=SimpleNamespace(get_book_db_path=MagicMock(return_value=runtime_root / "book.db")),
        _get_batch_task_store=lambda _self, bid: MainWindow._get_batch_task_store(pause_window, bid),
    )
    # Bind _get_batch_task_store properly for unbound call
    pause_window._get_batch_task_store = lambda bid: MainWindow._get_batch_task_store(pause_window, bid)
    MainWindow._pause_global_task_after_worker_error(pause_window, "book-1", task.task_id, "boom")
    # Close cached stores
    for s in pause_window._global_batch_task_stores.values():
        s.close()
    reopened = TranslationBatchTaskStore(task_store_path)
    try:
        updated = reopened.get(task.task_id)
    finally:
        reopened.close()

    assert updated is not None
    assert updated.status == STATUS_PAUSED
    assert updated.last_error is not None and "boom" in updated.last_error


def test_on_global_batch_worker_success_sets_backoff_for_quota_paused_result():
    from context_aware_translation.ui.main_window import MainWindow

    fake_window = SimpleNamespace(
        _global_batch_retry_after={},
        _GLOBAL_BATCH_AUTORUN_RETRY_BACKOFF_SEC=30,
    )

    before = time.monotonic()
    MainWindow._on_global_batch_worker_success(
        fake_window,
        "book-1",
        {
            "action": "run",
            "task": {
                "status": STATUS_PAUSED,
                "last_error": "429 RESOURCE_EXHAUSTED quota exceeded",
            },
        },
    )
    retry_after = fake_window._global_batch_retry_after.get("book-1")
    assert retry_after is not None
    assert retry_after > before
