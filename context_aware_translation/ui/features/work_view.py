from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
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
from context_aware_translation.application.contracts.document import DocumentOverviewState
from context_aware_translation.application.contracts.terms import TermsTableState
from context_aware_translation.application.contracts.work import ExportDialogState, WorkboardState, WorkDocumentRow
from context_aware_translation.application.errors import ApplicationError
from context_aware_translation.application.events import (
    ApplicationEventSubscriber,
    DocumentInvalidatedEvent,
    SetupInvalidatedEvent,
    WorkboardInvalidatedEvent,
)
from context_aware_translation.application.services.document import DocumentService
from context_aware_translation.application.services.terms import TermsService
from context_aware_translation.application.services.work import WorkService
from context_aware_translation.ui.adapters import QtApplicationEventBridge
from context_aware_translation.ui.i18n import qarg
from context_aware_translation.ui.utils import create_tip_label

_STATUS_LABELS: dict[SurfaceStatus, str] = {
    SurfaceStatus.READY: "Ready",
    SurfaceStatus.RUNNING: "Running",
    SurfaceStatus.BLOCKED: "Blocked",
    SurfaceStatus.FAILED: "Failed",
    SurfaceStatus.DONE: "Done",
    SurfaceStatus.CANCELLED: "Cancelled",
}

_STATUS_COLORS: dict[SurfaceStatus, str] = {
    SurfaceStatus.READY: "#2563eb",
    SurfaceStatus.RUNNING: "#b45309",
    SurfaceStatus.BLOCKED: "#b91c1c",
    SurfaceStatus.FAILED: "#b91c1c",
    SurfaceStatus.DONE: "#15803d",
    SurfaceStatus.CANCELLED: "#6b7280",
}

_SECTION_LABELS: dict[DocumentSection, str] = {
    DocumentSection.OVERVIEW: "Overview",
    DocumentSection.OCR: "OCR",
    DocumentSection.TERMS: "Terms",
    DocumentSection.TRANSLATION: "Translation",
    DocumentSection.IMAGES: "Images",
    DocumentSection.EXPORT: "Export",
}

_TARGET_TO_SECTION: dict[NavigationTargetKind, DocumentSection] = {
    NavigationTargetKind.DOCUMENT_OVERVIEW: DocumentSection.OVERVIEW,
    NavigationTargetKind.DOCUMENT_OCR: DocumentSection.OCR,
    NavigationTargetKind.DOCUMENT_TERMS: DocumentSection.TERMS,
    NavigationTargetKind.DOCUMENT_TRANSLATION: DocumentSection.TRANSLATION,
    NavigationTargetKind.DOCUMENT_IMAGES: DocumentSection.IMAGES,
    NavigationTargetKind.DOCUMENT_EXPORT: DocumentSection.EXPORT,
}


class _StatusChip(QLabel):
    def set_status(self, status: SurfaceStatus) -> None:
        self.setText(self.tr(_STATUS_LABELS[status]))
        color = _STATUS_COLORS[status]
        self.setStyleSheet(
            f"QLabel {{ background-color: {color}; color: white; border-radius: 10px; padding: 2px 8px; font-weight: 600; }}"
        )


