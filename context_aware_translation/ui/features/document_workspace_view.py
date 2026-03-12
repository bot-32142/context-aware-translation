from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from superqt import QElidingLabel

from context_aware_translation.adapters.qt.application_event_bridge import QtApplicationEventBridge
from context_aware_translation.application.contracts.common import DocumentSection
from context_aware_translation.application.contracts.document import (
    DocumentExportResult,
    DocumentExportState,
    RunDocumentExportRequest,
)
from context_aware_translation.application.contracts.work import ExportDialogState, RunExportRequest
from context_aware_translation.application.errors import ApplicationError
from context_aware_translation.application.events import (
    ApplicationEventSubscriber,
    DocumentInvalidatedEvent,
    SetupInvalidatedEvent,
)
from context_aware_translation.application.services.document import DocumentService
from context_aware_translation.application.services.terms import TermsService
from context_aware_translation.application.services.work import WorkService
from context_aware_translation.ui.features.document_images_view import DocumentImagesView
from context_aware_translation.ui.features.document_ocr_tab import DocumentOCRTab
from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView
from context_aware_translation.ui.features.terms_view import TermsView
from context_aware_translation.ui.i18n import qarg
from context_aware_translation.ui.shell_hosts.document_shell_host import DocumentShellHost
from context_aware_translation.ui.shell_hosts.hybrid import QmlChromeHost
from context_aware_translation.ui.tips import create_tip_label
from context_aware_translation.ui.viewmodels.document_export_pane import DocumentExportPaneViewModel

_SECTION_LABELS: dict[DocumentSection, str] = {
    DocumentSection.OCR: "OCR",
    DocumentSection.TERMS: "Terms",
    DocumentSection.TRANSLATION: "Translation",
    DocumentSection.IMAGES: "Images",
    DocumentSection.EXPORT: "Export",
}
_DOCUMENT_SECTIONS: tuple[DocumentSection, ...] = tuple(_SECTION_LABELS)


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
            self.preserve_structure_cb.setToolTip(
                self.tr("Preserve folder structure is not supported for this export.")
            )
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

    def submission(self, parent: QWidget) -> _ExportSubmission | None:
        output_path = self.output_path()
        if not output_path:
            QMessageBox.warning(parent, self.tr("Missing Information"), self.tr("Output path is required."))
            return None
        format_id = self.format_id()
        if not format_id:
            QMessageBox.warning(parent, self.tr("Missing Information"), self.tr("Export format is required."))
            return None
        return _ExportSubmission(format_id=format_id, output_path=output_path, options=self.options())

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


