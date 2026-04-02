from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

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
from context_aware_translation.application.errors import ApplicationError, ApplicationErrorCode
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
from context_aware_translation.ui.i18n import qarg, translate_backend_text
from context_aware_translation.ui.shell_hosts.document_shell_host import DocumentShellHost
from context_aware_translation.ui.shell_hosts.hybrid import QmlChromeHost
from context_aware_translation.ui.tips import create_tip_label
from context_aware_translation.ui.viewmodels.document_export_pane import DocumentExportPaneViewModel
from context_aware_translation.ui.widgets.hybrid_controls import apply_hybrid_control_theme, set_button_tone

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
        self._supports_epub_layout_conversion = False
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

        self.epub_force_horizontal_ltr_cb = QCheckBox(
            self.tr("Convert vertical Japanese EPUB to horizontal left-to-right")
        )
        self.epub_force_horizontal_ltr_cb.setVisible(False)
        self.epub_force_horizontal_ltr_cb.setToolTip(
            self.tr("EPUB only. Forces horizontal left-to-right layout and scrollbar direction in the exported file.")
        )
        self.epub_force_horizontal_ltr_cb.toggled.connect(self._on_options_changed)
        layout.addWidget(self.epub_force_horizontal_ltr_cb)
        apply_hybrid_control_theme(self)
        set_button_tone(self.browse_button)

    def apply_state(self, state: ExportDialogState | DocumentExportState) -> None:
        self._default_output_path = state.default_output_path or ""
        self._supports_epub_layout_conversion = state.supports_epub_layout_conversion
        self.blocker_label.setVisible(state.blocker is not None)
        self.blocker_label.setText(translate_backend_text(state.blocker.message if state.blocker is not None else ""))
        self.warning_label.setVisible(bool(state.incomplete_translation_message))
        self.warning_label.setText(translate_backend_text(state.incomplete_translation_message or ""))

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
            self.allow_original_fallback_cb.setToolTip(translate_backend_text(state.incomplete_translation_message))
        if not self._supports_epub_layout_conversion:
            self.epub_force_horizontal_ltr_cb.setChecked(False)

        if not self.output_path_edit.text().strip():
            self.output_path_edit.setText(self._default_output_path)
        else:
            self._sync_output_path()
        self._sync_output_tooltip()
        self._sync_epub_layout_controls()
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

    def options(self) -> dict[str, str | int | float | bool | None]:
        return {
            "preserve_structure": self.preserve_structure_cb.isChecked(),
            "allow_original_fallback": self.allow_original_fallback_cb.isChecked(),
            "epub_force_horizontal_ltr": self._epub_layout_conversion_enabled(),
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
        return _ExportSubmission(
            format_id=format_id,
            output_path=output_path,
            options=cast(dict[str, str | int | float | bool | None], self.options()),
        )

    def _on_options_changed(self) -> None:
        self._sync_output_path()
        self._sync_epub_layout_controls()
        self.changed.emit()

    def _sync_output_path(self) -> None:
        if not self._default_output_path:
            return
        self._sync_epub_layout_controls()
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

    def _epub_layout_conversion_enabled(self) -> bool:
        return (
            self._supports_epub_layout_conversion
            and not self.preserve_structure_cb.isChecked()
            and self.format_id() == "epub"
            and self.epub_force_horizontal_ltr_cb.isChecked()
        )

    def _sync_epub_layout_controls(self) -> None:
        visible = (
            self._supports_epub_layout_conversion
            and not self.preserve_structure_cb.isChecked()
            and self.format_id() == "epub"
        )
        self.epub_force_horizontal_ltr_cb.setVisible(visible)
        self.epub_force_horizontal_ltr_cb.setEnabled(visible)

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
        apply_hybrid_control_theme(self)
        set_button_tone(self.export_button, "primary")
        cancel_button = self.button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button is not None:
            set_button_tone(cancel_button, "ghost")

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
            QMessageBox.warning(self, self.tr("Export Failed"), translate_backend_text(exc.payload.message))
            return
        QMessageBox.information(
            self,
            self.tr("Export Complete"),
            translate_backend_text(result.message.text) if result.message is not None else result.output_path,
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
        self._can_export = False
        self._result_text = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.chrome_host = QmlChromeHost(
            "document/export/DocumentExportPaneChrome.qml",
            context_objects={"exportPane": self.viewmodel},
            parent=self,
        )
        layout.addWidget(self.chrome_host)
        self.controls_card = QFrame(self)
        self.controls_card.setFrameShape(QFrame.Shape.StyledPanel)
        self.controls_card.setStyleSheet(
            """
            QFrame {
                border: 1px solid #dbcdb9;
                border-radius: 12px;
                background-color: #fdfaf5;
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
        layout.addWidget(self.controls_card)
        layout.addStretch()
        apply_hybrid_control_theme(self.controls_card)
        self._connect_qml_signals()
        self._sync_chrome_state()

    def refresh(self) -> None:
        try:
            self._state = self._service.get_export(self._project_id, self._document_id)
        except ApplicationError as exc:
            QMessageBox.warning(self, self.tr("Export"), translate_backend_text(exc.payload.message))
            return
        self.controls.apply_state(self._state)
        self._result_text = ""
        self._can_export = self._state.can_export and self.controls.can_submit(self._state)
        self._sync_chrome_state()

    def _update_export_enabled(self) -> None:
        if self._state is None:
            self._can_export = False
            self._sync_chrome_state()
            return
        self._can_export = self._state.can_export and self.controls.can_submit(self._state)
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
            QMessageBox.warning(self, self.tr("Export Failed"), translate_backend_text(exc.payload.message))
            return
        self._show_result(result)

    def _show_result(self, result: DocumentExportResult) -> None:
        message = translate_backend_text(result.message.text) if result.message is not None else result.output_path
        self._result_text = message
        self._sync_chrome_state()

    def retranslate(self) -> None:
        self.viewmodel.retranslate()
        self._sync_chrome_state()

    def _connect_qml_signals(self) -> None:
        root = cast(Any, self.chrome_host.rootObject())
        if root is None:
            return
        root.exportRequested.connect(self._run_export)

    def _sync_chrome_state(self) -> None:
        export_tooltip = self.tr("Export this document using the selected format and options.")
        if self._state is not None and self._state.blocker is not None:
            export_tooltip = translate_backend_text(self._state.blocker.message)
        elif self._state is not None and not self.controls.can_submit(self._state):
            export_tooltip = self.tr("Choose a valid format and output path before exporting this document.")
        self.viewmodel.apply_state(
            can_export=self._can_export,
            result_text=self._result_text.strip(),
            export_tooltip=export_tooltip,
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
        self._document_missing = False
        self._section_widgets: dict[DocumentSection, QWidget] = {}
        self._dirty_sections: set[DocumentSection] = set()
        self._refresh_error_sections: set[DocumentSection] = set()
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
        self.shell_host.set_section_widget_factory(self._create_section_widget)
        self.shell_host.set_section_show_handler(self._prepare_section_widget)
        self.shell_host.back_requested.connect(self.back_requested.emit)
        layout.addWidget(self.shell_host, 1)

    def refresh(self) -> None:
        current_section = self.current_section()
        try:
            self._state = self._document_service.get_workspace(self._project_id, self._document_id)
        except ApplicationError as exc:
            if exc.payload.code == ApplicationErrorCode.NOT_FOUND:
                self._document_missing = True
                self.back_requested.emit()
                return
            QMessageBox.warning(self, self.tr("Document"), translate_backend_text(exc.payload.message))
            return
        self._document_missing = False
        target_section = current_section or self._state.active_tab
        self._dirty_sections.update(self._section_widgets)
        self.shell_host.set_document_context(
            self._project_id,
            self._document_id,
            qarg(self.tr("%1"), self._state.document.label),
            section=target_section,
        )

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

    def _create_section_widget(self, section: DocumentSection) -> QWidget:
        widget = self._section_widgets.get(section)
        if widget is not None:
            return widget
        widget = self._make_section_widget(section)
        self._section_widgets[section] = widget
        self._dirty_sections.add(section)
        return widget

    def _prepare_section_widget(self, section: DocumentSection, widget: QWidget) -> None:
        if section not in self._dirty_sections:
            return
        refresh = getattr(widget, "refresh", None)
        if callable(refresh):
            try:
                refresh()
            except ApplicationError as exc:
                self._refresh_error_sections.add(section)
                QMessageBox.warning(self, _SECTION_LABELS.get(section, self.tr("Document")), exc.payload.message)
                return
            self._refresh_error_sections.discard(section)
        self._dirty_sections.discard(section)

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

    def get_navigation_blocking_operations(self) -> list[str]:
        get_navigation_blockers = getattr(self.shell_host, "get_navigation_blocking_operations", None)
        if callable(get_navigation_blockers):
            blockers = get_navigation_blockers()
            return blockers if isinstance(blockers, list) else []
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
        if self._document_missing:
            return
        if event.project_id not in {None, self._project_id}:
            return
        if event.document_id not in {None, self._document_id}:
            return
        self.refresh()

    def _on_setup_invalidated(self, event: SetupInvalidatedEvent) -> None:
        if self._document_missing:
            return
        if event.project_id not in {None, self._project_id}:
            return
        self.refresh()


__all__ = ["DocumentWorkspaceView", "WorkExportDialog"]
