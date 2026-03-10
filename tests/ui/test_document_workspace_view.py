from __future__ import annotations

from unittest.mock import patch

import pytest

from context_aware_translation.application.contracts.common import (
    ActionState,
    DocumentRef,
    DocumentSection,
    ExportOption,
    ProjectRef,
    SurfaceStatus,
    UserMessage,
    UserMessageSeverity,
)
from context_aware_translation.application.contracts.document import (
    DocumentExportResult,
    DocumentExportState,
    DocumentImagesState,
    DocumentOCRActions,
    DocumentOCRState,
    DocumentOverviewState,
    DocumentSectionCard,
    DocumentTranslationState,
    DocumentWorkspaceState,
    ImageAssetState,
    OCRPageState,
    TranslationUnitActionState,
    TranslationUnitKind,
    TranslationUnitState,
)
from context_aware_translation.application.contracts.terms import (
    TermsScope,
    TermsScopeKind,
    TermsTableState,
    TermStatus,
    TermsToolbarState,
    TermTableRow,
)
from context_aware_translation.application.events import (
    DocumentInvalidatedEvent,
    InMemoryApplicationEventBus,
    SetupInvalidatedEvent,
    TermsInvalidatedEvent,
)
from tests.application.fakes import FakeDocumentService, FakeTermsService, FakeWorkService

try:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage
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


def _make_workspace_state() -> DocumentWorkspaceState:
    return DocumentWorkspaceState(
        project=ProjectRef(project_id="proj-1", name="One Piece"),
        document=DocumentRef(document_id=4, order_index=4, label="04.png"),
        active_tab=DocumentSection.OVERVIEW,
        available_tabs=[
            DocumentSection.OVERVIEW,
            DocumentSection.OCR,
            DocumentSection.TERMS,
            DocumentSection.TRANSLATION,
            DocumentSection.IMAGES,
            DocumentSection.EXPORT,
        ],
    )


def _make_terms_state() -> TermsTableState:
    return TermsTableState(
        scope=TermsScope(
            kind=TermsScopeKind.DOCUMENT,
            project=ProjectRef(project_id="proj-1", name="One Piece"),
            document=DocumentRef(document_id=4, order_index=4, label="04.png"),
        ),
        toolbar=TermsToolbarState(
            can_build=True,
            can_translate_pending=True,
            can_review=True,
            can_filter_noise=True,
        ),
        rows=[
            TermTableRow(
                term_id=1,
                term_key="ルフィ",
                term="ルフィ",
                translation="Luffy",
                description="Main character",
                occurrences=4,
                votes=2,
                reviewed=False,
                ignored=False,
                status=TermStatus.NEEDS_REVIEW,
            )
        ],
    )


def _make_ocr_state() -> DocumentOCRState:
    return DocumentOCRState(
        workspace=_make_workspace_state().model_copy(update={"active_tab": DocumentSection.OCR}),
        pages=[
            OCRPageState(
                source_id=101,
                page_number=1,
                total_pages=2,
                status=SurfaceStatus.DONE,
                extracted_text="hello\nworld",
            ),
            OCRPageState(
                source_id=102,
                page_number=2,
                total_pages=2,
                status=SurfaceStatus.READY,
                extracted_text="second page",
            ),
        ],
        current_page_index=0,
        actions=DocumentOCRActions(
            save=ActionState(enabled=True),
            run_current=ActionState(enabled=True),
            run_pending=ActionState(enabled=True),
        ),
    )


def _png(width: int = 200, height: int = 200) -> bytes:
    image = QImage(width, height, QImage.Format.Format_RGBA8888)
    image.fill(QColor("white"))
    payload = QByteArray()
    buffer = QBuffer(payload)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(payload)


def _make_translation_state() -> DocumentTranslationState:
    workspace = _make_workspace_state().model_copy(update={"active_tab": DocumentSection.TRANSLATION})
    return DocumentTranslationState(
        workspace=workspace,
        run_action=ActionState(enabled=True),
        batch_action=ActionState(enabled=True),
        supports_batch=True,
        units=[
            TranslationUnitState(
                unit_id="1",
                unit_kind=TranslationUnitKind.CHUNK,
                label="Chunk 1",
                status=SurfaceStatus.READY,
                source_text="全員さっさと降りろ!!!",
                translated_text="Everyone, get down now!!!",
                line_count=1,
                actions=TranslationUnitActionState(can_save=True, can_retranslate=True),
            )
        ],
        current_unit_id="1",
    )


