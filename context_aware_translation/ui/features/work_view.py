from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.application.contracts.common import (
    BlockerInfo,
    DocumentRowActionKind,
    DocumentSection,
    NavigationTarget,
    NavigationTargetKind,
    SurfaceStatus,
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
from context_aware_translation.ui.adapters import QtApplicationEventBridge
from context_aware_translation.ui.features.document_workspace_view import DocumentWorkspaceView, WorkExportDialog
from context_aware_translation.ui.utils import create_tip_label

_STATUS_LABELS: dict[SurfaceStatus, str] = {
    SurfaceStatus.READY: "Ready",
    SurfaceStatus.RUNNING: "Running",
    SurfaceStatus.BLOCKED: "Blocked",
    SurfaceStatus.FAILED: "Failed",
    SurfaceStatus.DONE: "Done",
    SurfaceStatus.CANCELLED: "Cancelled",
}

_TARGET_TO_SECTION: dict[NavigationTargetKind, DocumentSection] = {
    NavigationTargetKind.DOCUMENT_OCR: DocumentSection.OCR,
    NavigationTargetKind.DOCUMENT_TERMS: DocumentSection.TERMS,
    NavigationTargetKind.DOCUMENT_TRANSLATION: DocumentSection.TRANSLATION,
    NavigationTargetKind.DOCUMENT_IMAGES: DocumentSection.IMAGES,
    NavigationTargetKind.DOCUMENT_EXPORT: DocumentSection.EXPORT,
}


class WorkView(QWidget):
    _TABLE_MAX_VISIBLE_ROWS = 10

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

        self.tip_label = create_tip_label(
            self.tr(
                "Import documents here, review project-wide progress, and open the next document tool directly from the table."
            )
        )
        home_layout.addWidget(self.tip_label)

        self.import_strip = QFrame()
        self.import_strip.setFrameShape(QFrame.Shape.StyledPanel)
        import_layout = QVBoxLayout(self.import_strip)
        import_buttons = QHBoxLayout()
        self.select_files_button = QPushButton(self.tr("Select Files"))
        self.select_files_button.clicked.connect(self._select_files)
        import_buttons.addWidget(self.select_files_button)
        self.select_folder_button = QPushButton(self.tr("Select Folder"))
        self.select_folder_button.clicked.connect(self._select_folder)
        import_buttons.addWidget(self.select_folder_button)
        self.import_type_combo = QComboBox()
        self.import_type_combo.setEnabled(False)
        import_buttons.addWidget(self.import_type_combo, 1)
        self.import_button = QPushButton(self.tr("Import"))
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self._run_import)
        import_buttons.addWidget(self.import_button)
        import_layout.addLayout(import_buttons)
        self.import_summary_label = QLabel(self.tr("No file or folder selected"))
        self.import_summary_label.setWordWrap(True)
        import_layout.addWidget(self.import_summary_label)
        self.import_message_label = QLabel()
        self.import_message_label.setWordWrap(True)
        self.import_message_label.hide()
        import_layout.addWidget(self.import_message_label)
        home_layout.addWidget(self.import_strip)

        self.context_strip = QFrame()
        self.context_strip.setFrameShape(QFrame.Shape.StyledPanel)
        self.context_strip.setStyleSheet("QFrame { border: 1px solid #d8dee9; border-radius: 6px; }")
        context_layout = QVBoxLayout(self.context_strip)
        self.context_label = QLabel()
        self.context_label.setStyleSheet("font-weight: 600;")
        self.blocker_label = QLabel()
        self.blocker_label.setWordWrap(True)
        self.blocker_label.setStyleSheet("color: #b42318;")
        context_layout.addWidget(self.context_label)
        context_layout.addWidget(self.blocker_label)
        home_layout.addWidget(self.context_strip)

        self.setup_strip = QFrame()
        self.setup_strip.setFrameShape(QFrame.Shape.StyledPanel)
        self.setup_strip.setStyleSheet(
            "QFrame { border: 1px solid #fed7aa; background-color: #fff7ed; border-radius: 6px; }"
        )
        setup_layout = QHBoxLayout(self.setup_strip)
        self.setup_label = QLabel()
        self.setup_label.setWordWrap(True)
        self.setup_action_button = QPushButton()
        self.setup_action_button.clicked.connect(self._on_setup_action_clicked)
        setup_layout.addWidget(self.setup_label, 1)
        setup_layout.addWidget(self.setup_action_button)
        home_layout.addWidget(self.setup_strip)

        self.rows_table = QTableWidget(0, 8)
        self.rows_table.setHorizontalHeaderLabels(
            [
                self.tr("#"),
                self.tr("Document"),
                self.tr("Sources"),
                self.tr("OCR"),
                self.tr("Terms"),
                self.tr("Translation"),
                self.tr("State"),
                self.tr("Action"),
            ]
        )
        self.rows_table.verticalHeader().setVisible(False)
        self.rows_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.rows_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.rows_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.rows_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.rows_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.rows_table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        home_layout.addWidget(self.rows_table)

        row_actions = QHBoxLayout()
        self.reset_document_button = QPushButton(self.tr("Reset Document"))
        self.reset_document_button.setEnabled(False)
        self.reset_document_button.clicked.connect(self._reset_selected_document)
        row_actions.addWidget(self.reset_document_button)
        self.delete_document_button = QPushButton(self.tr("Delete Document"))
        self.delete_document_button.setEnabled(False)
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

    def retranslateUi(self) -> None:
        self.tip_label.setText(
            self.tr(
                "Import documents here, review project-wide progress, and open the next document tool directly from the table."
            )
        )
        self.select_files_button.setText(self.tr("Select Files"))
        self.select_folder_button.setText(self.tr("Select Folder"))
        self.import_button.setText(self.tr("Import"))
        self.import_summary_label.setText(
            self.tr("No file or folder selected")
            if not self._selected_import_paths
            else self.import_summary_label.text()
        )
        self.rows_table.setHorizontalHeaderLabels(
            [
                self.tr("#"),
                self.tr("Document"),
                self.tr("Sources"),
                self.tr("OCR"),
                self.tr("Terms"),
                self.tr("Translation"),
                self.tr("State"),
                self.tr("Action"),
            ]
        )
        self.reset_document_button.setText(self.tr("Reset Document"))
        self.delete_document_button.setText(self.tr("Delete Document"))
        self.empty_label.setText(self.tr("No documents imported yet."))
        if self._document_view is not None:
            self._document_view.back_button.setText("\u2190 " + self.tr("Back to Work"))

    def _apply_state(self, state: WorkboardState) -> None:
        self._state = state
        self.context_label.setText(
            state.context_frontier.summary if state.context_frontier is not None else self.tr("Context not ready yet.")
        )
        blocker_text = (
            state.context_frontier.blocker.message
            if state.context_frontier and state.context_frontier.blocker is not None
            else ""
        )
        self.blocker_label.setText(blocker_text)
        self.blocker_label.setVisible(bool(blocker_text))

        if state.setup_blocker is not None:
            self.setup_label.setText(state.setup_blocker.message)
            self.setup_action_button.setText(self._setup_action_label(state.setup_blocker))
            self.setup_action_button.setVisible(True)
            self.setup_strip.setVisible(True)
        else:
            self.setup_strip.hide()

        self.rows_table.setRowCount(0)
        self._row_states = list(state.rows)
        self.empty_label.setVisible(not state.rows)
        for row_state in state.rows:
            self._append_row(row_state)
        self.rows_table.resizeColumnsToContents()
        self.rows_table.horizontalHeader().setStretchLastSection(False)
        self.rows_table.horizontalHeader().resizeSection(1, 260)
        self.rows_table.horizontalHeader().resizeSection(6, 260)
        self._fit_table_height()
        self._on_selection_changed()

    def _append_row(self, row_state: WorkDocumentRow) -> None:
        row = self.rows_table.rowCount()
        self.rows_table.insertRow(row)
        document_item = QTableWidgetItem(row_state.document.label)
        document_item.setData(Qt.ItemDataRole.UserRole, row_state.document.document_id)
        self.rows_table.setItem(row, 0, QTableWidgetItem(str(row_state.document.order_index)))
        self.rows_table.setItem(row, 1, document_item)
        self.rows_table.setItem(row, 2, QTableWidgetItem(str(row_state.source_count)))
        self.rows_table.setItem(row, 3, QTableWidgetItem(row_state.ocr_status))
        self.rows_table.setItem(row, 4, QTableWidgetItem(row_state.terms_status))
        self.rows_table.setItem(row, 5, QTableWidgetItem(row_state.translation_status))
        summary_text = row_state.state_summary
        if row_state.blocker is not None and row_state.blocker.message not in summary_text:
            summary_text = f"{summary_text}\n{row_state.blocker.message}"
        summary_item = QTableWidgetItem(summary_text)
        summary_item.setToolTip(row_state.blocker.message if row_state.blocker is not None else row_state.state_summary)
        self.rows_table.setItem(row, 6, summary_item)

        button = QPushButton(row_state.primary_action.label)
        button.setEnabled(row_state.primary_action.kind is not DocumentRowActionKind.BLOCKED)
        button.clicked.connect(lambda _checked=False, item=row_state: self._handle_row_action(item))
        self.rows_table.setCellWidget(row, 7, button)

    def _fit_table_height(self) -> None:
        header_height = self.rows_table.horizontalHeader().height()
        frame_height = self.rows_table.frameWidth() * 2
        row_count = self.rows_table.rowCount()
        if row_count == 0:
            self.rows_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.rows_table.setFixedHeight(header_height + frame_height + 8)
            return
        row_heights = [self.rows_table.rowHeight(index) for index in range(row_count)]
        visible_rows = min(row_count, self._TABLE_MAX_VISIBLE_ROWS)
        visible_height = sum(row_heights[:visible_rows])
        self.rows_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            if row_count <= self._TABLE_MAX_VISIBLE_ROWS
            else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.rows_table.setFixedHeight(header_height + visible_height + frame_height + 8)

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
        self.import_type_combo.clear()
        for option in state.available_types:
            self.import_type_combo.addItem(option.label, option.document_type)
        self.import_type_combo.setEnabled(bool(state.available_types))
        self.import_button.setEnabled(bool(state.available_types))
        self.import_summary_label.setText(state.summary or self.tr("No file or folder selected"))
        if state.error_message:
            self._set_import_message(state.error_message, is_error=True)
        else:
            self._set_import_message("", is_error=False)

    def _run_import(self) -> None:
        if not self._selected_import_paths:
            return
        document_type = self.import_type_combo.currentData()
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
        self.import_type_combo.clear()
        self.import_type_combo.setEnabled(False)
        self.import_button.setEnabled(False)
        self.import_summary_label.setText(self.tr("No file or folder selected"))
        self.refresh()

    def _set_import_message(self, text: str, *, is_error: bool) -> None:
        if not text:
            self.import_message_label.hide()
            self.import_message_label.clear()
            return
        color = "#b42318" if is_error else "#027a48"
        self.import_message_label.setStyleSheet(f"QLabel {{ color: {color}; font-weight: 600; }}")
        self.import_message_label.setText(text)
        self.import_message_label.show()

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
        if action.kind is DocumentRowActionKind.FIX_SETUP:
            self._route_setup_target(action.target)
            return
        if action.target is None or action.target.document_id is None:
            return
        section = self._section_for_target(action.target)
        if section is None:
            return
        self._open_document_workspace(action.target.document_id, section)

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
        if target.kind is NavigationTargetKind.DOCUMENT_OVERVIEW:
            workspace = self._document_service.get_workspace(self._project_id, target.document_id or 0)
            for section in workspace.available_tabs:
                if section is not DocumentSection.OVERVIEW:
                    return section
            return None
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

    def _route_setup_target(self, target: NavigationTarget | None) -> None:
        if target is None:
            return
        if target.kind is NavigationTargetKind.APP_SETUP:
            self.open_app_setup_requested.emit()
        else:
            self.open_project_setup_requested.emit()

    def _setup_action_label(self, blocker: BlockerInfo) -> str:
        if blocker.target is not None and blocker.target.kind is NavigationTargetKind.APP_SETUP:
            return self.tr("Open App Setup")
        return self.tr("Open Setup")

    def _on_setup_action_clicked(self) -> None:
        if self._state is None:
            return
        self._route_setup_target(self._state.setup_blocker.target if self._state.setup_blocker is not None else None)

    def _on_workboard_invalidated(self, event: WorkboardInvalidatedEvent) -> None:
        if event.project_id not in {None, self._project_id}:
            return
        self.refresh()

    def _on_setup_invalidated(self, event: SetupInvalidatedEvent) -> None:
        if event.project_id not in {None, self._project_id}:
            return
        self.refresh()


__all__ = ["WorkView"]
