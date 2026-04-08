from __future__ import annotations

from unittest.mock import patch

import pytest

from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    ActionState,
    BlockerCode,
    BlockerInfo,
    DocumentRef,
    DocumentRowActionKind,
    DocumentSection,
    ExportOption,
    ExportResult,
    NavigationTarget,
    NavigationTargetKind,
    ProjectRef,
    SurfaceStatus,
    UserMessage,
    UserMessageSeverity,
)
from context_aware_translation.application.contracts.document import (
    DocumentExportState,
    DocumentImagesState,
    DocumentOCRActions,
    DocumentOCRState,
    DocumentTranslationState,
    DocumentWorkspaceState,
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
    TermsToolbarState,
)
from context_aware_translation.application.contracts.work import (
    ContextFrontierState,
    DeleteDocumentStackRequest,
    DocumentRowAction,
    ExportDialogState,
    ImportDocumentsRequest,
    ImportDocumentTypeOption,
    ImportInspectionState,
    InspectImportPathsRequest,
    ResetDocumentStackRequest,
    WorkboardState,
    WorkDocumentRow,
    WorkMutationResult,
)
from context_aware_translation.application.events import InMemoryApplicationEventBus, WorkboardInvalidatedEvent
from tests.application.fakes import FakeDocumentService, FakeTermsService, FakeWorkService

try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
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


def _make_workspace_state(active_tab: DocumentSection = DocumentSection.OCR) -> DocumentWorkspaceState:
    return DocumentWorkspaceState(
        project=ProjectRef(project_id="proj-1", name="One Piece"),
        document=DocumentRef(document_id=4, order_index=4, label="04.png"),
        active_tab=active_tab,
    )


def _make_workboard(
    *, action: DocumentRowAction, setup_blocker: BlockerInfo | None = None, summary: str = "Open Translation"
) -> WorkboardState:
    return WorkboardState(
        project=ProjectRef(project_id="proj-1", name="One Piece"),
        context_frontier=ContextFrontierState(summary="Context ready through 03"),
        rows=[
            WorkDocumentRow(
                document=DocumentRef(document_id=4, order_index=4, label="04.png"),
                status=SurfaceStatus.READY,
                source_count=2,
                ocr_status="Complete",
                terms_status="In progress (1/2)",
                translation_status="In progress (1/2)",
                state_summary=summary,
                blocker=None,
                primary_action=action,
            )
        ],
        setup_blocker=setup_blocker,
    )


def _make_view(*, work_state: WorkboardState):
    from context_aware_translation.ui.features.work_view import WorkView

    bus = InMemoryApplicationEventBus()
    work_service = FakeWorkService(state_by_project={"proj-1": work_state})
    work_service.import_inspection_state = ImportInspectionState(
        selected_paths=["/tmp/04.png"],
        available_types=[ImportDocumentTypeOption(document_type="manga", label="Manga")],
        summary="04.png",
    )
    work_service.import_result = AcceptedCommand(
        command_name="import_documents",
        message=UserMessage(severity=UserMessageSeverity.SUCCESS, text="Import complete."),
    )
    work_service.reset_result = WorkMutationResult(
        message=UserMessage(severity=UserMessageSeverity.SUCCESS, text="Reset complete.")
    )
    work_service.delete_result = WorkMutationResult(
        message=UserMessage(severity=UserMessageSeverity.SUCCESS, text="Delete complete.")
    )
    document_service = FakeDocumentService(
        workspace=_make_workspace_state(),
        export=DocumentExportState(
            workspace=_make_workspace_state(active_tab=DocumentSection.EXPORT),
            can_export=True,
            available_formats=[ExportOption(format_id="txt", label="TXT", is_default=True)],
            default_output_path="/tmp/04.txt",
        ),
        translate_and_export=TranslateAndExportState(
            workspace=_make_workspace_state(),
            can_start=True,
            available_formats=[ExportOption(format_id="txt", label="TXT", is_default=True)],
            default_output_path="/tmp/04.txt",
            batch_available=True,
            reembedding_available=True,
        ),
        ocr=DocumentOCRState(
            workspace=_make_workspace_state(active_tab=DocumentSection.OCR),
            pages=[
                OCRPageState(
                    source_id=101, page_number=1, total_pages=1, status=SurfaceStatus.DONE, extracted_text="hello"
                )
            ],
            current_page_index=0,
            actions=DocumentOCRActions(
                save=ActionState(enabled=True),
                run_current=ActionState(enabled=True),
                run_pending=ActionState(enabled=True),
            ),
        ),
        ocr_page_images={101: None},
        translation=DocumentTranslationState(
            workspace=_make_workspace_state(active_tab=DocumentSection.TRANSLATION),
            units=[
                TranslationUnitState(
                    unit_id="1",
                    unit_kind=TranslationUnitKind.CHUNK,
                    label="Chunk 1",
                    status=SurfaceStatus.READY,
                    source_text="hello",
                    translated_text="world",
                    actions=TranslationUnitActionState(can_save=True, can_retranslate=True),
                )
            ],
            current_unit_id="1",
        ),
        images=DocumentImagesState(
            workspace=_make_workspace_state(active_tab=DocumentSection.IMAGES),
            assets=[],
        ),
    )
    terms_service = FakeTermsService(
        project_state=TermsTableState(
            scope=TermsScope(kind=TermsScopeKind.PROJECT, project=ProjectRef(project_id="proj-1", name="One Piece")),
        ),
        document_state=TermsTableState(
            scope=TermsScope(
                kind=TermsScopeKind.DOCUMENT,
                project=ProjectRef(project_id="proj-1", name="One Piece"),
                document=DocumentRef(document_id=4, order_index=4, label="04.png"),
            ),
            toolbar=TermsToolbarState(can_build=True),
        ),
    )
    view = WorkView("proj-1", work_service, document_service, terms_service, bus)
    return view, bus, work_service, document_service, terms_service


