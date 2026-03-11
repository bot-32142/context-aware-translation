from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSizePolicy, QWidget

from context_aware_translation.application.contracts.common import DocumentSection
from context_aware_translation.ui.shell_hosts.hybrid import HybridShellHost
from context_aware_translation.ui.viewmodels.document_shell import DocumentShellViewModel


class DocumentShellHost(HybridShellHost):
    """Document-scoped shell host with local QML navigation and hosted QWidget panes."""

    back_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        self.viewmodel = DocumentShellViewModel(parent)
        super().__init__(
            "document/DocumentShellChrome.qml",
            orientation=Qt.Orientation.Horizontal,
            context_objects={"documentShell": self.viewmodel},
            parent=parent,
        )
        self.chrome_host.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.chrome_host.setMinimumWidth(240)
        self.chrome_host.setMaximumWidth(240)
        self._connect_qml_signals()

    def set_section_widget(self, section: DocumentSection, widget: QWidget) -> QWidget:
        registered = self.register_content(section.value, widget)
        if self.viewmodel.current_section() is section or self.current_content_key() == section.value:
            self._show_section_content(section)
        return registered

    def remove_section_widget(self, section: DocumentSection) -> QWidget | None:
        return self.remove_content(section.value)

    def section_widget(self, section: DocumentSection) -> QWidget | None:
        return self.content_widget(section.value)

    def set_ocr_widget(self, widget: QWidget) -> QWidget:
        return self.set_section_widget(DocumentSection.OCR, widget)

    def set_terms_widget(self, widget: QWidget) -> QWidget:
        return self.set_section_widget(DocumentSection.TERMS, widget)

    def set_translation_widget(self, widget: QWidget) -> QWidget:
        return self.set_section_widget(DocumentSection.TRANSLATION, widget)

    def set_images_widget(self, widget: QWidget) -> QWidget:
        return self.set_section_widget(DocumentSection.IMAGES, widget)

    def set_export_widget(self, widget: QWidget) -> QWidget:
        return self.set_section_widget(DocumentSection.EXPORT, widget)

    def set_document_context(
        self,
        project_id: str,
        document_id: int,
        document_label: str,
        *,
        section: DocumentSection = DocumentSection.OCR,
    ) -> None:
        self.viewmodel.set_document_context(project_id, document_id, document_label, section=section)
        self._show_section_content(section)

    def current_section(self) -> DocumentSection | None:
        return self.viewmodel.current_section()

    def show_section(self, section: DocumentSection) -> None:
        self.viewmodel.show_section(section)
        if self.viewmodel.current_section() is not section:
            return
        self._show_section_content(section)

    def show_ocr_view(self) -> None:
        self.show_section(DocumentSection.OCR)

    def show_terms_view(self) -> None:
        self.show_section(DocumentSection.TERMS)

    def show_translation_view(self) -> None:
        self.show_section(DocumentSection.TRANSLATION)

    def show_images_view(self) -> None:
        self.show_section(DocumentSection.IMAGES)

    def show_export_view(self) -> None:
        self.show_section(DocumentSection.EXPORT)

    def retranslate(self) -> None:
        self.viewmodel.retranslate()
        for widget in self._registered_widgets():
            retranslate = getattr(widget, "retranslateUi", None)
            if callable(retranslate):
                retranslate()
                continue
            retranslate = getattr(widget, "retranslate", None)
            if callable(retranslate):
                retranslate()

    def get_running_operations(self) -> list[str]:
        current_widget = self.content_stack.currentWidget()
        if current_widget is None:
            return []
        get_running_operations = getattr(current_widget, "get_running_operations", None)
        if not callable(get_running_operations):
            return []
        running = get_running_operations()
        return running if isinstance(running, list) else []

    def request_cancel_running_operations(self, *, include_engine_tasks: bool = False) -> None:
        current_widget = self.content_stack.currentWidget()
        if current_widget is None:
            return
        request_cancel = getattr(current_widget, "request_cancel_running_operations", None)
        if callable(request_cancel):
            request_cancel(include_engine_tasks=include_engine_tasks)

    def _connect_qml_signals(self) -> None:
        root = self.chrome_host.rootObject()
        if root is None:
            return
        root.backRequested.connect(self.back_requested.emit)
        root.ocrRequested.connect(self.show_ocr_view)
        root.termsRequested.connect(self.show_terms_view)
        root.translationRequested.connect(self.show_translation_view)
        root.imagesRequested.connect(self.show_images_view)
        root.exportRequested.connect(self.show_export_view)

    def _registered_widgets(self) -> Iterable[QWidget]:
        sections = (
            DocumentSection.OCR,
            DocumentSection.TERMS,
            DocumentSection.TRANSLATION,
            DocumentSection.IMAGES,
            DocumentSection.EXPORT,
        )
        for section in sections:
            widget = self.section_widget(section)
            if widget is not None:
                yield widget

    def _show_section_content(self, section: DocumentSection) -> None:
        widget = self.section_widget(section)
        if widget is None:
            return
        self.show_content(section.value)
        activate_view = getattr(widget, "activate_view", None)
        if callable(activate_view):
            activate_view()
