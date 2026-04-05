from __future__ import annotations

from unittest.mock import patch

import pytest

from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    ActionState,
    BlockerCode,
    BlockerInfo,
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
    DocumentTranslationState,
    DocumentWorkspaceState,
    ImageAssetState,
    OCRPageState,
    TranslateAndExportState,
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
from context_aware_translation.application.errors import ApplicationError, ApplicationErrorCode, ApplicationErrorPayload
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
        active_tab=DocumentSection.OCR,
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
                term_type="character",
                translation="Luffy",
                description="Main character",
                occurrences=4,
                votes=2,
                reviewed=False,
                ignored=False,
                status=TermStatus.NEEDS_REVIEW,
            ),
            TermTableRow(
                term_id=2,
                term_key="ニカ",
                term="ニカ",
                term_type="organization",
                translation="Nika",
                description="Sun god",
                occurrences=2,
                votes=1,
                reviewed=False,
                ignored=False,
                status=TermStatus.NEEDS_REVIEW,
            ),
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


def _make_translate_and_export_state(
    *,
    can_start: bool = True,
    batch_available: bool = True,
    reembedding_available: bool = True,
    batch_blocker: str | None = None,
    reembedding_blocker: str | None = None,
) -> TranslateAndExportState:
    return TranslateAndExportState(
        workspace=_make_workspace_state(),
        can_start=can_start,
        available_formats=[ExportOption(format_id="epub", label="EPUB", is_default=True)],
        default_output_path="/tmp/book.epub",
        supports_preserve_structure=True,
        supports_original_image_export=True,
        supports_epub_layout_conversion=True,
        batch_available=batch_available,
        batch_blocker=(
            BlockerInfo(code=BlockerCode.NEEDS_SETUP, message=batch_blocker) if batch_blocker is not None else None
        ),
        reembedding_available=reembedding_available,
        reembedding_blocker=(
            BlockerInfo(code=BlockerCode.NEEDS_SETUP, message=reembedding_blocker)
            if reembedding_blocker is not None
            else None
        ),
    )


def _cleanup_view(view) -> None:  # noqa: ANN001
    view.close()
    QApplication.processEvents()
    view.cleanup()
    QApplication.processEvents()


def _current_section_widget(view):
    current_section = view.current_section()
    assert current_section is not None
    widget = view.section_widget(current_section)
    assert widget is not None
    return widget


def test_document_workspace_view_renders_shell_tabs():
    view, _bus, _document_service, _terms_service = _make_view()
    try:
        root = view.shell_host.chrome_host.rootObject()
        assert root is not None
        assert root.objectName() == "documentShellChrome"
        assert root.property("surfaceTitleText") == "04.png"
        assert "current document" in str(root.property("scopeTipText")).lower()
        assert root.property("backToWorkLabelText") == "Back to Work"
        assert root.property("ocrLabelText") == "OCR"
        assert root.property("termsLabelText") == "Terms"
        assert root.property("translationLabelText") == "Translation"
        assert root.property("imagesLabelText") == "Images"
        assert root.property("exportLabelText") == "Export"
        assert view.current_section() is DocumentSection.OCR
    finally:
        _cleanup_view(view)


def test_document_workspace_only_builds_current_section_initially():
    view, _bus, document_service, terms_service = _make_view()
    try:
        assert view.current_section() is DocumentSection.OCR
        assert view.section_widget(DocumentSection.OCR) is not None
        assert view.section_widget(DocumentSection.TERMS) is None
        assert view.section_widget(DocumentSection.TRANSLATION) is None
        assert view.section_widget(DocumentSection.IMAGES) is None
        assert view.section_widget(DocumentSection.EXPORT) is None

        workspace_calls = [name for name, _payload in document_service.calls if name == "get_workspace"]
        ocr_calls = [name for name, _payload in document_service.calls if name == "get_ocr"]
        translation_calls = [name for name, _payload in document_service.calls if name == "get_translation"]
        images_calls = [name for name, _payload in document_service.calls if name == "get_images"]
        terms_calls = [name for name, _payload in terms_service.calls if name == "get_document_terms"]
        assert len(workspace_calls) == 1
        assert len(ocr_calls) == 1
        assert len(translation_calls) == 0
        assert len(images_calls) == 0
        assert len(terms_calls) == 0
    finally:
        _cleanup_view(view)


