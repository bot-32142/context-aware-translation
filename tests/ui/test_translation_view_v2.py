"""Tests for TranslationView v2 behavior: split-aware submission, status strip, no TaskConsole."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

try:
    from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QPushButton

    HAS_PYSIDE6 = True
except ImportError:
    HAS_PYSIDE6 = False

from context_aware_translation.workflow.tasks.models import (
    STATUS_RUNNING,
)

pytestmark = pytest.mark.skipif(not HAS_PYSIDE6, reason="PySide6 not available")


@pytest.fixture(autouse=True, scope="module")
def _qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _noop_init(self, *_args, **_kwargs):  # noqa: ANN001
    """No-op replacement for TranslationView.__init__."""


def _make_book_manager() -> MagicMock:
    manager = MagicMock()
    manager.get_book_db_path.return_value = Path("/tmp/context-aware-translation-tests/book.db")
    return manager


def _make_view():
    from context_aware_translation.ui.views.translation_view import TranslationView

    with patch.object(TranslationView, "__init__", _noop_init):
        view = TranslationView(None, "")
    view._is_cleaned_up = False
    view._task_engine = MagicMock()
    view._task_engine.get_task.return_value = None
    view._pending_retranslations = {}
    view._document_type_cache = {}
    view.book_id = "test-book"
    view.book_manager = _make_book_manager()
    view.term_db = MagicMock()
    view.document_repo = MagicMock()
    view.document_repo.get_document_by_id.return_value = {"document_type": "text"}
    return view


# ------------------------------------------------------------------
# No TaskConsole widget
# ------------------------------------------------------------------


def test_translation_view_has_no_task_console_attribute():
    """TranslationView must not have task_console or sync_task_console attributes after migration."""

    view = _make_view()
    assert not hasattr(view, "task_console"), "task_console should not exist on TranslationView"
    assert not hasattr(view, "sync_task_console"), "sync_task_console should not exist on TranslationView"


def test_translation_view_has_no_sync_task_id():
    """_sync_task_id must not be present — sync_translation is gone."""
    view = _make_view()
    assert not hasattr(view, "_sync_task_id"), "_sync_task_id should not exist after migration"


# ------------------------------------------------------------------
# Split-aware _start_translation
# ------------------------------------------------------------------


def test_start_translation_text_only_submits_translation_text():
    """Text-only selection submits exactly one translation_text task."""
    view = _make_view()
    view.book_id = "book-id"
    view._resolve_trigger_conditions = MagicMock(return_value=([1, 2], False))
    view._has_document_reservation = MagicMock(return_value=False)
    view._split_doc_ids_by_type = MagicMock(return_value=([1, 2], []))
    view.start_btn = QPushButton()
    view.doc_combo = QComboBox()
    view.skip_context_cb = QCheckBox()
    view.skip_context_cb.setChecked(False)
    view.status_label = MagicMock()

    preflight_ok = MagicMock()
    preflight_ok.allowed = True
    view._task_engine.preflight.return_value = preflight_ok

    submitted = MagicMock()
    submitted.task_id = "tt-1"
    submitted.status = STATUS_RUNNING
    submitted.last_error = None
    view._task_engine.submit_and_start.return_value = submitted

    view._start_translation()

    view._task_engine.submit_and_start.assert_called_once_with(
        "translation_text",
        "book-id",
        document_ids=[1, 2],
        force=False,
        skip_context=False,
        enable_polish=True,
    )


def test_start_translation_manga_only_submits_translation_manga():
    """Manga-only selection submits exactly one translation_manga task."""
    view = _make_view()
    view.book_id = "book-id"
    view._resolve_trigger_conditions = MagicMock(return_value=([3], False))
    view._has_document_reservation = MagicMock(return_value=False)
    view._split_doc_ids_by_type = MagicMock(return_value=([], [3]))
    view.start_btn = QPushButton()
    view.doc_combo = QComboBox()
    view.skip_context_cb = QCheckBox()
    view.skip_context_cb.setChecked(False)
    view.status_label = MagicMock()

    preflight_ok = MagicMock()
    preflight_ok.allowed = True
    view._task_engine.preflight.return_value = preflight_ok

    submitted = MagicMock()
    submitted.task_id = "tm-1"
    submitted.status = STATUS_RUNNING
    submitted.last_error = None
    view._task_engine.submit_and_start.return_value = submitted

    view._start_translation()

    view._task_engine.submit_and_start.assert_called_once_with(
        "translation_manga",
        "book-id",
        document_ids=[3],
        force=False,
        skip_context=False,
        enable_polish=True,
    )


def test_start_translation_mixed_selection_submits_both_task_types():
    """Mixed selection (text + manga) submits both translation_text and translation_manga."""
    view = _make_view()
    view.book_id = "book-id"
    view._resolve_trigger_conditions = MagicMock(return_value=([1, 3], False))
    view._has_document_reservation = MagicMock(return_value=False)
    view._split_doc_ids_by_type = MagicMock(return_value=([1], [3]))
    view.start_btn = QPushButton()
    view.doc_combo = QComboBox()
    view.skip_context_cb = QCheckBox()
    view.skip_context_cb.setChecked(False)
    view.status_label = MagicMock()

    preflight_ok = MagicMock()
    preflight_ok.allowed = True
    view._task_engine.preflight.return_value = preflight_ok

    submitted = MagicMock()
    submitted.task_id = "task-x"
    submitted.status = STATUS_RUNNING
    submitted.last_error = None
    view._task_engine.submit_and_start.return_value = submitted

    view._start_translation()

    assert view._task_engine.submit_and_start.call_count == 2
    calls = {call.args[0] for call in view._task_engine.submit_and_start.call_args_list}
    assert calls == {"translation_text", "translation_manga"}


def test_start_translation_mixed_selection_submits_nothing_when_text_preflight_denied():
    """All-or-none: if text bucket preflight is denied, nothing is submitted."""
    view = _make_view()
    view.book_id = "book-id"
    view._resolve_trigger_conditions = MagicMock(return_value=([1, 3], False))
    view._has_document_reservation = MagicMock(return_value=False)
    view._split_doc_ids_by_type = MagicMock(return_value=([1], [3]))
    view.start_btn = QPushButton()
    view.doc_combo = QComboBox()
    view.skip_context_cb = QCheckBox()
    view.skip_context_cb.setChecked(False)
    view.status_label = MagicMock()

    def _preflight(task_type, _book_id, _params, _action):
        decision = MagicMock()
        decision.allowed = task_type != "translation_text"
        decision.reason = "text preflight denied"
        return decision

    view._task_engine.preflight.side_effect = _preflight

    with patch("context_aware_translation.ui.views.translation_view.QMessageBox.warning") as warn_mock:
        view._start_translation()

    view._task_engine.submit_and_start.assert_not_called()
    warn_mock.assert_called_once()


def test_start_translation_mixed_selection_submits_nothing_when_manga_preflight_denied():
    """All-or-none: if manga bucket preflight is denied, nothing is submitted."""
    view = _make_view()
    view.book_id = "book-id"
    view._resolve_trigger_conditions = MagicMock(return_value=([1, 3], False))
    view._has_document_reservation = MagicMock(return_value=False)
    view._split_doc_ids_by_type = MagicMock(return_value=([1], [3]))
    view.start_btn = QPushButton()
    view.doc_combo = QComboBox()
    view.skip_context_cb = QCheckBox()
    view.skip_context_cb.setChecked(False)
    view.status_label = MagicMock()

    def _preflight(task_type, _book_id, _params, _action):
        decision = MagicMock()
        decision.allowed = task_type != "translation_manga"
        decision.reason = "manga preflight denied"
        return decision

    view._task_engine.preflight.side_effect = _preflight

    with patch("context_aware_translation.ui.views.translation_view.QMessageBox.warning") as warn_mock:
        view._start_translation()

    view._task_engine.submit_and_start.assert_not_called()
    warn_mock.assert_called_once()


def test_start_translation_partial_start_error_when_second_submit_fails():
    """If second submit fails after first succeeds, first task keeps running (partial-start error shown)."""
    view = _make_view()
    view.book_id = "book-id"
    view._resolve_trigger_conditions = MagicMock(return_value=([1, 3], False))
    view._has_document_reservation = MagicMock(return_value=False)
    view._split_doc_ids_by_type = MagicMock(return_value=([1], [3]))
    view.start_btn = QPushButton()
    view.doc_combo = QComboBox()
    view.skip_context_cb = QCheckBox()
    view.skip_context_cb.setChecked(False)
    view.status_label = MagicMock()

    preflight_ok = MagicMock()
    preflight_ok.allowed = True
    view._task_engine.preflight.return_value = preflight_ok

    first_record = MagicMock()
    first_record.task_id = "task-1"
    first_record.status = STATUS_RUNNING
    first_record.last_error = None

    call_count = [0]

    def _submit_and_start(_task_type, _book_id, **_kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return first_record
        raise RuntimeError("second submit failed")

    view._task_engine.submit_and_start.side_effect = _submit_and_start

    with patch("context_aware_translation.ui.views.translation_view.QMessageBox.warning") as warn_mock:
        view._start_translation()

    # First task was submitted successfully
    assert call_count[0] == 2
    # Warning shown for partial failure (second submit failed after first succeeded)
    warn_mock.assert_called_once()


def test_start_translation_skip_context_forwarded_to_submit():
    """skip_context checkbox value is forwarded to submit_and_start."""
    view = _make_view()
    view.book_id = "book-id"
    view._resolve_trigger_conditions = MagicMock(return_value=([1], False))
    view._has_document_reservation = MagicMock(return_value=False)
    view._split_doc_ids_by_type = MagicMock(return_value=([1], []))
    view.start_btn = QPushButton()
    view.doc_combo = QComboBox()
    view.skip_context_cb = QCheckBox()
    view.skip_context_cb.setChecked(True)
    view.status_label = MagicMock()

    preflight_ok = MagicMock()
    preflight_ok.allowed = True
    view._task_engine.preflight.return_value = preflight_ok

    submitted = MagicMock()
    submitted.task_id = "t1"
    submitted.status = STATUS_RUNNING
    submitted.last_error = None
    view._task_engine.submit_and_start.return_value = submitted

    view._start_translation()

    _, kwargs = view._task_engine.submit_and_start.call_args
    assert kwargs.get("skip_context") is True


# ------------------------------------------------------------------
# _update_start_button_state: preflight-based, unrelated tasks do not block
# ------------------------------------------------------------------


def test_update_start_button_state_enabled_when_preflight_allowed():
    """Start button is enabled when preflight returns allowed for selected bucket."""
    view = _make_view()
    view.book_id = "book-1"
    view.doc_combo = QComboBox()
    view.doc_combo.addItem("All Documents", None)
    view.doc_combo.addItem("Document 1", 1)
    view.start_btn = QPushButton()
    view.skip_context_cb = QCheckBox()
    view.submit_batch_btn = QPushButton()
    view._get_preflight_docs_with_pending_ocr = MagicMock(return_value=[])
    view._is_retranslation = MagicMock(return_value=False)
    view._split_doc_ids_by_type = MagicMock(return_value=([1], []))
    view._update_retranslate_chunk_button_state = MagicMock()

    preflight_ok = MagicMock()
    preflight_ok.allowed = True
    view._task_engine.preflight.return_value = preflight_ok

    with patch(
        "context_aware_translation.ui.views.translation_view.DocumentOperationTracker.has_document_overlap",
        return_value=False,
    ):
        view._update_start_button_state()

    assert view.start_btn.isEnabled()


def test_update_start_button_state_disabled_when_preflight_denied():
    """Start button is disabled when preflight is denied for all buckets."""
    view = _make_view()
    view.book_id = "book-1"
    view.doc_combo = QComboBox()
    view.doc_combo.addItem("All Documents", None)
    view.doc_combo.addItem("Document 1", 1)
    view.start_btn = QPushButton()
    view.skip_context_cb = QCheckBox()
    view.submit_batch_btn = QPushButton()
    view._get_preflight_docs_with_pending_ocr = MagicMock(return_value=[])
    view._is_retranslation = MagicMock(return_value=False)
    view._split_doc_ids_by_type = MagicMock(return_value=([1], []))
    view._update_retranslate_chunk_button_state = MagicMock()

    preflight_denied = MagicMock()
    preflight_denied.allowed = False
    preflight_denied.reason = "Task already running"
    view._task_engine.preflight.return_value = preflight_denied

    with patch(
        "context_aware_translation.ui.views.translation_view.DocumentOperationTracker.has_document_overlap",
        return_value=False,
    ):
        view._update_start_button_state()

    assert not view.start_btn.isEnabled()
    assert "Task already running" in view.start_btn.toolTip()


def test_update_start_button_state_unrelated_running_tasks_do_not_block_start():
    """Non-overlapping tasks on other books/types don't block start button via preflight."""
    view = _make_view()
    view.book_id = "book-1"
    view.doc_combo = QComboBox()
    view.doc_combo.addItem("All Documents", None)
    view.doc_combo.addItem("Document 5", 5)
    view.start_btn = QPushButton()
    view.skip_context_cb = QCheckBox()
    view.submit_batch_btn = QPushButton()
    view._get_preflight_docs_with_pending_ocr = MagicMock(return_value=[])
    view._is_retranslation = MagicMock(return_value=False)
    # text bucket only, no manga
    view._split_doc_ids_by_type = MagicMock(return_value=([5], []))
    view._update_retranslate_chunk_button_state = MagicMock()

    # Preflight allows translation_text for doc 5
    preflight_ok = MagicMock()
    preflight_ok.allowed = True
    view._task_engine.preflight.return_value = preflight_ok

    with patch(
        "context_aware_translation.ui.views.translation_view.DocumentOperationTracker.has_document_overlap",
        return_value=False,
    ):
        view._update_start_button_state()

    assert view.start_btn.isEnabled()


