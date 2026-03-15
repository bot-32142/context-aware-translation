from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.adapters.qt.application_event_bridge import QtApplicationEventBridge
from context_aware_translation.application.contracts.common import (
    BlockerInfo,
    DocumentRowActionKind,
    DocumentSection,
    NavigationTarget,
    NavigationTargetKind,
)
from context_aware_translation.application.contracts.work import (
    DeleteDocumentStackRequest,
    ImportDocumentsRequest,
    InspectImportPathsRequest,
    ResetDocumentStackRequest,
    WorkboardState,
    WorkDocumentRow,
)
from context_aware_translation.application.errors import ApplicationError, BlockedOperationError
from context_aware_translation.application.events import (
    ApplicationEventSubscriber,
    SetupInvalidatedEvent,
    WorkboardInvalidatedEvent,
)
from context_aware_translation.application.services.document import DocumentService
from context_aware_translation.application.services.terms import TermsService
from context_aware_translation.application.services.work import WorkService
from context_aware_translation.ui.chrome_sizing import sync_qml_host_height
from context_aware_translation.ui.features.document_workspace_view import DocumentWorkspaceView, WorkExportDialog
from context_aware_translation.ui.shell_hosts.hybrid import QmlChromeHost
from context_aware_translation.ui.tips import create_tip_label
from context_aware_translation.ui.viewmodels.work_home import WorkHomeViewModel
from context_aware_translation.ui.widgets.table_support import (
    apply_header_resize_modes,
    configure_readonly_row_table,
    fit_table_height_to_rows,
)

_TARGET_TO_SECTION: dict[NavigationTargetKind, DocumentSection] = {
    NavigationTargetKind.DOCUMENT_OCR: DocumentSection.OCR,
    NavigationTargetKind.DOCUMENT_TERMS: DocumentSection.TERMS,
    NavigationTargetKind.DOCUMENT_TRANSLATION: DocumentSection.TRANSLATION,
    NavigationTargetKind.DOCUMENT_IMAGES: DocumentSection.IMAGES,
    NavigationTargetKind.DOCUMENT_EXPORT: DocumentSection.EXPORT,
}


