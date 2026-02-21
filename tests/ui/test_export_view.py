"""Unit tests for ExportView format and refresh behaviors."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QListWidget,
        QListWidgetItem,
        QPushButton,
    )

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
    """No-op replacement for ExportView.__init__."""


def _make_view(documents):
    """Create a minimal ExportView with only the widgets needed by _update_available_formats."""
    from context_aware_translation.ui.views.export_view import ExportView

    with patch.object(ExportView, "__init__", _noop_init):
        view = ExportView(None, "")

    normalized_documents = []
    for doc in documents:
        normalized = dict(doc)
        normalized.setdefault("total_chunks", 1)
        normalized.setdefault("chunks_translated", 1)
        normalized_documents.append(normalized)

    # Manually set the attributes that _update_available_formats uses
    view.documents = normalized_documents
    view.doc_list = QListWidget()
    view.format_combo = QComboBox()
    view.export_btn = QPushButton()
    view.preserve_structure_cb = QCheckBox()
    view.allow_original_fallback_cb = QCheckBox()

    # Populate the list widget with checked items
    for doc in normalized_documents:
        item = QListWidgetItem(f"Document {doc['document_id']}")
        item.setCheckState(Qt.CheckState.Checked)
        item.setData(Qt.ItemDataRole.UserRole, doc["document_id"])
        view.doc_list.addItem(item)

    return view


class TestMultiExportGuard:
    """Test that _update_available_formats blocks multi-select for types that don't support it."""

    def test_multi_epub_disables_export(self):
        """Selecting multiple EPUB documents should disable export."""
        view = _make_view(
            [
                {"document_id": 1, "document_type": "epub"},
                {"document_id": 2, "document_type": "epub"},
            ]
        )

        view._update_available_formats()

        assert not view.export_btn.isEnabled()

    def test_single_epub_enables_export(self):
        """Selecting a single EPUB document should enable export."""
        view = _make_view(
            [
                {"document_id": 1, "document_type": "epub"},
            ]
        )

        view._update_available_formats()

        assert view.export_btn.isEnabled()
        assert view.format_combo.count() > 0

    def test_multi_pdf_enables_export(self):
        """Selecting multiple PDF documents should still allow export (supports_multi_export=True)."""
        view = _make_view(
            [
                {"document_id": 1, "document_type": "pdf"},
                {"document_id": 2, "document_type": "pdf"},
            ]
        )

        view._update_available_formats()

        assert view.export_btn.isEnabled()
        assert view.format_combo.count() > 0

    def test_no_selection_disables_export_and_preserve_structure(self):
        """No selected documents should disable export actions."""
        view = _make_view(
            [
                {"document_id": 1, "document_type": "text"},
                {"document_id": 2, "document_type": "text"},
            ]
        )
        view.export_btn.setEnabled(True)
        view.preserve_structure_cb.setEnabled(True)
        view.preserve_structure_cb.setChecked(True)

        for i in range(view.doc_list.count()):
            view.doc_list.item(i).setCheckState(Qt.CheckState.Unchecked)

        view._update_available_formats()

        assert not view.export_btn.isEnabled()
        assert not view.preserve_structure_cb.isEnabled()
        assert not view.preserve_structure_cb.isChecked()

    def test_multi_text_enables_export(self):
        """Selecting multiple text documents should still allow export."""
        view = _make_view(
            [
                {"document_id": 1, "document_type": "text"},
                {"document_id": 2, "document_type": "text"},
            ]
        )

        view._update_available_formats()

        assert view.export_btn.isEnabled()

    def test_mixed_types_disables_export(self):
        """Selecting documents of different types should disable export."""
        view = _make_view(
            [
                {"document_id": 1, "document_type": "epub"},
                {"document_id": 2, "document_type": "pdf"},
            ]
        )

        view._update_available_formats()

        assert not view.export_btn.isEnabled()

    def test_incomplete_translation_disables_export_by_default(self):
        """Strict mode should block export when selected docs are not fully translated."""
        view = _make_view(
            [
                {"document_id": 1, "document_type": "text", "total_chunks": 4, "chunks_translated": 3},
            ]
        )

        view._update_available_formats()

        assert not view.export_btn.isEnabled()

    def test_incomplete_translation_can_export_with_fallback(self):
        """Fallback mode should allow export for partially translated docs."""
        view = _make_view(
            [
                {"document_id": 1, "document_type": "text", "total_chunks": 4, "chunks_translated": 3},
            ]
        )
        view.allow_original_fallback_cb.setChecked(True)

        view._update_available_formats()

        assert view.export_btn.isEnabled()

    def test_refresh_preserves_checked_and_unchecked_states(self):
        """Refresh should keep both checked and unchecked document states."""
        documents = [
            {"document_id": 1, "document_type": "text"},
            {"document_id": 2, "document_type": "text"},
            {"document_id": 3, "document_type": "text"},
        ]
        view = _make_view(documents)

        # User unchecks the middle item.
        view.doc_list.item(1).setCheckState(Qt.CheckState.Unchecked)

        def _fake_load_documents(*, show_errors: bool = True):
            # Mimic real load behavior: repopulate with default checked items.
            _ = show_errors
            for doc in view.documents:
                item = QListWidgetItem(f"Document {doc['document_id']}")
                item.setCheckState(Qt.CheckState.Checked)
                item.setData(Qt.ItemDataRole.UserRole, doc["document_id"])
                view.doc_list.addItem(item)

        with patch.object(view, "_load_documents", _fake_load_documents):
            view.refresh()

        assert view.doc_list.item(0).checkState() == Qt.CheckState.Checked
        assert view.doc_list.item(1).checkState() == Qt.CheckState.Unchecked
        assert view.doc_list.item(2).checkState() == Qt.CheckState.Checked

    def test_refresh_uses_non_modal_reload(self):
        """Refresh should reload documents in non-modal mode."""
        view = _make_view([{"document_id": 1, "document_type": "text"}])
        loader = MagicMock()
        view._load_documents = loader

        view.refresh()

        loader.assert_called_once_with(show_errors=False)

    def test_load_documents_non_modal_errors_use_inline_message(self):
        """Non-modal load should not open critical dialog."""
        view = _make_view([])
        view.book_manager = MagicMock()
        view.book_id = "book-id"
        view.book_manager.get_book_db_path.return_value = Path("/tmp/fake.db")
        view._show_error = MagicMock()
        view._show_inline_error = MagicMock()

        fake_db = MagicMock()
        fake_repo = MagicMock()
        fake_repo.get_documents_with_status.return_value = []

        with (
            patch("context_aware_translation.ui.views.export_view.SQLiteBookDB", return_value=fake_db),
            patch("context_aware_translation.ui.views.export_view.DocumentRepository", return_value=fake_repo),
        ):
            view._load_documents(show_errors=False)

        view._show_error.assert_not_called()
        view._show_inline_error.assert_called_once()
        assert not view.export_btn.isEnabled()
        fake_db.close.assert_called_once()
