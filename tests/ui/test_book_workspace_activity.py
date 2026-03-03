"""Tests for BookWorkspace Activity Panel integration."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

try:
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication

    HAS_PYSIDE6 = True
except ImportError:
    HAS_PYSIDE6 = False

from context_aware_translation.storage.task_store import TaskRecord
from context_aware_translation.workflow.tasks.models import Decision

pytestmark = pytest.mark.skipif(not HAS_PYSIDE6, reason="PySide6 not available")


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def _qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class _SignalHolder(QObject):
    tasks_changed = Signal(str)
    error_occurred = Signal(str)
    running_work_changed = Signal(bool)


def _make_engine(records: list[TaskRecord] | None = None) -> MagicMock:
    holder = _SignalHolder()
    engine = MagicMock()
    engine.tasks_changed = holder.tasks_changed
    engine.error_occurred = holder.error_occurred
    engine.running_work_changed = holder.running_work_changed
    engine._signal_holder = holder
    engine.get_tasks.return_value = records if records is not None else []
    engine.preflight_task.return_value = Decision(allowed=True, reason="")
    return engine


def _make_record(**overrides) -> TaskRecord:
    defaults = {
        "task_id": "abcd1234-5678-9abc-def0-1234567890ab",
        "book_id": "book-1",
        "task_type": "batch_translation",
        "status": "queued",
        "phase": None,
        "document_ids_json": None,
        "payload_json": None,
        "config_snapshot_json": None,
        "cancel_requested": False,
        "total_items": 10,
        "completed_items": 3,
        "failed_items": 0,
        "last_error": None,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    defaults.update(overrides)
    return TaskRecord(**defaults)


def _make_workspace(engine=None, book_id="book-1"):
    from PySide6.QtWidgets import QWidget

    from context_aware_translation.ui.views.book_workspace import BookWorkspace

    if engine is None:
        engine = _make_engine()

    book_manager = MagicMock()
    book_manager.list_endpoint_profiles.return_value = []

    # Patch all sub-view constructors to return real QWidget instances so
    # QTabWidget.insertTab does not reject them.
    # Each call must produce a distinct QWidget (can't reuse the same instance).
    def _stub(*_args, **_kwargs):
        return QWidget()

    with (
        patch("context_aware_translation.ui.views.book_workspace.ImportView", _stub),
        patch("context_aware_translation.ui.views.book_workspace.OCRReviewView", _stub),
        patch("context_aware_translation.ui.views.book_workspace.GlossaryView", _stub),
        patch("context_aware_translation.ui.views.book_workspace.TranslationView", _stub),
        patch("context_aware_translation.ui.views.book_workspace.ExportView", _stub),
    ):
        ws = BookWorkspace(book_manager, book_id, "Test Book", engine)
    return ws


# ---------------------------------------------------------------------------
# 1. test_activity_button_exists_in_header
# ---------------------------------------------------------------------------


def test_activity_button_exists_in_header():
    ws = _make_workspace()
    assert hasattr(ws, "activity_btn")
    assert ws.activity_btn.text()


# ---------------------------------------------------------------------------
# 2. test_activity_panel_hidden_by_default
# ---------------------------------------------------------------------------


def test_activity_panel_hidden_by_default():
    ws = _make_workspace()
    assert ws._activity_panel.isHidden()
    assert not ws.activity_btn.isChecked()


# ---------------------------------------------------------------------------
# 3. test_activity_button_toggles_panel_visible
# ---------------------------------------------------------------------------


def test_activity_button_toggles_panel_visible():
    ws = _make_workspace()

    # Simulate button click (checked=True)
    ws.activity_btn.setChecked(True)
    ws._on_activity_toggled(True)

    assert not ws._activity_panel.isHidden()


# ---------------------------------------------------------------------------
# 4. test_activity_button_toggles_panel_hidden
# ---------------------------------------------------------------------------


def test_activity_button_toggles_panel_hidden():
    ws = _make_workspace()

    # Show first
    ws.show_activity_panel()
    assert not ws._activity_panel.isHidden()

    # Hide via toggle
    ws._on_activity_toggled(False)
    assert ws._activity_panel.isHidden()


# ---------------------------------------------------------------------------
# 5. test_show_activity_panel_sets_button_checked
# ---------------------------------------------------------------------------


def test_show_activity_panel_sets_button_checked():
    ws = _make_workspace()
    ws.show_activity_panel()
    assert ws.activity_btn.isChecked()
    assert not ws._activity_panel.isHidden()


# ---------------------------------------------------------------------------
# 6. test_hide_activity_panel_unchecks_button
# ---------------------------------------------------------------------------


def test_hide_activity_panel_unchecks_button():
    ws = _make_workspace()
    ws.show_activity_panel()
    ws.hide_activity_panel()
    assert not ws.activity_btn.isChecked()
    assert ws._activity_panel.isHidden()


# ---------------------------------------------------------------------------
# 7. test_panel_close_requested_hides_panel
# ---------------------------------------------------------------------------


def test_panel_close_requested_hides_panel():
    ws = _make_workspace()
    ws.show_activity_panel()

    # Emit close_requested from panel
    ws._activity_panel.close_requested.emit()

    assert ws._activity_panel.isHidden()
    assert not ws.activity_btn.isChecked()


# ---------------------------------------------------------------------------
# 8. test_panel_uses_correct_book_id
# ---------------------------------------------------------------------------


def test_panel_uses_correct_book_id():
    engine = _make_engine()
    ws = _make_workspace(engine=engine, book_id="book-xyz")

    assert ws._activity_panel._book_id == "book-xyz"


# ---------------------------------------------------------------------------
# 9. test_panel_persists_across_tab_switches
# ---------------------------------------------------------------------------


def test_panel_persists_across_tab_switches():
    ws = _make_workspace()
    ws.show_activity_panel()

    # Verify the panel object identity does not change after a tab refresh
    # (tab 0 is already cached so _on_tab_changed(0) uses cache path, no factory).
    panel_before = ws._activity_panel
    ws._on_tab_changed(0)  # cached path — no factory call

    assert ws._activity_panel is panel_before
    assert not ws._activity_panel.isHidden()


# ---------------------------------------------------------------------------
# 10. test_splitter_contains_tab_widget_and_panel
# ---------------------------------------------------------------------------


def test_splitter_contains_tab_widget_and_panel():
    ws = _make_workspace()
    assert ws._main_splitter.widget(0) is ws.tab_widget
    assert ws._main_splitter.widget(1) is ws._activity_panel


# ---------------------------------------------------------------------------
# 11. test_get_running_operations_excludes_background_translation_text
# ---------------------------------------------------------------------------


def test_get_running_operations_excludes_background_translation_text():
    r = _make_record(task_type="translation_text", status="running")
    engine = _make_engine(records=[r])

    # get_tasks returns the running record for translation_text
    def _get_tasks(_book_id, task_type=None):
        if task_type == "translation_text":
            return [r]
        return []

    engine.get_tasks.side_effect = _get_tasks
    ws = _make_workspace(engine=engine)

    running = ws.get_running_operations()
    assert ws.tr("Translation") not in running


# ---------------------------------------------------------------------------
# 12. test_get_running_operations_excludes_background_translation_manga
# ---------------------------------------------------------------------------


def test_get_running_operations_excludes_background_translation_manga():
    r = _make_record(task_type="translation_manga", status="running")
    engine = _make_engine(records=[r])

    def _get_tasks(_book_id, task_type=None):
        if task_type == "translation_manga":
            return [r]
        return []

    engine.get_tasks.side_effect = _get_tasks
    ws = _make_workspace(engine=engine)

    running = ws.get_running_operations()
    assert ws.tr("Translation") not in running


# ---------------------------------------------------------------------------
# 13. test_get_running_operations_excludes_terminal_translation_tasks
# ---------------------------------------------------------------------------


def test_get_running_operations_excludes_terminal_translation_tasks():
    r = _make_record(task_type="translation_text", status="completed")
    engine = _make_engine(records=[r])

    def _get_tasks(_book_id, task_type=None):
        if task_type == "translation_text":
            return [r]
        return []

    engine.get_tasks.side_effect = _get_tasks
    ws = _make_workspace(engine=engine)

    running = ws.get_running_operations()
    assert ws.tr("Translation") not in running


# ---------------------------------------------------------------------------
# 14. test_retranslate_ui_sets_activity_button_text
# ---------------------------------------------------------------------------


def test_retranslate_ui_sets_activity_button_text():
    ws = _make_workspace()
    ws.retranslateUi()
    assert ws.activity_btn.text()
    assert ws.activity_btn.toolTip()


# ---------------------------------------------------------------------------
# 15. test_cleanup_calls_activity_panel_cleanup
# ---------------------------------------------------------------------------


def test_cleanup_calls_activity_panel_cleanup():
    ws = _make_workspace()

    # Replace activity panel with a mock to track cleanup calls
    mock_panel = MagicMock()
    ws._activity_panel = mock_panel

    ws.cleanup()

    mock_panel.cleanup.assert_called_once()


def test_show_activity_panel_does_not_reset_width_when_already_visible():
    ws = _make_workspace()
    ws.show_activity_panel()
    ws._main_splitter.setSizes([700, 320])
    before = ws._main_splitter.sizes()

    # Simulate stale cached width that would otherwise force a reset.
    ws._activity_panel_last_width = 460
    ws.show_activity_panel()

    after = ws._main_splitter.sizes()
    assert after[1] == before[1]


def test_deferred_restore_respects_user_resize():
    ws = _make_workspace()
    ws.show_activity_panel()
    ws._main_splitter.setSizes([650, 280])
    ws._on_splitter_moved(0, 0)  # marks user-resized and persists width
    before = ws._main_splitter.sizes()

    # If deferred restore runs despite user drag, this stale width could override.
    ws._activity_panel_last_width = 460
    ws._restore_activity_panel_width_deferred()

    after = ws._main_splitter.sizes()
    assert after[1] == before[1]
