"""Regression tests for TranslationView refresh behavior in review mode."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

try:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QMessageBox, QPushButton

    HAS_PYSIDE6 = True
except ImportError:
    HAS_PYSIDE6 = False

from context_aware_translation.workflow.tasks.models import (
    STATUS_CANCELLED,
    STATUS_COMPLETED,
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
    # Set attributes normally created in __init__ that production code accesses directly.
    view._is_cleaned_up = False
    view._task_engine = MagicMock()
    view._task_engine.get_task.return_value = None
    view.task_console = MagicMock()
    view._sync_task_id = None
    view._pending_retranslations = {}
    view._emitted_sync_translation_done = set()
    view.book_id = "test-book"
    view.book_manager = _make_book_manager()
    view.term_db = MagicMock()
    return view


def test_refresh_reloads_review_content_when_review_page_is_active():
    view = _make_view()
    review_page = object()
    view.review_page = review_page
    view.stack = MagicMock()
    view.stack.currentWidget.return_value = review_page
    view.review_doc_combo = MagicMock()
    view.review_doc_combo.currentIndex.return_value = 2
    view._is_cleaned_up = False
    view._document_type_cache = {123: "manga"}
    view._refresh_document_selector = MagicMock()
    view._refresh_review_document_selector = MagicMock()
    view._update_stats = MagicMock()
    view._on_review_document_changed = MagicMock()

    view.refresh()

    assert view._document_type_cache == {}
    view._on_review_document_changed.assert_called_once_with(2)
    view.task_console.refresh.assert_called_once()


def test_refresh_does_not_reload_review_content_when_progress_page_is_active():
    view = _make_view()
    view.review_page = object()
    view.stack = MagicMock()
    view.stack.currentWidget.return_value = object()
    view.review_doc_combo = MagicMock()
    view._document_type_cache = {}
    view._refresh_document_selector = MagicMock()
    view._refresh_review_document_selector = MagicMock()
    view._update_stats = MagicMock()
    view._on_review_document_changed = MagicMock()

    view.refresh()

    view._on_review_document_changed.assert_not_called()
    view.task_console.refresh.assert_called_once()


def test_load_chunks_list_clears_selection_when_no_chunks():
    view = _make_view()
    view.chunk_list = MagicMock()
    view.chunk_list.count.return_value = 0
    view.term_db = MagicMock()
    view.term_db.list_chunks.return_value = []
    view._get_review_document_id = MagicMock(return_value=1)
    view._on_chunk_selected = MagicMock()

    view._load_chunks_list()

    view._on_chunk_selected.assert_called_once_with(-1)


def test_on_chunk_selected_negative_row_disables_navigation():
    view = _make_view()
    view._current_chunk = object()
    view.original_text = MagicMock()
    view.translation_text = MagicMock()
    view.prev_btn = MagicMock()
    view.next_btn = MagicMock()

    view._on_chunk_selected(-1)

    assert view._current_chunk is None
    view.prev_btn.setEnabled.assert_called_once_with(False)
    view.next_btn.setEnabled.assert_called_once_with(False)


def test_apply_button_tooltips_sets_hover_explanations():
    view = _make_view()
    view.start_btn = QPushButton()
    view.skip_context_cb = QCheckBox()
    view.review_btn = QPushButton()
    view.back_btn = QPushButton()
    view.save_chunk_btn = QPushButton()
    view.retranslate_chunk_btn = QPushButton()
    view.prev_btn = QPushButton()
    view.next_btn = QPushButton()

    view._apply_button_tooltips()

    buttons = [
        ("start", view.start_btn),
        ("skip_context", view.skip_context_cb),
        ("review", view.review_btn),
        ("back", view.back_btn),
        ("save", view.save_chunk_btn),
        ("retranslate", view.retranslate_chunk_btn),
        ("prev", view.prev_btn),
        ("next", view.next_btn),
    ]
    missing = [name for name, button in buttons if not button.toolTip().strip()]
    assert missing == []


def test_start_translation_forwards_skip_context_to_engine():
    view = _make_view()
    view.book_manager = _make_book_manager()
    view.book_id = "book-id"
    view._resolve_trigger_conditions = MagicMock(return_value=([1], False))
    view._has_document_reservation = MagicMock(return_value=False)
    view.start_btn = QPushButton()
    view.doc_combo = QComboBox()
    view.skip_context_cb = QCheckBox()
    view.skip_context_cb.setChecked(True)
    view.status_label = MagicMock()

    preflight_decision = MagicMock()
    preflight_decision.allowed = True
    view._task_engine.preflight.return_value = preflight_decision

    submitted_record = MagicMock()
    submitted_record.task_id = "task-1"
    submitted_record.status = "running"
    submitted_record.last_error = None
    view._task_engine.submit.return_value = submitted_record

    view._start_translation()

    view._resolve_trigger_conditions.assert_called_once_with(for_batch_submit=False)
    view._task_engine.submit.assert_called_once_with(
        "sync_translation",
        "book-id",
        document_ids=[1],
        force=False,
        skip_context=True,
    )
    assert view._sync_task_id == "task-1"


def test_submit_batch_task_returns_when_sync_translation_running():
    from context_aware_translation.workflow.tasks.models import STATUS_RUNNING

    view = _make_view()
    # Simulate a running sync_translation task
    view._sync_task_id = "task-running"
    running_record = MagicMock()
    running_record.status = STATUS_RUNNING
    view._task_engine.get_task.return_value = running_record
    view._get_preflight_docs_with_pending_ocr = MagicMock(return_value=[])

    view._submit_batch_task()

    view._get_preflight_docs_with_pending_ocr.assert_not_called()


def test_submit_batch_task_does_not_require_translated_glossary_terms():
    view = _make_view()
    view.term_db = MagicMock()
    view.term_db.list_terms.return_value = [MagicMock()]
    view._resolve_trigger_conditions = MagicMock(return_value=([1], False))
    view.skip_context_cb = QCheckBox()
    view.skip_context_cb.setChecked(False)
    view.book_manager = _make_book_manager()
    view.book_id = "book-id"

    view._submit_batch_task()

    view._resolve_trigger_conditions.assert_called_once_with(for_batch_submit=True)
    view._task_engine.submit.assert_called_once_with(
        "batch_translation", "book-id", document_ids=[1], force=False, skip_context=False
    )
    view.term_db.list_terms.assert_not_called()


def test_submit_batch_task_returns_when_trigger_conditions_fail():
    view = _make_view()
    view._resolve_trigger_conditions = MagicMock(return_value=None)
    view.book_manager = _make_book_manager()
    view.book_id = "book-id"

    view._submit_batch_task()

    view._resolve_trigger_conditions.assert_called_once_with(for_batch_submit=True)
    view._task_engine.submit.assert_not_called()


def test_submit_batch_task_calls_engine_submit_with_correct_args():
    view = _make_view()
    view.book_id = "book-1"
    view._resolve_trigger_conditions = MagicMock(return_value=([2, 3], True))
    view.skip_context_cb = QCheckBox()
    view.skip_context_cb.setChecked(True)

    view._submit_batch_task()

    view._task_engine.submit.assert_called_once_with(
        "batch_translation", "book-1", document_ids=[2, 3], force=True, skip_context=True
    )


def test_update_retranslate_chunk_button_state_disables_retranslate_when_batch_tasks_active():
    view = _make_view()
    view.retranslate_chunk_btn = QPushButton()
    view._current_chunk = MagicMock()
    view._task_engine.get_tasks.return_value = [MagicMock(status="running", document_ids_json=None)]

    view._update_retranslate_chunk_button_state()

    assert not view.retranslate_chunk_btn.isEnabled()
    assert "batch task covers this document" in view.retranslate_chunk_btn.toolTip()


def test_update_retranslate_chunk_button_state_enables_retranslate_when_only_terminal_tasks():
    view = _make_view()
    view.retranslate_chunk_btn = QPushButton()
    view._current_chunk = MagicMock()
    view._task_engine.get_tasks.return_value = [
        MagicMock(status=STATUS_COMPLETED, document_ids_json=None),
        MagicMock(status=STATUS_CANCELLED, document_ids_json=None),
    ]

    view._update_retranslate_chunk_button_state()

    assert view.retranslate_chunk_btn.isEnabled()


def test_update_retranslate_chunk_button_state_disables_when_selected_doc_has_active_operation():
    view = _make_view()
    view.book_id = "book-1"
    view.retranslate_chunk_btn = QPushButton()
    view._current_chunk = MagicMock(document_id=1)
    view._task_engine.get_tasks.return_value = []

    with patch(
        "context_aware_translation.ui.views.translation_view.DocumentOperationTracker.has_document_overlap",
        return_value=True,
    ):
        view._update_retranslate_chunk_button_state()

    assert not view.retranslate_chunk_btn.isEnabled()
    assert "selected document has an active operation" in view.retranslate_chunk_btn.toolTip()


def test_retranslate_current_chunk_blocks_when_batch_tasks_active():
    view = _make_view()
    view._task_engine.get_tasks.return_value = [MagicMock(status="running", document_ids_json=None)]
    view._current_chunk = MagicMock()
    view.book_manager = _make_book_manager()
    view.book_id = "book-id"

    with (
        patch("context_aware_translation.ui.views.translation_view.QMessageBox.information") as info_mock,
        patch("context_aware_translation.ui.views.translation_view.QMessageBox.question") as question_mock,
    ):
        view._retranslate_current_chunk()

    info_mock.assert_called_once()
    question_mock.assert_not_called()
    view._task_engine.submit_and_start.assert_not_called()


def test_update_start_button_state_disables_retranslate_when_doc_has_active_operation():
    view = _make_view()
    view.book_id = "book-1"
    view.book_manager = _make_book_manager()
    view.book_manager.get_book_config.return_value = {}
    view.submit_batch_btn = QPushButton()
    view.doc_combo = QComboBox()
    view.doc_combo.addItem("All Documents", None)
    view.doc_combo.addItem("Document 1", 1)
    view.start_btn = QPushButton()
    view.skip_context_cb = QCheckBox()
    view._get_preflight_docs_with_pending_ocr = MagicMock(return_value=[])
    view._is_retranslation = MagicMock(return_value=True)

    with patch(
        "context_aware_translation.ui.views.translation_view.DocumentOperationTracker.has_document_overlap",
        return_value=True,
    ):
        view._update_start_button_state()

    assert not view.start_btn.isEnabled()
    assert "delete overlapping task(s) to unblock" in view.start_btn.toolTip()


def test_resolve_trigger_conditions_blocks_retranslate_when_batch_tasks_active():
    view = _make_view()
    view._get_preflight_docs_with_pending_ocr = MagicMock(return_value=[])
    view._get_selected_document_ids = MagicMock(return_value=[1])
    view._has_manga_documents = MagicMock(return_value=False)
    view.book_manager = _make_book_manager()
    view.book_manager.get_book_config.return_value = {}
    view.book_id = "book-id"
    view._is_retranslation = MagicMock(return_value=True)
    view._task_engine.get_tasks.return_value = [MagicMock(status="running", document_ids_json=None)]

    with (
        patch("context_aware_translation.ui.views.translation_view.QMessageBox.information") as info_mock,
        patch("context_aware_translation.ui.views.translation_view.QMessageBox.question") as question_mock,
    ):
        resolved = view._resolve_trigger_conditions(for_batch_submit=False)

    assert resolved is None
    info_mock.assert_called_once()
    question_mock.assert_not_called()


def test_update_start_button_state_disables_start_when_ocr_pending():
    view = _make_view()
    view.doc_combo = QComboBox()
    view.doc_combo.addItem("All Documents", None)
    view.doc_combo.addItem("Document 1", 1)
    view.start_btn = QPushButton()
    view.skip_context_cb = QCheckBox()
    view._get_preflight_docs_with_pending_ocr = MagicMock(return_value=[1])
    view._is_retranslation = MagicMock(return_value=False)

    with patch(
        "context_aware_translation.ui.views.translation_view.DocumentOperationTracker.has_document_overlap",
        return_value=False,
    ):
        view._update_start_button_state()

    assert not view.start_btn.isEnabled()
    assert "OCR is pending" in view.start_btn.toolTip()


def test_get_preflight_docs_with_pending_ocr_ignores_non_ocr_required_doc_types():
    view = _make_view()
    view.doc_combo = QComboBox()
    view.doc_combo.addItem("All Documents", None)
    view.doc_combo.addItem("Document 1", 1)
    view.doc_combo.setCurrentIndex(0)
    view.document_repo = MagicMock()
    view.document_repo.list_documents.return_value = [{"document_id": 1}, {"document_id": 2}]
    view.document_repo.get_documents_with_status.return_value = [
        {"document_id": 1, "document_type": "text", "ocr_pending": 5},
        {"document_id": 2, "document_type": "epub", "ocr_pending": 7},
    ]

    pending = view._get_preflight_docs_with_pending_ocr()

    assert pending == []


def test_get_preflight_document_ids_for_text_selection_does_not_include_earlier_pdf():
    view = _make_view()
    view.doc_combo = QComboBox()
    view.doc_combo.addItem("All Documents", None)
    view.doc_combo.addItem("Document 2", 2)
    view.doc_combo.setCurrentIndex(1)
    view.document_repo = MagicMock()
    view.document_repo.list_documents.return_value = [
        {"document_id": 1, "document_type": "pdf"},
        {"document_id": 2, "document_type": "text"},
        {"document_id": 3, "document_type": "text"},
    ]

    preflight = view._get_preflight_document_ids()

    assert preflight == [2]


def test_get_preflight_docs_with_pending_ocr_ignores_earlier_pdf_for_text_selection():
    view = _make_view()
    view.doc_combo = QComboBox()
    view.doc_combo.addItem("All Documents", None)
    view.doc_combo.addItem("Document 2", 2)
    view.doc_combo.setCurrentIndex(1)
    view.document_repo = MagicMock()
    view.document_repo.list_documents.return_value = [
        {"document_id": 1, "document_type": "pdf"},
        {"document_id": 2, "document_type": "text"},
    ]
    view.document_repo.get_documents_with_status.return_value = [
        {"document_id": 1, "document_type": "pdf", "ocr_pending": 2},
        {"document_id": 2, "document_type": "text", "ocr_pending": 0},
    ]

    pending = view._get_preflight_docs_with_pending_ocr()

    assert pending == []


def test_populate_documents_translates_document_type_in_labels():
    view = _make_view()
    view.doc_combo = QComboBox()
    view.document_repo = MagicMock()
    view.document_repo.list_documents.return_value = [{"document_id": 3, "document_type": "scanned_book"}]
    view.document_repo.get_documents_with_status.return_value = [
        {"document_id": 3, "total_chunks": 10, "chunks_translated": 0, "ocr_pending": 0}
    ]

    view._populate_documents()

    assert view.doc_combo.count() == 1
    text = view.doc_combo.itemText(0)
    assert view.doc_combo.itemData(0) == 3
    assert QCoreApplication.translate("ExportView", "Scanned Book") in text
    assert "scanned_book" not in text


def test_populate_review_documents_translates_document_type_in_labels():
    view = _make_view()
    view.review_doc_combo = QComboBox()
    view.document_repo = MagicMock()
    view.document_repo.list_documents.return_value = [{"document_id": 4, "document_type": "scanned_book"}]

    view._populate_review_documents()

    assert view.review_doc_combo.count() == 1
    text = view.review_doc_combo.itemText(0)
    assert view.review_doc_combo.itemData(0) == 4
    assert QCoreApplication.translate("ExportView", "Scanned Book") in text
    assert "scanned_book" not in text


# ------------------------------------------------------------------
# _pending_retranslations cleanup tests
# ------------------------------------------------------------------


def test_handle_chunk_retrans_clears_terminal_task_from_pending():
    """Terminal chunk tasks are removed from _pending_retranslations."""
    from context_aware_translation.workflow.tasks.models import STATUS_COMPLETED

    view = _make_view()
    completed_record = MagicMock()
    completed_record.task_id = "chunk-task-1"
    completed_record.status = STATUS_COMPLETED
    completed_record.payload_json = None
    completed_record.last_error = None
    view._task_engine.get_task.return_value = completed_record

    view._pending_retranslations = {"chunk-task-1": (3, 7)}
    view._on_retranslate_success = MagicMock()
    view._on_retranslate_error = MagicMock()
    view._on_retranslate_finished = MagicMock()

    view._handle_chunk_retrans_task_update()

    assert "chunk-task-1" not in view._pending_retranslations
    view._on_retranslate_finished.assert_called_once()


def test_handle_chunk_retrans_removes_deleted_task_from_pending():
    """Tasks deleted from store are removed from _pending_retranslations."""
    view = _make_view()
    view._task_engine.get_task.return_value = None  # task was deleted

    view._pending_retranslations = {"chunk-task-deleted": (5, 9)}
    view._on_retranslate_finished = MagicMock()

    view._handle_chunk_retrans_task_update()

    assert "chunk-task-deleted" not in view._pending_retranslations
    view._on_retranslate_finished.assert_called_once()


def test_handle_chunk_retrans_keeps_non_terminal_task_in_pending():
    """Non-terminal chunk tasks remain in _pending_retranslations."""
    from context_aware_translation.workflow.tasks.models import STATUS_RUNNING

    view = _make_view()
    running_record = MagicMock()
    running_record.task_id = "chunk-running"
    running_record.status = STATUS_RUNNING
    view._task_engine.get_task.return_value = running_record

    view._pending_retranslations = {"chunk-running": (2, 4)}
    view._on_retranslate_finished = MagicMock()

    view._handle_chunk_retrans_task_update()

    assert "chunk-running" in view._pending_retranslations
    view._on_retranslate_finished.assert_not_called()


# ------------------------------------------------------------------
# translation_completed dedupe test
# ------------------------------------------------------------------


def test_translation_completed_emitted_only_once_per_task_terminal_transition():
    """translation_completed signal emitted once per task_id terminal transition (dedupe via set)."""
    from context_aware_translation.workflow.tasks.models import STATUS_COMPLETED

    view = _make_view()
    completed_record = MagicMock()
    completed_record.task_id = "sync-task-dedupe"
    completed_record.status = STATUS_COMPLETED
    completed_record.last_error = None
    view._task_engine.get_task.return_value = completed_record
    view._task_engine.get_tasks.return_value = [completed_record]

    view._sync_task_id = "sync-task-dedupe"
    view._on_sync_task_finished = MagicMock()
    success_calls: list[object] = []
    view._on_translation_success = MagicMock(side_effect=lambda r: success_calls.append(r))

    # First call — should call _on_translation_success and add to emitted set
    view._handle_sync_task_update()
    # _sync_task_id is now None — second call is a no-op
    view._handle_sync_task_update()

    # _on_translation_success called exactly once
    assert len(success_calls) == 1
    # ID is tracked in emitted set
    assert "sync-task-dedupe" in view._emitted_sync_translation_done


# ------------------------------------------------------------------
# _retranslate_current_chunk wiring test
# ------------------------------------------------------------------


def test_retranslate_current_chunk_uses_strict_submit_and_tracks_task():
    """_retranslate_current_chunk uses submit_and_start and tracks task_id in _pending_retranslations."""
    view = _make_view()
    view.book_id = "book-id"
    view._task_engine.get_tasks.return_value = []  # no batch tasks blocking

    chunk = MagicMock()
    chunk.chunk_id = 5
    chunk.document_id = 3
    view._current_chunk = chunk
    view.skip_context_cb = QCheckBox()
    view.skip_context_cb.setChecked(False)
    view.retranslate_chunk_btn = QPushButton()

    submitted_record = MagicMock()
    submitted_record.task_id = "chunk-task-new"
    submitted_record.status = "running"
    submitted_record.last_error = None
    view._task_engine.submit_and_start.return_value = submitted_record

    with (
        patch("context_aware_translation.ui.views.translation_view.QMessageBox.question",
              return_value=QMessageBox.StandardButton.Yes),
    ):
        view._retranslate_current_chunk()

    view._task_engine.submit_and_start.assert_called_once_with(
        "chunk_retranslation",
        "book-id",
        chunk_id=5,
        document_id=3,
        skip_context=False,
    )
    assert "chunk-task-new" in view._pending_retranslations
    assert view._pending_retranslations["chunk-task-new"] == (5, 3)