# ------------------------------------------------------------------
# TaskStatusStrip wired to translation task types
# ------------------------------------------------------------------


def test_task_status_strip_is_wired_to_translation_task_types():
    """_TRANSLATION_TASK_TYPES must include all four translation-related task types."""
    from context_aware_translation.ui.views.translation_view import _TRANSLATION_TASK_TYPES

    expected = {"translation_text", "translation_manga", "batch_translation", "chunk_retranslation"}
    assert set(_TRANSLATION_TASK_TYPES) == expected


def test_translation_view_has_open_activity_requested_signal():
    """TranslationView must expose open_activity_requested signal for workspace integration."""
    from context_aware_translation.ui.views.translation_view import TranslationView

    assert hasattr(TranslationView, "open_activity_requested")


def test_on_tasks_changed_triggers_update_start_button_state():
    """_on_tasks_changed calls _update_start_button_state for matching book_id."""
    view = _make_view()
    view._update_start_button_state = MagicMock()
    view._handle_chunk_retrans_task_update = MagicMock()

    view._on_tasks_changed("test-book")

    view._update_start_button_state.assert_called_once()
    view._handle_chunk_retrans_task_update.assert_called_once()


def test_on_tasks_changed_ignores_different_book_id():
    """_on_tasks_changed is a no-op when book_id does not match."""
    view = _make_view()
    view._update_start_button_state = MagicMock()
    view._handle_chunk_retrans_task_update = MagicMock()

    view._on_tasks_changed("other-book")

    view._update_start_button_state.assert_not_called()
    view._handle_chunk_retrans_task_update.assert_not_called()


