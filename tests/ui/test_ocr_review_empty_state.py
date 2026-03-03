"""Regression tests for OCRReviewView empty-state transitions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

try:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication, QComboBox

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
    """No-op replacement for OCRReviewView.__init__."""


def _make_view():
    from context_aware_translation.ui.views.ocr_review_view import OCRReviewView

    with patch.object(OCRReviewView, "__init__", _noop_init):
        view = OCRReviewView(None, "")
    return view


def _attach_control_mocks(view) -> None:  # noqa: ANN001
    view.image_viewer = MagicMock()
    view.text_edit = MagicMock()
    view.element_list = MagicMock()
    view.page_label = MagicMock()
    view.ocr_status_label = MagicMock()
    view.page_spinbox = MagicMock()
    view.go_to_label = MagicMock()
    view.go_button = MagicMock()
    view.empty_label = MagicMock()
    view.first_button = MagicMock()
    view.prev_button = MagicMock()
    view.next_button = MagicMock()
    view.last_button = MagicMock()
    view.run_ocr_button = MagicMock()
    view.run_all_ocr_button = MagicMock()
    view.save_button = MagicMock()


def test_show_empty_state_clears_stale_document_state_and_disables_go_controls():
    view = _make_view()
    _attach_control_mocks(view)
    view.sources = [{"source_id": 1}]
    view.current_index = 5
    view.document_id = 9
    view._current_ocr_content = object()
    view._current_original_texts = ["abc"]
    view._is_structured_mode = True
    view._element_to_bbox = {1: 2}
    view._bbox_to_element = {2: 1}

    view._show_empty_state()

    assert view.sources == []
    assert view.current_index == -1
    assert view.document_id is None
    assert view._current_ocr_content is None
    assert view._current_original_texts == []
    assert view._is_structured_mode is False
    assert view._element_to_bbox == {}
    assert view._bbox_to_element == {}
    view.image_viewer.clear_image.assert_called_once()
    view.page_spinbox.setMaximum.assert_called_once_with(1)
    view.go_to_label.setEnabled.assert_called_once_with(False)
    view.page_spinbox.setEnabled.assert_called_once_with(False)
    view.go_button.setEnabled.assert_called_once_with(False)


def test_go_to_entered_page_is_noop_after_empty_state():
    view = _make_view()
    _attach_control_mocks(view)
    view.sources = [{"source_id": 1}]
    view.page_spinbox.value.return_value = 1
    view._go_to_page = MagicMock()

    view._show_empty_state()
    view._go_to_entered_page()

    view._go_to_page.assert_not_called()


def test_enable_controls_re_enables_go_controls():
    view = _make_view()
    _attach_control_mocks(view)

    view._enable_controls()

    view.go_to_label.setEnabled.assert_called_once_with(True)
    view.page_spinbox.setEnabled.assert_called_once_with(True)
    view.go_button.setEnabled.assert_called_once_with(True)


def test_go_to_page_without_binary_content_clears_stale_image():
    view = _make_view()
    _attach_control_mocks(view)
    view._right_stack = MagicMock()
    view._element_to_bbox = {}
    view._bbox_to_element = {}
    view.sources = [{"source_id": 1, "ocr_json": None, "is_ocr_completed": 0}]
    view.current_index = -1
    view.document_id = None
    view.document_repo = MagicMock()
    view.document_repo.get_source_binary_content.return_value = None

    view._go_to_page(0)

    view.image_viewer.clear_image.assert_called_once()


def test_load_data_translates_document_type_labels_in_combo():
    view = _make_view()
    view.doc_combo = QComboBox()
    view.document_repo = MagicMock()
    view.document_repo.list_documents_with_image_sources.return_value = [
        {"document_id": 7, "document_type": "scanned_book"}
    ]
    view._show_empty_state = MagicMock()
    view._load_document_sources = MagicMock()

    view._load_data()

    assert view.doc_combo.count() == 1
    assert view.doc_combo.itemData(0) == 7
    assert view.doc_combo.itemText(0) == f"Document 7 ({QCoreApplication.translate('ExportView', 'Scanned Book')})"
    assert "scanned_book" not in view.doc_combo.itemText(0)


def test_tip_text_hides_preflight_wording():
    view = _make_view()
    tip = view._tip_text().lower()
    assert "preflight" not in tip
    assert "translation start" in tip


def test_ocr_action_buttons_use_minimum_size_policy():
    from context_aware_translation.ui.views.ocr_review_view import OCRReviewView

    book_manager = MagicMock()
    book_manager.get_book.return_value = {"book_id": "b1"}
    book_manager.get_book_db_path.return_value = "/tmp/ocr-view-test.db"
    task_engine = MagicMock()
    task_engine.tasks_changed = MagicMock()

    with (
        patch("context_aware_translation.ui.views.ocr_review_view.SQLiteBookDB"),
        patch("context_aware_translation.ui.views.ocr_review_view.DocumentRepository") as mock_repo_cls,
    ):
        mock_repo = MagicMock()
        mock_repo.list_documents_with_image_sources.return_value = []
        mock_repo_cls.return_value = mock_repo
        view = OCRReviewView(book_manager, "b1", task_engine=task_engine)

    assert view.run_ocr_button.sizePolicy().horizontalPolicy().name == "Minimum"
    assert view.run_all_ocr_button.sizePolicy().horizontalPolicy().name == "Minimum"
    assert view.save_button.sizePolicy().horizontalPolicy().name == "Minimum"
