from __future__ import annotations

from PySide6.QtCore import Property, QCoreApplication, Signal

from context_aware_translation.application.contracts.common import DocumentSection
from context_aware_translation.ui.viewmodels.router import RouteStateViewModel


class DocumentShellViewModel(RouteStateViewModel):
    """QML-facing state for the document-scoped shell chrome."""

    current_document_changed = Signal()
    labels_changed = Signal()
    selection_changed = Signal()

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._current_document_label = ""
        self.route_changed.connect(self.selection_changed.emit)

    @Property(bool, notify=current_document_changed)
    def has_current_document(self) -> bool:
        return bool(self._current_document_label)

    @Property(str, notify=current_document_changed)
    def current_document_label(self) -> str:
        return self._current_document_label

    @Property(str, notify=current_document_changed)
    def surface_title(self) -> str:
        return self._current_document_label

    @Property(str, notify=labels_changed)
    def scope_tip(self) -> str:
        return QCoreApplication.translate("DocumentWorkspaceView", "These tools apply only to the current document.")

    @Property(str, notify=labels_changed)
    def back_to_work_label(self) -> str:
        return QCoreApplication.translate("DocumentWorkspaceView", "Back to Work")

    @Property(str, notify=labels_changed)
    def ocr_label(self) -> str:
        return QCoreApplication.translate("WorkView", "OCR")

    @Property(str, notify=labels_changed)
    def terms_label(self) -> str:
        return QCoreApplication.translate("WorkView", "Terms")

    @Property(str, notify=labels_changed)
    def translation_label(self) -> str:
        return QCoreApplication.translate("WorkView", "Translation")

    @Property(str, notify=labels_changed)
    def images_label(self) -> str:
        return QCoreApplication.translate("DocumentImagesView", "Images")

    @Property(str, notify=labels_changed)
    def export_label(self) -> str:
        return QCoreApplication.translate("WorkView", "Export")

    @Property(bool, notify=selection_changed)
    def ocr_selected(self) -> bool:
        return self.route_state().document_section is DocumentSection.OCR

    @Property(bool, notify=selection_changed)
    def terms_selected(self) -> bool:
        return self.route_state().document_section is DocumentSection.TERMS

    @Property(bool, notify=selection_changed)
    def translation_selected(self) -> bool:
        return self.route_state().document_section is DocumentSection.TRANSLATION

    @Property(bool, notify=selection_changed)
    def images_selected(self) -> bool:
        return self.route_state().document_section is DocumentSection.IMAGES

    @Property(bool, notify=selection_changed)
    def export_selected(self) -> bool:
        return self.route_state().document_section is DocumentSection.EXPORT

    def current_section(self) -> DocumentSection | None:
        return self.route_state().document_section

    def set_document_context(
        self,
        project_id: str,
        document_id: int,
        document_label: str,
        *,
        section: DocumentSection = DocumentSection.OCR,
    ) -> None:
        normalized_label = document_label.strip()
        if normalized_label != self._current_document_label:
            self._current_document_label = normalized_label
            self.current_document_changed.emit()
            self.mark_changed()
        self.open_document(project_id, document_id, section)

    def show_section(self, section: DocumentSection) -> None:
        state = self.route_state()
        if state.project_id is None or state.document_id is None:
            return
        self.open_document(state.project_id, state.document_id, section)

    def show_ocr(self) -> None:
        self.show_section(DocumentSection.OCR)

    def show_terms(self) -> None:
        self.show_section(DocumentSection.TERMS)

    def show_translation(self) -> None:
        self.show_section(DocumentSection.TRANSLATION)

    def show_images(self) -> None:
        self.show_section(DocumentSection.IMAGES)

    def show_export(self) -> None:
        self.show_section(DocumentSection.EXPORT)

    def retranslate(self) -> None:
        self.labels_changed.emit()
        self.mark_changed()