# ------------------------------------------------------------------
# Batch translation still works via batch_translation
# ------------------------------------------------------------------


def test_submit_batch_task_submits_batch_translation():
    """_submit_batch_task still submits via batch_translation task type."""
    view = _make_view()
    view.book_id = "book-1"
    view._resolve_trigger_conditions = MagicMock(return_value=([1], False))
    view.skip_context_cb = QCheckBox()
    view.skip_context_cb.setChecked(False)

    view._submit_batch_task()

    view._task_engine.submit.assert_called_once_with(
        "batch_translation",
        "book-1",
        document_ids=[1],
        force=False,
        skip_context=False,
        enable_polish=True,
    )


# ------------------------------------------------------------------
# Retranslate chunk still works via chunk_retranslation
# ------------------------------------------------------------------


def test_retranslate_chunk_submits_chunk_retranslation():
    """_retranslate_current_chunk uses chunk_retranslation task type via submit_and_start."""
    from PySide6.QtWidgets import QMessageBox

    view = _make_view()
    view.book_id = "book-id"
    view._task_engine.get_tasks.return_value = []

    chunk = MagicMock()
    chunk.chunk_id = 7
    chunk.document_id = 2
    view._current_chunk = chunk
    view.skip_context_cb = QCheckBox()
    view.skip_context_cb.setChecked(False)
    view.retranslate_chunk_btn = QPushButton()

    submitted = MagicMock()
    submitted.task_id = "cr-1"
    submitted.status = STATUS_RUNNING
    submitted.last_error = None
    view._task_engine.submit_and_start.return_value = submitted

    with patch(
        "context_aware_translation.ui.views.translation_view.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        view._retranslate_current_chunk()

    view._task_engine.submit_and_start.assert_called_once_with(
        "chunk_retranslation",
        "book-id",
        chunk_id=7,
        document_id=2,
        skip_context=False,
        enable_polish=True,
    )
    assert "cr-1" in view._pending_retranslations


def test_retranslate_chunk_for_manga_submits_translation_manga():
    """Manga chunk retranslate routes through translation_manga with force=True."""
    from PySide6.QtWidgets import QMessageBox

    view = _make_view()
    view.book_id = "book-id"
    view._task_engine.get_tasks.return_value = []
    view.document_repo.get_document_by_id.return_value = {"document_type": "manga"}

    chunk = MagicMock()
    chunk.chunk_id = 7
    chunk.document_id = 2
    view._current_chunk = chunk
    view.skip_context_cb = QCheckBox()
    view.skip_context_cb.setChecked(False)
    view.retranslate_chunk_btn = QPushButton()

    preflight_ok = MagicMock()
    preflight_ok.allowed = True
    view._task_engine.preflight.return_value = preflight_ok

    submitted = MagicMock()
    submitted.task_id = "tm-rt-1"
    submitted.status = STATUS_RUNNING
    submitted.last_error = None
    view._task_engine.submit_and_start.return_value = submitted

    with patch(
        "context_aware_translation.ui.views.translation_view.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        view._retranslate_current_chunk()

    view._task_engine.submit_and_start.assert_called_once_with(
        "translation_manga",
        "book-id",
        document_ids=[2],
        force=True,
        skip_context=False,
        enable_polish=True,
    )
    assert "tm-rt-1" in view._pending_retranslations


def test_retranslate_chunk_allows_parallel_different_chunk_same_document():
    """Active retranslation on chunk A must not block submitting chunk B in the same doc."""
    from PySide6.QtWidgets import QMessageBox

    view = _make_view()
    view.book_id = "book-id"
    view._task_engine.get_tasks.return_value = []
    view.retranslate_chunk_btn = QPushButton()
    view.skip_context_cb = QCheckBox()
    view.skip_context_cb.setChecked(False)
    view._pending_retranslations = {"cr-1": (7, 2)}

    active_record = MagicMock()
    active_record.status = STATUS_RUNNING

    def _get_task(task_id: str):
        return active_record if task_id == "cr-1" else None

    view._task_engine.get_task.side_effect = _get_task

    chunk = MagicMock()
    chunk.chunk_id = 8
    chunk.document_id = 2
    view._current_chunk = chunk

    submitted = MagicMock()
    submitted.task_id = "cr-2"
    submitted.status = STATUS_RUNNING
    submitted.last_error = None
    view._task_engine.submit_and_start.return_value = submitted

    with patch(
        "context_aware_translation.ui.views.translation_view.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        view._retranslate_current_chunk()

    view._task_engine.submit_and_start.assert_called_once_with(
        "chunk_retranslation",
        "book-id",
        chunk_id=8,
        document_id=2,
        skip_context=False,
        enable_polish=True,
    )
    assert "cr-1" in view._pending_retranslations
    assert "cr-2" in view._pending_retranslations


def test_retranslate_chunk_blocks_duplicate_submit_for_same_chunk():
    """Submitting another retranslation for the exact same chunk is ignored."""
    view = _make_view()
    view.book_id = "book-id"
    view._task_engine.get_tasks.return_value = []
    view.retranslate_chunk_btn = QPushButton()
    view.skip_context_cb = QCheckBox()
    view.skip_context_cb.setChecked(False)
    view._pending_retranslations = {"cr-1": (7, 2)}

    active_record = MagicMock()
    active_record.status = STATUS_RUNNING

    def _get_task(task_id: str):
        return active_record if task_id == "cr-1" else None

    view._task_engine.get_task.side_effect = _get_task

    chunk = MagicMock()
    chunk.chunk_id = 7
    chunk.document_id = 2
    view._current_chunk = chunk

    with patch("context_aware_translation.ui.views.translation_view.QMessageBox.question") as question_mock:
        view._retranslate_current_chunk()

    question_mock.assert_not_called()
    view._task_engine.submit_and_start.assert_not_called()


# ------------------------------------------------------------------
# cleanup uses task_status_strip not task_console
# ------------------------------------------------------------------


def test_cleanup_calls_task_status_strip_cleanup():
    """cleanup() calls task_status_strip.cleanup(), not task_console.refresh."""
    view = _make_view()
    view.task_status_strip = MagicMock()
    view.term_db = MagicMock()

    view.cleanup()

    assert view._is_cleaned_up
    view.task_status_strip.cleanup.assert_called_once()
