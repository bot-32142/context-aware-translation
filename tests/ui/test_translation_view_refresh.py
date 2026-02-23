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

from context_aware_translation.storage.translation_batch_task_store import (
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
    view._batch_tasks_cache = []
    view._batch_task_store = MagicMock()
    view.worker = None
    view.retranslate_worker = None
    view.batch_task_worker = None
    view._active_batch_task_id = None
    view._batch_auto_timer = None
    view.book_id = "test-book"
    view.book_manager = _make_book_manager()
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
    view._refresh_batch_tasks = MagicMock()
    view._update_stats = MagicMock()
    view._on_review_document_changed = MagicMock()

    view.refresh()

    assert view._document_type_cache == {}
    view._on_review_document_changed.assert_called_once_with(2)


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


def test_start_translation_forwards_skip_context_to_worker():
    view = _make_view()
    view.worker = None
    view.book_manager = _make_book_manager()
    view.book_id = "book-id"
    view._resolve_trigger_conditions = MagicMock(return_value=([1], False))
    view.start_btn = QPushButton()
    view.doc_combo = QComboBox()
    view.skip_context_cb = QCheckBox()
    view.skip_context_cb.setChecked(True)
    view.status_label = MagicMock()
    view.progress_widget = MagicMock()

    worker_instance = MagicMock()
    worker_instance.progress = MagicMock()
    worker_instance.finished_success = MagicMock()
    worker_instance.cancelled = MagicMock()
    worker_instance.error = MagicMock()
    worker_instance.finished = MagicMock()

    with patch(
        "context_aware_translation.ui.views.translation_view.TranslationWorker", return_value=worker_instance
    ) as cls:
        view._start_translation()

    view._resolve_trigger_conditions.assert_called_once_with(for_batch_submit=False)
    assert cls.call_count == 1
    assert cls.call_args.kwargs.get("skip_context") is True
    worker_instance.start.assert_called_once()


def test_submit_batch_task_returns_when_translation_worker_running():
    class _RunningWorker:
        def isRunning(self) -> bool:  # noqa: N802
            return True

    view = _make_view()
    view.worker = _RunningWorker()
    view.batch_task_worker = None
    view._get_preflight_docs_with_pending_ocr = MagicMock(return_value=[])

    view._submit_batch_task()

    view._get_preflight_docs_with_pending_ocr.assert_not_called()


def test_submit_batch_task_does_not_require_translated_glossary_terms():
    view = _make_view()
    view.worker = None
    view.batch_task_worker = None
    view.term_db = MagicMock()
    view.term_db.list_terms.return_value = [MagicMock()]
    view._resolve_trigger_conditions = MagicMock(return_value=([1], False))
    view.skip_context_cb = QCheckBox()
    view.skip_context_cb.setChecked(False)
    view._start_batch_task_worker = MagicMock()
    view.book_manager = _make_book_manager()
    view.book_id = "book-id"

    worker_instance = MagicMock()
    with patch(
        "context_aware_translation.ui.views.translation_view.BatchTranslationTaskWorker",
        return_value=worker_instance,
    ) as worker_cls:
        view._submit_batch_task()

    view._resolve_trigger_conditions.assert_called_once_with(for_batch_submit=True)
    worker_cls.assert_called_once()
    view._start_batch_task_worker.assert_called_once_with(worker_instance)
    view.term_db.list_terms.assert_not_called()


def test_submit_batch_task_returns_when_trigger_conditions_fail():
    view = _make_view()
    view.worker = None
    view.batch_task_worker = None
    view._resolve_trigger_conditions = MagicMock(return_value=None)
    view._start_batch_task_worker = MagicMock()
    view.book_manager = _make_book_manager()
    view.book_id = "book-id"

    with patch("context_aware_translation.ui.views.translation_view.BatchTranslationTaskWorker") as worker_cls:
        view._submit_batch_task()

    view._resolve_trigger_conditions.assert_called_once_with(for_batch_submit=True)
    worker_cls.assert_not_called()
    view._start_batch_task_worker.assert_not_called()


def test_run_selected_batch_task_returns_when_translation_worker_running():
    class _RunningWorker:
        def isRunning(self) -> bool:  # noqa: N802
            return True

    view = _make_view()
    view.worker = _RunningWorker()
    view.batch_task_worker = None
    view._selected_batch_task_id = MagicMock(return_value="task-1")
    view._start_batch_task_worker = MagicMock()

    view._run_selected_batch_task()

    view._selected_batch_task_id.assert_not_called()
    view._start_batch_task_worker.assert_not_called()


def test_run_selected_batch_task_blocks_when_docs_overlap_other_task_reservation():
    view = _make_view()
    view.worker = None
    view.batch_task_worker = None
    view._selected_batch_task_id = MagicMock(return_value="task-1")
    view._start_batch_task_worker = MagicMock()
    view.batch_status_label = MagicMock()
    view._batch_task_store.get.return_value = MagicMock(document_ids_json="[1]")

    with (
        patch(
            "context_aware_translation.ui.views.translation_view.DocumentOperationTracker.has_document_overlap",
            return_value=False,
        ),
        patch("context_aware_translation.ui.views.translation_view.has_any_batch_task_overlap", return_value=True),
    ):
        view._run_selected_batch_task()

    view._start_batch_task_worker.assert_not_called()
    view.batch_status_label.setText.assert_called_once_with(
        "Selected task's documents are reserved by active operations or overlapping tasks."
    )


def test_start_batch_task_worker_blocks_duplicate_run_worker_for_same_book():
    view = _make_view()
    view.book_id = "book-1"
    view.batch_status_label = MagicMock()
    view.submit_batch_btn = MagicMock()
    view.run_batch_task_btn = MagicMock()
    view.cancel_batch_task_btn = MagicMock()
    view.delete_batch_task_btn = MagicMock()
    view.start_btn = MagicMock()
    worker = MagicMock()
    worker.action = "run"
    worker.task_id = "task-1"
    worker.document_ids = None

    with patch(
        "context_aware_translation.ui.views.translation_view.DocumentOperationTracker.has_document_overlap",
        return_value=True,
    ):
        view._start_batch_task_worker(worker)

    assert view.batch_task_worker is None
    worker.start.assert_not_called()
    view.batch_status_label.setText.assert_called_once_with(view.tr("Selected documents have active operations."))


def test_cancel_selected_batch_task_returns_when_translation_worker_running():
    class _RunningWorker:
        def isRunning(self) -> bool:  # noqa: N802
            return True

    view = _make_view()
    view.worker = _RunningWorker()
    view.batch_task_worker = None
    view._selected_batch_task_id = MagicMock(return_value="task-1")
    view._start_batch_task_worker = MagicMock()

    view._cancel_selected_batch_task()

    view._selected_batch_task_id.assert_not_called()
    view._start_batch_task_worker.assert_not_called()


def test_cancel_selected_batch_task_marks_cancel_requested_for_active_run_worker():
    class _RunningWorker:
        def isRunning(self) -> bool:  # noqa: N802
            return True

    view = _make_view()
    view.worker = None
    view.batch_task_worker = _RunningWorker()
    view._active_batch_task_id = "task-1"
    view._selected_batch_task_id = MagicMock(return_value="task-1")
    view.batch_status_label = MagicMock()
    view._refresh_batch_tasks = MagicMock()
    view._start_batch_task_worker = MagicMock()

    view._cancel_selected_batch_task()

    view._batch_task_store.mark_cancel_requested.assert_called_once_with("task-1")
    view._start_batch_task_worker.assert_not_called()


def test_cancel_selected_batch_task_skips_terminal_task_for_active_run_worker():
    class _RunningWorker:
        def isRunning(self) -> bool:  # noqa: N802
            return True

    view = _make_view()
    view.worker = None
    view.batch_task_worker = _RunningWorker()
    view._active_batch_task_id = "task-1"
    view._selected_batch_task_id = MagicMock(return_value="task-1")
    view.batch_status_label = MagicMock()
    view._refresh_batch_tasks = MagicMock()
    view._start_batch_task_worker = MagicMock()
    view._batch_task_store.get.return_value = MagicMock(status=STATUS_COMPLETED)

    view._cancel_selected_batch_task()

    view._batch_task_store.get.assert_called_once_with("task-1")
    view._batch_task_store.mark_cancel_requested.assert_not_called()
    view._refresh_batch_tasks.assert_called_once()
    view._start_batch_task_worker.assert_not_called()


def test_update_retranslate_chunk_button_state_disables_retranslate_when_batch_tasks_active():
    view = _make_view()
    view.retranslate_chunk_btn = QPushButton()
    view._current_chunk = MagicMock()
    view._batch_tasks_cache = [MagicMock(status="running")]
    view.retranslate_worker = None

    view._update_retranslate_chunk_button_state()

    assert not view.retranslate_chunk_btn.isEnabled()
    assert "async batch tasks are active" in view.retranslate_chunk_btn.toolTip()


def test_update_retranslate_chunk_button_state_enables_retranslate_when_only_terminal_tasks():
    view = _make_view()
    view.retranslate_chunk_btn = QPushButton()
    view._current_chunk = MagicMock()
    view._batch_tasks_cache = [MagicMock(status=STATUS_COMPLETED), MagicMock(status=STATUS_CANCELLED)]
    view.retranslate_worker = None

    view._update_retranslate_chunk_button_state()

    assert view.retranslate_chunk_btn.isEnabled()


def test_update_retranslate_chunk_button_state_disables_when_selected_doc_has_active_operation():
    view = _make_view()
    view.book_id = "book-1"
    view.retranslate_chunk_btn = QPushButton()
    view._current_chunk = MagicMock(document_id=1)
    view._batch_tasks_cache = []
    view.retranslate_worker = None

    with patch(
        "context_aware_translation.ui.views.translation_view.DocumentOperationTracker.has_document_overlap",
        return_value=True,
    ):
        view._update_retranslate_chunk_button_state()

    assert not view.retranslate_chunk_btn.isEnabled()
    assert "selected document has an active operation" in view.retranslate_chunk_btn.toolTip()


def test_retranslate_current_chunk_blocks_when_batch_tasks_active():
    view = _make_view()
    view._batch_tasks_cache = [MagicMock(status="running")]
    view._current_chunk = MagicMock()
    view.retranslate_worker = None
    view.book_manager = _make_book_manager()
    view.book_id = "book-id"

    with (
        patch("context_aware_translation.ui.views.translation_view.QMessageBox.information") as info_mock,
        patch("context_aware_translation.ui.views.translation_view.RetranslateChunkWorker") as worker_cls,
        patch("context_aware_translation.ui.views.translation_view.QMessageBox.question") as question_mock,
    ):
        view._retranslate_current_chunk()

    info_mock.assert_called_once()
    worker_cls.assert_not_called()
    question_mock.assert_not_called()


def test_batch_task_success_callback_noops_after_cleanup():
    view = _make_view()
    view._is_cleaned_up = True
    view.batch_status_label = MagicMock()
    view._refresh_batch_tasks = MagicMock()
    view._update_stats = MagicMock()
    view._refresh_document_selector = MagicMock()
    view._refresh_review_document_selector = MagicMock()

    view._on_batch_task_success({"action": "run", "task": {"status": "failed"}})

    view.batch_status_label.setText.assert_not_called()
    view._refresh_batch_tasks.assert_not_called()
    view._update_stats.assert_not_called()


def test_batch_task_delete_success_shows_remote_cleanup_warning():
    view = _make_view()
    view._is_cleaned_up = False
    view.batch_status_label = MagicMock()
    view._refresh_batch_tasks = MagicMock()
    view._update_stats = MagicMock()
    view._refresh_document_selector = MagicMock()
    view._refresh_review_document_selector = MagicMock()

    view._on_batch_task_success(
        {
            "action": "delete",
            "cleanup_warnings": ["Failed to delete remote batch 'batches/1': RuntimeError: boom"],
        }
    )

    view.batch_status_label.setText.assert_called_once_with(
        "Batch task deleted locally; remote cleanup completed with warnings."
    )


def test_batch_task_finished_callback_noops_after_cleanup():
    view = _make_view()
    view._is_cleaned_up = True
    view.batch_task_worker = MagicMock()
    view._active_batch_task_id = "task-1"
    view._refresh_batch_tasks = MagicMock()
    view._on_batch_task_selected = MagicMock()
    view._update_start_button_state = MagicMock()
    view.submit_batch_btn = MagicMock()
    view.batch_task_list = MagicMock()

    view._on_batch_task_finished()

    assert view.batch_task_worker is None
    assert view._active_batch_task_id is None
    view._refresh_batch_tasks.assert_not_called()
    view._update_start_button_state.assert_not_called()


def test_delete_selected_batch_task_returns_when_translation_worker_running():
    class _RunningWorker:
        def isRunning(self) -> bool:  # noqa: N802
            return True

    view = _make_view()
    view.worker = _RunningWorker()
    view.batch_task_worker = None
    view._selected_batch_task_id = MagicMock(return_value="task-1")
    view._start_batch_task_worker = MagicMock()

    view._delete_selected_batch_task()

    view._selected_batch_task_id.assert_not_called()
    view._start_batch_task_worker.assert_not_called()


def test_delete_selected_batch_task_starts_worker_after_confirmation():
    view = _make_view()
    view.worker = None
    view.batch_task_worker = None
    view._selected_batch_task_id = MagicMock(return_value="task-1")
    view._start_batch_task_worker = MagicMock()
    view.book_manager = _make_book_manager()
    view.book_id = "book-id"

    worker_instance = MagicMock()
    with (
        patch(
            "context_aware_translation.ui.views.translation_view.BatchTranslationTaskWorker",
            return_value=worker_instance,
        ) as worker_cls,
        patch(
            "context_aware_translation.ui.views.translation_view.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ),
    ):
        view._delete_selected_batch_task()

    worker_cls.assert_called_once()
    assert worker_cls.call_args.kwargs["action"] == "delete"
    assert worker_cls.call_args.kwargs["task_id"] == "task-1"
    view._start_batch_task_worker.assert_called_once_with(worker_instance)


def test_update_start_button_state_disables_retranslate_when_batch_tasks_active():
    view = _make_view()
    view.worker = None
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
    view._batch_tasks_cache = [MagicMock(status="running")]

    with (
        patch(
            "context_aware_translation.ui.views.translation_view.DocumentOperationTracker.has_document_overlap",
            return_value=False,
        ),
        patch(
            "context_aware_translation.ui.views.translation_view.has_any_batch_task_overlap",
            return_value=True,
        ),
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
    view._batch_tasks_cache = [MagicMock(status="running")]

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
    view.worker = None
    view.doc_combo = QComboBox()
    view.doc_combo.addItem("All Documents", None)
    view.doc_combo.addItem("Document 1", 1)
    view.start_btn = QPushButton()
    view.skip_context_cb = QCheckBox()
    view._get_preflight_docs_with_pending_ocr = MagicMock(return_value=[1])
    view._is_retranslation = MagicMock(return_value=False)

    with (
        patch(
            "context_aware_translation.ui.views.translation_view.DocumentOperationTracker.has_document_overlap",
            return_value=False,
        ),
        patch(
            "context_aware_translation.ui.views.translation_view.has_any_batch_task_overlap",
            return_value=False,
        ),
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