def _make_view():
    from context_aware_translation.ui.features.document_workspace_view import DocumentWorkspaceView

    bus = InMemoryApplicationEventBus()
    document_service = FakeDocumentService(
        workspace=_make_workspace_state(),
        overview=DocumentOverviewState(
            workspace=_make_workspace_state(),
            sections=[
                DocumentSectionCard(
                    section=DocumentSection.TERMS,
                    status=SurfaceStatus.READY,
                    summary="Open Terms",
                )
            ],
        ),
        ocr=_make_ocr_state(),
        ocr_page_images={101: None, 102: None},
        translation=_make_translation_state(),
        images=DocumentImagesState(
            workspace=_make_workspace_state().model_copy(update={"active_tab": DocumentSection.IMAGES}),
            assets=[],
        ),
        export=DocumentExportState(
            workspace=_make_workspace_state(),
            can_export=True,
            available_formats=[ExportOption(format_id="txt", label="TXT", is_default=True)],
            default_output_path="/tmp/04.txt",
        ),
    )
    terms_service = FakeTermsService(project_state=_make_terms_state(), document_state=_make_terms_state())
    work_service = FakeWorkService(state_by_project={"proj-1": object()})
    view = DocumentWorkspaceView("proj-1", 4, document_service, terms_service, work_service, bus)
    return view, bus, document_service, terms_service


def test_document_workspace_view_renders_shell_tabs():
    view, _bus, _document_service, _terms_service = _make_view()
    try:
        assert view.title_label.text() == "04.png"
        assert "current document" in view.tip_label.text().lower()
        assert [view.tab_widget.tabText(index) for index in range(view.tab_widget.count())] == [
            "OCR",
            "Terms",
            "Translation",
            "Images",
            "Export",
        ]
    finally:
        view.cleanup()


def test_document_workspace_terms_tab_uses_shared_terms_component():
    view, _bus, _document_service, terms_service = _make_view()
    try:
        view.show_section(DocumentSection.TERMS)
        terms_tab = view.tab_widget.currentWidget()
        assert terms_tab is not None
        assert hasattr(terms_tab, "table_panel")
        assert terms_tab.table_panel.proxy_model.rowCount() == 1

        terms_tab.build_button.click()
        terms_tab.translate_button.click()
        terms_tab.review_button.click()
        with patch.object(QMessageBox, "warning") as mock_warning:
            terms_tab.filter_noise_button.click()
        mock_warning.assert_not_called()
        translation_item = terms_tab.table_panel.table_model.item(0, 1)
        translation_item.setText("Monkey D. Luffy")

        call_names = [name for name, _payload in terms_service.calls]
        assert "build_terms" in call_names
        assert "translate_pending" in call_names
        assert "review_terms" in call_names
        assert "filter_noise" in call_names
        assert "update_term" in call_names
    finally:
        view.cleanup()


def test_document_workspace_ocr_tab_routes_save_and_run_actions():
    view, _bus, document_service, _terms_service = _make_view()
    try:
        view.show_section(DocumentSection.OCR)
        ocr_tab = view.tab_widget.currentWidget()
        assert ocr_tab is not None
        assert hasattr(ocr_tab, "save_button")
        assert ocr_tab.page_spinbox.maximum() == 2

        ocr_tab.text_edit.setPlainText("edited\npage")
        ocr_tab.save_button.click()
        ocr_tab.run_current_button.click()
        ocr_tab.run_pending_button.click()

        call_names = [name for name, _payload in document_service.calls]
        assert "save_ocr" in call_names
        assert call_names.count("run_ocr") == 2
    finally:
        view.cleanup()


def test_document_workspace_translation_tab_uses_migrated_translation_widget():
    view, _bus, document_service, _terms_service = _make_view()
    try:
        view.show_section(DocumentSection.TRANSLATION)
        translation_tab = view.tab_widget.currentWidget()
        assert translation_tab is not None
        assert hasattr(translation_tab, "unit_list")
        assert translation_tab.unit_list.count() == 1
        assert translation_tab.translate_button.isEnabled()

        translation_tab.translation_text.setPlainText("Everyone get down now!!!")
        translation_tab.save_button.click()
        translation_tab.translate_button.click()

        call_names = [name for name, _payload in document_service.calls]
        assert "get_translation" in call_names
        assert "save_translation" in call_names
        assert "run_translation" in call_names
    finally:
        view.cleanup()