def test_document_workspace_terms_tab_uses_shared_terms_component():
    view, _bus, _document_service, terms_service = _make_view()
    try:
        view.show_section(DocumentSection.TERMS)
        terms_tab = _current_section_widget(view)
        assert hasattr(terms_tab, "table_panel")
        assert terms_tab.table_panel.proxy_model.rowCount() == 2

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
        assert "update_term_rows" in call_names
    finally:
        _cleanup_view(view)


def test_document_workspace_terms_context_menu_preserves_multi_selection_and_opens_editors():
    view, _bus, _document_service, terms_service = _make_view()
    try:
        view.show()
        QApplication.processEvents()
        view.show_section(DocumentSection.TERMS)
        terms_tab = _current_section_widget(view)

        second_rect = terms_tab.table_panel.table_view.visualRect(terms_tab.table_panel.proxy_model.index(1, 0))

        terms_tab.table_panel._toggle_row_selection(0)
        terms_tab.table_panel._toggle_row_selection(1)
        QApplication.processEvents()

        assert len(terms_tab.table_panel.selected_rows()) == 2
        terms_tab._show_context_menu(second_rect.center())
        assert len(terms_tab.table_panel.selected_rows()) == 2

        terms_tab.edit_selected_action.trigger()
        QApplication.processEvents()
        assert terms_tab.table_panel.table_view.isPersistentEditorOpen(terms_tab.table_panel.proxy_model.index(0, 1))
        assert terms_tab.table_panel.table_view.isPersistentEditorOpen(terms_tab.table_panel.proxy_model.index(1, 1))

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            terms_tab.mark_reviewed_action.trigger()
        assert any(name == "bulk_update_terms" for name, _payload in terms_service.calls)
    finally:
        _cleanup_view(view)


def test_document_workspace_terms_bulk_updates_stay_local_first():
    view, bus, document_service, terms_service = _make_view()
    original_bulk_update = terms_service.bulk_update_terms

    def _bulk_update(request):  # noqa: ANN001
        result = original_bulk_update(request)
        bus.publish(TermsInvalidatedEvent(project_id="proj-1", document_id=4))
        return result

    terms_service.bulk_update_terms = _bulk_update
    try:
        view.show()
        QApplication.processEvents()
        view.show_section(DocumentSection.TERMS)
        terms_tab = _current_section_widget(view)
        initial_workspace_calls = len([name for name, _payload in document_service.calls if name == "get_workspace"])
        initial_terms_calls = len([name for name, _payload in terms_service.calls if name == "get_document_terms"])

        terms_tab.table_panel._toggle_row_selection(0)
        QApplication.processEvents()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            terms_tab.mark_reviewed_action.trigger()

        workspace_calls = [name for name, _payload in document_service.calls if name == "get_workspace"]
        terms_calls = [name for name, _payload in terms_service.calls if name == "get_document_terms"]
        assert len(workspace_calls) == initial_workspace_calls
        assert len(terms_calls) == initial_terms_calls
    finally:
        _cleanup_view(view)


def test_document_workspace_ocr_tab_routes_save_and_run_actions():
    view, _bus, document_service, _terms_service = _make_view()
    try:
        view.show_section(DocumentSection.OCR)
        ocr_tab = _current_section_widget(view)
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
        _cleanup_view(view)


