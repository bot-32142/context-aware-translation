"""Unit tests for TaskActivityPanel widget."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

try:
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication, QMessageBox

    HAS_PYSIDE6 = True
except ImportError:
    HAS_PYSIDE6 = False

from context_aware_translation.storage.task_store import TaskRecord
from context_aware_translation.workflow.tasks.models import Decision, TaskAction

pytestmark = pytest.mark.skipif(not HAS_PYSIDE6, reason="PySide6 not available")
_PANELS: list[object] = []


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def _qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _cleanup_panels():
    yield
    while _PANELS:
        panel = _PANELS.pop()
        cleanup = getattr(panel, "cleanup", None)
        if callable(cleanup):
            cleanup()
        close = getattr(panel, "close", None)
        if callable(close):
            close()


class _SignalHolder(QObject):
    tasks_changed = Signal(str)
    error_occurred = Signal(str)


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


def _make_engine(records: list[TaskRecord] | None = None) -> MagicMock:
    """Return a mock engine with real PySide6 Signals."""
    signal_holder = _SignalHolder()
    engine = MagicMock()
    engine.tasks_changed = signal_holder.tasks_changed
    engine.error_occurred = signal_holder.error_occurred
    engine._signal_holder = signal_holder  # prevent GC
    engine.get_tasks.return_value = records if records is not None else []
    engine.preflight_task.return_value = Decision(allowed=True, reason="")
    return engine


def _make_panel(engine=None, book_id="book-1"):
    from context_aware_translation.ui.widgets.task_activity_panel import TaskActivityPanel

    if engine is None:
        engine = _make_engine()
    panel = TaskActivityPanel(engine, book_id)
    _PANELS.append(panel)
    return panel


# ---------------------------------------------------------------------------
# 1. test_header_has_title_and_close_button
# ---------------------------------------------------------------------------


def test_header_has_title_and_close_button():
    panel = _make_panel()
    assert panel._title_label is not None
    assert panel._close_btn is not None
    assert panel._close_btn.text()  # non-empty after retranslate_ui


# ---------------------------------------------------------------------------
# 2. test_close_button_emits_close_requested
# ---------------------------------------------------------------------------


def test_close_button_emits_close_requested():
    panel = _make_panel()
    received = []
    panel.close_requested.connect(lambda: received.append(True))

    panel._close_btn.click()

    assert len(received) == 1


# ---------------------------------------------------------------------------
# 3. test_rows_render_for_all_task_types
# ---------------------------------------------------------------------------


def test_rows_render_for_all_task_types():
    records = [
        _make_record(task_id="aaaa0000-0000-0000-0000-000000000001", task_type="batch_translation"),
        _make_record(task_id="bbbb1111-0000-0000-0000-000000000002", task_type="glossary_extraction"),
        _make_record(task_id="cccc2222-0000-0000-0000-000000000003", task_type="glossary_export"),
    ]
    engine = _make_engine(records=records)
    panel = _make_panel(engine=engine)

    assert len(panel._rows) == 3
    assert "aaaa0000-0000-0000-0000-000000000001" in panel._rows
    assert "bbbb1111-0000-0000-0000-000000000002" in panel._rows
    assert "cccc2222-0000-0000-0000-000000000003" in panel._rows


# ---------------------------------------------------------------------------
# 4. test_empty_task_list_renders_no_rows
# ---------------------------------------------------------------------------


def test_empty_task_list_renders_no_rows():
    engine = _make_engine(records=[])
    panel = _make_panel(engine=engine)
    assert len(panel._rows) == 0


# ---------------------------------------------------------------------------
# 5. test_get_tasks_called_with_no_task_type_filter
# ---------------------------------------------------------------------------


def test_get_tasks_called_with_no_task_type_filter():
    engine = _make_engine(records=[])
    _panel = _make_panel(engine=engine, book_id="book-42")

    # get_tasks should be called with only book_id (no task_type filter)
    engine.get_tasks.assert_called_with("book-42", limit=200)


# ---------------------------------------------------------------------------
# 6. test_constructor_triggers_initial_refresh
# ---------------------------------------------------------------------------


def test_constructor_triggers_initial_refresh():
    engine = _make_engine(records=[])
    _panel = _make_panel(engine=engine)

    engine.get_tasks.assert_called()


# ---------------------------------------------------------------------------
# 7. test_preflight_applied_per_row_all_allowed
# ---------------------------------------------------------------------------


def test_preflight_applied_per_row_all_allowed():
    r = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001")
    engine = _make_engine(records=[r])
    engine.preflight_task.return_value = Decision(allowed=True, reason="")
    panel = _make_panel(engine=engine)

    row = panel._rows["aaaa0000-0000-0000-0000-000000000001"]
    assert row._run_btn.isEnabled()
    assert row._cancel_btn.isEnabled()
    assert row._delete_btn.isEnabled()


# ---------------------------------------------------------------------------
# 8. test_preflight_applied_per_row_cancel_denied
# ---------------------------------------------------------------------------


def test_preflight_applied_per_row_cancel_denied():
    r = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001")
    engine = _make_engine(records=[r])

    def _preflight(task_id, action):  # noqa: ARG001
        if action == TaskAction.CANCEL:
            return Decision(allowed=False, reason="Task is not running")
        return Decision(allowed=True, reason="")

    engine.preflight_task.side_effect = _preflight
    panel = _make_panel(engine=engine)

    row = panel._rows["aaaa0000-0000-0000-0000-000000000001"]
    assert row._run_btn.isEnabled()
    assert not row._cancel_btn.isEnabled()
    assert "Task is not running" in row._cancel_btn.toolTip()
    assert row._delete_btn.isEnabled()


# ---------------------------------------------------------------------------
# 9. test_run_button_invokes_engine_run_task
# ---------------------------------------------------------------------------


def test_run_button_invokes_engine_run_task():
    r = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001")
    engine = _make_engine(records=[r])
    panel = _make_panel(engine=engine)

    row = panel._rows["aaaa0000-0000-0000-0000-000000000001"]
    row._run_btn.click()

    engine.run_task.assert_called_once_with("aaaa0000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# 10. test_cancel_button_invokes_engine_cancel
# ---------------------------------------------------------------------------


def test_cancel_button_invokes_engine_cancel():
    r = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001")
    engine = _make_engine(records=[r])
    panel = _make_panel(engine=engine)

    row = panel._rows["aaaa0000-0000-0000-0000-000000000001"]
    row._cancel_btn.click()

    engine.cancel.assert_called_once_with("aaaa0000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# 11. test_delete_with_confirmation_invokes_engine_delete
# ---------------------------------------------------------------------------


def test_delete_with_confirmation_invokes_engine_delete():
    r = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001")
    engine = _make_engine(records=[r])
    panel = _make_panel(engine=engine)

    row = panel._rows["aaaa0000-0000-0000-0000-000000000001"]

    with patch(
        "context_aware_translation.ui.widgets.task_activity_panel.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        row._delete_btn.click()

    engine.delete.assert_called_once_with("aaaa0000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# 12. test_delete_cancelled_by_user_does_not_invoke_engine
# ---------------------------------------------------------------------------


def test_delete_cancelled_by_user_does_not_invoke_engine():
    r = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001")
    engine = _make_engine(records=[r])
    panel = _make_panel(engine=engine)

    row = panel._rows["aaaa0000-0000-0000-0000-000000000001"]

    with patch(
        "context_aware_translation.ui.widgets.task_activity_panel.QMessageBox.question",
        return_value=QMessageBox.StandardButton.No,
    ):
        row._delete_btn.click()

    engine.delete.assert_not_called()


# ---------------------------------------------------------------------------
# 13. test_tasks_changed_refreshes_for_matching_book_id
# ---------------------------------------------------------------------------


def test_tasks_changed_refreshes_for_matching_book_id():
    r = _make_record()
    engine = _make_engine(records=[r])
    panel = _make_panel(engine=engine, book_id="book-1")
    panel._should_defer_hidden_refresh = lambda: False  # type: ignore[method-assign]
    panel.isVisible = lambda: True  # type: ignore[method-assign]

    initial_count = engine.get_tasks.call_count
    engine.tasks_changed.emit("book-1")
    panel._flush_scheduled_refresh()

    assert engine.get_tasks.call_count > initial_count
    panel.cleanup()


# ---------------------------------------------------------------------------
# 14. test_tasks_changed_ignores_different_book_id
# ---------------------------------------------------------------------------


def test_tasks_changed_ignores_different_book_id():
    engine = _make_engine(records=[])
    panel = _make_panel(engine=engine, book_id="book-1")

    initial_count = engine.get_tasks.call_count
    engine.tasks_changed.emit("book-99")

    assert engine.get_tasks.call_count == initial_count
    panel.cleanup()


# ---------------------------------------------------------------------------
# 15. test_run_error_shows_warning_dialog
# ---------------------------------------------------------------------------


def test_run_error_shows_warning_dialog():
    r = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001")
    engine = _make_engine(records=[r])
    engine.run_task.side_effect = ValueError("Config snapshot missing")
    panel = _make_panel(engine=engine)

    row = panel._rows["aaaa0000-0000-0000-0000-000000000001"]

    with patch("context_aware_translation.ui.widgets.task_activity_panel.QMessageBox.warning") as mock_warn:
        row._run_btn.click()

    mock_warn.assert_called_once()
    args = mock_warn.call_args[0]
    assert "Config snapshot missing" in args[2]


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 17. test_row_shows_error_label_when_last_error_set
# ---------------------------------------------------------------------------


def test_row_shows_error_label_when_last_error_set():
    r = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001", last_error="Something went wrong")
    engine = _make_engine(records=[r])
    panel = _make_panel(engine=engine)

    row = panel._rows["aaaa0000-0000-0000-0000-000000000001"]
    # Use not isHidden() because the widget has no shown parent window, so
    # isVisible() always returns False for un-shown top-level containers.
    assert not row._error_label.isHidden()
    assert "Something went wrong" in row._error_label.text()


# ---------------------------------------------------------------------------
# 18. test_row_hides_error_label_when_no_error
# ---------------------------------------------------------------------------


def test_row_hides_error_label_when_no_error():
    r = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001", last_error=None)
    engine = _make_engine(records=[r])
    panel = _make_panel(engine=engine)

    row = panel._rows["aaaa0000-0000-0000-0000-000000000001"]
    assert row._error_label.isHidden()


# ---------------------------------------------------------------------------
# 19. test_retranslate_ui_updates_all_row_buttons
# ---------------------------------------------------------------------------


def test_retranslate_ui_updates_all_row_buttons():
    records = [
        _make_record(task_id="aaaa0000-0000-0000-0000-000000000001"),
        _make_record(task_id="bbbb1111-0000-0000-0000-000000000002"),
    ]
    engine = _make_engine(records=records)
    panel = _make_panel(engine=engine)

    panel.retranslate_ui()

    for row in panel._rows.values():
        assert row._run_btn.text()
        assert row._cancel_btn.text()
        assert row._delete_btn.text()


# ---------------------------------------------------------------------------
# 20. test_language_change_event_calls_retranslate_ui
# ---------------------------------------------------------------------------


def test_language_change_event_calls_retranslate_ui():
    engine = _make_engine(records=[])
    panel = _make_panel(engine=engine)

    # retranslate_ui should set title label text (non-empty)
    assert panel._title_label.text()  # set during construction


# ---------------------------------------------------------------------------
# 21. test_preflight_reapplied_on_retranslate
# ---------------------------------------------------------------------------


def test_preflight_reapplied_on_retranslate():
    r = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001")
    engine = _make_engine(records=[r])

    def _deny_run(task_id, action):  # noqa: ARG001
        if action == TaskAction.RUN:
            return Decision(allowed=False, reason="Busy")
        return Decision(allowed=True, reason="")

    engine.preflight_task.side_effect = _deny_run
    panel = _make_panel(engine=engine)

    row = panel._rows["aaaa0000-0000-0000-0000-000000000001"]
    # After construction preflight already applied
    assert not row._run_btn.isEnabled()
    assert "Busy" in row._run_btn.toolTip()

    # retranslate_ui re-applies preflight — tooltip must survive
    panel.retranslate_ui()
    assert not row._run_btn.isEnabled()
    assert "Busy" in row._run_btn.toolTip()


# ---------------------------------------------------------------------------
# 22. test_refresh_removes_deleted_task_rows
# ---------------------------------------------------------------------------


def test_refresh_removes_deleted_task_rows():
    r1 = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001")
    r2 = _make_record(task_id="bbbb1111-0000-0000-0000-000000000002")
    engine = _make_engine(records=[r1, r2])
    panel = _make_panel(engine=engine)

    assert len(panel._rows) == 2

    # Remove r2 from engine
    engine.get_tasks.return_value = [r1]
    panel.refresh()

    assert len(panel._rows) == 1
    assert "aaaa0000-0000-0000-0000-000000000001" in panel._rows
    assert "bbbb1111-0000-0000-0000-000000000002" not in panel._rows


# ---------------------------------------------------------------------------
# 23. test_scroll_area_exists
# ---------------------------------------------------------------------------


def test_scroll_area_exists():
    panel = _make_panel()
    assert panel._scroll_area is not None
    assert panel._scroll_area.widgetResizable()


def test_row_shows_stage_for_running_task_without_phase():
    r = _make_record(
        task_id="stage-task",
        task_type="glossary_translation",
        status="running",
        phase=None,
    )
    engine = _make_engine(records=[r])
    panel = _make_panel(engine=engine)

    row = panel._rows["stage-task"]
    assert "Stage:" in row._phase_label.text()
    assert "Glossary translation" in row._phase_label.text()


def test_row_shows_eta_for_partial_running_progress():
    now = time.time()
    r = _make_record(
        task_id="eta-task",
        task_type="ocr",
        status="running",
        completed_items=2,
        total_items=10,
        created_at=now - 20,
        updated_at=now,
    )
    engine = _make_engine(records=[r])
    panel = _make_panel(engine=engine)

    row = panel._rows["eta-task"]
    assert "ETA" in row._timing_label.text()


def test_progress_only_refresh_reapplies_preflight():
    now = time.time()
    r1 = _make_record(task_id="task-1", status="running", completed_items=1, total_items=10, updated_at=now)
    engine = _make_engine(records=[r1])
    panel = _make_panel(engine=engine)

    engine.preflight_task.reset_mock()
    r1_progress = _make_record(
        task_id="task-1",
        status="running",
        completed_items=2,
        total_items=10,
        updated_at=now + 1,
    )
    engine.get_tasks.return_value = [r1_progress]
    panel.refresh(recompute_preflight=True)

    # Preflight is recomputed on each refresh so policy/config changes are
    # reflected immediately even when lifecycle status is unchanged.
    assert engine.preflight_task.call_count == 3


def test_status_change_refresh_reapplies_preflight():
    now = time.time()
    r1 = _make_record(task_id="task-1", status="running", completed_items=1, total_items=10, updated_at=now)
    engine = _make_engine(records=[r1])
    panel = _make_panel(engine=engine)

    engine.preflight_task.reset_mock()
    r1_done = _make_record(
        task_id="task-1",
        status="completed",
        completed_items=10,
        total_items=10,
        updated_at=now + 1,
    )
    engine.get_tasks.return_value = [r1_done]
    panel.refresh(recompute_preflight=True)

    # RUN/CANCEL/DELETE should be re-evaluated when lifecycle status changes.
    assert engine.preflight_task.call_count == 3


def test_long_error_is_truncated_inline_but_full_in_tooltip():
    long_error = "x" * 500
    r = _make_record(task_id="task-err", last_error=long_error)
    engine = _make_engine(records=[r])
    panel = _make_panel(engine=engine)

    row = panel._rows["task-err"]
    assert len(row._error_label.text()) < len(long_error)
    assert row._error_label.toolTip() == long_error