class WorkExportDialog(QDialog):
    def __init__(
        self,
        service: WorkService,
        state: ExportDialogState,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._state = state
        self.setWindowTitle(self.tr("Export"))
        self.resize(520, 220)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        docs_label = QLabel(
            qarg(self.tr("Export %1"), ", ".join(self._state.document_labels))
            if self._state.document_labels
            else self.tr("Export selected documents")
        )
        docs_label.setWordWrap(True)
        docs_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(docs_label)

        self.blocker_label = create_tip_label(self._state.blocker.message if self._state.blocker is not None else "")
        self.blocker_label.setVisible(self._state.blocker is not None)
        layout.addWidget(self.blocker_label)

        form = QFormLayout()
        self.format_combo = QComboBox()
        default_index = 0
        for index, option in enumerate(self._state.available_formats):
            self.format_combo.addItem(option.label, option.format_id)
            if option.is_default:
                default_index = index
        if self._state.available_formats:
            self.format_combo.setCurrentIndex(default_index)
        self.output_path_edit = QLineEdit(self._state.default_output_path or "")
        form.addRow(self.tr("Format"), self.format_combo)
        form.addRow(self.tr("Output path"), self.output_path_edit)
        layout.addLayout(form)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.export_button = self.button_box.addButton(self.tr("Export"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.export_button.clicked.connect(self._run_export)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        can_export = self._state.blocker is None and bool(self._state.available_formats)
        self.export_button.setEnabled(can_export)

    def _run_export(self) -> None:
        output_path = self.output_path_edit.text().strip()
        if not output_path:
            QMessageBox.warning(self, self.tr("Missing Information"), self.tr("Output path is required."))
            return
        from context_aware_translation.application.contracts.work import RunExportRequest

        format_id = str(self.format_combo.currentData() or "").strip()
        if not format_id:
            QMessageBox.warning(self, self.tr("Missing Information"), self.tr("Export format is required."))
            return
        try:
            result = self._service.run_export(
                RunExportRequest(
                    project_id=self._state.project_id,
                    document_ids=self._state.document_ids,
                    format_id=format_id,
                    output_path=output_path,
                )
            )
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Export Failed"), exc.payload.message)
            return
        QMessageBox.information(self, self.tr("Export Complete"), result.message.text if result.message is not None else result.output_path)
        self.accept()


class _DocumentOverviewTab(QWidget):
    def __init__(self, service: DocumentService, project_id: str, document_id: int, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._project_id = project_id
        self._document_id = document_id
        self._cards: list[QFrame] = []
        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.tip_label = create_tip_label(
            self.tr("Overview summarizes the current document and links the rest of the document-scoped tools."),
        )
        layout.addWidget(self.tip_label)
        self.cards_host = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_host)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(12)
        layout.addWidget(self.cards_host)
        layout.addStretch()

    def refresh(self) -> None:
        state = self._service.get_overview(self._project_id, self._document_id)
        self._apply_state(state)

    def _apply_state(self, state: DocumentOverviewState) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards.clear()
        for section in state.sections:
            card = QFrame()
            card.setFrameShape(QFrame.Shape.StyledPanel)
            card.setStyleSheet("QFrame { border: 1px solid #d8dee9; border-radius: 6px; }")
            card_layout = QVBoxLayout(card)
            title = QLabel(self.tr(_SECTION_LABELS[section.section]))
            title.setStyleSheet("font-weight: 600;")
            status = _StatusChip()
            status.set_status(section.status)
            summary = QLabel(section.summary)
            summary.setWordWrap(True)
            card_layout.addWidget(title)
            card_layout.addWidget(status)
            card_layout.addWidget(summary)
            if section.blocker is not None:
                blocker = create_tip_label(section.blocker.message)
                blocker.setStyleSheet("QLabel { color: #b42318; }")
                card_layout.addWidget(blocker)
            self.cards_layout.addWidget(card)
            self._cards.append(card)
        self.cards_layout.addStretch(1)


class _DocumentTermsTab(QWidget):
    def __init__(
        self,
        service: TermsService,
        project_id: str,
        document_id: int,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._project_id = project_id
        self._document_id = document_id
        self._state: TermsTableState | None = None
        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.build_button = QPushButton(self.tr("Build Terms"))
        self.build_button.clicked.connect(self._on_build_terms)
        toolbar.addWidget(self.build_button)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.summary_label = create_tip_label("")
        layout.addWidget(self.summary_label)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            [self.tr("Term"), self.tr("Translation"), self.tr("Status"), self.tr("Occurrences"), self.tr("Notes")]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        layout.addWidget(self.table, 1)

    def refresh(self) -> None:
        self._apply_state(self._service.get_document_terms(self._project_id, self._document_id))

    def _apply_state(self, state: TermsTableState) -> None:
        self._state = state
        self.summary_label.setText(
            self.tr("Build Terms extracts glossary terms for this document. Editing shared terms will attach in a later migration task.")
        )
        self.build_button.setEnabled(state.toolbar.can_build)
        self.build_button.setToolTip(state.toolbar.build_blocker.message if state.toolbar.build_blocker is not None else "")

        self.table.setRowCount(0)
        for row_state in state.rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(row_state.term))
            self.table.setItem(row, 1, QTableWidgetItem(row_state.translation or ""))
            self.table.setItem(row, 2, QTableWidgetItem(row_state.status.value.replace("_", " ").title()))
            self.table.setItem(row, 3, QTableWidgetItem(str(row_state.occurrences)))
            self.table.setItem(row, 4, QTableWidgetItem(row_state.description or ""))
        self.table.resizeColumnsToContents()

    def _on_build_terms(self) -> None:
        from context_aware_translation.application.contracts.terms import BuildTermsRequest

        try:
            self._service.build_terms(BuildTermsRequest(project_id=self._project_id, document_id=self._document_id))
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Build Terms Failed"), exc.payload.message)
            return
        QMessageBox.information(self, self.tr("Build Terms"), self.tr("Terms extraction queued for this document."))


class _PlaceholderDocumentTab(QWidget):
    def __init__(self, title: str, description: str, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        heading = QLabel(f"<h3>{title}</h3>")
        body = QLabel(description)
        body.setWordWrap(True)
        body.setStyleSheet("color: #666666;")
        layout.addWidget(heading)
        layout.addWidget(body)
        layout.addStretch()


class _DocumentExportTab(QWidget):
    def __init__(self, project_id: str, document_id: int, service: WorkService, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project_id = project_id
        self._document_id = document_id
        self._service = service
        layout = QVBoxLayout(self)
        self.tip_label = create_tip_label(
            self.tr("Export can be started here or directly from the Work list. The export execution backend is still transitional."),
        )
        layout.addWidget(self.tip_label)
        self.export_button = QPushButton(self.tr("Export This Document"))
        self.export_button.clicked.connect(self._open_export_dialog)
        layout.addWidget(self.export_button)
        layout.addStretch()

    def _open_export_dialog(self) -> None:
        from context_aware_translation.application.contracts.work import PrepareExportRequest

        try:
            state = self._service.prepare_export(
                PrepareExportRequest(project_id=self._project_id, document_ids=[self._document_id])
            )
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Export"), exc.payload.message)
            return
        dialog = WorkExportDialog(self._service, state, parent=self)
        dialog.exec()


class DocumentWorkspaceView(QWidget):
    back_requested = Signal()

    def __init__(
        self,
        project_id: str,
        document_id: int,
        document_service: DocumentService,
        terms_service: TermsService,
        work_service: WorkService,
        events: ApplicationEventSubscriber,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project_id = project_id
        self._document_id = document_id
        self._document_service = document_service
        self._terms_service = terms_service
        self._work_service = work_service
        self._state = self._document_service.get_workspace(project_id, document_id)
        self._event_bridge = QtApplicationEventBridge(events, parent=self)
        self._event_bridge.document_invalidated.connect(self._on_document_invalidated)
        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-size: 18px; font-weight: 600;")
        header.addWidget(self.title_label)
        header.addStretch()
        self.back_button = QPushButton("\u2190 " + self.tr("Back to Work"))
        self.back_button.clicked.connect(self.back_requested.emit)
        header.addWidget(self.back_button)
        layout.addLayout(header)

        self.tip_label = create_tip_label(self._tip_text())
        layout.addWidget(self.tip_label)

        self.tab_widget = QTabWidget()
        self._tab_indexes: dict[DocumentSection, int] = {}
        self._build_tabs()
        layout.addWidget(self.tab_widget, 1)

    def _build_tabs(self) -> None:
        for section in self._state.available_tabs:
            widget = self._make_tab_widget(section)
            self._tab_indexes[section] = self.tab_widget.addTab(widget, self.tr(_SECTION_LABELS[section]))

    def _make_tab_widget(self, section: DocumentSection) -> QWidget:
        if section is DocumentSection.OVERVIEW:
            return _DocumentOverviewTab(self._document_service, self._project_id, self._document_id, parent=self)
        if section is DocumentSection.TERMS:
            return _DocumentTermsTab(self._terms_service, self._project_id, self._document_id, parent=self)
        if section is DocumentSection.EXPORT:
            return _DocumentExportTab(self._project_id, self._document_id, self._work_service, parent=self)
        return _PlaceholderDocumentTab(
            self.tr(_SECTION_LABELS[section]),
            self.tr("This document-scoped surface will be attached in a later migration task."),
            parent=self,
        )

    def refresh(self) -> None:
        self._state = self._document_service.get_workspace(self._project_id, self._document_id)
        self.title_label.setText(qarg(self.tr("%1"), self._state.document.label))
        for index in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(index)
            if widget is not None and hasattr(widget, "refresh"):
                widget.refresh()

    def show_section(self, section: DocumentSection) -> None:
        index = self._tab_indexes.get(section)
        if index is not None:
            self.tab_widget.setCurrentIndex(index)

    def cleanup(self) -> None:
        self._event_bridge.close()
        for index in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(index)
            if widget is not None and hasattr(widget, "cleanup"):
                widget.cleanup()

    def get_running_operations(self) -> list[str]:
        current_widget = self.tab_widget.currentWidget()
        if current_widget is not None and hasattr(current_widget, "get_running_operations"):
            running = current_widget.get_running_operations()
            if isinstance(running, list):
                return running
        return []

    def request_cancel_running_operations(self, *, include_engine_tasks: bool = False) -> None:
        current_widget = self.tab_widget.currentWidget()
        if current_widget is not None and hasattr(current_widget, "request_cancel_running_operations"):
            current_widget.request_cancel_running_operations(include_engine_tasks=include_engine_tasks)

    def _on_document_invalidated(self, event: DocumentInvalidatedEvent) -> None:
        if event.project_id not in {None, self._project_id}:
            return
        if event.document_id not in {None, self._document_id}:
            return
        self.refresh()

    def _tip_text(self) -> str:
        return self.tr("These tools apply only to the current document.")


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
            self.tr("Work shows the ordered document stack, the current context frontier, and the next action for each document."),
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
        self.setup_strip.setStyleSheet("QFrame { border: 1px solid #fed7aa; background-color: #fff7ed; border-radius: 6px; }")
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

        self.empty_label = create_tip_label(self.tr("No documents imported yet. Import will attach to Work in a later migration task."))
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
            self.tr("Work shows the ordered document stack, the current context frontier, and the next action for each document."),
        )
        self.rows_table.setHorizontalHeaderLabels(
            [self.tr("#"), self.tr("Document"), self.tr("Status"), self.tr("State"), self.tr("Action")]
        )
        self.empty_label.setText(self.tr("No documents imported yet. Import will attach to Work in a later migration task."))
        if self._document_view is not None:
            self._document_view.back_button.setText("\u2190 " + self.tr("Back to Work"))

    def _apply_state(self, state: WorkboardState) -> None:
        self._state = state
        self.context_label.setText(state.context_frontier.summary if state.context_frontier is not None else self.tr("Context not ready yet."))
        blocker_text = state.context_frontier.blocker.message if state.context_frontier and state.context_frontier.blocker is not None else ""
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
        if self._document_view is None or self._document_view._document_id != document_id:
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
