"""Tests that context-menu actions target the right-clicked row."""

from __future__ import annotations

from unittest.mock import patch

import pytest

try:
    from PySide6.QtGui import QStandardItem, QStandardItemModel
    from PySide6.QtWidgets import QApplication, QTableView, QWidget

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
    """No-op replacement for view __init__ methods."""
    QWidget.__init__(self)


def _make_table(rows: int = 3) -> QTableView:
    model = QStandardItemModel(rows, 1)
    for row in range(rows):
        model.setItem(row, 0, QStandardItem(f"row-{row}"))
    table = QTableView()
    table.setModel(model)
    table.resize(240, 160)
    table.show()
    QApplication.processEvents()
    return table


def _row_position(table: QTableView, row: int):
    index = table.model().index(row, 0)
    return table.visualRect(index).center()


def _selected_row(table: QTableView) -> int | None:
    selected = table.selectionModel().selectedRows()
    if not selected:
        return None
    return selected[0].row()


def test_library_context_menu_selects_clicked_row():
    from context_aware_translation.ui.views.library_view import LibraryView

    with patch.object(LibraryView, "__init__", _noop_init):
        view = LibraryView(None)

    view.table_view = _make_table()

    class _LibraryModel:
        @staticmethod
        def get_book(_row: int) -> object:
            return object()

    view.model = _LibraryModel()
    view.table_view.selectRow(0)

    with patch("context_aware_translation.ui.views.library_view.QMenu.exec", return_value=None):
        view._show_context_menu(_row_position(view.table_view, 2))

    assert _selected_row(view.table_view) == 2
