"""Regression tests for OCR rerun backup/restore behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

try:
    from PySide6.QtWidgets import QApplication

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


def test_save_rerun_backup_only_keeps_completed_source_state():
    view = _make_view()

    view.document_repo = MagicMock()

    view._save_rerun_backup({"source_id": 10, "is_ocr_completed": 0})
    assert view._rerun_backup is None

    view.document_repo.get_source_ocr_json.return_value = '{"text":"old"}'
    view._save_rerun_backup({"source_id": 10, "is_ocr_completed": 1})
    assert view._rerun_backup == {
        "source_id": 10,
        "ocr_json": '{"text":"old"}',
        "is_ocr_completed": True,
    }


def test_restore_rerun_backup_restores_repo_and_local_source_state():
    view = _make_view()
    view.document_repo = MagicMock()
    view.sources = [{"source_id": 10, "ocr_json": None, "is_ocr_completed": 0}]
    view.current_index = 0
    view._go_to_page = MagicMock()
    view._rerun_backup = {
        "source_id": 10,
        "ocr_json": '{"text":"old"}',
        "is_ocr_completed": True,
    }

    view._restore_rerun_backup()

    view.document_repo.update_source_ocr.assert_called_once_with(10, '{"text":"old"}')
    view.document_repo.update_source_ocr_completed.assert_called_once_with(10)
    assert view.sources[0]["ocr_json"] == '{"text":"old"}'
    assert view.sources[0]["is_ocr_completed"] == 1
    view._go_to_page.assert_called_once_with(0)
    assert view._rerun_backup is None


def test_set_buttons_enabled_toggles_doc_and_page_controls():
    view = _make_view()
    view.sources = [{"source_id": 10}]
    view.image_viewer = MagicMock()
    view.text_edit = MagicMock()
    view.element_list = MagicMock()
    view.doc_combo = MagicMock()
    view.doc_combo.count.return_value = 2
    view.go_to_label = MagicMock()
    view.page_spinbox = MagicMock()
    view.go_button = MagicMock()
    view.first_button = MagicMock()
    view.prev_button = MagicMock()
    view.next_button = MagicMock()
    view.last_button = MagicMock()
    view.run_ocr_button = MagicMock()
    view.run_all_ocr_button = MagicMock()
    view.save_button = MagicMock()
    view._update_navigation = MagicMock()

    view._set_buttons_enabled(False)
    view.image_viewer.setEnabled.assert_called_with(False)
    view.text_edit.setEnabled.assert_called_with(False)
    view.element_list.setEnabled.assert_called_with(False)
    view.doc_combo.setEnabled.assert_called_with(False)
    view.page_spinbox.setEnabled.assert_called_with(False)
    view.go_button.setEnabled.assert_called_with(False)

    view.image_viewer.reset_mock()
    view.text_edit.reset_mock()
    view.element_list.reset_mock()
    view.doc_combo.reset_mock()
    view.page_spinbox.reset_mock()
    view.go_button.reset_mock()
    view._update_navigation.reset_mock()
    view._set_buttons_enabled(True)

    view.image_viewer.setEnabled.assert_called_once_with(True)
    view.text_edit.setEnabled.assert_called_once_with(True)
    view.element_list.setEnabled.assert_called_once_with(True)
    view.doc_combo.setEnabled.assert_called_once_with(True)
    view.page_spinbox.setEnabled.assert_called_once_with(True)
    view.go_button.setEnabled.assert_called_once_with(True)
    view._update_navigation.assert_called_once()


def test_on_ocr_finished_uses_captured_run_context_for_reload():
    view = _make_view()
    view.progress_widget = MagicMock()
    view._set_buttons_enabled = MagicMock()
    view._rerun_backup = {"source_id": 10}
    view.ocr_completed = MagicMock()
    view.document_id = 99
    view.current_index = 0
    view._ocr_run_document_id = 7
    view._ocr_run_page_index = 5
    view.sources = []

    def _fake_load(doc_id: int) -> None:
        assert doc_id == 7
        view.sources = [{"source_id": 1}, {"source_id": 2}, {"source_id": 3}]

    view._load_document_sources = MagicMock(side_effect=_fake_load)
    view._go_to_page = MagicMock()

    with patch("context_aware_translation.ui.views.ocr_review_view.QMessageBox.information"):
        view._on_ocr_finished(3)

    view._load_document_sources.assert_called_once_with(7)
    view._go_to_page.assert_called_once_with(2)
    assert view._rerun_backup is None
    view.ocr_completed.emit.assert_called_once()


def test_on_ocr_worker_finished_clears_captured_run_context():
    view = _make_view()
    view.progress_widget = MagicMock()
    view._ocr_run_document_id = 7
    view._ocr_run_page_index = 3
    view.ocr_worker = object()

    view._on_ocr_worker_finished()

    assert view._ocr_run_document_id is None
    assert view._ocr_run_page_index == -1
    assert view.ocr_worker is None
