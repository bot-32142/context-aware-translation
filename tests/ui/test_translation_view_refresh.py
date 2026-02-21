"""Regression tests for TranslationView refresh behavior in review mode."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

try:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QPushButton

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


def _noop_init(self, *_args, **_kwargs):  # noqa: ANN001
    """No-op replacement for TranslationView.__init__."""


def _make_view():
    from context_aware_translation.ui.views.translation_view import TranslationView

    with patch.object(TranslationView, "__init__", _noop_init):
        view = TranslationView(None, "")
    return view


def test_refresh_reloads_review_content_when_review_page_is_active():
    view = _make_view()
    review_page = object()
    view.review_page = review_page
    view.stack = MagicMock()
    view.stack.currentWidget.return_value = review_page
    view.review_doc_combo = MagicMock()
    view.review_doc_combo.currentIndex.return_value = 2
    view._document_type_cache = {123: "manga"}
    view._refresh_document_selector = MagicMock()
    view._refresh_review_document_selector = MagicMock()
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
    view.book_manager = MagicMock()
    view.book_id = "book-id"
    view.term_db = MagicMock()
    view.term_db.list_terms.return_value = []
    view._get_preflight_docs_with_pending_ocr = MagicMock(return_value=[])
    view._get_selected_document_ids = MagicMock(return_value=[1])
    view._has_manga_documents = MagicMock(return_value=False)
    view._is_retranslation = MagicMock(return_value=False)
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

    assert cls.call_count == 1
    assert cls.call_args.kwargs.get("skip_context") is True
    worker_instance.start.assert_called_once()


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
