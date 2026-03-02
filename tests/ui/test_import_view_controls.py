"""Regression tests for ImportView control-state behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

try:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QPushButton

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
    """No-op replacement for ImportView.__init__."""


def _make_view(selected_path: Path | None, *, selected_type_data: str | None):
    from context_aware_translation.ui.views.import_view import ImportView

    with patch.object(ImportView, "__init__", _noop_init):
        view = ImportView(None, "")

    view.selected_path = selected_path
    view.selected_paths = []
    view.select_file_btn = QPushButton()
    view.select_folder_btn = QPushButton()
    view.import_btn = QPushButton()
    view.type_combo = QComboBox()

    if selected_type_data is None:
        view.type_combo.addItem("(No compatible type detected)")
    else:
        view.type_combo.addItem(selected_type_data.capitalize(), selected_type_data)

    return view


def test_enable_controls_reenables_import_for_selected_path_and_valid_type():
    view = _make_view(Path("/tmp/document.pdf"), selected_type_data="pdf")

    view._enable_controls(False)
    assert not view.import_btn.isEnabled()
    assert not view.type_combo.isEnabled()

    view._enable_controls(True)

    assert view.select_file_btn.isEnabled()
    assert view.select_folder_btn.isEnabled()
    assert view.type_combo.isEnabled()
    assert view.import_btn.isEnabled()


def test_enable_controls_keeps_import_disabled_without_selected_path():
    view = _make_view(None, selected_type_data="pdf")

    view._enable_controls(True)

    assert view.select_file_btn.isEnabled()
    assert view.select_folder_btn.isEnabled()
    assert not view.type_combo.isEnabled()
    assert not view.import_btn.isEnabled()


def test_enable_controls_keeps_import_disabled_for_placeholder_type():
    view = _make_view(Path("/tmp/unsupported"), selected_type_data=None)

    view._enable_controls(True)

    assert not view.type_combo.isEnabled()
    assert not view.import_btn.isEnabled()


def test_enable_controls_reenables_import_for_selected_paths_and_valid_type():
    view = _make_view(None, selected_type_data="text")
    view.selected_paths = [Path("/tmp/ch1.txt"), Path("/tmp/ch2.txt")]

    view._enable_controls(True)

    assert view.select_file_btn.isEnabled()
    assert view.select_folder_btn.isEnabled()
    assert view.type_combo.isEnabled()
    assert view.import_btn.isEnabled()


def test_handle_path_selection_uses_export_document_type_translation():
    from context_aware_translation.ui.views.import_view import ImportView

    class _PdfDoc:
        document_type = "pdf"

        @staticmethod
        def can_import(_path: Path) -> bool:
            return True

    with patch.object(ImportView, "__init__", _noop_init):
        view = ImportView(None, "")

    view.selected_path = None
    view.selected_paths = []
    view.path_label = QLabel()
    view.result_label = QLabel()
    view.select_file_btn = QPushButton()
    view.select_folder_btn = QPushButton()
    view.type_combo = QComboBox()
    view.import_btn = QPushButton()
    view._config_valid = True

    with patch(
        "context_aware_translation.ui.views.import_view.get_compatible_document_classes_for_paths",
        return_value=[_PdfDoc],
    ):
        view._handle_path_selection(Path("/tmp/book.pdf"))

    assert view.type_combo.count() == 1
    assert view.type_combo.itemData(0) == "pdf"
    assert view.type_combo.itemText(0) == QCoreApplication.translate("ExportView", "PDF")


def test_handle_paths_selection_uses_detected_compatible_types():
    from context_aware_translation.ui.views.import_view import ImportView

    class _TextDoc:
        document_type = "text"

    with patch.object(ImportView, "__init__", _noop_init):
        view = ImportView(None, "")

    selected = [Path("/tmp/ch1.txt"), Path("/tmp/ch2.txt")]
    view.selected_path = None
    view.selected_paths = []
    view.path_label = QLabel()
    view.result_label = QLabel()
    view.select_file_btn = QPushButton()
    view.select_folder_btn = QPushButton()
    view.type_combo = QComboBox()
    view.import_btn = QPushButton()
    view._config_valid = True

    with patch(
        "context_aware_translation.ui.views.import_view.get_compatible_document_classes_for_paths",
        return_value=[_TextDoc],
    ):
        view._handle_paths_selection(selected)

    assert view.selected_path is None
    assert view.selected_paths == selected
    assert view.type_combo.count() == 1
    assert view.type_combo.itemData(0) == "text"
    assert view.import_btn.isEnabled()


def test_check_config_missing_profiles_shows_warning_but_keeps_import_available():
    from context_aware_translation.ui.views.import_view import ImportView

    with patch.object(ImportView, "__init__", _noop_init):
        view = ImportView(None, "")

    view.book_id = "book-id"
    view.book_manager = MagicMock()
    view.book_manager.get_book_config.return_value = {
        "extractor_config": {},
        "summarizor_config": {},
        "glossary_config": {},
        "translator_config": {},
    }

    view.warning_label = QLabel()
    view.select_file_btn = QPushButton()
    view.select_folder_btn = QPushButton()
    view.import_btn = QPushButton()
    view.type_combo = QComboBox()
    view.type_combo.addItem("PDF", "pdf")
    view.selected_path = Path("/tmp/book.pdf")
    view.selected_paths = []

    view._check_config()

    assert view._config_valid is True
    assert view.warning_label.isVisible()
    assert view.select_file_btn.isEnabled()
    assert view.select_folder_btn.isEnabled()


def test_tip_text_emphasizes_import_order_and_ocr_blocking():
    from context_aware_translation.ui.views.import_view import ImportView

    with patch.object(ImportView, "__init__", _noop_init):
        view = ImportView(None, "")

    tip = view._tip_text()
    assert "reading order" in tip
    assert "blocks later glossary/translation" in tip