def _make_translate_and_export_state(
    *,
    can_start: bool = True,
    blocker: BlockerInfo | None = None,
    batch_available: bool = True,
    batch_blocker: BlockerInfo | None = None,
    reembedding_available: bool = True,
    reembedding_blocker: BlockerInfo | None = None,
) -> TranslateAndExportState:
    return TranslateAndExportState(
        workspace=_make_workspace_state(),
        can_start=can_start,
        available_formats=[ExportOption(format_id="txt", label="TXT", is_default=True)],
        default_output_path="/tmp/04.txt",
        blocker=blocker,
        batch_available=batch_available,
        batch_blocker=batch_blocker,
        reembedding_available=reembedding_available,
        reembedding_blocker=reembedding_blocker,
    )


def test_work_view_renders_workboard_from_service():
    action = DocumentRowAction(
        kind=DocumentRowActionKind.OPEN_TRANSLATION,
        label="Open Translation",
        target=NavigationTarget(
            kind=NavigationTargetKind.DOCUMENT_TRANSLATION,
            project_id="proj-1",
            document_id=4,
        ),
    )
    view, _bus, work_service, _document_service, _terms_service = _make_view(work_state=_make_workboard(action=action))
    try:
        assert view.viewmodel.context_summary == "Context ready through 03"
        assert view.viewmodel.context_blocker_text == ""
        assert view.viewmodel.has_setup_blocker is False
        assert view.rows_table.rowCount() == 1
        assert view.rows_table.item(0, 1).text() == "04.png"
        assert view.rows_table.item(0, 2).text() == "2"
        assert view.rows_table.item(0, 3).text() == "Complete"
        assert view.rows_table.item(0, 4).text() == "In progress (1/2)"
        assert view.rows_table.item(0, 5).text() == "In progress (1/2)"
        assert view.rows_table.columnCount() == 6
        assert view.rows_table.item(0, 1).toolTip() == "Double-click or press Enter to Open Translation."
        assert view.rows_table.cellWidget(0, 3) is not None
        assert view.rows_table.cellWidget(0, 4) is not None
        assert view.rows_table.cellWidget(0, 5) is not None
        assert view.rows_table.rowHeight(0) >= 44
        assert work_service.calls == [("get_workboard", "proj-1")]
    finally:
        view.cleanup()


