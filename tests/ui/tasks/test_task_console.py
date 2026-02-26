"""Unit tests for TaskConsole widget."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

try:
    from PySide6.QtCore import QEvent, QObject, Qt, Signal
    from PySide6.QtWidgets import QApplication, QMessageBox

    HAS_PYSIDE6 = True
except ImportError:
    HAS_PYSIDE6 = False

from context_aware_translation.storage.task_store import TaskRecord
from context_aware_translation.workflow.tasks.models import Decision, TaskAction

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


def _make_record(**overrides) -> TaskRecord:
    defaults = dict(
        task_id="abcd1234-5678-9abc-def0-1234567890ab",
        book_id="book-1",
        task_type="batch_translation",
        status="queued",
        phase=None,
        document_ids_json=None,
        payload_json=None,
        config_snapshot_json=None,
        cancel_requested=False,
        total_items=10,
        completed_items=3,
        failed_items=0,
        last_error=None,
        created_at=time.time(),
        updated_at=time.time(),
    )
    defaults.update(overrides)
    return TaskRecord(**defaults)


def _make_engine(records: list[TaskRecord] | None = None) -> MagicMock:
    """Return a mock engine with a real PySide6 Signal for tasks_changed."""
    signal_holder = _SignalHolder()
    engine = MagicMock()
    engine.tasks_changed = signal_holder.tasks_changed
    engine._signal_holder = signal_holder  # prevent GC
    engine.get_tasks.return_value = records if records is not None else []
    engine.preflight_task.return_value = Decision(allowed=True, reason="")
    return engine


def _make_console(engine=None, book_id="book-1", task_type="batch_translation"):
    from context_aware_translation.ui.tasks.task_console import TaskConsole

    if engine is None:
        engine = _make_engine()
    return TaskConsole(engine, book_id, task_type)


# ---------------------------------------------------------------------------
# 1. test_rows_render_from_vm_mapping
# ---------------------------------------------------------------------------


def test_rows_render_from_vm_mapping():
    r1 = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001", status="queued", phase="prepare")
    r2 = _make_record(task_id="bbbb1111-0000-0000-0000-000000000002", status="running", phase="apply")
    engine = _make_engine(records=[r1, r2])
    console = _make_console(engine=engine)

    assert console._task_list.count() == 2
    text0 = console._task_list.item(0).text()
    text1 = console._task_list.item(1).text()
    assert "#aaaa0000" in text0
    assert "queued" in text0
    assert "#bbbb1111" in text1
    assert "running" in text1


# ---------------------------------------------------------------------------
# 2. test_empty_task_list_renders_no_rows
# ---------------------------------------------------------------------------


def test_empty_task_list_renders_no_rows():
    engine = _make_engine(records=[])
    console = _make_console(engine=engine)
    assert console._task_list.count() == 0


# ---------------------------------------------------------------------------
# 3. test_buttons_use_per_action_preflight_decisions
# ---------------------------------------------------------------------------


def test_buttons_use_per_action_preflight_decisions():
    r = _make_record()
    engine = _make_engine(records=[r])

    def _preflight(task_id, action):
        if action == TaskAction.RUN:
            return Decision(allowed=True, reason="")
        if action == TaskAction.CANCEL:
            return Decision(allowed=False, reason="Task is not running")
        return Decision(allowed=True, reason="")

    engine.preflight_task.side_effect = _preflight
    console = _make_console(engine=engine)
    console._task_list.setCurrentRow(0)

    assert console._run_btn.isEnabled()
    assert not console._cancel_btn.isEnabled()
    assert "Task is not running" in console._cancel_btn.toolTip()
    assert console._delete_btn.isEnabled()


# ---------------------------------------------------------------------------
# 4. test_button_state_updates_when_preflight_all_denied
# ---------------------------------------------------------------------------


def test_button_state_updates_when_preflight_all_denied():
    r = _make_record()
    engine = _make_engine(records=[r])

    def _preflight(task_id, action):
        if action == TaskAction.RUN:
            return Decision(allowed=False, reason="Already running")
        if action == TaskAction.CANCEL:
            return Decision(allowed=False, reason="Not cancellable")
        return Decision(allowed=False, reason="Has active claim")

    engine.preflight_task.side_effect = _preflight
    console = _make_console(engine=engine)
    console._task_list.setCurrentRow(0)

    assert not console._run_btn.isEnabled()
    assert "Already running" in console._run_btn.toolTip()
    assert not console._cancel_btn.isEnabled()
    assert "Not cancellable" in console._cancel_btn.toolTip()
    assert not console._delete_btn.isEnabled()
    assert "Has active claim" in console._delete_btn.toolTip()


# ---------------------------------------------------------------------------
# 5. test_no_selection_disables_all_buttons
# ---------------------------------------------------------------------------


def test_no_selection_disables_all_buttons():
    engine = _make_engine(records=[])
    console = _make_console(engine=engine)

    assert not console._run_btn.isEnabled()
    assert not console._cancel_btn.isEnabled()
    assert not console._delete_btn.isEnabled()


# ---------------------------------------------------------------------------
# 6. test_run_invokes_engine_run_task
# ---------------------------------------------------------------------------


def test_run_invokes_engine_run_task():
    r = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001")
    engine = _make_engine(records=[r])
    console = _make_console(engine=engine)
    console._task_list.setCurrentRow(0)

    console._run_btn.click()

    engine.run_task.assert_called_once_with("aaaa0000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# 7. test_cancel_invokes_engine_cancel
# ---------------------------------------------------------------------------


def test_cancel_invokes_engine_cancel():
    r = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001")
    engine = _make_engine(records=[r])
    console = _make_console(engine=engine)
    console._task_list.setCurrentRow(0)

    console._cancel_btn.click()

    engine.cancel.assert_called_once_with("aaaa0000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# 8. test_delete_with_confirmation_invokes_engine_delete
# ---------------------------------------------------------------------------


def test_delete_with_confirmation_invokes_engine_delete():
    r = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001")
    engine = _make_engine(records=[r])
    console = _make_console(engine=engine)
    console._task_list.setCurrentRow(0)

    with patch(
        "context_aware_translation.ui.tasks.task_console.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        console._delete_btn.click()

    engine.delete.assert_called_once_with("aaaa0000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# 9. test_delete_cancelled_by_user_does_not_invoke_engine
# ---------------------------------------------------------------------------


def test_delete_cancelled_by_user_does_not_invoke_engine():
    r = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001")
    engine = _make_engine(records=[r])
    console = _make_console(engine=engine)
    console._task_list.setCurrentRow(0)

    with patch(
        "context_aware_translation.ui.tasks.task_console.QMessageBox.question",
        return_value=QMessageBox.StandardButton.No,
    ):
        console._delete_btn.click()

    engine.delete.assert_not_called()


# ---------------------------------------------------------------------------
# 10. test_tasks_changed_refreshes_for_matching_book_id
# ---------------------------------------------------------------------------


def test_tasks_changed_refreshes_for_matching_book_id():
    r = _make_record()
    engine = _make_engine(records=[r])
    console = _make_console(engine=engine, book_id="book-1")

    initial_count = engine.get_tasks.call_count
    engine.tasks_changed.emit("book-1")

    assert engine.get_tasks.call_count > initial_count


# ---------------------------------------------------------------------------
# 11. test_tasks_changed_ignores_different_book_id
# ---------------------------------------------------------------------------


def test_tasks_changed_ignores_different_book_id():
    engine = _make_engine(records=[])
    console = _make_console(engine=engine, book_id="book-1")

    initial_count = engine.get_tasks.call_count
    engine.tasks_changed.emit("book-2")

    assert engine.get_tasks.call_count == initial_count


# ---------------------------------------------------------------------------
# 12. test_stable_selection_across_refresh
# ---------------------------------------------------------------------------


def test_stable_selection_across_refresh():
    r1 = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001")
    r2 = _make_record(task_id="bbbb1111-0000-0000-0000-000000000002")
    r3 = _make_record(task_id="cccc2222-0000-0000-0000-000000000003")
    engine = _make_engine(records=[r1, r2, r3])
    console = _make_console(engine=engine)

    # Select the second row
    console._task_list.setCurrentRow(1)
    assert console.selected_task_id() == "bbbb1111-0000-0000-0000-000000000002"

    # Refresh with the same 3 tasks
    console.refresh()

    assert console.selected_task_id() == "bbbb1111-0000-0000-0000-000000000002"


# ---------------------------------------------------------------------------
# 13. test_constructor_triggers_initial_refresh
# ---------------------------------------------------------------------------


def test_constructor_triggers_initial_refresh():
    engine = _make_engine(records=[])
    _console = _make_console(engine=engine)

    # get_tasks must have been called during construction
    engine.get_tasks.assert_called()


# ---------------------------------------------------------------------------
# 14. test_refresh_recomputes_action_buttons_when_selection_unchanged
# ---------------------------------------------------------------------------


def test_refresh_recomputes_action_buttons_when_selection_unchanged():
    r = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001")
    engine = _make_engine(records=[r])
    # First: RUN allowed
    engine.preflight_task.return_value = Decision(allowed=True, reason="")
    console = _make_console(engine=engine)
    console._task_list.setCurrentRow(0)
    assert console._run_btn.isEnabled()

    # Change preflight to deny RUN
    def _deny_run(task_id, action):
        if action == TaskAction.RUN:
            return Decision(allowed=False, reason="Cooldown active")
        return Decision(allowed=True, reason="")

    engine.preflight_task.side_effect = _deny_run

    # Refresh — same task still selected, but button state must update
    console.refresh()

    assert not console._run_btn.isEnabled()
    assert "Cooldown active" in console._run_btn.toolTip()


# ---------------------------------------------------------------------------
# 15. test_unknown_task_type_propagates_error
# ---------------------------------------------------------------------------


def test_unknown_task_type_propagates_error():
    r = _make_record(task_type="unknown")
    engine = _make_engine(records=[r])

    with pytest.raises(RuntimeError, match="Unknown task type"):
        _make_console(engine=engine)


# ---------------------------------------------------------------------------
# 16. test_language_change_updates_task_console_labels
# ---------------------------------------------------------------------------


def test_language_change_updates_task_console_labels():
    engine = _make_engine(records=[])
    console = _make_console(engine=engine)

    # Trigger retranslate_ui directly
    console.retranslate_ui()

    # Button labels should be set (non-empty)
    assert console._run_btn.text()
    assert console._cancel_btn.text()
    assert console._delete_btn.text()


# ---------------------------------------------------------------------------
# 17. test_language_change_preserves_preflight_reason_tooltips
# ---------------------------------------------------------------------------


def test_language_change_preserves_preflight_reason_tooltips():
    r = _make_record()
    engine = _make_engine(records=[r])

    def _deny_cancel(task_id, action):
        if action == TaskAction.CANCEL:
            return Decision(allowed=False, reason="Task is not running")
        return Decision(allowed=True, reason="")

    engine.preflight_task.side_effect = _deny_cancel
    console = _make_console(engine=engine)
    console._task_list.setCurrentRow(0)

    assert "Task is not running" in console._cancel_btn.toolTip()

    # Trigger language change
    console.retranslate_ui()

    # Tooltip must still show the preflight reason, not be wiped by relabeling
    assert "Task is not running" in console._cancel_btn.toolTip()


# ---------------------------------------------------------------------------
# 18. test_console_refreshed_emitted_after_refresh
# ---------------------------------------------------------------------------


def test_console_refreshed_emitted_after_refresh():
    engine = _make_engine(records=[])
    console = _make_console(engine=engine)

    received = []
    console.console_refreshed.connect(lambda: received.append(True))

    # Construction already triggered one refresh; clear and re-check
    received.clear()
    console.refresh()

    assert len(received) == 1
