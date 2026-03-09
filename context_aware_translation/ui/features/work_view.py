from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
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

from context_aware_translation.application.contracts.common import (
    BlockerInfo,
    DocumentRowActionKind,
    DocumentSection,
    NavigationTarget,
    NavigationTargetKind,
    SurfaceStatus,
)
from context_aware_translation.application.contracts.work import WorkboardState, WorkDocumentRow
from context_aware_translation.application.errors import ApplicationError
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
    NavigationTargetKind.DOCUMENT_OVERVIEW: DocumentSection.OVERVIEW,
    NavigationTargetKind.DOCUMENT_OCR: DocumentSection.OCR,
    NavigationTargetKind.DOCUMENT_TERMS: DocumentSection.TERMS,
    NavigationTargetKind.DOCUMENT_TRANSLATION: DocumentSection.TRANSLATION,
    NavigationTargetKind.DOCUMENT_IMAGES: DocumentSection.IMAGES,
    NavigationTargetKind.DOCUMENT_EXPORT: DocumentSection.EXPORT,
}


class WorkView(QWidget):
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
        self._document_view: DocumentWorkspaceView | None = None
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
                "Work shows the ordered document stack, the current context frontier, and the next action for each document."
            ),
        )
        home_layout.addWidget(self.tip_label)

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

        self.rows_table = QTableWidget(0, 5)
        self.rows_table.setHorizontalHeaderLabels(
            [self.tr("#"), self.tr("Document"), self.tr("Status"), self.tr("State"), self.tr("Action")]
        )
        self.rows_table.verticalHeader().setVisible(False)
        self.rows_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.rows_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        home_layout.addWidget(self.rows_table, 1)

        self.empty_label = create_tip_label(self.tr("No documents imported yet."))
        self.empty_label.hide()
        home_layout.addWidget(self.empty_label)

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
                "Work shows the ordered document stack, the current context frontier, and the next action for each document."
            ),
        )
        self.rows_table.setHorizontalHeaderLabels(
            [self.tr("#"), self.tr("Document"), self.tr("Status"), self.tr("State"), self.tr("Action")]
        )
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
        self.empty_label.setVisible(not state.rows)
        for row_state in state.rows:
            self._append_row(row_state)
        self.rows_table.resizeColumnsToContents()

    def _append_row(self, row_state: WorkDocumentRow) -> None:
        row = self.rows_table.rowCount()
        self.rows_table.insertRow(row)
        self.rows_table.setItem(row, 0, QTableWidgetItem(str(row_state.document.order_index)))
        self.rows_table.setItem(row, 1, QTableWidgetItem(row_state.document.label))
        status_item = QTableWidgetItem(self.tr(_STATUS_LABELS[row_state.status]))
        status_item.setForeground(Qt.GlobalColor.black)
        self.rows_table.setItem(row, 2, status_item)
        summary_text = row_state.state_summary
        if row_state.blocker is not None and row_state.blocker.message not in summary_text:
            summary_text = f"{summary_text}\n{row_state.blocker.message}"
        summary_item = QTableWidgetItem(summary_text)
        summary_item.setToolTip(row_state.blocker.message if row_state.blocker is not None else row_state.state_summary)
        self.rows_table.setItem(row, 3, summary_item)

        button = QPushButton(row_state.primary_action.label)
        button.setEnabled(row_state.primary_action.kind is not DocumentRowActionKind.BLOCKED)
        button.clicked.connect(lambda _checked=False, item=row_state: self._handle_row_action(item))
        self.rows_table.setCellWidget(row, 4, button)

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
        if action.target is None:
            return
        section = _TARGET_TO_SECTION.get(action.target.kind)
        if section is None or action.target.document_id is None:
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
        section = _TARGET_TO_SECTION.get(target.kind)
        if section is None or target.document_id is None:
            return
        self._open_document_workspace(target.document_id, section)

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
