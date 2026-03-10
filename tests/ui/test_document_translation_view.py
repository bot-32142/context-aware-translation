from __future__ import annotations

from unittest.mock import patch

import pytest

from context_aware_translation.application.contracts.common import (
    ActionState,
    BlockerCode,
    BlockerInfo,
    DocumentRef,
    ProjectRef,
    SurfaceStatus,
)
from context_aware_translation.application.contracts.document import (
    DocumentSection,
    DocumentTranslationState,
    DocumentWorkspaceState,
    TranslationUnitActionState,
    TranslationUnitKind,
    TranslationUnitState,
)
from tests.application.fakes import FakeDocumentService

try:
    from PySide6.QtWidgets import QApplication, QMessageBox

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


def _make_state() -> DocumentTranslationState:
    workspace = DocumentWorkspaceState(
        project=ProjectRef(project_id="proj-1", name="One Piece"),
        document=DocumentRef(document_id=4, order_index=4, label="04.png"),
        active_tab=DocumentSection.TRANSLATION,
        available_tabs=[
            DocumentSection.OCR,
            DocumentSection.TERMS,
            DocumentSection.TRANSLATION,
            DocumentSection.IMAGES,
            DocumentSection.EXPORT,
        ],
    )
    return DocumentTranslationState(
        workspace=workspace,
        units=[
            TranslationUnitState(
                unit_id="1",
                unit_kind=TranslationUnitKind.CHUNK,
                label="Chunk 1",
                status=SurfaceStatus.READY,
                source_text="One\nTwo",
                translated_text="Uno\nDos",
                line_count=2,
                actions=TranslationUnitActionState(can_save=True, can_retranslate=True),
            ),
            TranslationUnitState(
                unit_id="2",
                unit_kind=TranslationUnitKind.PAGE,
                label="Page 2",
                status=SurfaceStatus.BLOCKED,
                source_text="",
                actions=TranslationUnitActionState(can_save=False, can_retranslate=False),
                blocker=BlockerInfo(code=BlockerCode.NOTHING_TO_DO, message="No OCR text detected on this page."),
            ),
        ],
        run_action=ActionState(enabled=True),
        batch_action=ActionState(enabled=True),
        supports_batch=True,
        current_unit_id="1",
    )


def test_document_translation_view_renders_units_and_routes_actions():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    state = _make_state()
    service = FakeDocumentService(workspace=state.workspace, translation=state)
    view = DocumentTranslationView(service, "proj-1", 4)
    try:
        view.refresh()
        assert view.unit_list.count() == 2
        assert view.translate_button.isEnabled()
        assert view.batch_translate_button.isEnabled()
        assert view.save_button.isEnabled()
        assert view.retranslate_button.isEnabled()
        assert not view.previous_button.isEnabled()
        assert view.next_button.isEnabled()
        assert "Line count must stay at 2" in view.line_hint.text()

        view.translation_text.setPlainText("One\nTwo updated")
        view.save_button.click()
        view.translate_button.click()
        view.enable_polish_cb.setChecked(False)
        view.batch_translate_button.click()

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            view.retranslate_button.click()

        call_names = [name for name, _payload in service.calls]
        assert "run_translation" in call_names
        assert "save_translation" in call_names
        assert "retranslate" in call_names
        assert any(name == "run_translation" and payload.batch for name, payload in service.calls if name == "run_translation")
        view.next_button.click()
        assert view.unit_list.currentRow() == 1
    finally:
        view.deleteLater()


def test_document_translation_view_disables_editing_for_blocked_page():
    from context_aware_translation.ui.features.document_translation_view import DocumentTranslationView

    state = _make_state()
    service = FakeDocumentService(workspace=state.workspace, translation=state)
    view = DocumentTranslationView(service, "proj-1", 4)
    try:
        view.refresh()
        view.unit_list.setCurrentRow(1)

        assert not view.save_button.isEnabled()
        assert not view.retranslate_button.isEnabled()
        assert view.translation_text.isReadOnly()
        assert "No OCR text detected" in view.blocker_label.text()
    finally:
        view.deleteLater()