def test_work_view_loads_qml_home_chrome_and_routes_setup_signal():
    blocker = BlockerInfo(
        code=BlockerCode.NEEDS_SETUP,
        message="Target language is not configured for this project.",
        target=NavigationTarget(kind=NavigationTargetKind.PROJECT_SETUP, project_id="proj-1"),
    )
    action = DocumentRowAction(
        kind=DocumentRowActionKind.FIX_SETUP,
        label="Open Setup",
        target=NavigationTarget(kind=NavigationTargetKind.PROJECT_SETUP, project_id="proj-1"),
    )
    view, _bus, _work_service, _document_service, _terms_service = _make_view(
        work_state=_make_workboard(action=action, setup_blocker=blocker, summary="Needs setup")
    )
    opened: list[bool] = []
    view.open_project_setup_requested.connect(lambda: opened.append(True))
    try:
        root = view.chrome_host.rootObject()
        assert root is not None
        assert root.objectName() == "workHomeChrome"
        assert root.property("contextSummaryText") == "Context ready through 03"
        assert root.property("hasSetupBlocker") is True
        assert root.property("selectFilesLabelText") == "Select Files"
        assert root.property("selectFilesTooltipText") == "Choose one or more source files to import."
        assert root.property("selectFolderTooltipText") == "Choose a folder and import supported files from it."
        assert root.property("importTooltipText") == "Select files or a folder before importing."
        assert root.property("setupActionTooltipText") == "Open project setup to fix this blocker."
        assert int(root.property("implicitHeight")) > 180
        assert view.chrome_host.minimumHeight() >= int(root.property("implicitHeight"))
        assert view.viewmodel.setup_message == blocker.message
        assert view.viewmodel.setup_action_label == "Open Setup"

        root.setupActionRequested.emit()
        assert opened == [True]
    finally:
        view.cleanup()


def test_work_view_routes_setup_blocker_to_project_setup():
    blocker = BlockerInfo(
        code=BlockerCode.NEEDS_SETUP,
        message="Target language is not configured for this project.",
        target=NavigationTarget(kind=NavigationTargetKind.PROJECT_SETUP, project_id="proj-1"),
    )
    action = DocumentRowAction(
        kind=DocumentRowActionKind.FIX_SETUP,
        label="Open Setup",
        target=NavigationTarget(kind=NavigationTargetKind.PROJECT_SETUP, project_id="proj-1"),
    )
    view, _bus, _work_service, _document_service, _terms_service = _make_view(
        work_state=_make_workboard(action=action, setup_blocker=blocker, summary="Needs setup")
    )
    opened: list[bool] = []
    view.open_project_setup_requested.connect(lambda: opened.append(True))
    try:
        assert view.viewmodel.has_setup_blocker is True
        view._on_setup_action_clicked()
        assert opened == [True]
    finally:
        view.cleanup()


def test_work_view_opens_document_workspace_for_row_target():
    action = DocumentRowAction(
        kind=DocumentRowActionKind.OPEN_TRANSLATION,
        label="Open Translation",
        target=NavigationTarget(
            kind=NavigationTargetKind.DOCUMENT_TRANSLATION,
            project_id="proj-1",
            document_id=4,
        ),
    )
    view, _bus, _work_service, _document_service, _terms_service = _make_view(work_state=_make_workboard(action=action))
    try:
        view.rows_table.selectRow(0)
        QTest.keyClick(view.rows_table, Qt.Key.Key_Return)
        assert view._document_view is not None
        assert view.stack.currentWidget() is view._document_view
        assert view._document_view.current_section() is DocumentSection.TRANSLATION
    finally:
        view.cleanup()


def test_work_view_routes_open_target_to_ocr_tab():
    action = DocumentRowAction(
        kind=DocumentRowActionKind.OPEN,
        label="Open",
        target=NavigationTarget(kind=NavigationTargetKind.DOCUMENT_OCR, project_id="proj-1", document_id=4),
    )
    view, _bus, _work_service, _document_service, _terms_service = _make_view(
        work_state=_make_workboard(action=action, summary="Open")
    )
    try:
        view._on_cell_double_clicked(0, 0)
        assert view._document_view is not None
        assert view._document_view.current_section() is DocumentSection.OCR
    finally:
        view.cleanup()