class WorkView(QWidget):
    _TABLE_MAX_VISIBLE_ROWS = 10
    _TOOLBAR_BUTTON_STYLE = """
        QPushButton {
            min-width: 150px;
            min-height: 38px;
            padding: 0 16px;
            border-radius: 14px;
            border: 1px solid #d9d0c4;
            background: #f8f3ea;
            color: #2f251d;
            font-weight: 600;
        }
        QPushButton:hover:enabled {
            background: #efe7da;
        }
        QPushButton:disabled {
            background: #efe7da;
            color: #8b8174;
        }
    """

    open_app_setup_requested = Signal()
    open_project_setup_requested = Signal()

    def __init__(
        self,
        project_id: str,
        work_service: WorkService,
        document_service: DocumentService,
        terms_service: TermsService,
        events: ApplicationEventSubscriber,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project_id = project_id
        self._work_service = work_service
        self._document_service = document_service
        self._terms_service = terms_service
        self._events = events
        self._state: WorkboardState | None = None
        self._row_states: list[WorkDocumentRow] = []
        self._document_view: DocumentWorkspaceView | None = None
        self._selected_import_paths: list[str] = []
        self._import_options: list[tuple[str, str]] = []
        self._selected_import_type: str | None = None
        self._import_summary = ""
        self._import_message = ""
        self._import_message_is_error = False
        self._can_import = False
        self.viewmodel = WorkHomeViewModel(self)
        self._event_bridge = QtApplicationEventBridge(events, parent=self)
        self._event_bridge.workboard_invalidated.connect(self._on_workboard_invalidated)
        self._event_bridge.setup_invalidated.connect(self._on_setup_invalidated)
        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.stack = QStackedWidget()

        self.home_page = QWidget()
        home_layout = QVBoxLayout(self.home_page)
        home_layout.setContentsMargins(0, 0, 0, 0)
        self.chrome_host = QmlChromeHost(
            "project/work_home/WorkHomeChrome.qml",
            context_objects={"workHome": self.viewmodel},
            parent=self.home_page,
        )
        home_layout.addWidget(self.chrome_host)
        self._connect_qml_signals()

        self.rows_table = QTableWidget(0, 6)
        self.rows_table.setHorizontalHeaderLabels(
            [
                self.tr("#"),
                self.tr("Document"),
                self.tr("Sources"),
                self.tr("OCR"),
                self.tr("Terms"),
                self.tr("Translation"),
            ]
        )
        configure_readonly_row_table(self.rows_table)
        self.rows_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.rows_table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.rows_table.installEventFilter(self)
        self.rows_table.verticalHeader().setDefaultSectionSize(44)
        self.rows_table.verticalHeader().setMinimumSectionSize(44)
        self.rows_table.setStyleSheet(
            """
            QTableWidget {
                background: #fcfaf6;
                alternate-background-color: #f7f1e8;
                border: 1px solid #d9d0c4;
                border-radius: 12px;
                gridline-color: #e7ddd0;
                selection-background-color: #efe7da;
                selection-color: #2f251d;
            }
            QHeaderView::section {
                background: #efe7da;
                color: #2f251d;
                border: none;
                border-bottom: 1px solid #d9d0c4;
                padding: 8px;
                font-weight: 600;
            }
            """
        )
        self.rows_table.setAlternatingRowColors(True)
        home_layout.addWidget(self.rows_table)

        row_actions = QHBoxLayout()
        self.reset_document_button = QPushButton(self.tr("Reset Document"))
        self.reset_document_button.setEnabled(False)
        self.reset_document_button.setStyleSheet(self._TOOLBAR_BUTTON_STYLE)
        self.reset_document_button.clicked.connect(self._reset_selected_document)
        row_actions.addWidget(self.reset_document_button)
        self.delete_document_button = QPushButton(self.tr("Delete Document"))
        self.delete_document_button.setEnabled(False)
        self.delete_document_button.setStyleSheet(self._TOOLBAR_BUTTON_STYLE)
        self.delete_document_button.clicked.connect(self._delete_selected_document)
        row_actions.addWidget(self.delete_document_button)
        row_actions.addStretch()
        home_layout.addLayout(row_actions)

        self.empty_label = create_tip_label(self.tr("No documents imported yet."))
        self.empty_label.hide()
        home_layout.addWidget(self.empty_label)
        home_layout.addStretch()

        self.stack.addWidget(self.home_page)
        layout.addWidget(self.stack)
        self._sync_import_chrome_state()
        self._schedule_chrome_resize()

    def refresh(self) -> None:
        self._apply_state(self._work_service.get_workboard(self._project_id))

    def cleanup(self) -> None:
        self._event_bridge.close()
        if self._document_view is not None:
            self._document_view.cleanup()

    def get_running_operations(self) -> list[str]:
        if self._document_view is not None and self.stack.currentWidget() is self._document_view:
            return self._document_view.get_running_operations()
        return []

    def request_cancel_running_operations(self, *, include_engine_tasks: bool = False) -> None:
        if self._document_view is not None and self.stack.currentWidget() is self._document_view:
            self._document_view.request_cancel_running_operations(include_engine_tasks=include_engine_tasks)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001
        if (
            watched is self.rows_table
            and event is not None
            and event.type() == QEvent.Type.KeyPress
            and event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}
        ):
            selected = self._selected_row_state()
            if selected is not None:
                self._handle_row_action(selected)
                return True
        return super().eventFilter(watched, event)

    def retranslateUi(self) -> None:
        if not self._selected_import_paths:
            self._import_summary = self._default_import_summary()
        self.rows_table.setHorizontalHeaderLabels(
            [
                self.tr("#"),
                self.tr("Document"),
                self.tr("Sources"),
                self.tr("OCR"),
                self.tr("Terms"),
                self.tr("Translation"),
            ]
        )
        self.reset_document_button.setText(self.tr("Reset Document"))
        self.delete_document_button.setText(self.tr("Delete Document"))
        self.empty_label.setText(self.tr("No documents imported yet."))
        self.viewmodel.retranslate()
        self._sync_import_chrome_state()
        if self._document_view is not None:
            self._document_view.retranslateUi()
        self._schedule_chrome_resize()

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._schedule_chrome_resize()

    def _apply_state(self, state: WorkboardState) -> None:
        self._state = state
        context_summary = (
            state.context_frontier.summary if state.context_frontier is not None else self.tr("Context not ready yet.")
        )
        blocker_text = (
            state.context_frontier.blocker.message
            if state.context_frontier and state.context_frontier.blocker is not None
            else ""
        )
        self.viewmodel.set_context(context_summary, blocker_text)

        if state.setup_blocker is not None:
            setup_action_label = self._setup_action_label(state.setup_blocker)
            self.viewmodel.set_setup(state.setup_blocker.message, setup_action_label)
        else:
            self.viewmodel.clear_setup()

        self.rows_table.setRowCount(0)
        self._row_states = list(state.rows)
        self.empty_label.setVisible(not state.rows)
        for row_state in state.rows:
            self._append_row(row_state)
        self.rows_table.resizeColumnsToContents()
        apply_header_resize_modes(self.rows_table, (), column_widths=((1, 280), (3, 170), (4, 170), (5, 170)))
        self.rows_table.horizontalHeader().setStretchLastSection(False)
        self._ensure_row_heights()
        self._fit_table_height()
        self._on_selection_changed()
        self._schedule_chrome_resize()

    def _append_row(self, row_state: WorkDocumentRow) -> None:
        row = self.rows_table.rowCount()
        self.rows_table.insertRow(row)
        row_tooltip = self._row_tooltip(row_state)
        document_item = QTableWidgetItem(row_state.document.label)
        document_item.setData(Qt.ItemDataRole.UserRole, row_state.document.document_id)
        document_item.setToolTip(row_tooltip)
        self.rows_table.setItem(row, 0, QTableWidgetItem(str(row_state.document.order_index)))
        self.rows_table.setItem(row, 1, document_item)
        self.rows_table.setItem(row, 2, QTableWidgetItem(str(row_state.source_count)))
        self._set_status_cell(row, 3, row_state.ocr_status, tooltip=row_tooltip)
        self._set_status_cell(row, 4, row_state.terms_status, tooltip=row_tooltip)
        self._set_status_cell(row, 5, row_state.translation_status, tooltip=row_tooltip)

    def _set_status_cell(self, row: int, column: int, text: str, *, tooltip: str) -> None:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setToolTip(tooltip)
        self.rows_table.setItem(row, column, item)
        self.rows_table.setCellWidget(row, column, self._build_status_badge(text, tooltip=tooltip))

    def _build_status_badge(self, text: str, *, tooltip: str) -> QWidget:
        background, foreground = self._status_colors(text)
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setToolTip(tooltip)
        label.setStyleSheet(
            "QLabel {"
            f" background-color: {background};"
            f" color: {foreground};"
            " border-radius: 10px;"
            " font-weight: 600;"
            " padding: 4px 10px;"
            "}"
        )
        container = QWidget(self.rows_table)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(0)
        layout.addWidget(label, 0, Qt.AlignmentFlag.AlignCenter)
        return container

    def _status_colors(self, text: str) -> tuple[str, str]:
        normalized = text.strip().lower()
        if normalized in {"n/a", "not started"}:
            return "#f2f4f7", "#475467"
        if "fail" in normalized or "block" in normalized or "cancel" in normalized:
            return "#fee4e2", "#b42318"
        if "complete" in normalized or normalized in {"done", "ready"}:
            return "#dcfae6", "#067647"
        if "progress" in normalized or "pending" in normalized or "running" in normalized:
            return "#fef3c7", "#b54708"
        return "#eef2ff", "#3730a3"

    def _row_tooltip(self, row_state: WorkDocumentRow) -> str:
        if row_state.blocker is not None:
            return row_state.blocker.message
        return self.tr("Double-click or press Enter to %1.").replace("%1", row_state.primary_action.label)

    def _fit_table_height(self) -> None:
        fit_table_height_to_rows(self.rows_table, max_visible_rows=self._TABLE_MAX_VISIBLE_ROWS)

    def _ensure_row_heights(self) -> None:
        self.rows_table.resizeRowsToContents()
        for row in range(self.rows_table.rowCount()):
            self.rows_table.setRowHeight(row, max(self.rows_table.rowHeight(row), 44))

    def _select_files(self) -> None:
        file_paths, _selected = QFileDialog.getOpenFileNames(
            self,
            self.tr("Select Document File(s)"),
            str(Path.home()),
            self.tr("All Files (*.*)"),
        )
        if file_paths:
            self._inspect_import_paths(file_paths)

    def _select_folder(self) -> None:
        folder_path = QFileDialog.getExistingDirectory(
            self,
            self.tr("Select Document Folder"),
            str(Path.home()),
        )
        if folder_path:
            self._inspect_import_paths([folder_path])

    def _inspect_import_paths(self, paths: list[str]) -> None:
        self._selected_import_paths = list(paths)
        state = self._work_service.inspect_import_paths(
            InspectImportPathsRequest(project_id=self._project_id, paths=paths)
        )
        self._import_options = [(option.document_type, option.label) for option in state.available_types]
        self._selected_import_type = self._import_options[0][0] if self._import_options else None
        self._can_import = bool(self._import_options)
        self._import_summary = state.summary or self._default_import_summary()
        if state.error_message:
            self._set_import_message(state.error_message, is_error=True)
        else:
            self._set_import_message("", is_error=False)

    def _run_import(self) -> None:
        if not self._selected_import_paths:
            return
        document_type = self._selected_import_type
        try:
            result = self._work_service.import_documents(
                ImportDocumentsRequest(
                    project_id=self._project_id,
                    paths=self._selected_import_paths,
                    document_type=str(document_type) if document_type else None,
                )
            )
        except BlockedOperationError as exc:
            self._set_import_message(exc.payload.message, is_error=True)
            return
        except ApplicationError as exc:
            self._set_import_message(exc.payload.message, is_error=True)
            return
        self._set_import_message(
            result.message.text if result.message is not None else self.tr("Import complete."),
            is_error=False,
        )
        self._selected_import_paths = []
        self._import_options = []
        self._selected_import_type = None
        self._can_import = False
        self._import_summary = self._default_import_summary()
        self._sync_import_chrome_state()
        self.refresh()

    def _set_import_message(self, text: str, *, is_error: bool) -> None:
        self._import_message_is_error = is_error
        self._import_message = text
        self._sync_import_chrome_state()

    def _connect_qml_signals(self) -> None:
        root = self.chrome_host.rootObject()
        if root is None:
            return
        root.selectFilesRequested.connect(self._select_files)
        root.selectFolderRequested.connect(self._select_folder)
        root.importRequested.connect(self._run_import)
        root.setupActionRequested.connect(self._on_setup_action_clicked)
        root.importTypeSelected.connect(self._on_import_type_selected)

    def _on_import_type_selected(self, document_type: str) -> None:
        if document_type not in {option[0] for option in self._import_options}:
            return
        self._selected_import_type = document_type
        self._sync_import_chrome_state()

    def _sync_import_chrome_state(self) -> None:
        self.viewmodel.set_import_state(
            summary=self._import_summary.strip() or self._default_import_summary(),
            message=self._import_message.strip(),
            is_error=self._import_message_is_error,
            can_import=self._can_import,
            options=self._import_options,
            selected_import_type=self._selected_import_type,
        )
        self._schedule_chrome_resize()

    def _default_import_summary(self) -> str:
        return self.tr("No file or folder selected")

    def _schedule_chrome_resize(self) -> None:
        self._sync_chrome_height()
        QTimer.singleShot(0, self._sync_chrome_height)

    def _sync_chrome_height(self) -> None:
        sync_qml_host_height(self.chrome_host)

    def _selected_row_state(self) -> WorkDocumentRow | None:
        row = self.rows_table.currentRow()
        if row < 0 or row >= len(self._row_states):
            return None
        return self._row_states[row]

    def _on_selection_changed(self) -> None:
        selected = self._selected_row_state()
        enabled = selected is not None
        self.reset_document_button.setEnabled(enabled)
        self.delete_document_button.setEnabled(enabled)

    def _reset_selected_document(self) -> None:
        selected = self._selected_row_state()
        if selected is None:
            return
        reply = QMessageBox.warning(
            self,
            self.tr("Reset Document"),
            self.tr(
                "This will reset the selected document and all documents added after it. Glossary data, translations, and OCR state for affected documents will be cleared. Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            result = self._work_service.reset_document_stack(
                ResetDocumentStackRequest(project_id=self._project_id, document_id=selected.document.document_id)
            )
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Reset Document"), exc.payload.message)
            return
        QMessageBox.information(self, self.tr("Reset Complete"), result.message.text)
        self.refresh()

    def _delete_selected_document(self) -> None:
        selected = self._selected_row_state()
        if selected is None:
            return
        reply = QMessageBox.warning(
            self,
            self.tr("Delete Document"),
            self.tr(
                "This will permanently delete the selected document and all documents added after it. This cannot be undone. Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            result = self._work_service.delete_document_stack(
                DeleteDocumentStackRequest(project_id=self._project_id, document_id=selected.document.document_id)
            )
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Delete Document"), exc.payload.message)
            return
        QMessageBox.information(self, self.tr("Delete Complete"), result.message.text)
        self.refresh()

    def _on_cell_double_clicked(self, row: int, _column: int) -> None:
        if row < 0 or row >= len(self._row_states):
            return
        self._handle_row_action(self._row_states[row])

    def _handle_row_action(self, row_state: WorkDocumentRow) -> None:
        action = row_state.primary_action
        if action.kind is DocumentRowActionKind.BLOCKED:
            return
        if action.kind is DocumentRowActionKind.EXPORT:
            self._open_export_dialog(row_state.document.document_id)
            return
        if action.target is None:
            return
        self.open_navigation_target(action.target)

    def _open_document_workspace(self, document_id: int, section: DocumentSection) -> None:
        if self._document_view is None or self._document_view.document_id != document_id:
            if self._document_view is not None:
                self._document_view.cleanup()
                self.stack.removeWidget(self._document_view)
                self._document_view.deleteLater()
            self._document_view = DocumentWorkspaceView(
                self._project_id,
                document_id,
                self._document_service,
                self._terms_service,
                self._work_service,
                self._events,
                parent=self,
            )
            self._document_view.back_requested.connect(self._show_home)
            self._document_view.open_app_setup_requested.connect(self.open_app_setup_requested.emit)
            self._document_view.open_project_setup_requested.connect(self.open_project_setup_requested.emit)
            self.stack.addWidget(self._document_view)
        self._document_view.show_section(section)
        self.stack.setCurrentWidget(self._document_view)

    def _show_home(self) -> None:
        self.stack.setCurrentWidget(self.home_page)

    def open_navigation_target(self, target: NavigationTarget) -> None:
        if target.kind is NavigationTargetKind.APP_SETUP:
            self.open_app_setup_requested.emit()
            return
        if target.kind is NavigationTargetKind.PROJECT_SETUP:
            self.open_project_setup_requested.emit()
            return
        if target.kind is NavigationTargetKind.WORK:
            self._show_home()
            return
        if target.document_id is None:
            return
        section = self._section_for_target(target)
        if section is None:
            return
        self._open_document_workspace(target.document_id, section)

    def _section_for_target(self, target: NavigationTarget) -> DocumentSection | None:
        return _TARGET_TO_SECTION.get(target.kind)

    def _open_export_dialog(self, document_id: int) -> None:
        from context_aware_translation.application.contracts.work import PrepareExportRequest

        try:
            state = self._work_service.prepare_export(
                PrepareExportRequest(project_id=self._project_id, document_ids=[document_id])
            )
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Export"), exc.payload.message)
            return
        dialog = WorkExportDialog(self._work_service, state, parent=self)
        dialog.exec()

    def _setup_action_label(self, blocker: BlockerInfo) -> str:
        if blocker.target is not None and blocker.target.kind is NavigationTargetKind.APP_SETUP:
            return self.tr("Open App Setup")
        return self.tr("Open Setup")

    def _on_setup_action_clicked(self) -> None:
        target = self._state.setup_blocker.target if self._state is not None and self._state.setup_blocker else None
        if target is None:
            return
        self.open_navigation_target(target)

    def _on_workboard_invalidated(self, event: WorkboardInvalidatedEvent) -> None:
        if event.project_id not in {None, self._project_id}:
            return
        self.refresh()

    def _on_setup_invalidated(self, event: SetupInvalidatedEvent) -> None:
        if event.project_id not in {None, self._project_id}:
            return
        self.refresh()


__all__ = ["WorkView"]
