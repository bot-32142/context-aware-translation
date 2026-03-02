"""Unit tests for TaskStatusCard and TaskStatusStrip widgets."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

try:
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication

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
        "total_items": 0,
        "completed_items": 0,
        "failed_items": 0,
        "last_error": None,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    defaults.update(overrides)
    return TaskRecord(**defaults)


def _make_engine(records: list[TaskRecord] | None = None) -> MagicMock:
    """Return a mock engine with real PySide6 signals."""
    signal_holder = _SignalHolder()
    engine = MagicMock()
    engine.tasks_changed = signal_holder.tasks_changed
    engine.error_occurred = signal_holder.error_occurred
    engine._signal_holder = signal_holder  # prevent GC
    engine.get_tasks.return_value = records if records is not None else []
    engine.preflight_task.return_value = Decision(allowed=False, reason="")
    return engine


def _make_card(engine=None, book_id="book-1", task_types=None, display_label="Extraction"):
    from context_aware_translation.ui.widgets.task_status_card import TaskStatusCard

    if engine is None:
        engine = _make_engine()
    if task_types is None:
        task_types = ["batch_translation"]
    return TaskStatusCard(engine, book_id, task_types, display_label)


def _make_strip(engine=None, book_id="book-1", task_types=None):
    from context_aware_translation.ui.widgets.task_status_card import TaskStatusStrip

    if engine is None:
        engine = _make_engine()
    if task_types is None:
        task_types = ["batch_translation"]
    return TaskStatusStrip(engine, book_id, task_types)


# ---------------------------------------------------------------------------
# TaskStatusCard tests
# ---------------------------------------------------------------------------


def test_card_hidden_when_no_tasks():
    engine = _make_engine(records=[])
    card = _make_card(engine=engine)
    assert not card.isVisible()


def test_card_visible_when_tasks_exist():
    r = _make_record(status="queued")
    engine = _make_engine(records=[r])
    card = _make_card(engine=engine)
    assert card.isVisible()


def test_card_shows_status_chip_text():
    r = _make_record(status="running")
    engine = _make_engine(records=[r])
    card = _make_card(engine=engine)
    assert card._chip.text() == "Running"


def test_card_prefers_non_terminal_task():
    now = time.time()
    r_completed = _make_record(
        task_id="aaaa0000-0000-0000-0000-000000000001",
        status="completed",
        updated_at=now + 10,
    )
    r_running = _make_record(
        task_id="bbbb1111-0000-0000-0000-000000000002",
        status="running",
        updated_at=now,
    )
    # Most recent is completed, but running should be preferred
    engine = _make_engine(records=[r_completed, r_running])
    card = _make_card(engine=engine)
    assert card._chip.text() == "Running"


def test_card_falls_back_to_most_recent_if_all_terminal():
    now = time.time()
    r1 = _make_record(
        task_id="aaaa0000-0000-0000-0000-000000000001",
        status="completed",
        updated_at=now + 5,
    )
    r2 = _make_record(
        task_id="bbbb1111-0000-0000-0000-000000000002",
        status="failed",
        updated_at=now,
    )
    engine = _make_engine(records=[r1, r2])
    card = _make_card(engine=engine)
    # Most recent by updated_at (after sorting newest-first) is r1
    assert card._chip.text() == "Completed"


def test_card_shows_phase_and_progress():
    r = _make_record(status="running", phase="extraction", total_items=120, completed_items=45)
    engine = _make_engine(records=[r])
    card = _make_card(engine=engine)
    detail = card._detail_label.text()
    assert "Extraction" in detail
    assert "45/120" in detail
    assert card._detail_label.isVisible()


def test_card_hides_detail_when_no_phase_no_progress():
    r = _make_record(status="queued", phase=None, total_items=0, completed_items=0)
    engine = _make_engine(records=[r])
    card = _make_card(engine=engine)
    assert not card._detail_label.isVisible()


def test_card_shows_last_error():
    r = _make_record(status="failed", last_error="Connection refused")
    engine = _make_engine(records=[r])
    card = _make_card(engine=engine)
    assert card._error_label.isVisible()
    assert "Connection refused" in card._error_label.text()


def test_card_hides_error_label_when_no_error():
    r = _make_record(status="running", last_error=None)
    engine = _make_engine(records=[r])
    card = _make_card(engine=engine)
    assert not card._error_label.isVisible()


def test_card_cancel_button_visible_when_preflight_allows():
    r = _make_record(status="running")
    engine = _make_engine(records=[r])

    def _preflight(task_id, action):  # noqa: ARG001
        if action == TaskAction.CANCEL:
            return Decision(allowed=True, reason="")
        return Decision(allowed=False, reason="")

    engine.preflight_task.side_effect = _preflight
    card = _make_card(engine=engine)
    assert card._cancel_btn.isVisible()
    assert not card._run_btn.isVisible()


def test_card_run_button_visible_when_preflight_allows():
    r = _make_record(status="queued")
    engine = _make_engine(records=[r])

    def _preflight(task_id, action):  # noqa: ARG001
        if action == TaskAction.RUN:
            return Decision(allowed=True, reason="")
        return Decision(allowed=False, reason="")

    engine.preflight_task.side_effect = _preflight
    card = _make_card(engine=engine)
    assert card._run_btn.isVisible()
    assert not card._cancel_btn.isVisible()


def test_card_run_button_labeled_retry_for_terminal_tasks():
    r = _make_record(status="failed")
    engine = _make_engine(records=[r])

    def _preflight(task_id, action):  # noqa: ARG001
        if action == TaskAction.RUN:
            return Decision(allowed=True, reason="")
        return Decision(allowed=False, reason="")

    engine.preflight_task.side_effect = _preflight
    card = _make_card(engine=engine)
    assert "Retry" in card._run_btn.text()


def test_card_run_button_labeled_run_for_non_terminal():
    r = _make_record(status="queued")
    engine = _make_engine(records=[r])

    def _preflight(task_id, action):  # noqa: ARG001
        if action == TaskAction.RUN:
            return Decision(allowed=True, reason="")
        return Decision(allowed=False, reason="")

    engine.preflight_task.side_effect = _preflight
    card = _make_card(engine=engine)
    assert card._run_btn.text() == "Run"


def test_card_open_activity_always_visible():
    r = _make_record(status="queued")
    engine = _make_engine(records=[r])
    card = _make_card(engine=engine)
    assert card._open_activity_btn.isVisible()


def test_card_open_activity_emits_signal():
    r = _make_record(status="queued")
    engine = _make_engine(records=[r])
    card = _make_card(engine=engine)

    received = []
    card.open_activity_requested.connect(lambda: received.append(True))
    card._open_activity_btn.click()
    assert len(received) == 1


def test_card_cancel_invokes_engine_cancel():
    r = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001", status="running")
    engine = _make_engine(records=[r])
    engine.preflight_task.side_effect = lambda _tid, action: (
        Decision(allowed=True, reason="") if action == TaskAction.CANCEL else Decision(allowed=False, reason="")
    )
    card = _make_card(engine=engine)
    card._cancel_btn.click()
    engine.cancel.assert_called_once_with("aaaa0000-0000-0000-0000-000000000001")


def test_card_run_invokes_engine_run_task():
    r = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001", status="queued")
    engine = _make_engine(records=[r])
    engine.preflight_task.side_effect = lambda _tid, action: (
        Decision(allowed=True, reason="") if action == TaskAction.RUN else Decision(allowed=False, reason="")
    )
    card = _make_card(engine=engine)
    card._run_btn.click()
    engine.run_task.assert_called_once_with("aaaa0000-0000-0000-0000-000000000001")


def test_card_refreshes_on_tasks_changed_for_matching_book():
    r = _make_record()
    engine = _make_engine(records=[r])
    card = _make_card(engine=engine, book_id="book-1")  # noqa: F841
    initial_count = engine.get_tasks.call_count

    engine.tasks_changed.emit("book-1")

    assert engine.get_tasks.call_count > initial_count


def test_card_ignores_tasks_changed_for_other_book():
    r = _make_record()
    engine = _make_engine(records=[r])
    card = _make_card(engine=engine, book_id="book-1")  # noqa: F841
    initial_count = engine.get_tasks.call_count

    engine.tasks_changed.emit("book-99")

    assert engine.get_tasks.call_count == initial_count


def test_card_hides_after_tasks_removed():
    r = _make_record()
    engine = _make_engine(records=[r])
    card = _make_card(engine=engine, book_id="book-1")
    assert card.isVisible()

    engine.get_tasks.return_value = []
    engine.tasks_changed.emit("book-1")

    assert not card.isVisible()


def test_card_retranslate_ui_sets_button_labels():
    engine = _make_engine(records=[])
    card = _make_card(engine=engine)
    card.retranslateUi()
    assert card._open_activity_btn.text()
    assert card._cancel_btn.text()
    assert card._run_btn.text()


def test_card_multiple_task_types_aggregates_all():
    now = time.time()
    r1 = _make_record(
        task_id="aaaa0000-0000-0000-0000-000000000001",
        task_type="batch_translation",
        status="running",
        updated_at=now + 1,
    )
    r2 = _make_record(
        task_id="bbbb1111-0000-0000-0000-000000000002",
        task_type="translation_text",
        status="queued",
        updated_at=now,
    )
    engine = _make_engine()

    def _get_tasks(book_id, task_type):  # noqa: ARG001
        if task_type == "batch_translation":
            return [r1]
        if task_type == "translation_text":
            return [r2]
        return []

    engine.get_tasks.side_effect = _get_tasks
    card = _make_card(engine=engine, task_types=["batch_translation", "translation_text"])
    # running is non-terminal, should be preferred over queued
    assert card._chip.text() == "Running"


# ---------------------------------------------------------------------------
# TaskStatusStrip tests
# ---------------------------------------------------------------------------


def test_strip_hidden_when_no_tasks():
    engine = _make_engine(records=[])
    strip = _make_strip(engine=engine)
    assert not strip.isVisible()


def test_strip_visible_with_tasks():
    r = _make_record(status="queued")
    engine = _make_engine(records=[r])
    strip = _make_strip(engine=engine)
    assert strip.isVisible()


def test_strip_creates_one_card_per_task():
    r1 = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001", status="running")
    r2 = _make_record(task_id="bbbb1111-0000-0000-0000-000000000002", status="queued")
    engine = _make_engine(records=[r1, r2])
    strip = _make_strip(engine=engine)
    assert len(strip._cards) == 2


def test_strip_shows_all_tasks_not_just_primary():
    r1 = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001", status="running")
    r2 = _make_record(task_id="bbbb1111-0000-0000-0000-000000000002", status="completed")
    r3 = _make_record(task_id="cccc2222-0000-0000-0000-000000000003", status="failed")
    engine = _make_engine(records=[r1, r2, r3])
    strip = _make_strip(engine=engine)
    assert len(strip._cards) == 3


def test_strip_open_activity_signal_forwarded():
    r = _make_record(status="running")
    engine = _make_engine(records=[r])
    strip = _make_strip(engine=engine)

    received = []
    strip.open_activity_requested.connect(lambda: received.append(True))

    # Trigger via the mini-card
    task_id = list(strip._cards.keys())[0]
    strip._cards[task_id].open_activity_requested.emit()
    assert len(received) == 1


def test_strip_refreshes_on_tasks_changed():
    r = _make_record()
    engine = _make_engine(records=[r])
    strip = _make_strip(engine=engine, book_id="book-1")  # noqa: F841
    initial = engine.get_tasks.call_count

    engine.tasks_changed.emit("book-1")

    assert engine.get_tasks.call_count > initial


def test_strip_ignores_tasks_changed_for_other_book():
    engine = _make_engine(records=[])
    strip = _make_strip(engine=engine, book_id="book-1")  # noqa: F841
    initial = engine.get_tasks.call_count

    engine.tasks_changed.emit("book-99")

    assert engine.get_tasks.call_count == initial


def test_strip_removes_stale_cards_on_refresh():
    r1 = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001", status="running")
    r2 = _make_record(task_id="bbbb1111-0000-0000-0000-000000000002", status="queued")
    engine = _make_engine(records=[r1, r2])
    strip = _make_strip(engine=engine, book_id="book-1")
    assert len(strip._cards) == 2

    # Remove r2 from results
    engine.get_tasks.return_value = [r1]
    engine.tasks_changed.emit("book-1")
    assert len(strip._cards) == 1
    assert "aaaa0000-0000-0000-0000-000000000001" in strip._cards


def test_strip_hides_after_all_tasks_removed():
    r = _make_record()
    engine = _make_engine(records=[r])
    strip = _make_strip(engine=engine, book_id="book-1")
    assert strip.isVisible()

    engine.get_tasks.return_value = []
    engine.tasks_changed.emit("book-1")
    assert not strip.isVisible()


def test_strip_multiple_task_types():
    r1 = _make_record(task_id="aaaa0000-0000-0000-0000-000000000001", task_type="batch_translation", status="running")
    r2 = _make_record(task_id="bbbb1111-0000-0000-0000-000000000002", task_type="translation_text", status="queued")
    engine = _make_engine()

    def _get_tasks(book_id, task_type):  # noqa: ARG001
        if task_type == "batch_translation":
            return [r1]
        if task_type == "translation_text":
            return [r2]
        return []

    engine.get_tasks.side_effect = _get_tasks
    strip = _make_strip(engine=engine, task_types=["batch_translation", "translation_text"])
    assert len(strip._cards) == 2


def test_strip_shows_only_latest_three_tasks():
    now = time.time()
    r1 = _make_record(task_id="t1", status="running", updated_at=now + 5)
    r2 = _make_record(task_id="t2", status="queued", updated_at=now + 4)
    r3 = _make_record(task_id="t3", status="completed", updated_at=now + 3)
    r4 = _make_record(task_id="t4", status="failed", updated_at=now + 2)
    r5 = _make_record(task_id="t5", status="cancelled", updated_at=now + 1)
    engine = _make_engine(records=[r1, r2, r3, r4, r5])

    strip = _make_strip(engine=engine)

    assert len(strip._cards) == 3
    assert set(strip._cards.keys()) == {"t1", "t2", "t3"}
    assert "t4" not in strip._cards
    assert "t5" not in strip._cards