def test_document_workspace_translation_tab_uses_migrated_translation_widget():
    view, _bus, document_service, _terms_service = _make_view()
    try:
        view.show_section(DocumentSection.TRANSLATION)
        translation_tab = _current_section_widget(view)
        root = translation_tab.chrome_host.rootObject()
        assert root is not None
        assert hasattr(translation_tab, "unit_list")
        assert translation_tab.unit_list.count() == 1
        assert translation_tab.viewmodel.can_translate is True

        translation_tab.translation_text.setPlainText("Everyone get down now!!!")
        translation_tab.save_button.click()
        root.translateRequested.emit()

        call_names = [name for name, _payload in document_service.calls]
        assert "get_translation" in call_names
        assert "save_translation" in call_names
        assert "run_translation" in call_names
    finally:
        _cleanup_view(view)


def test_document_workspace_refreshes_on_invalidations():
    view, bus, document_service, terms_service = _make_view()
    try:
        bus.publish(DocumentInvalidatedEvent(project_id="proj-1", document_id=4))
        bus.publish(TermsInvalidatedEvent(project_id="proj-1", document_id=4))
        bus.publish(SetupInvalidatedEvent(project_id="proj-1"))

        workspace_calls = [name for name, _payload in document_service.calls if name == "get_workspace"]
        ocr_calls = [name for name, _payload in document_service.calls if name == "get_ocr"]
        terms_calls = [name for name, _payload in terms_service.calls if name == "get_document_terms"]
        assert len(workspace_calls) == 3
        assert len(ocr_calls) == 3
        assert len(terms_calls) == 0

        view.show_section(DocumentSection.TERMS)
        QApplication.processEvents()

        terms_calls = [name for name, _payload in terms_service.calls if name == "get_document_terms"]
        assert len(terms_calls) == 1
    finally:
        _cleanup_view(view)


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
        export_tab = _current_section_widget(view)
        root = export_tab.chrome_host.rootObject()
        assert root is not None
        assert root.objectName() == "documentExportPaneChrome"
        assert root.property("exportLabelText") == "Export This Document"
        assert root.property("exportTooltipText") == "Export this document using the selected format and options."
        export_tab.controls.preserve_structure_cb.setChecked(True)
        export_tab.controls.output_path_edit.setText("/tmp/export-dir")
        with patch.object(QMessageBox, "warning") as mock_warning:
            root.exportRequested.emit()
        mock_warning.assert_not_called()

        assert document_service.calls[-1][0] == "export_document"
        request = document_service.calls[-1][1]
        assert request.project_id == "proj-1"
        assert request.document_id == 4
        assert request.options["preserve_structure"] is True
        assert "background-color: #fdfaf5" in export_tab.controls_card.styleSheet()
        assert root.property("hasResult") is True
        assert root.property("resultText") == "Export complete."
        assert export_tab.viewmodel.result_text == "Export complete."
    finally:
        _cleanup_view(view)


def test_document_workspace_export_tab_exposes_epub_layout_toggle():
    from context_aware_translation.ui.features.document_workspace_view import DocumentWorkspaceView

    bus = InMemoryApplicationEventBus()
    export_state = DocumentExportState(
        workspace=_make_workspace_state(),
        can_export=True,
        available_formats=[ExportOption(format_id="epub", label="EPUB", is_default=True)],
        default_output_path="/tmp/book.epub",
        supports_epub_layout_conversion=True,
    )
    document_service = FakeDocumentService(
        workspace=_make_workspace_state(),
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
            output_path="/tmp/book.epub",
            message=UserMessage(severity=UserMessageSeverity.SUCCESS, text="Export complete."),
        ),
    )
    terms_service = FakeTermsService(project_state=_make_terms_state(), document_state=_make_terms_state())
    work_service = FakeWorkService(state_by_project={"proj-1": object()})
    view = DocumentWorkspaceView("proj-1", 4, document_service, terms_service, work_service, bus)
    try:
        view.show_section(DocumentSection.EXPORT)
        export_tab = _current_section_widget(view)
        assert export_tab.controls.epub_force_horizontal_ltr_cb.isHidden() is False

        export_tab.controls.epub_force_horizontal_ltr_cb.setChecked(True)
        with patch("context_aware_translation.ui.features.document_workspace_view.QMessageBox.warning") as mock_warning:
            export_tab._run_export()

        mock_warning.assert_not_called()
        request = document_service.calls[-1][1]
        assert request.options["epub_force_horizontal_ltr"] is True
    finally:
        _cleanup_view(view)