def test_work_view_refreshes_on_invalidation():
    first_action = DocumentRowAction(
        kind=DocumentRowActionKind.OPEN,
        label="Open",
        target=NavigationTarget(kind=NavigationTargetKind.DOCUMENT_OCR, project_id="proj-1", document_id=4),
    )
    second_action = DocumentRowAction(
        kind=DocumentRowActionKind.OPEN_TERMS,
        label="Open Terms",
        target=NavigationTarget(kind=NavigationTargetKind.DOCUMENT_TERMS, project_id="proj-1", document_id=4),
    )
    view, bus, work_service, _document_service, _terms_service = _make_view(
        work_state=_make_workboard(action=first_action, summary="Open")
    )
    try:
        work_service.state_by_project["proj-1"] = _make_workboard(action=second_action, summary="Open Terms")
        bus.publish(WorkboardInvalidatedEvent(project_id="proj-1"))

        assert view.rows_table.item(0, 1).toolTip() == "Double-click or press Enter to Open Terms."
        view._on_cell_double_clicked(0, 0)
        assert view._document_view is not None
        assert view._document_view.current_section() is DocumentSection.TERMS
        assert work_service.calls == [("get_workboard", "proj-1"), ("get_workboard", "proj-1")]
    finally:
        view.cleanup()


def test_work_view_export_action_prepares_dialog():
    action = DocumentRowAction(kind=DocumentRowActionKind.EXPORT, label="Export")
    view, _bus, work_service, _document_service, _terms_service = _make_view(
        work_state=_make_workboard(action=action, summary="Ready to export")
    )
    work_service.export_state = ExportDialogState(
        project_id="proj-1",
        document_ids=[4],
        document_labels=["04.png"],
        available_formats=[ExportOption(format_id="epub", label="EPUB", is_default=True)],
        default_output_path="/tmp/out.epub",
    )
    work_service.export_result = ExportResult(
        output_path="/tmp/out.epub",
        message=UserMessage(severity=UserMessageSeverity.SUCCESS, text="Export complete."),
    )
    try:
        with patch.object(view, "_open_export_dialog") as mock_open_export_dialog:
            view._on_cell_double_clicked(0, 0)
        mock_open_export_dialog.assert_called_once_with(4)
    finally:
        view.cleanup()


def test_work_view_inspects_paths_and_imports_document():
    action = DocumentRowAction(
        kind=DocumentRowActionKind.OPEN_TRANSLATION,
        label="Open Translation",
        target=NavigationTarget(
            kind=NavigationTargetKind.DOCUMENT_TRANSLATION,
            project_id="proj-1",
            document_id=4,
        ),
    )
    view, _bus, work_service, _document_service, _terms_service = _make_view(work_state=_make_workboard(action=action))
    try:
        view._inspect_import_paths(["/tmp/04.png"])
        root = view.chrome_host.rootObject()
        assert root is not None
        assert view.viewmodel.import_type_options == [{"documentType": "manga", "label": "Manga", "selected": True}]
        assert view.viewmodel.can_import is True

        root.importRequested.emit()

        assert (
            "inspect_import_paths",
            InspectImportPathsRequest(project_id="proj-1", paths=["/tmp/04.png"]),
        ) in work_service.calls
        assert (
            "import_documents",
            ImportDocumentsRequest(project_id="proj-1", paths=["/tmp/04.png"], document_type="manga"),
        ) in work_service.calls
        assert view.viewmodel.import_summary == "No file or folder selected"
    finally:
        view.cleanup()


def test_work_view_passes_remove_hard_wraps_for_supported_imports():
    action = DocumentRowAction(
        kind=DocumentRowActionKind.OPEN_TRANSLATION,
        label="Open Translation",
        target=NavigationTarget(
            kind=NavigationTargetKind.DOCUMENT_TRANSLATION,
            project_id="proj-1",
            document_id=4,
        ),
    )
    view, _bus, work_service, _document_service, _terms_service = _make_view(work_state=_make_workboard(action=action))
    work_service.import_inspection_state = ImportInspectionState(
        selected_paths=["/tmp/book.epub"],
        available_types=[ImportDocumentTypeOption(document_type="epub", label="EPUB")],
        summary="book.epub",
    )
    try:
        view._inspect_import_paths(["/tmp/book.epub"])
        root = view.chrome_host.rootObject()
        assert root is not None
        assert root.property("canRemoveHardWraps") is True
        assert root.property("removeHardWrapsEnabled") is False

        root.removeHardWrapsToggled.emit(True)
        root.importRequested.emit()

        assert (
            "import_documents",
            ImportDocumentsRequest(
                project_id="proj-1",
                paths=["/tmp/book.epub"],
                document_type="epub",
                remove_hard_wraps=True,
            ),
        ) in work_service.calls
    finally:
        view.cleanup()


