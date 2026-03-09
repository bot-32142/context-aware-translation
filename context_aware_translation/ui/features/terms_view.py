from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QEvent, QSortFilterProxyModel, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.application.contracts.common import UserMessageSeverity
from context_aware_translation.application.contracts.terms import (
    ExportTermsRequest,
    FilterNoiseRequest,
    ImportTermsRequest,
    ReviewTermsRequest,
    TermsScopeKind,
    TermsTableState,
    TermTableRow,
    TranslatePendingTermsRequest,
    UpdateTermRequest,
)
from context_aware_translation.application.errors import ApplicationError, BlockedOperationError
from context_aware_translation.application.events import (
    ApplicationEventSubscriber,
    SetupInvalidatedEvent,
    TermsInvalidatedEvent,
)
from context_aware_translation.application.services.terms import TermsService
from context_aware_translation.ui.adapters import QtApplicationEventBridge
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


class TermsView(QWidget):
    """Project-level shared Terms surface backed by application services."""

    def __init__(
        self,
        project_id: str,
        service: TermsService,
        events: ApplicationEventSubscriber,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project_id = project_id
        self._service = service
        self._state: TermsTableState | None = None
        self._suppress_item_changed = False
        self._event_bridge = QtApplicationEventBridge(events, parent=self)
        self._event_bridge.terms_invalidated.connect(self._on_terms_invalidated)
        self._event_bridge.setup_invalidated.connect(self._on_setup_invalidated)
        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.title_label = QLabel(self.tr("Terms"))
        self.title_label.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(self.title_label)

        self.tip_label = create_tip_label(self._tip_text())
        layout.addWidget(self.tip_label)

        self.scope_label = create_tip_label("")
        layout.addWidget(self.scope_label)

        self.message_label = QLabel()
        self.message_label.hide()
        layout.addWidget(self.message_label)

        toolbar_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.tr("Search terms..."))
        self.search_input.textChanged.connect(self._apply_local_filters)
        toolbar_layout.addWidget(self.search_input, 1)

        self.filter_combo = QComboBox()
        self.filter_combo.addItem(self.tr("All"), "all")
        self.filter_combo.addItem(self.tr("Unreviewed"), "unreviewed")
        self.filter_combo.addItem(self.tr("Ignored"), "ignored")
        self.filter_combo.addItem(self.tr("Translated"), "translated")
        self.filter_combo.addItem(self.tr("Untranslated"), "untranslated")
        self.filter_combo.currentIndexChanged.connect(self._apply_local_filters)
        toolbar_layout.addWidget(self.filter_combo)

        self.translate_button = QPushButton(self.tr("Translate Untranslated"))
        self.translate_button.clicked.connect(self._on_translate_pending)
        toolbar_layout.addWidget(self.translate_button)

        self.review_button = QPushButton(self.tr("Review Terms"))
        self.review_button.clicked.connect(self._on_review_terms)
        toolbar_layout.addWidget(self.review_button)

        self.filter_noise_button = QPushButton(self.tr("Filter Rare"))
        self.filter_noise_button.clicked.connect(self._on_filter_noise)
        toolbar_layout.addWidget(self.filter_noise_button)

        self.import_button = QPushButton(self.tr("Import Glossary"))
        self.import_button.clicked.connect(self._on_import_terms)
        toolbar_layout.addWidget(self.import_button)

        self.export_button = QPushButton(self.tr("Export Glossary"))
        self.export_button.clicked.connect(self._on_export_terms)
        toolbar_layout.addWidget(self.export_button)

        self.refresh_button = QPushButton(self.tr("Refresh"))
        self.refresh_button.clicked.connect(self.refresh)
        toolbar_layout.addWidget(self.refresh_button)

        layout.addLayout(toolbar_layout)

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
        self.table_view.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table_view.horizontalHeader().setSectionResizeMode(_COLUMN_TERM, QHeaderView.ResizeMode.Stretch)
        self.table_view.horizontalHeader().setSectionResizeMode(_COLUMN_TRANSLATION, QHeaderView.ResizeMode.Stretch)
        self.table_view.horizontalHeader().setSectionResizeMode(_COLUMN_DESCRIPTION, QHeaderView.ResizeMode.Stretch)
        self.table_view.horizontalHeader().setSectionResizeMode(_COLUMN_OCCURRENCES, QHeaderView.ResizeMode.ResizeToContents)
        self.table_view.horizontalHeader().setSectionResizeMode(_COLUMN_VOTES, QHeaderView.ResizeMode.ResizeToContents)
        self.table_view.horizontalHeader().setSectionResizeMode(_COLUMN_IGNORED, QHeaderView.ResizeMode.ResizeToContents)
        self.table_view.horizontalHeader().setSectionResizeMode(_COLUMN_REVIEWED, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table_view, 1)

        self._retranslate_table_headers()

    def refresh(self) -> None:
        self._apply_state(self._service.get_project_terms(self.project_id))

    def cleanup(self) -> None:
        self._event_bridge.close()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.title_label.setText(self.tr("Terms"))
        self.tip_label.setText(self._tip_text())
        self.search_input.setPlaceholderText(self.tr("Search terms..."))
        self.filter_combo.setItemText(0, self.tr("All"))
        self.filter_combo.setItemText(1, self.tr("Unreviewed"))
        self.filter_combo.setItemText(2, self.tr("Ignored"))
        self.filter_combo.setItemText(3, self.tr("Translated"))
        self.filter_combo.setItemText(4, self.tr("Untranslated"))
        self.translate_button.setText(self.tr("Translate Untranslated"))
        self.review_button.setText(self.tr("Review Terms"))
        self.filter_noise_button.setText(self.tr("Filter Rare"))
        self.import_button.setText(self.tr("Import Glossary"))
        self.export_button.setText(self.tr("Export Glossary"))
        self.refresh_button.setText(self.tr("Refresh"))
        self._retranslate_table_headers()
        if self._state is not None:
            self.scope_label.setText(self._scope_text(self._state))
            self.summary_label.setText(self._summary_text(self._state.rows))
            self._apply_toolbar_state(self._state.toolbar)

    def _retranslate_table_headers(self) -> None:
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

    def _apply_state(self, state: TermsTableState) -> None:
        self._state = state
        self.scope_label.setText(self._scope_text(state))
        self.summary_label.setText(self._summary_text(state.rows))
        self._apply_toolbar_state(state.toolbar)
        self._populate_table(state.rows)
        self._show_message(UserMessageSeverity.INFO, "", show_dialog=False)
        self._apply_local_filters()

    def _populate_table(self, rows: list[TermTableRow]) -> None:
        self._suppress_item_changed = True
        self.table_model.removeRows(0, self.table_model.rowCount())
        for row in rows:
            items = self._build_items_for_row(row)
            self.table_model.appendRow(items)
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

    def _apply_toolbar_state(self, toolbar) -> None:  # noqa: ANN001
        self.translate_button.setEnabled(toolbar.can_translate_pending)
        self.review_button.setEnabled(toolbar.can_review)
        self.filter_noise_button.setEnabled(toolbar.can_filter_noise)
        self.import_button.setEnabled(toolbar.can_import)
        self.export_button.setEnabled(toolbar.can_export)

        self.translate_button.setToolTip(toolbar.translate_pending_blocker.message if toolbar.translate_pending_blocker else self.tr("Translate all currently untranslated glossary terms."))
        self.review_button.setToolTip(toolbar.review_blocker.message if toolbar.review_blocker else self.tr("Run an LLM review pass on unreviewed glossary terms."))
        self.filter_noise_button.setToolTip(toolbar.filter_noise_blocker.message if toolbar.filter_noise_blocker else self.tr("Automatically ignore terms that occurred only once or were recognized by the LLM in only one chunk."))
        self.import_button.setToolTip(toolbar.import_blocker.message if toolbar.import_blocker else self.tr("Import glossary terms from a JSON file and replace current glossary."))
        self.export_button.setToolTip(toolbar.export_blocker.message if toolbar.export_blocker else self.tr("Export glossary terms to a JSON file."))

    def _apply_local_filters(self) -> None:
        self.proxy_model.set_query(self.search_input.text())
        current_filter = self.filter_combo.currentData()
        self.proxy_model.set_filter_id(current_filter if isinstance(current_filter, str) else "all")

    def _scope_text(self, state: TermsTableState) -> str:
        if state.scope.kind is TermsScopeKind.PROJECT:
            return self.tr("Shared terms for this project. Editing here updates the project glossary. Existing translations are unchanged.")
        return self.tr("Terms for the selected document. Editing here updates the shared project glossary.")

    def _summary_text(self, rows: Iterable[TermTableRow]) -> str:
        rows_list = list(rows)
        translated = sum(1 for row in rows_list if (row.translation or "").strip())
        reviewed = sum(1 for row in rows_list if row.reviewed)
        ignored = sum(1 for row in rows_list if row.ignored)
        return self.tr("Showing %1 terms | Reviewed: %2 | Translated: %3 | Ignored: %4").replace("%1", str(len(rows_list))).replace("%2", str(reviewed)).replace("%3", str(translated)).replace("%4", str(ignored))

    def _on_translate_pending(self) -> None:
        self._run_command(
            lambda: self._service.translate_pending(TranslatePendingTermsRequest(project_id=self.project_id)),
            title=self.tr("Translate Terms"),
        )

    def _on_review_terms(self) -> None:
        self._run_command(
            lambda: self._service.review_terms(ReviewTermsRequest(project_id=self.project_id)),
            title=self.tr("Review Terms"),
        )

    def _on_filter_noise(self) -> None:
        if QMessageBox.question(
            self,
            self.tr("Filter Rare Terms"),
            self.tr(
                "This will mark terms as ignored when they occurred only once or were recognized in only one chunk. Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            state = self._service.filter_noise(FilterNoiseRequest(project_id=self.project_id))
        except BlockedOperationError as exc:
            self._show_application_error(self.tr("Filter Rare Terms"), exc)
            return
        except ApplicationError as exc:
            self._show_application_error(self.tr("Filter Rare Terms"), exc)
            return
        self._apply_state(state)
        self._show_message(UserMessageSeverity.SUCCESS, self.tr("Rare terms were filtered."))

    def _on_import_terms(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            self.tr("Import Glossary"),
            "",
            self.tr("JSON Files (*.json);;All Files (*)"),
        )
        if not path:
            return
        try:
            state = self._service.import_terms(ImportTermsRequest(project_id=self.project_id, input_path=path))
        except BlockedOperationError as exc:
            self._show_application_error(self.tr("Import Glossary"), exc)
            return
        except ApplicationError as exc:
            self._show_application_error(self.tr("Import Glossary"), exc)
            return
        self._apply_state(state)
        self._show_message(UserMessageSeverity.SUCCESS, self.tr("Glossary imported."))

    def _on_export_terms(self) -> None:
        path, _selected = QFileDialog.getSaveFileName(
            self,
            self.tr("Export Glossary"),
            "glossary.json",
            self.tr("JSON Files (*.json);;All Files (*)"),
        )
        if not path:
            return
        self._run_command(
            lambda: self._service.export_terms(ExportTermsRequest(project_id=self.project_id, output_path=path)),
            title=self.tr("Export Glossary"),
        )

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

        try:
            state = self._service.update_term(request)
        except BlockedOperationError as exc:
            self._show_application_error(self.tr("Terms"), exc)
            self.refresh()
            return
        except ApplicationError as exc:
            self._show_application_error(self.tr("Terms"), exc)
            self.refresh()
            return
        self._apply_state(state)

    def _run_command(self, action, *, title: str) -> None:  # noqa: ANN001
        try:
            accepted = action()
        except BlockedOperationError as exc:
            self._show_application_error(title, exc)
            return
        except ApplicationError as exc:
            self._show_application_error(title, exc)
            return
        message = accepted.message.text if accepted.message is not None else self.tr("Task queued.")
        severity = accepted.message.severity if accepted.message is not None else UserMessageSeverity.INFO
        self._show_message(severity, message)
        self.refresh()

    def _show_application_error(self, title: str, exc: ApplicationError) -> None:
        if isinstance(exc, BlockedOperationError):
            QMessageBox.warning(self, title, exc.payload.message)
        else:
            QMessageBox.warning(self, title, exc.payload.message)
        self._show_message(UserMessageSeverity.ERROR, exc.payload.message, show_dialog=False)

    def _show_message(self, severity: UserMessageSeverity, text: str, *, show_dialog: bool = False) -> None:
        if not text:
            self.message_label.hide()
            self.message_label.clear()
            return
        color = {
            UserMessageSeverity.SUCCESS: "#15803d",
            UserMessageSeverity.WARNING: "#b45309",
            UserMessageSeverity.ERROR: "#b91c1c",
        }.get(severity, "#2563eb")
        self.message_label.setStyleSheet(f"color: {color};")
        self.message_label.setText(text)
        self.message_label.show()
        if show_dialog:
            QMessageBox.information(self, self.tr("Terms"), text)

    def _on_terms_invalidated(self, event: TermsInvalidatedEvent) -> None:
        if event.project_id != self.project_id:
            return
        self.refresh()

    def _on_setup_invalidated(self, event: SetupInvalidatedEvent) -> None:
        if event.project_id not in {None, self.project_id}:
            return
        self.refresh()

    def _tip_text(self) -> str:
        return self.tr(
            "Terms are shared across the project. Build terms from document pages in document Terms, then translate, review, filter, import, or export them here."
        )
