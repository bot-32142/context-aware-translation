from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.application.contracts.common import DocumentSection, UserMessageSeverity
from context_aware_translation.application.contracts.document import (
    DocumentExportResult,
    DocumentExportState,
)
from context_aware_translation.application.contracts.terms import (
    BuildTermsRequest,
    FilterNoiseRequest,
    ReviewTermsRequest,
    TermsTableState,
    TranslatePendingTermsRequest,
    UpdateTermRequest,
)
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
from context_aware_translation.ui.features.document_images_view import DocumentImagesView
from context_aware_translation.ui.features.document_ocr_tab import DocumentOCRTab
from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView
from context_aware_translation.ui.features.terms_table_widget import TermsTableWidget
from context_aware_translation.ui.i18n import qarg
from context_aware_translation.ui.utils import create_tip_label

_SECTION_LABELS: dict[DocumentSection, str] = {
    DocumentSection.OVERVIEW: "Overview",
    DocumentSection.OCR: "OCR",
    DocumentSection.TERMS: "Terms",
    DocumentSection.TRANSLATION: "Translation",
    DocumentSection.IMAGES: "Images",
    DocumentSection.EXPORT: "Export",
}


class _ExportControls(QWidget):
    changed = Signal()

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._default_output_path = ""
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.blocker_label = create_tip_label("")
        self.blocker_label.setVisible(False)
        layout.addWidget(self.blocker_label)

        self.warning_label = create_tip_label("")
        self.warning_label.setVisible(False)
        layout.addWidget(self.warning_label)

        form = QFormLayout()
        self.format_combo = QComboBox()
        self.format_combo.currentIndexChanged.connect(self._sync_output_path)
        self.format_combo.currentIndexChanged.connect(lambda *_args: self.changed.emit())
        form.addRow(self.tr("Format"), self.format_combo)

        output_row = QHBoxLayout()
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setMinimumWidth(420)
        self.output_path_edit.textChanged.connect(self._sync_output_tooltip)
        self.output_path_edit.textChanged.connect(lambda *_args: self.changed.emit())
        output_row.addWidget(self.output_path_edit, 1)
        self.browse_button = QPushButton(self.tr("Browse..."))
        self.browse_button.clicked.connect(self._browse_output)
        output_row.addWidget(self.browse_button)
        form.addRow(self.tr("Output path"), output_row)
        layout.addLayout(form)

        self.preserve_structure_cb = QCheckBox(self.tr("Preserve folder structure"))
        self.preserve_structure_cb.toggled.connect(self._on_options_changed)
        layout.addWidget(self.preserve_structure_cb)

        self.allow_original_fallback_cb = QCheckBox(
            self.tr("Allow fallback to original content for untranslated chunks")
        )
        self.allow_original_fallback_cb.toggled.connect(self._on_options_changed)
        layout.addWidget(self.allow_original_fallback_cb)

    def apply_state(self, state: ExportDialogState | DocumentExportState) -> None:
        self._default_output_path = state.default_output_path or ""
        self.blocker_label.setVisible(state.blocker is not None)
        self.blocker_label.setText(state.blocker.message if state.blocker is not None else "")
        self.warning_label.setVisible(bool(state.incomplete_translation_message))
        self.warning_label.setText(state.incomplete_translation_message or "")

        self.format_combo.blockSignals(True)
        self.format_combo.clear()
        default_index = 0
        for index, option in enumerate(state.available_formats):
            self.format_combo.addItem(option.label, option.format_id)
            if option.is_default:
                default_index = index
        if state.available_formats:
            self.format_combo.setCurrentIndex(default_index)
        self.format_combo.blockSignals(False)

        self.preserve_structure_cb.setVisible(True)
        self.preserve_structure_cb.setEnabled(state.supports_preserve_structure)
        if not state.supports_preserve_structure:
            self.preserve_structure_cb.setChecked(False)
            self.preserve_structure_cb.setToolTip(self.tr("Preserve folder structure is not supported for this export."))
        else:
            self.preserve_structure_cb.setToolTip("")
        self.allow_original_fallback_cb.setVisible(True)
        self.allow_original_fallback_cb.setEnabled(bool(state.incomplete_translation_message))
        if not state.incomplete_translation_message:
            self.allow_original_fallback_cb.setChecked(False)
            self.allow_original_fallback_cb.setToolTip(
                self.tr("Fallback to original content is only needed when translation is incomplete.")
            )
        else:
            self.allow_original_fallback_cb.setToolTip(state.incomplete_translation_message)

        if not self.output_path_edit.text().strip():
            self.output_path_edit.setText(self._default_output_path)
        else:
            self._sync_output_path()
        self._sync_output_tooltip()
        self.changed.emit()

    def can_submit(self, state: ExportDialogState | DocumentExportState) -> bool:
        return (
            state.blocker is None
            and bool(state.available_formats)
            and (not state.incomplete_translation_message or self.allow_original_fallback_cb.isChecked())
        )

    def format_id(self) -> str:
        return str(self.format_combo.currentData() or "").strip()

    def output_path(self) -> str:
        return self.output_path_edit.text().strip()

    def options(self) -> dict[str, bool]:
        return {
            "preserve_structure": self.preserve_structure_cb.isChecked(),
            "allow_original_fallback": self.allow_original_fallback_cb.isChecked(),
        }

    def _on_options_changed(self) -> None:
        self._sync_output_path()
        self.changed.emit()

    def _sync_output_path(self) -> None:
        if not self._default_output_path:
            return
        if self.preserve_structure_cb.isChecked():
            self.output_path_edit.setText(str(Path(self._default_output_path).parent))
            return
        format_id = self.format_id()
        if not format_id:
            self.output_path_edit.setText(self._default_output_path)
            return
        current = self.output_path_edit.text().strip()
        if not current or current == str(Path(self._default_output_path).parent):
            self.output_path_edit.setText(str(Path(self._default_output_path).with_suffix(f".{format_id}")))
            return
        self.output_path_edit.setText(str(Path(current).with_suffix(f".{format_id}")))
        self._sync_output_tooltip()

    def _sync_output_tooltip(self) -> None:
        text = self.output_path_edit.text().strip()
        self.output_path_edit.setToolTip(text)
        if text:
            self.output_path_edit.setCursorPosition(0)

    def _browse_output(self) -> None:
        if self.preserve_structure_cb.isChecked():
            folder = QFileDialog.getExistingDirectory(self, self.tr("Select Output Folder"))
            if folder:
                self.output_path_edit.setText(folder)
            return
        format_id = self.format_id()
        if not format_id:
            QMessageBox.warning(self, self.tr("Missing Information"), self.tr("Export format is required."))
            return
        suggested = self.output_path_edit.text().strip() or self._default_output_path or f"export.{format_id}"
        file_path, _filter = QFileDialog.getSaveFileName(
            self,
            self.tr("Save Export File"),
            suggested,
            qarg(self.tr("%1 Files (*.%2)"), format_id.upper(), format_id),
        )
        if file_path:
            self.output_path_edit.setText(file_path)


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
        self.controls = _ExportControls(parent=self)
        self.controls.apply_state(self._state)
        self.controls.changed.connect(self._update_export_enabled)
        layout.addWidget(self.controls)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.export_button = self.button_box.addButton(self.tr("Export"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.export_button.clicked.connect(self._run_export)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self._update_export_enabled()

    def _run_export(self) -> None:
        output_path = self.controls.output_path()
        if not output_path:
            QMessageBox.warning(self, self.tr("Missing Information"), self.tr("Output path is required."))
            return
        from context_aware_translation.application.contracts.work import RunExportRequest

        format_id = self.controls.format_id()
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
                    options=self.controls.options(),
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

    def _update_export_enabled(self) -> None:
        self.export_button.setEnabled(self.controls.can_submit(self._state) and bool(self.controls.output_path()))


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
        self.translate_button = QPushButton(self.tr("Translate Untranslated"))
        self.translate_button.clicked.connect(self._on_translate_terms)
        toolbar.addWidget(self.translate_button)
        self.review_button = QPushButton(self.tr("Review Terms"))
        self.review_button.clicked.connect(self._on_review_terms)
        toolbar.addWidget(self.review_button)
        self.filter_noise_button = QPushButton(self.tr("Filter Rare"))
        self.filter_noise_button.clicked.connect(self._on_filter_noise)
        toolbar.addWidget(self.filter_noise_button)
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
        self.build_button.setToolTip(
            state.toolbar.build_blocker.message if state.toolbar.build_blocker is not None else ""
        )
        self.translate_button.setEnabled(state.toolbar.can_translate_pending)
        self.translate_button.setToolTip(
            state.toolbar.translate_pending_blocker.message
            if state.toolbar.translate_pending_blocker is not None
            else self.tr("Translate all currently untranslated glossary terms for this document.")
        )
        self.review_button.setEnabled(state.toolbar.can_review)
        self.review_button.setToolTip(
            state.toolbar.review_blocker.message
            if state.toolbar.review_blocker is not None
            else self.tr("Run the review pass for this document terms.")
        )
        self.filter_noise_button.setEnabled(state.toolbar.can_filter_noise)
        self.filter_noise_button.setToolTip(
            state.toolbar.filter_noise_blocker.message
            if state.toolbar.filter_noise_blocker is not None
            else self.tr("Ignore rare terms for this document.")
        )
        self.table_panel.set_state(state)

    def _on_build_terms(self) -> None:
        try:
            self._service.build_terms(BuildTermsRequest(project_id=self._project_id, document_id=self._document_id))
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Build Terms Failed"), exc.payload.message)
            return
        self.table_panel.set_message(UserMessageSeverity.INFO, self.tr("Terms extraction queued for this document."))

    def _on_translate_terms(self) -> None:
        try:
            accepted = self._service.translate_pending(
                TranslatePendingTermsRequest(project_id=self._project_id, document_id=self._document_id)
            )
        except BlockedOperationError as exc:
            QMessageBox.warning(self, self.tr("Translate Terms"), exc.payload.message)
            return
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Translate Terms"), exc.payload.message)
            return
        self.table_panel.set_message(
            UserMessageSeverity.INFO,
            accepted.message.text if accepted.message is not None else self.tr("Terms translation queued."),
        )

    def _on_review_terms(self) -> None:
        try:
            accepted = self._service.review_terms(
                ReviewTermsRequest(project_id=self._project_id, document_id=self._document_id)
            )
        except BlockedOperationError as exc:
            QMessageBox.warning(self, self.tr("Review Terms"), exc.payload.message)
            return
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Review Terms"), exc.payload.message)
            return
        self.table_panel.set_message(
            UserMessageSeverity.INFO,
            accepted.message.text if accepted.message is not None else self.tr("Terms review queued."),
        )

    def _on_filter_noise(self) -> None:
        try:
            state = self._service.filter_noise(FilterNoiseRequest(project_id=self._project_id, document_id=self._document_id))
        except BlockedOperationError as exc:
            QMessageBox.warning(self, self.tr("Filter Rare Terms"), exc.payload.message)
            self.refresh()
            return
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Filter Rare Terms"), exc.payload.message)
            self.refresh()
            return
        self._apply_state(state)
        self.table_panel.set_message(UserMessageSeverity.SUCCESS, self.tr("Rare document terms were filtered."))

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


class _UnavailableDocumentTab(QWidget):
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
    def __init__(
        self,
        project_id: str,
        document_id: int,
        service: DocumentService,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project_id = project_id
        self._document_id = document_id
        self._service = service
        self._state: DocumentExportState | None = None
        layout = QVBoxLayout(self)
        self.tip_label = create_tip_label(
            self.tr(
                "Export applies only to the current document. You can also start export directly from the Work list when that row is exportable."
            ),
        )
        layout.addWidget(self.tip_label)
        self.controls = _ExportControls(parent=self)
        self.controls.changed.connect(self._update_export_enabled)
        layout.addWidget(self.controls)
        self.export_button = QPushButton(self.tr("Export This Document"))
        self.export_button.clicked.connect(self._run_export)
        layout.addWidget(self.export_button)
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.result_label.hide()
        layout.addWidget(self.result_label)
        layout.addStretch()

    def refresh(self) -> None:
        try:
            self._state = self._service.get_export(self._project_id, self._document_id)
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Export"), exc.payload.message)
            return
        self.controls.apply_state(self._state)
        self.result_label.hide()
        self.export_button.setEnabled(self._state.can_export and self.controls.can_submit(self._state))

    def _update_export_enabled(self) -> None:
        if self._state is None:
            self.export_button.setEnabled(False)
            return
        self.export_button.setEnabled(self._state.can_export and self.controls.can_submit(self._state))

    def _run_export(self) -> None:
        if self._state is None:
            return
        output_path = self.controls.output_path()
        if not output_path:
            QMessageBox.warning(self, self.tr("Missing Information"), self.tr("Output path is required."))
            return
        format_id = self.controls.format_id()
        if not format_id:
            QMessageBox.warning(self, self.tr("Missing Information"), self.tr("Export format is required."))
            return
        from context_aware_translation.application.contracts.document import RunDocumentExportRequest

        try:
            result = self._service.export_document(
                RunDocumentExportRequest(
                    project_id=self._project_id,
                    document_id=self._document_id,
                    format_id=format_id,
                    output_path=output_path,
                    options=self.controls.options(),
                )
            )
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Export Failed"), exc.payload.message)
            return
        self._show_result(result)

    def _show_result(self, result: DocumentExportResult) -> None:
        message = result.message.text if result.message is not None else result.output_path
        self.result_label.setText(message)
        self.result_label.setStyleSheet("color: #15803d;")
        self.result_label.show()


class DocumentWorkspaceView(QWidget):
    back_requested = Signal()
    open_app_setup_requested = Signal()
    open_project_setup_requested = Signal()

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
        wanted_sections = [section for section in self._state.available_tabs if section is not DocumentSection.OVERVIEW]
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
        if section is DocumentSection.OCR:
            return DocumentOCRTab(self._document_service, self._project_id, self._document_id, parent=self)
        if section is DocumentSection.TERMS:
            return _DocumentTermsTab(self._terms_service, self._project_id, self._document_id, parent=self)
        if section is DocumentSection.IMAGES:
            widget = DocumentImagesView(self._project_id, self._document_id, self._document_service, parent=self)
            widget.open_app_setup_requested.connect(self.open_app_setup_requested.emit)
            widget.open_project_setup_requested.connect(self.open_project_setup_requested.emit)
            return widget
        if section is DocumentSection.TRANSLATION:
            return DocumentTranslationView(self._document_service, self._project_id, self._document_id, parent=self)
        if section is DocumentSection.EXPORT:
            return _DocumentExportTab(self._project_id, self._document_id, self._document_service, parent=self)
        return _UnavailableDocumentTab(
            self.tr(_SECTION_LABELS[section]),
            self.tr("This section is not available for the current document."),
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