def test_document_workspace_export_tab_exposes_original_image_toggle():
    from context_aware_translation.ui.features.document_workspace_view import DocumentWorkspaceView

    bus = InMemoryApplicationEventBus()
    export_state = DocumentExportState(
        workspace=_make_workspace_state(),
        can_export=True,
        available_formats=[ExportOption(format_id="epub", label="EPUB", is_default=True)],
        default_output_path="/tmp/book.epub",
        supports_original_image_export=True,
    )
    document_service = FakeDocumentService(
        workspace=_make_workspace_state(),
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
            output_path="/tmp/book.epub",
            message=UserMessage(severity=UserMessageSeverity.SUCCESS, text="Export complete."),
        ),
    )
    terms_service = FakeTermsService(project_state=_make_terms_state(), document_state=_make_terms_state())
    work_service = FakeWorkService(state_by_project={"proj-1": object()})
    view = DocumentWorkspaceView("proj-1", 4, document_service, terms_service, work_service, bus)
    try:
        view.show_section(DocumentSection.EXPORT)
        export_tab = _current_section_widget(view)
        assert export_tab.controls.use_original_images_cb.isHidden() is False

        export_tab.controls.use_original_images_cb.setChecked(True)
        with patch("context_aware_translation.ui.features.document_workspace_view.QMessageBox.warning") as mock_warning:
            export_tab._run_export()

        mock_warning.assert_not_called()
        request = document_service.calls[-1][1]
        assert request.options["use_original_images"] is True
    finally:
        _cleanup_view(view)


def test_translate_and_export_dialog_runs_document_service_with_default_one_shot_options():
    from context_aware_translation.ui.features.document_workspace_view import TranslateAndExportDialog

    state = _make_translate_and_export_state()
    document_service = FakeDocumentService(
        workspace=_make_workspace_state(),
        translate_and_export=state,
        command_result=AcceptedCommand(
            command_name="run_translate_and_export",
            message=UserMessage(severity=UserMessageSeverity.SUCCESS, text="Translate and Export queued."),
        ),
    )
    dialog = TranslateAndExportDialog(document_service, state)
    try:
        dialog.batch_cb.setChecked(True)
        dialog.reembedding_cb.setChecked(True)
        assert dialog.controls.use_original_images_cb.isHidden() is True
        assert dialog.controls.epub_force_horizontal_ltr_cb.isChecked() is True
        dialog.controls.output_path_edit.setText("/tmp/out-dir")
        with patch.object(QMessageBox, "information") as mock_information:
            dialog.start_button.click()

        assert (document_service.calls[-1][0],) == ("run_translate_and_export",)
        request = document_service.calls[-1][1]
        assert request.project_id == "proj-1"
        assert request.document_id == 4
        assert request.use_batch is True
        assert request.use_reembedding is True
        assert request.enable_polish is True
        assert request.output_path == "/tmp/out-dir"
        assert request.options["preserve_structure"] is False
        assert request.options["use_original_images"] is False
        assert request.options["epub_force_horizontal_ltr"] is True
        mock_information.assert_called_once()
    finally:
        dialog.close()


def test_translate_and_export_dialog_disables_unsupported_toggles():
    from context_aware_translation.ui.features.document_workspace_view import TranslateAndExportDialog

    state = _make_translate_and_export_state(
        batch_available=False,
        reembedding_available=False,
        batch_blocker="Async batch translation is unavailable.",
        reembedding_blocker="Image reembedding is unavailable.",
    )
    dialog = TranslateAndExportDialog(
        FakeDocumentService(workspace=_make_workspace_state(), translate_and_export=state), state
    )
    try:
        assert dialog.batch_cb.isEnabled() is False
        assert dialog.reembedding_cb.isEnabled() is False
        assert "Async batch translation is unavailable." in dialog.batch_hint.text()
        assert "Image reembedding is unavailable." in dialog.reembedding_hint.text()
        assert dialog.start_button.isEnabled() is True
    finally:
        dialog.close()


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

        images_tab = _current_section_widget(view)
        assert images_tab.image_viewer.transform().m11() > 1.0
    finally:
        _cleanup_view(view)


