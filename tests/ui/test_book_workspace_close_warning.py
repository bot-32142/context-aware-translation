"""Tests for BookWorkspace close warnings when background operations are active."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

try:
    from PySide6.QtWidgets import QApplication, QMessageBox

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
    def __init__(self, running: bool):
        self._running = running
        self.interruption_requested = False

    def isRunning(self) -> bool:  # noqa: N802
        return self._running

    def requestInterruption(self) -> None:  # noqa: N802
        self.interruption_requested = True


def _make_workspace():
    from context_aware_translation.ui.views.book_workspace import BookWorkspace

    with patch.object(BookWorkspace, "_init_ui", lambda _self: None):
        workspace = BookWorkspace(MagicMock(), "book-id", "Book Name", task_engine=MagicMock())
    workspace._view_cache = {}
    return workspace


def test_get_running_operations_detects_all_supported_views():
    from context_aware_translation.workflow.tasks.models import TERMINAL_TASK_STATUSES

    workspace = _make_workspace()
    # Engine-managed tasks (sync_translation, batch_translation) continue in
    # background and are NOT reported as running operations on leave-book.
    # Glossary operations are now fully engine-managed — simulate a running extraction.
    _running_task = SimpleNamespace(status="running")

    def _mock_get_tasks(book_id, task_type=None):
        if task_type == "glossary_extraction":
            return [_running_task]
        return []

    workspace._task_engine.get_tasks.side_effect = _mock_get_tasks
    workspace._view_cache = {
        0: SimpleNamespace(worker=_Worker(True)),  # Import
        1: SimpleNamespace(ocr_worker=_Worker(True)),  # OCR
        4: SimpleNamespace(worker=_Worker(False)),  # Export
    }

    assert workspace.get_running_operations() == [
        workspace.tr("Import"),
        workspace.tr("OCR"),
        workspace.tr("Glossary"),
    ]


def test_get_running_operations_no_translation_when_no_engine_tasks():
    workspace = _make_workspace()
    workspace._task_engine.get_tasks.return_value = []
    workspace._view_cache = {}

    assert workspace.get_running_operations() == []


def test_get_running_operations_detects_glossary_when_only_export_task_running():
    workspace = _make_workspace()
    _running_task = SimpleNamespace(status="running")

    def _mock_get_tasks(_book_id, task_type=None):
        if task_type == "glossary_export":
            return [_running_task]
        return []

    workspace._task_engine.get_tasks.side_effect = _mock_get_tasks
    workspace._view_cache = {}

    assert workspace.get_running_operations() == [workspace.tr("Glossary")]


def test_close_requested_without_running_operations_emits_without_warning():
    workspace = _make_workspace()
    workspace._view_cache = {0: SimpleNamespace(worker=_Worker(False))}
    emitted: list[bool] = []
    workspace.close_requested.connect(lambda: emitted.append(True))

    with patch("context_aware_translation.ui.views.book_workspace.QMessageBox.warning") as warning_mock:
        workspace._on_close_requested()

    assert emitted == [True]
    warning_mock.assert_not_called()


def test_close_requested_with_running_operation_shows_warning_and_can_cancel():
    workspace = _make_workspace()
    workspace._view_cache = {1: SimpleNamespace(ocr_worker=_Worker(True))}
    emitted: list[bool] = []
    workspace.close_requested.connect(lambda: emitted.append(True))

    with patch(
        "context_aware_translation.ui.views.book_workspace.QMessageBox.warning",
        return_value=QMessageBox.StandardButton.Cancel,
    ) as warning_mock:
        workspace._on_close_requested()

    assert emitted == []
    warning_mock.assert_called_once()
    message = warning_mock.call_args.args[2]
    assert workspace.tr("OCR") in message


def test_close_requested_with_running_operation_confirmed_emits():
    workspace = _make_workspace()
    workspace._view_cache = {4: SimpleNamespace(worker=_Worker(True))}
    emitted: list[bool] = []
    workspace.close_requested.connect(lambda: emitted.append(True))

    with patch(
        "context_aware_translation.ui.views.book_workspace.QMessageBox.warning",
        return_value=QMessageBox.StandardButton.Ok,
    ):
        workspace._on_close_requested()

    assert emitted == [True]


def test_build_token_usage_summary_aggregates_endpoint_stats():
    workspace = _make_workspace()
    profiles = [
        SimpleNamespace(
            tokens_used=100,
            input_tokens_used=70,
            cached_input_tokens_used=20,
            uncached_input_tokens_used=50,
            output_tokens_used=30,
        ),
        SimpleNamespace(
            tokens_used=50,
            input_tokens_used=35,
            cached_input_tokens_used=10,
            uncached_input_tokens_used=25,
            output_tokens_used=15,
        ),
    ]

    summary = workspace._build_token_usage_summary(profiles)
    assert "Total 150" in summary
    assert "Input 105" in summary
    assert "cached 30" in summary
    assert "uncached 75" in summary
    assert "Output 45" in summary
    assert "Active endpoints 2" in summary


def test_refresh_token_usage_sets_label_and_handles_errors():
    workspace = _make_workspace()
    workspace.token_usage_label = MagicMock()
    workspace.book_manager = MagicMock()
    workspace.book_manager.list_endpoint_profiles.return_value = [
        SimpleNamespace(
            tokens_used=10,
            input_tokens_used=6,
            cached_input_tokens_used=2,
            uncached_input_tokens_used=4,
            output_tokens_used=4,
        )
    ]

    workspace._refresh_token_usage()
    first_text = workspace.token_usage_label.setText.call_args.args[0]
    assert "Total 10" in first_text

    workspace.token_usage_label.reset_mock()
    workspace.book_manager.list_endpoint_profiles.side_effect = RuntimeError("boom")
    workspace._refresh_token_usage()
    assert workspace.token_usage_label.setText.call_args.args[0] == workspace.tr("Token usage unavailable")


def test_request_cancel_running_operations_requests_interruption_for_all_running_workers():
    workspace = _make_workspace()
    import_worker = _Worker(True)
    ocr_worker = _Worker(True)
    export_worker = _Worker(True)

    workspace._view_cache = {
        0: SimpleNamespace(worker=import_worker),
        1: SimpleNamespace(ocr_worker=ocr_worker),
        # Translation tab (index 3): no direct worker — cancelled via engine
        4: SimpleNamespace(worker=export_worker),
    }

    workspace.request_cancel_running_operations()

    assert import_worker.interruption_requested is True
    assert ocr_worker.interruption_requested is True
    assert export_worker.interruption_requested is True
    # Engine cancel_running_tasks is called for engine-managed translation tasks
    workspace._task_engine.cancel_running_tasks.assert_called_once_with("book-id")