def test_work_view_resets_remove_hard_wraps_for_new_selection_and_after_import():
    action = DocumentRowAction(
        kind=DocumentRowActionKind.OPEN_TRANSLATION,
        label="Open Translation",
        target=NavigationTarget(
            kind=NavigationTargetKind.DOCUMENT_TRANSLATION,
            project_id="proj-1",
            document_id=4,
        ),
    )
    view, _bus, work_service, _document_service, _terms_service = _make_view(work_state=_make_workboard(action=action))
    try:
        work_service.import_inspection_state = ImportInspectionState(
            selected_paths=["/tmp/book.epub"],
            available_types=[ImportDocumentTypeOption(document_type="epub", label="EPUB")],
            summary="book.epub",
        )
        view._inspect_import_paths(["/tmp/book.epub"])
        root = view.chrome_host.rootObject()
        assert root is not None

        root.removeHardWrapsToggled.emit(True)
        assert root.property("removeHardWrapsEnabled") is True

        work_service.import_inspection_state = ImportInspectionState(
            selected_paths=["/tmp/book2.epub"],
            available_types=[ImportDocumentTypeOption(document_type="epub", label="EPUB")],
            summary="book2.epub",
        )
        view._inspect_import_paths(["/tmp/book2.epub"])
        assert root.property("removeHardWrapsEnabled") is False

        root.removeHardWrapsToggled.emit(True)
        root.importRequested.emit()

        assert root.property("removeHardWrapsEnabled") is False
        assert view.viewmodel.import_summary == "No file or folder selected"
    finally:
        view.cleanup()


