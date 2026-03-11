from __future__ import annotations

import pytest

from context_aware_translation.application.contracts.common import DocumentSection
from context_aware_translation.ui.viewmodels.document_shell import DocumentShellViewModel

try:
    from PySide6.QtWidgets import QApplication

    HAS_PYSIDE6 = True
except ImportError:  # pragma: no cover - environment dependent
    HAS_PYSIDE6 = False

pytestmark = pytest.mark.skipif(not HAS_PYSIDE6, reason="PySide6 not available")


@pytest.fixture(autouse=True, scope="module")
def _qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_document_shell_viewmodel_tracks_document_context_and_section_selection() -> None:
    viewmodel = DocumentShellViewModel()

    viewmodel.set_document_context("proj-1", 7, "Chapter 7", section=DocumentSection.TRANSLATION)

    assert viewmodel.has_current_document is True
    assert viewmodel.current_document_label == "Chapter 7"
    assert viewmodel.surface_title == "Chapter 7"
    assert viewmodel.scope == "document"
    assert viewmodel.project_id == "proj-1"
    assert viewmodel.document_id == 7
    assert viewmodel.document_section == DocumentSection.TRANSLATION.value
    assert viewmodel.current_section() is DocumentSection.TRANSLATION
    assert viewmodel.translation_selected is True
    assert viewmodel.ocr_selected is False

    viewmodel.show_images()
    assert viewmodel.current_section() is DocumentSection.IMAGES
    assert viewmodel.images_selected is True
    assert viewmodel.translation_selected is False

    viewmodel.show_export()
    assert viewmodel.current_section() is DocumentSection.EXPORT
    assert viewmodel.export_selected is True


def test_document_shell_viewmodel_exposes_document_scope_labels() -> None:
    viewmodel = DocumentShellViewModel()

    assert viewmodel.back_to_work_label == "Back to Work"
    assert viewmodel.ocr_label == "OCR"
    assert viewmodel.terms_label == "Terms"
    assert viewmodel.translation_label == "Translation"
    assert viewmodel.images_label == "Images"
    assert viewmodel.export_label == "Export"
    assert "current document" in viewmodel.scope_tip.lower()
