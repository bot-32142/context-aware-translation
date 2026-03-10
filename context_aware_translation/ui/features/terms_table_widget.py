from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QEvent, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.application.contracts.common import UserMessageSeverity
from context_aware_translation.application.contracts.terms import (
    TermsScopeKind,
    TermsTableState,
    TermTableRow,
    UpdateTermRequest,
)
from context_aware_translation.ui.utils import create_tip_label

_ROLE_ROW = Qt.ItemDataRole.UserRole + 1
_COLUMN_TERM = 0
_COLUMN_TRANSLATION = 1
_COLUMN_DESCRIPTION = 2
_COLUMN_OCCURRENCES = 3
_COLUMN_VOTES = 4
_COLUMN_IGNORED = 5
_COLUMN_REVIEWED = 6


class _TermsFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._query = ""
        self._filter_id = "all"
        self.setDynamicSortFilter(True)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_query(self, query: str) -> None:
        self._query = query.casefold().strip()
        self.beginFilterChange()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def set_filter_id(self, filter_id: str) -> None:
        self._filter_id = filter_id
        self.beginFilterChange()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:  # noqa: ANN001
        model = self.sourceModel()
        if model is None:
            return False
        row_index = model.index(source_row, 0, source_parent)
        row = model.data(row_index, _ROLE_ROW)
        if not isinstance(row, TermTableRow):
            return False

        if self._query:
            haystacks = [row.term, row.translation or "", row.description or ""]
            if not any(self._query in value.casefold() for value in haystacks):
                return False

        if self._filter_id == "unreviewed" and row.reviewed:
            return False
        if self._filter_id == "ignored" and not row.ignored:
            return False
        if self._filter_id == "translated" and not (row.translation or "").strip():
            return False
        if self._filter_id == "untranslated":
            return (row.translation or "").strip() == ""
        return True