def test_work_view_reset_and_delete_selected_document():
    action = DocumentRowAction(
        kind=DocumentRowActionKind.OPEN_TRANSLATION,
        label="Open Translation",
        target=NavigationTarget(
            kind=NavigationTargetKind.DOCUMENT_TRANSLATION,
            project_id="proj-1",
            document_id=4,
        ),
    )
    view, _bus, work_service, _document_service, _terms_service = _make_view(work_state=_make_workboard(action=action))
    try:
        assert view.reset_document_button.styleSheet() == view.delete_document_button.styleSheet()
        view.rows_table.selectRow(0)
        with (
            patch(
                "context_aware_translation.ui.features.work_view.QMessageBox.warning",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            patch("context_aware_translation.ui.features.work_view.QMessageBox.information"),
        ):
            view.reset_document_button.click()
            view.rows_table.selectRow(0)
            view.delete_document_button.click()

        assert (
            "reset_document_stack",
            ResetDocumentStackRequest(project_id="proj-1", document_id=4),
        ) in work_service.calls
        assert (
            "delete_document_stack",
            DeleteDocumentStackRequest(project_id="proj-1", document_id=4),
        ) in work_service.calls
    finally:
        view.cleanup()


def test_work_view_translate_and_export_button_uses_prepare_state():
    action = DocumentRowAction(
        kind=DocumentRowActionKind.OPEN_TRANSLATION,
        label="Open Translation",
        target=NavigationTarget(
            kind=NavigationTargetKind.DOCUMENT_TRANSLATION,
            project_id="proj-1",
            document_id=4,
        ),
    )
    blocker = BlockerInfo(
        code=BlockerCode.NEEDS_SETUP,
        message="Translate and Export is available only before work has started for this document.",
    )
    view, _bus, _work_service, document_service, _terms_service = _make_view(work_state=_make_workboard(action=action))
    document_service.translate_and_export = _make_translate_and_export_state(can_start=False, blocker=blocker)
    try:
        view.rows_table.selectRow(0)
        QApplication.processEvents()

        assert view.translate_and_export_button.isEnabled() is False
        assert view.translate_and_export_button.toolTip() == blocker.message
        assert ("prepare_translate_and_export", ("proj-1", 4)) in document_service.calls
    finally:
        view.cleanup()


def test_work_view_translate_and_export_button_opens_dialog_for_ready_document():
    action = DocumentRowAction(
        kind=DocumentRowActionKind.OPEN_TRANSLATION,
        label="Open Translation",
        target=NavigationTarget(
            kind=NavigationTargetKind.DOCUMENT_TRANSLATION,
            project_id="proj-1",
            document_id=4,
        ),
    )
    view, _bus, _work_service, document_service, _terms_service = _make_view(work_state=_make_workboard(action=action))
    document_service.translate_and_export = _make_translate_and_export_state(can_start=True)
    try:
        view.rows_table.selectRow(0)
        QApplication.processEvents()
        with patch("context_aware_translation.ui.features.work_view.TranslateAndExportDialog") as mock_dialog_cls:
            view.translate_and_export_button.click()

        mock_dialog_cls.assert_called_once()
        mock_dialog_cls.return_value.exec.assert_called_once()
        assert document_service.calls.count(("prepare_translate_and_export", ("proj-1", 4))) >= 2
    finally:
        view.cleanup()


def test_work_export_dialog_runs_service_with_selected_options():
    from PySide6.QtWidgets import QMessageBox

    from context_aware_translation.ui.features.document_workspace_view import WorkExportDialog

    work_service = FakeWorkService(state_by_project={})
    work_service.export_result = ExportResult(
        output_path="/tmp/out.epub",
        message=UserMessage(severity=UserMessageSeverity.SUCCESS, text="Export complete."),
    )
    state = ExportDialogState(
        project_id="proj-1",
        document_ids=[4],
        document_labels=["04.png"],
        available_formats=[ExportOption(format_id="epub", label="EPUB", is_default=True)],
        default_output_path="/tmp/out.epub",
        supports_preserve_structure=True,
        incomplete_translation_message="Needs fallback",
    )
    dialog = WorkExportDialog(work_service, state)
    try:
        dialog.controls.allow_original_fallback_cb.setChecked(True)
        dialog.controls.preserve_structure_cb.setChecked(True)
        dialog.controls.output_path_edit.setText("/tmp/export-dir")
        with patch.object(QMessageBox, "information") as mock_information:
            dialog.export_button.click()

        assert (work_service.calls[-1][0],) == ("run_export",)
        request = work_service.calls[-1][1]
        assert request.project_id == "proj-1"
        assert request.document_ids == [4]
        assert request.options["allow_original_fallback"] is True
        assert request.options["preserve_structure"] is True
        assert request.output_path == "/tmp/export-dir"
        mock_information.assert_called_once()
    finally:
        dialog.close()


def test_work_export_dialog_exposes_epub_layout_toggle_for_epub_exports():
    from PySide6.QtWidgets import QMessageBox

    from context_aware_translation.ui.features.document_workspace_view import WorkExportDialog

    work_service = FakeWorkService(state_by_project={})
    work_service.export_result = ExportResult(
        output_path="/tmp/out.epub",
        message=UserMessage(severity=UserMessageSeverity.SUCCESS, text="Export complete."),
    )
    state = ExportDialogState(
        project_id="proj-1",
        document_ids=[4],
        document_labels=["book.epub"],
        available_formats=[ExportOption(format_id="epub", label="EPUB", is_default=True)],
        default_output_path="/tmp/out.epub",
        supports_epub_layout_conversion=True,
    )
    dialog = WorkExportDialog(work_service, state)
    try:
        assert dialog.controls.epub_force_horizontal_ltr_cb.isHidden() is False
        dialog.controls.epub_force_horizontal_ltr_cb.setChecked(True)
        with patch.object(QMessageBox, "information") as mock_information:
            dialog.export_button.click()

        request = work_service.calls[-1][1]
        assert request.options["epub_force_horizontal_ltr"] is True
        mock_information.assert_called_once()
    finally:
        dialog.close()


def test_work_export_dialog_exposes_original_image_toggle_for_supported_exports():
    from PySide6.QtWidgets import QMessageBox

    from context_aware_translation.ui.features.document_workspace_view import WorkExportDialog

    work_service = FakeWorkService(state_by_project={})
    work_service.export_result = ExportResult(
        output_path="/tmp/out.epub",
        message=UserMessage(severity=UserMessageSeverity.SUCCESS, text="Export complete."),
    )
    state = ExportDialogState(
        project_id="proj-1",
        document_ids=[4],
        document_labels=["book.epub"],
        available_formats=[ExportOption(format_id="epub", label="EPUB", is_default=True)],
        default_output_path="/tmp/out.epub",
        supports_original_image_export=True,
    )
    dialog = WorkExportDialog(work_service, state)
    try:
        assert dialog.controls.use_original_images_cb.isHidden() is False
        dialog.controls.use_original_images_cb.setChecked(True)
        with patch.object(QMessageBox, "information") as mock_information:
            dialog.export_button.click()

        request = work_service.calls[-1][1]
        assert request.options["use_original_images"] is True
        mock_information.assert_called_once()
    finally:
        dialog.close()
