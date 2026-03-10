from __future__ import annotations

import pytest

from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    BlockerCode,
    BlockerInfo,
    DocumentRef,
    DocumentSection,
    NavigationTarget,
    NavigationTargetKind,
    ProgressInfo,
    ProjectRef,
    SurfaceStatus,
    UserMessage,
    UserMessageSeverity,
)
from context_aware_translation.application.contracts.document import (
    DocumentExportState,
    DocumentImagesState,
    DocumentImagesToolbarState,
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
from context_aware_translation.application.contracts.terms import TermsScope, TermsScopeKind, TermsTableState
from tests.application.fakes import FakeDocumentService, FakeTermsService, FakeWorkService

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


def _workspace_state(active_tab: DocumentSection = DocumentSection.IMAGES) -> DocumentWorkspaceState:
    return DocumentWorkspaceState(
        project=ProjectRef(project_id="proj-1", name="One Piece"),
        document=DocumentRef(document_id=4, order_index=4, label="04.png"),
        active_tab=active_tab,
        available_tabs=[
            DocumentSection.OVERVIEW,
            DocumentSection.OCR,
            DocumentSection.TERMS,
            DocumentSection.TRANSLATION,
            DocumentSection.IMAGES,
            DocumentSection.EXPORT,
        ],
    )


def _images_state(
    *,
    asset_blocker: BlockerInfo | None = None,
    toolbar_blocker: BlockerInfo | None = None,
    active_task_id: str | None = None,
) -> DocumentImagesState:
    return DocumentImagesState(
        workspace=_workspace_state(),
        assets=[
            ImageAssetState(
                asset_id="asset-1",
                label="Image 1",
                status=SurfaceStatus.READY,
                source_id=101,
                translated_text="Everyone, get down now!!!",
                can_run=asset_blocker is None and active_task_id is None,
                run_blocker=asset_blocker,
            ),
            ImageAssetState(
                asset_id="asset-2",
                label="Image 2",
                status=SurfaceStatus.DONE,
                source_id=102,
                translated_text="Luffy!",
                can_run=asset_blocker is None and active_task_id is None,
                run_blocker=asset_blocker,
            ),
        ],
        toolbar=DocumentImagesToolbarState(
            can_run_pending=toolbar_blocker is None and active_task_id is None,
            can_force_all=toolbar_blocker is None and active_task_id is None,
            can_cancel=active_task_id is not None,
            run_pending_blocker=toolbar_blocker,
            force_all_blocker=toolbar_blocker,
        ),
        progress=ProgressInfo(current=1, total=2, label="apply") if active_task_id is not None else None,
        active_task_id=active_task_id,
    )


def test_document_images_view_renders_backend_state_and_runs_actions():
    from context_aware_translation.ui.features.document_images_view import DocumentImagesView

    service = FakeDocumentService(
        workspace=_workspace_state(),
        images=_images_state(),
        ocr_page_images={101: b"image-1", 102: b"image-2"},
        command_result=AcceptedCommand(
            command_name="run_image_reinsertion",
            message=UserMessage(severity=UserMessageSeverity.INFO, text="Queued."),
        ),
    )
    view = DocumentImagesView("proj-1", 4, service)
    try:
        view.refresh()

        assert view.page_label.text() == "Image 1 of 2"
        assert view.status_label.text() == "Ready"
        assert view.text_panel.toPlainText() == "Everyone, get down now!!!"
        assert view.run_selected_button.isEnabled()
        assert view.run_pending_button.isEnabled()
        assert view.force_all_button.isEnabled()
        assert not view.cancel_button.isEnabled()

        view.run_selected_button.click()
        selected_request = next(payload for name, payload in service.calls if name == "run_image_reinsertion")
        assert selected_request.source_id == 101
        assert selected_request.force_all is True

        view.run_pending_button.click()
        pending_request = [payload for name, payload in service.calls if name == "run_image_reinsertion"][1]
        assert pending_request.source_id is None
        assert pending_request.force_all is False

        view.force_all_button.click()
        force_request = [payload for name, payload in service.calls if name == "run_image_reinsertion"][2]
        assert force_request.source_id is None
        assert force_request.force_all is True
        assert view.message_label.text() == "Queued."
    finally:
        view.deleteLater()


def test_document_images_view_cancels_active_task():
    from context_aware_translation.ui.features.document_images_view import DocumentImagesView

    service = FakeDocumentService(
        workspace=_workspace_state(),
        images=_images_state(active_task_id="task-1"),
        ocr_page_images={101: b"image-1", 102: b"image-2"},
        command_result=AcceptedCommand(
            command_name="cancel_image_reinsertion",
            message=UserMessage(severity=UserMessageSeverity.INFO, text="Cancel requested."),
        ),
    )
    view = DocumentImagesView("proj-1", 4, service)
    try:
        view.refresh()

        assert view.cancel_button.isEnabled()
        assert "1/2" in view.progress_label.text()
        assert view.get_running_operations() == ["Put text back into images"]

        view.cancel_button.click()
        assert ("cancel_image_reinsertion", ("proj-1", "task-1")) in service.calls
    finally:
        view.deleteLater()


def test_document_images_view_routes_setup_blocker_and_document_workspace_forwards_it():
    from context_aware_translation.application.events import InMemoryApplicationEventBus
    from context_aware_translation.ui.features.document_workspace_view import DocumentWorkspaceView

    blocker = BlockerInfo(
        code=BlockerCode.NEEDS_SETUP,
        message="Image editing needs a shared connection in App Setup.",
        target=NavigationTarget(kind=NavigationTargetKind.APP_SETUP, project_id="proj-1"),
    )
    document_service = FakeDocumentService(
        workspace=_workspace_state(active_tab=DocumentSection.OVERVIEW),
        overview=DocumentOverviewState(
            workspace=_workspace_state(active_tab=DocumentSection.OVERVIEW),
            sections=[
                DocumentSectionCard(
                    section=DocumentSection.IMAGES,
                    status=SurfaceStatus.BLOCKED,
                    summary="Needs setup",
                    blocker=blocker,
                )
            ],
        ),
        images=_images_state(asset_blocker=blocker, toolbar_blocker=blocker),
        ocr=DocumentOCRState(
            workspace=_workspace_state(active_tab=DocumentSection.OCR),
            pages=[OCRPageState(source_id=101, page_number=1, total_pages=1, status=SurfaceStatus.DONE, extracted_text="hello")],
            current_page_index=0,
            actions=DocumentOCRActions(),
        ),
        translation=DocumentTranslationState(
            workspace=_workspace_state(active_tab=DocumentSection.TRANSLATION),
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
        export=DocumentExportState(
            workspace=_workspace_state(active_tab=DocumentSection.EXPORT),
            can_export=True,
        ),
    )
    terms_service = FakeTermsService(
        project_state=TermsTableState(
            scope=TermsScope(kind=TermsScopeKind.PROJECT, project=ProjectRef(project_id="proj-1", name="One Piece")),
        ),
    )
    work_service = FakeWorkService(state_by_project={"proj-1": object()})
    workspace = DocumentWorkspaceView(
        "proj-1",
        4,
        document_service,
        terms_service,
        work_service,
        InMemoryApplicationEventBus(),
    )
    requested: list[str] = []
    workspace.open_app_setup_requested.connect(lambda: requested.append("app"))
    try:
        workspace.show_section(DocumentSection.IMAGES)
        images_tab = workspace.tab_widget.currentWidget()
        assert images_tab is not None
        assert not images_tab.blocker_strip.isHidden()
        assert images_tab.blocker_action_button.text() == "Open App Setup"

        images_tab.blocker_action_button.click()
        assert requested == ["app"]
    finally:
        workspace.cleanup()
