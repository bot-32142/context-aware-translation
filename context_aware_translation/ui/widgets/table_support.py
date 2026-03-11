from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QSizePolicy, QTableWidget


def configure_readonly_row_table(
    table: QTableWidget,
    *,
    selection_mode: QTableWidget.SelectionMode = QTableWidget.SelectionMode.SingleSelection,
    vertical_policy: QSizePolicy.Policy = QSizePolicy.Policy.Fixed,
) -> None:
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(selection_mode)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSizePolicy(QSizePolicy.Policy.Expanding, vertical_policy)


def apply_header_resize_modes(
    table: QTableWidget,
    modes: Iterable[tuple[int, QHeaderView.ResizeMode]],
    *,
    column_widths: Iterable[tuple[int, int]] = (),
) -> None:
    header = table.horizontalHeader()
    for column, mode in modes:
        header.setSectionResizeMode(column, mode)
    for column, width in column_widths:
        table.setColumnWidth(column, width)


def fit_table_height_to_rows(table: QTableWidget, *, max_visible_rows: int | None = None, padding: int = 8) -> None:
    header_height = table.horizontalHeader().height()
    frame_height = table.frameWidth() * 2
    row_count = table.rowCount()
    if row_count == 0:
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setFixedHeight(header_height + frame_height + padding)
        return

    row_heights = [table.rowHeight(index) for index in range(row_count)]
    visible_rows = row_count if max_visible_rows is None else min(row_count, max_visible_rows)
    visible_height = sum(row_heights[:visible_rows])
    table.setVerticalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        if max_visible_rows is None or row_count <= max_visible_rows
        else Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    table.setFixedHeight(header_height + visible_height + frame_height + padding)


def fit_table_min_width(table: QTableWidget) -> None:
    total_width = table.verticalHeader().width() + table.frameWidth() * 2 + 6
    for column in range(table.columnCount()):
        total_width += table.columnWidth(column)
    table.setMinimumWidth(total_width)