def test_document_workspace_refreshes_on_invalidations():
    view, bus, document_service, terms_service = _make_view()
    try:
        bus.publish(DocumentInvalidatedEvent(project_id="proj-1", document_id=4))
        bus.publish(TermsInvalidatedEvent(project_id="proj-1", document_id=4))
        bus.publish(SetupInvalidatedEvent(project_id="proj-1"))

        workspace_calls = [name for name, _payload in document_service.calls if name == "get_workspace"]
        ocr_calls = [name for name, _payload in document_service.calls if name == "get_ocr"]
        terms_calls = [name for name, _payload in terms_service.calls if name == "get_document_terms"]
        assert len(workspace_calls) == 4
        assert len(ocr_calls) == 4
        assert len(terms_calls) == 4
    finally:
        view.cleanup()


def test_document_workspace_export_tab_runs_document_service():
    from PySide6.QtWidgets import QMessageBox

    from context_aware_translation.ui.features.document_workspace_view import DocumentWorkspaceView

    bus = InMemoryApplicationEventBus()
    export_state = DocumentExportState(
        workspace=_make_workspace_state(),
        can_export=True,
        available_formats=[ExportOption(format_id="txt", label="TXT", is_default=True)],
        default_output_path="/tmp/04.txt",
        supports_preserve_structure=True,
    )
    document_service = FakeDocumentService(
        workspace=_make_workspace_state(),
        overview=DocumentOverviewState(
            workspace=_make_workspace_state(),
            sections=[
                DocumentSectionCard(
                    section=DocumentSection.EXPORT,
                    status=SurfaceStatus.READY,
                    summary="Export",
                )
            ],
        ),
        export=export_state,
        translation=_make_translation_state(),
        images=DocumentImagesState(
            workspace=_make_workspace_state().model_copy(update={"active_tab": DocumentSection.IMAGES}),
            assets=[],
        ),
        ocr=_make_ocr_state(),
        ocr_page_images={101: None, 102: None},
        export_result=DocumentExportResult(
            document_id=4,
            output_path="/tmp/04.txt",
            message=UserMessage(severity=UserMessageSeverity.SUCCESS, text="Export complete."),
        ),
    )
    terms_service = FakeTermsService(project_state=_make_terms_state(), document_state=_make_terms_state())
    work_service = FakeWorkService(state_by_project={"proj-1": object()})
    view = DocumentWorkspaceView("proj-1", 4, document_service, terms_service, work_service, bus)
    try:
        view.show_section(DocumentSection.EXPORT)
        export_tab = view.tab_widget.currentWidget()
        assert export_tab is not None
        export_tab.controls.preserve_structure_cb.setChecked(True)
        export_tab.controls.output_path_edit.setText("/tmp/export-dir")
        with patch.object(QMessageBox, "warning") as mock_warning:
            export_tab.export_button.click()
        mock_warning.assert_not_called()

        assert document_service.calls[-1][0] == "export_document"
        request = document_service.calls[-1][1]
        assert request.project_id == "proj-1"
        assert request.document_id == 4
        assert request.options["preserve_structure"] is True
        assert not export_tab.result_label.isHidden()
        assert export_tab.result_label.text() == "Export complete."
    finally:
        view.cleanup()


def test_document_workspace_images_tab_refits_when_activated():
    view, _bus, document_service, _terms_service = _make_view()
    image_bytes = _png()
    document_service.images = DocumentImagesState(
        workspace=_make_workspace_state().model_copy(update={"active_tab": DocumentSection.IMAGES}),
        assets=[
            document_service.images.assets[0].model_copy(update={"source_id": 101})
            if document_service.images.assets
            else ImageAssetState(
                asset_id="asset-1",
                label="Image 1",
                status=SurfaceStatus.READY,
                source_id=101,
                translated_text="hello",
                can_run=True,
            )
        ],
    )
    document_service.ocr_page_images = {101: image_bytes}
    try:
        view.resize(1400, 900)
        view.show()
        QApplication.processEvents()
        view.refresh()
        QApplication.processEvents()

        view.show_section(DocumentSection.IMAGES)
        QApplication.processEvents()
        QApplication.processEvents()

        images_tab = view.tab_widget.currentWidget()
        assert images_tab is not None
        assert images_tab.image_viewer.transform().m11() > 1.0
    finally:
        view.cleanup()