class TermsTableWidget(QWidget):
    term_update_requested = Signal(object)

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state: TermsTableState | None = None
        self._suppress_item_changed = False
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.scope_label = create_tip_label("")
        layout.addWidget(self.scope_label)

        self.message_label = QLabel()
        self.message_label.hide()
        layout.addWidget(self.message_label)

        self.search_input = QLineEdit()
        self.search_input.textChanged.connect(self._apply_local_filters)
        layout.addWidget(self.search_input)

        self.filter_combo = QComboBox()
        self.filter_combo.currentIndexChanged.connect(self._apply_local_filters)
        layout.addWidget(self.filter_combo)

        self.summary_label = QLabel()
        self.summary_label.setStyleSheet("color: #666666;")
        layout.addWidget(self.summary_label)

        self.table_model = QStandardItemModel(self)
        self.table_model.setColumnCount(7)
        self.table_model.itemChanged.connect(self._on_item_changed)

        self.proxy_model = _TermsFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.table_model)

        self.table_view = QTableView()
        self.table_view.setModel(self.proxy_model)
        self.table_view.setSortingEnabled(True)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table_view.horizontalHeader().setSectionResizeMode(_COLUMN_TERM, QHeaderView.ResizeMode.Stretch)
        self.table_view.horizontalHeader().setSectionResizeMode(_COLUMN_TRANSLATION, QHeaderView.ResizeMode.Stretch)
        self.table_view.horizontalHeader().setSectionResizeMode(_COLUMN_DESCRIPTION, QHeaderView.ResizeMode.Stretch)
        self.table_view.horizontalHeader().setSectionResizeMode(
            _COLUMN_OCCURRENCES, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table_view.horizontalHeader().setSectionResizeMode(_COLUMN_VOTES, QHeaderView.ResizeMode.ResizeToContents)
        self.table_view.horizontalHeader().setSectionResizeMode(
            _COLUMN_IGNORED, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table_view.horizontalHeader().setSectionResizeMode(
            _COLUMN_REVIEWED, QHeaderView.ResizeMode.ResizeToContents
        )
        layout.addWidget(self.table_view, 1)

        self.retranslateUi()

    def set_state(self, state: TermsTableState) -> None:
        self._state = state
        self.scope_label.setText(self._scope_text(state))
        self.summary_label.setText(self._summary_text(state.rows))
        self._populate_table(state.rows)
        self._apply_local_filters()

    def clear_message(self) -> None:
        self.message_label.hide()
        self.message_label.clear()

    def set_message(self, severity: UserMessageSeverity, text: str) -> None:
        if not text:
            self.clear_message()
            return
        color = {
            UserMessageSeverity.SUCCESS: "#15803d",
            UserMessageSeverity.WARNING: "#b45309",
            UserMessageSeverity.ERROR: "#b91c1c",
        }.get(severity, "#2563eb")
        self.message_label.setStyleSheet(f"color: {color};")
        self.message_label.setText(text)
        self.message_label.show()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.search_input.setPlaceholderText(self.tr("Search terms..."))
        self.filter_combo.clear()
        self.filter_combo.addItem(self.tr("All"), "all")
        self.filter_combo.addItem(self.tr("Unreviewed"), "unreviewed")
        self.filter_combo.addItem(self.tr("Ignored"), "ignored")
        self.filter_combo.addItem(self.tr("Translated"), "translated")
        self.filter_combo.addItem(self.tr("Untranslated"), "untranslated")
        self.table_model.setHorizontalHeaderLabels(
            [
                self.tr("Term"),
                self.tr("Translation"),
                self.tr("Description"),
                self.tr("Occurrences"),
                self.tr("Recognized"),
                self.tr("Ignored"),
                self.tr("Reviewed"),
            ]
        )
        if self._state is not None:
            self.scope_label.setText(self._scope_text(self._state))
            self.summary_label.setText(self._summary_text(self._state.rows))

    def _populate_table(self, rows: list[TermTableRow]) -> None:
        self._suppress_item_changed = True
        self.table_model.removeRows(0, self.table_model.rowCount())
        for row in rows:
            self.table_model.appendRow(self._build_items_for_row(row))
        self._suppress_item_changed = False
        self.table_view.sortByColumn(_COLUMN_TERM, Qt.SortOrder.AscendingOrder)

    def _build_items_for_row(self, row: TermTableRow) -> list[QStandardItem]:
        term_item = QStandardItem(row.term)
        term_item.setEditable(False)
        term_item.setData(row, _ROLE_ROW)

        translation_item = QStandardItem(row.translation or "")
        translation_item.setData(row, _ROLE_ROW)

        description_item = QStandardItem(row.description or "")
        description_item.setData(row, _ROLE_ROW)

        occurrences_item = QStandardItem(str(row.occurrences))
        occurrences_item.setEditable(False)
        occurrences_item.setData(row, _ROLE_ROW)

        votes_item = QStandardItem(str(row.votes))
        votes_item.setEditable(False)
        votes_item.setData(row, _ROLE_ROW)

        ignored_item = QStandardItem()
        ignored_item.setCheckable(True)
        ignored_item.setEditable(False)
        ignored_item.setCheckState(Qt.CheckState.Checked if row.ignored else Qt.CheckState.Unchecked)
        ignored_item.setData(row, _ROLE_ROW)

        reviewed_item = QStandardItem()
        reviewed_item.setCheckable(True)
        reviewed_item.setEditable(False)
        reviewed_item.setCheckState(Qt.CheckState.Checked if row.reviewed else Qt.CheckState.Unchecked)
        reviewed_item.setData(row, _ROLE_ROW)

        return [
            term_item,
            translation_item,
            description_item,
            occurrences_item,
            votes_item,
            ignored_item,
            reviewed_item,
        ]

    def _apply_local_filters(self) -> None:
        self.proxy_model.set_query(self.search_input.text())
        current_filter = self.filter_combo.currentData()
        self.proxy_model.set_filter_id(current_filter if isinstance(current_filter, str) else "all")

    def _on_item_changed(self, item: QStandardItem) -> None:
        if self._suppress_item_changed or self._state is None:
            return
        row = item.data(_ROLE_ROW)
        if not isinstance(row, TermTableRow):
            return

        request = UpdateTermRequest(scope=self._state.scope, term_id=row.term_id, term_key=row.term_key)
        if item.column() == _COLUMN_TRANSLATION:
            request = request.model_copy(update={"translation": item.text()})
        elif item.column() == _COLUMN_DESCRIPTION:
            request = request.model_copy(update={"description": item.text()})
        elif item.column() == _COLUMN_IGNORED:
            request = request.model_copy(update={"ignored": item.checkState() == Qt.CheckState.Checked})
        elif item.column() == _COLUMN_REVIEWED:
            request = request.model_copy(update={"reviewed": item.checkState() == Qt.CheckState.Checked})
        else:
            return
        self.term_update_requested.emit(request)

    def _scope_text(self, state: TermsTableState) -> str:
        if state.scope.kind is TermsScopeKind.PROJECT:
            return self.tr(
                "Shared terms for this project. Editing here updates the project terms. Existing translations are unchanged."
            )
        return self.tr("Terms for the selected document. Editing here updates the shared project terms.")

    def _summary_text(self, rows: Iterable[TermTableRow]) -> str:
        rows_list = list(rows)
        translated = sum(1 for row in rows_list if (row.translation or "").strip())
        reviewed = sum(1 for row in rows_list if row.reviewed)
        ignored = sum(1 for row in rows_list if row.ignored)
        return (
            self.tr("Showing %1 terms | Reviewed: %2 | Translated: %3 | Ignored: %4")
            .replace("%1", str(len(rows_list)))
            .replace("%2", str(reviewed))
            .replace("%3", str(translated))
            .replace("%4", str(ignored))
        )

    def selected_rows(self) -> list[TermTableRow]:
        rows: list[TermTableRow] = []
        seen_keys: set[str] = set()
        for index in self.table_view.selectionModel().selectedRows():
            source_index = self.proxy_model.mapToSource(index)
            row = self.table_model.data(source_index, _ROLE_ROW)
            if not isinstance(row, TermTableRow) or row.term_key in seen_keys:
                continue
            seen_keys.add(row.term_key)
            rows.append(row)
        return rows


__all__ = ["TermsTableWidget"]