def test_document_workspace_invalidation_refresh_preserves_ocr_draft():
    view, bus, _document_service, _terms_service = _make_view()
    try:
        view.show_section(DocumentSection.OCR)
        ocr_tab = _current_section_widget(view)
        ocr_tab.text_edit.setPlainText("draft survives")

        bus.publish(DocumentInvalidatedEvent(project_id="proj-1", document_id=4))

        assert ocr_tab.text_edit.toPlainText() == "draft survives"
    finally:
        _cleanup_view(view)


def test_document_workspace_missing_document_navigates_back_without_warning():
    from context_aware_translation.ui.features.document_workspace_view import DocumentWorkspaceView

    bus = InMemoryApplicationEventBus()
    document_service = FakeDocumentService(
        workspace=_make_workspace_state(),
        ocr=_make_ocr_state(),
        ocr_page_images={101: None, 102: None},
    )
    terms_service = FakeTermsService(project_state=_make_terms_state(), document_state=_make_terms_state())
    work_service = FakeWorkService(state_by_project={"proj-1": object()})
    view = DocumentWorkspaceView("proj-1", 4, document_service, terms_service, work_service, bus)
    back_events: list[bool] = []
    view.back_requested.connect(lambda: back_events.append(True))

    def _raise_missing(_project_id: str, _document_id: int):
        raise ApplicationError(
            ApplicationErrorPayload(code=ApplicationErrorCode.NOT_FOUND, message="Document not found: 4")
        )

    document_service.get_workspace = _raise_missing
    try:
        with patch.object(QMessageBox, "warning") as mock_warning:
            bus.publish(DocumentInvalidatedEvent(project_id="proj-1", document_id=4))
        mock_warning.assert_not_called()
        assert back_events == [True]
        assert view._document_missing is True
    finally:
        _cleanup_view(view)


def test_document_workspace_refresh_handles_workspace_error_without_raising():
    from context_aware_translation.ui.features.document_workspace_view import DocumentWorkspaceView

    bus = InMemoryApplicationEventBus()
    document_service = FakeDocumentService(
        workspace=_make_workspace_state(),
        ocr=_make_ocr_state(),
        ocr_page_images={101: None, 102: None},
    )
    terms_service = FakeTermsService(project_state=_make_terms_state(), document_state=_make_terms_state())
    work_service = FakeWorkService(state_by_project={"proj-1": object()})

    def _raise(_project_id: str, _document_id: int):
        raise ApplicationError(
            ApplicationErrorPayload(code=ApplicationErrorCode.INTERNAL, message="workspace refresh failed")
        )

    document_service.get_workspace = _raise
    with patch.object(QMessageBox, "warning") as mock_warning:
        view = DocumentWorkspaceView("proj-1", 4, document_service, terms_service, work_service, bus)
    try:
        mock_warning.assert_called()
        assert view.current_section() is None
    finally:
        _cleanup_view(view)


def test_document_workspace_event_refresh_handles_child_refresh_error_without_raising():
    view, bus, _document_service, _terms_service = _make_view()
    try:
        view.show_section(DocumentSection.OCR)
        ocr_tab = _current_section_widget(view)

        def _raise():
            raise ApplicationError(
                ApplicationErrorPayload(code=ApplicationErrorCode.INTERNAL, message="ocr pane failed")
            )

        ocr_tab.refresh = _raise
        with patch.object(QMessageBox, "warning") as mock_warning:
            bus.publish(DocumentInvalidatedEvent(project_id="proj-1", document_id=4))
        mock_warning.assert_called()
    finally:
        _cleanup_view(view)