@dataclass(slots=True)
class _ExportSubmission:
    format_id: str
    output_path: str
    options: dict[str, str | int | float | bool | None]


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
        docs_label = QElidingLabel(
            qarg(self.tr("Export %1"), ", ".join(self._state.document_labels))
            if self._state.document_labels
            else self.tr("Export selected documents")
        )
        docs_label.setElideMode(Qt.TextElideMode.ElideMiddle)
        docs_label.setToolTip(docs_label.text())
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
        submission = self.controls.submission(self)
        if submission is None:
            return
        try:
            result = self._service.run_export(
                RunExportRequest(
                    project_id=self._state.project_id,
                    document_ids=self._state.document_ids,
                    format_id=submission.format_id,
                    output_path=submission.output_path,
                    options=submission.options,
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
        self.viewmodel = DocumentExportPaneViewModel(self)
        self._state: DocumentExportState | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.chrome_host = QmlChromeHost(
            "document/export/DocumentExportPaneChrome.qml",
            context_objects={"exportPane": self.viewmodel},
            parent=self,
        )
        layout.addWidget(self.chrome_host)
        self.tip_label = create_tip_label(
            self.tr(
                "Export applies only to the current document. You can also start export directly from the Work list when that row is exportable."
            ),
        )
        self.tip_label.setParent(self)
        self.tip_label.hide()
        self.controls_card = QFrame(self)
        self.controls_card.setFrameShape(QFrame.Shape.StyledPanel)
        self.controls_card.setStyleSheet(
            """
            QFrame {
                border: 1px solid #dbcdb9;
                border-radius: 12px;
                background-color: #fdfaf5;
            }
            QComboBox, QLineEdit {
                min-height: 34px;
                border: 1px solid #d8cdbf;
                border-radius: 8px;
                padding: 0 10px;
                background-color: #ffffff;
            }
            QPushButton {
                min-height: 34px;
                border-radius: 10px;
                padding: 0 14px;
                background-color: #efe0ca;
                color: #2f251d;
                font-weight: 600;
            }
            QCheckBox {
                color: #2f251d;
            }
            """
        )
        controls_layout = QVBoxLayout(self.controls_card)
        controls_layout.setContentsMargins(18, 18, 18, 18)
        controls_layout.setSpacing(12)

        self.controls = _ExportControls(parent=self.controls_card)
        self.controls.changed.connect(self._update_export_enabled)
        controls_layout.addWidget(self.controls)
        self.export_button = QPushButton(self.tr("Export This Document"))
        self.export_button.clicked.connect(self._run_export)
        self.export_button.hide()
        controls_layout.addWidget(self.export_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("color: #15803d; font-weight: 600;")
        self.result_label.hide()
        controls_layout.addWidget(self.result_label)
        layout.addWidget(self.controls_card)
        layout.addStretch()
        self._connect_qml_signals()
        self._sync_chrome_state()

    def refresh(self) -> None:
        try:
            self._state = self._service.get_export(self._project_id, self._document_id)
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Export"), exc.payload.message)
            return
        self.controls.apply_state(self._state)
        self.result_label.hide()
        self.export_button.setEnabled(self._state.can_export and self.controls.can_submit(self._state))
        self._sync_chrome_state()

    def _update_export_enabled(self) -> None:
        if self._state is None:
            self.export_button.setEnabled(False)
            self._sync_chrome_state()
            return
        self.export_button.setEnabled(self._state.can_export and self.controls.can_submit(self._state))
        self._sync_chrome_state()

    def _run_export(self) -> None:
        if self._state is None:
            return
        submission = self.controls.submission(self)
        if submission is None:
            return
        try:
            result = self._service.export_document(
                RunDocumentExportRequest(
                    project_id=self._project_id,
                    document_id=self._document_id,
                    format_id=submission.format_id,
                    output_path=submission.output_path,
                    options=submission.options,
                )
            )
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Export Failed"), exc.payload.message)
            return
        self._show_result(result)

    def _show_result(self, result: DocumentExportResult) -> None:
        message = result.message.text if result.message is not None else result.output_path
        self.result_label.setText(message)
        self.result_label.show()
        self._sync_chrome_state()

    def retranslate(self) -> None:
        self.tip_label.setText(
            self.tr(
                "Export applies only to the current document. You can also start export directly from the Work list when that row is exportable."
            ),
        )
        self.export_button.setText(self.tr("Export This Document"))
        self.viewmodel.retranslate()
        self._sync_chrome_state()

    def _connect_qml_signals(self) -> None:
        root = self.chrome_host.rootObject()
        if root is None:
            return
        root.exportRequested.connect(self._run_export)

    def _sync_chrome_state(self) -> None:
        self.viewmodel.apply_state(
            can_export=self.export_button.isEnabled(),
            result_text=self.result_label.text().strip() if not self.result_label.isHidden() else "",
        )


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
        self._events = events
        self._state = None
        self._section_widgets: dict[DocumentSection, QWidget] = {}
        self._event_bridge = QtApplicationEventBridge(events, parent=self)
        self._event_bridge.document_invalidated.connect(self._on_document_invalidated)
        self._event_bridge.setup_invalidated.connect(self._on_setup_invalidated)
        self._init_ui()
        self.refresh()

    @property
    def document_id(self) -> int:
        return self._document_id

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.shell_host = DocumentShellHost(self)
        self.shell_host.back_requested.connect(self.back_requested.emit)
        layout.addWidget(self.shell_host, 1)

    def refresh(self) -> None:
        current_section = self.current_section()
        self._state = self._document_service.get_workspace(self._project_id, self._document_id)
        target_section = current_section or self._state.active_tab
        self._sync_sections()
        self.shell_host.set_document_context(
            self._project_id,
            self._document_id,
            qarg(self.tr("%1"), self._state.document.label),
            section=target_section,
        )
        for widget in self._section_widgets.values():
            if widget is not None and hasattr(widget, "refresh"):
                widget.refresh()
        self.show_section(target_section)

    def _sync_sections(self) -> None:
        if self._state is None:
            return
        for section in _DOCUMENT_SECTIONS:
            if section in self._section_widgets:
                continue
            widget = self._make_section_widget(section)
            self._section_widgets[section] = widget
            self.shell_host.set_section_widget(section, widget)

    def _make_section_widget(self, section: DocumentSection) -> QWidget:
        if section is DocumentSection.OCR:
            return DocumentOCRTab(self._document_service, self._project_id, self._document_id, parent=self)
        if section is DocumentSection.TERMS:
            return TermsView(
                self._project_id,
                self._terms_service,
                self._events,
                document_id=self._document_id,
                embedded=True,
                parent=self,
            )
        if section is DocumentSection.IMAGES:
            widget = DocumentImagesView(self._project_id, self._document_id, self._document_service, parent=self)
            widget.open_app_setup_requested.connect(self.open_app_setup_requested.emit)
            widget.open_project_setup_requested.connect(self.open_project_setup_requested.emit)
            return widget
        if section is DocumentSection.TRANSLATION:
            return DocumentTranslationView(self._document_service, self._project_id, self._document_id, parent=self)
        if section is DocumentSection.EXPORT:
            return _DocumentExportTab(self._project_id, self._document_id, self._document_service, parent=self)
        raise ValueError(f"Unknown document section: {section}")

    def section_widget(self, section: DocumentSection) -> QWidget | None:
        return self._section_widgets.get(section)

    def current_section(self) -> DocumentSection | None:
        return self.shell_host.current_section()

    def show_section(self, section: DocumentSection) -> None:
        self.shell_host.show_section(section)

    def cleanup(self) -> None:
        self._event_bridge.close()
        self.shell_host.cleanup()
        self._section_widgets.clear()

    def get_running_operations(self) -> list[str]:
        return self.shell_host.get_running_operations()

    def request_cancel_running_operations(self, *, include_engine_tasks: bool = False) -> None:
        self.shell_host.request_cancel_running_operations(include_engine_tasks=include_engine_tasks)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.shell_host.retranslate()

    def _on_document_invalidated(self, event: DocumentInvalidatedEvent) -> None:
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
