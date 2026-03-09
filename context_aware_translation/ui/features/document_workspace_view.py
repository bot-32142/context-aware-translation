from __future__ import annotations

from PySide6.QtCore import Signal
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.application.contracts.common import (
    DocumentSection,
    SurfaceStatus,
    UserMessageSeverity,
)
from context_aware_translation.application.contracts.document import DocumentOverviewState
from context_aware_translation.application.contracts.terms import BuildTermsRequest, TermsTableState, UpdateTermRequest
from context_aware_translation.application.contracts.work import ExportDialogState
from context_aware_translation.application.errors import ApplicationError, BlockedOperationError
from context_aware_translation.application.events import (
    ApplicationEventSubscriber,
    DocumentInvalidatedEvent,
    SetupInvalidatedEvent,
    TermsInvalidatedEvent,
)
from context_aware_translation.application.services.document import DocumentService
from context_aware_translation.application.services.terms import TermsService
from context_aware_translation.application.services.work import WorkService
from context_aware_translation.ui.adapters import QtApplicationEventBridge
from context_aware_translation.ui.features.document_ocr_tab import DocumentOCRTab
from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView
from context_aware_translation.ui.features.terms_table_widget import TermsTableWidget
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

        self.export_button.setEnabled(self._state.blocker is None and bool(self._state.available_formats))

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
        QMessageBox.information(
            self,
            self.tr("Export Complete"),
            result.message.text if result.message is not None else result.output_path,
        )
        self.accept()


class _DocumentOverviewTab(QWidget):
    def __init__(self, service: DocumentService, project_id: str, document_id: int, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._project_id = project_id
        self._document_id = document_id
        self._init_ui()

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

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.build_button = QPushButton(self.tr("Build Terms"))
        self.build_button.clicked.connect(self._on_build_terms)
        toolbar.addWidget(self.build_button)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.table_panel = TermsTableWidget(parent=self)
        layout.addWidget(self.table_panel, 1)
        self.table_panel.term_update_requested.connect(self._on_term_update_requested)

    def refresh(self) -> None:
        self._apply_state(self._service.get_document_terms(self._project_id, self._document_id))

    def _apply_state(self, state: TermsTableState) -> None:
        self._state = state
        self.build_button.setEnabled(state.toolbar.can_build)
        self.build_button.setToolTip(state.toolbar.build_blocker.message if state.toolbar.build_blocker is not None else "")
        self.table_panel.set_state(state)

    def _on_build_terms(self) -> None:
        try:
            self._service.build_terms(BuildTermsRequest(project_id=self._project_id, document_id=self._document_id))
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Build Terms Failed"), exc.payload.message)
            return
        self.table_panel.set_message(UserMessageSeverity.INFO, self.tr("Terms extraction queued for this document."))

    def _on_term_update_requested(self, request: UpdateTermRequest) -> None:
        try:
            state = self._service.update_term(request)
        except BlockedOperationError as exc:
            QMessageBox.warning(self, self.tr("Terms"), exc.payload.message)
            self.refresh()
            return
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Terms"), exc.payload.message)
            self.refresh()
            return
        self._apply_state(state)


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
        self._state = None
        self._tab_indexes: dict[DocumentSection, int] = {}
        self._event_bridge = QtApplicationEventBridge(events, parent=self)
        self._event_bridge.document_invalidated.connect(self._on_document_invalidated)
        self._event_bridge.terms_invalidated.connect(self._on_terms_invalidated)
        self._event_bridge.setup_invalidated.connect(self._on_setup_invalidated)
        self._init_ui()
        self.refresh()

    @property
    def document_id(self) -> int:
        return self._document_id

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

        self.tip_label = create_tip_label(self.tr("These tools apply only to the current document."))
        layout.addWidget(self.tip_label)

        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget, 1)

    def refresh(self) -> None:
        current_section = self.current_section()
        self._state = self._document_service.get_workspace(self._project_id, self._document_id)
        self.title_label.setText(qarg(self.tr("%1"), self._state.document.label))
        self._sync_tabs()
        if current_section is not None:
            self.show_section(current_section)
        for index in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(index)
            if widget is not None and hasattr(widget, "refresh"):
                widget.refresh()

    def _sync_tabs(self) -> None:
        if self._state is None:
            return
        wanted_sections = list(self._state.available_tabs)
        if list(self._tab_indexes.keys()) == wanted_sections:
            return
        while self.tab_widget.count():
            widget = self.tab_widget.widget(0)
            self.tab_widget.removeTab(0)
            if widget is not None and hasattr(widget, "cleanup"):
                widget.cleanup()
            if widget is not None:
                widget.deleteLater()
        self._tab_indexes.clear()
        for section in wanted_sections:
            widget = self._make_tab_widget(section)
            self._tab_indexes[section] = self.tab_widget.addTab(widget, self.tr(_SECTION_LABELS[section]))

    def _make_tab_widget(self, section: DocumentSection) -> QWidget:
        if section is DocumentSection.OVERVIEW:
            return _DocumentOverviewTab(self._document_service, self._project_id, self._document_id, parent=self)
        if section is DocumentSection.OCR:
            return DocumentOCRTab(self._document_service, self._project_id, self._document_id, parent=self)
        if section is DocumentSection.TERMS:
            return _DocumentTermsTab(self._terms_service, self._project_id, self._document_id, parent=self)
        if section is DocumentSection.TRANSLATION:
            return DocumentTranslationView(self._document_service, self._project_id, self._document_id, parent=self)
        if section is DocumentSection.EXPORT:
            return _DocumentExportTab(self._project_id, self._document_id, self._work_service, parent=self)
        return _PlaceholderDocumentTab(
            self.tr(_SECTION_LABELS[section]),
            self.tr("This document-scoped surface will be attached in a later migration task."),
            parent=self,
        )

    def current_section(self) -> DocumentSection | None:
        current_index = self.tab_widget.currentIndex()
        for section, index in self._tab_indexes.items():
            if index == current_index:
                return section
        return None

    def show_section(self, section: DocumentSection) -> None:
        index = self._tab_indexes.get(section)
        if index is not None:
            self.tab_widget.setCurrentIndex(index)

    def cleanup(self) -> None:
        self._event_bridge.close()
        while self.tab_widget.count():
            widget = self.tab_widget.widget(0)
            self.tab_widget.removeTab(0)
            if widget is not None and hasattr(widget, "cleanup"):
                widget.cleanup()
            if widget is not None:
                widget.deleteLater()

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

    def _on_terms_invalidated(self, event: TermsInvalidatedEvent) -> None:
        if event.project_id not in {None, self._project_id}:
            return
        if event.document_id not in {None, self._document_id}:
            return
        self.refresh()

    def _on_setup_invalidated(self, event: SetupInvalidatedEvent) -> None:
        if event.project_id not in {None, self._project_id}:
            return
        self.refresh()


__all__ = ["DocumentWorkspaceView", "WorkExportDialog"]
