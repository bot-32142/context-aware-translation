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
    )


def _images_state(
    *,
    asset_blocker: BlockerInfo | None = None,
    toolbar_blocker: BlockerInfo | None = None,
    active_task_id: str | None = None,
    include_reembedded: bool = True,
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
                original_image_bytes=b"image-1",
                can_run=asset_blocker is None and active_task_id is None,
                run_blocker=asset_blocker,
            ),
            ImageAssetState(
                asset_id="asset-2",
                label="Image 2",
                status=SurfaceStatus.DONE,
                source_id=102,
                translated_text="Luffy!",
                original_image_bytes=b"image-2",
                reembedded_image_bytes=b"reembedded-2" if include_reembedded else None,
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


def _transparent_png_with_center_dot(size: int = 64, dot: int = 8) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage

    image = QImage(size, size, QImage.Format.Format_RGBA8888)
    image.fill(QColor(0, 0, 0, 0))
    offset = (size - dot) // 2
    for y in range(offset, offset + dot):
        for x in range(offset, offset + dot):
            image.setPixelColor(x, y, QColor("white"))
    payload = QByteArray()
    buffer = QBuffer(payload)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(payload)


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
        root = view.chrome_host.rootObject()

        assert root is not None
        assert root.objectName() == "documentImagesPaneChrome"
        assert root.property("pageLabelText") == "Image 1 of 2"
        assert root.property("statusText") == "Pending"
        assert view.chrome_host.minimumHeight() >= int(root.property("implicitHeight"))
        assert root.property("runSelectedEnabled") is True
        assert root.property("runPendingEnabled") is True
        assert root.property("forceAllEnabled") is True
        assert view.page_label.text() == "Image 1 of 2"
        assert view.status_label.text() == "Pending"
        assert view.text_panel.toPlainText() == "Everyone, get down now!!!"
        assert view.run_selected_button.isEnabled()
        assert view.run_pending_button.isEnabled()
        assert view.force_all_button.isEnabled()
        assert root.property("progressVisible") is False
        assert not view.toggle_button.isEnabled()
        assert view.toggle_button.text() == "Show Image"
        assert root.property("toggleLabelText") == "Show Image"

        root.runSelectedRequested.emit()
        selected_request = next(payload for name, payload in service.calls if name == "run_image_reinsertion")
        assert selected_request.source_id == 101
        assert selected_request.force_all is True

        root.runPendingRequested.emit()
        pending_request = [payload for name, payload in service.calls if name == "run_image_reinsertion"][1]
        assert pending_request.source_id is None
        assert pending_request.force_all is False

        root.forceAllRequested.emit()
        force_request = [payload for name, payload in service.calls if name == "run_image_reinsertion"][2]
        assert force_request.source_id is None
        assert force_request.force_all is True
        assert root.property("messageText") == "Queued."

        root.setProperty("width", 280)
        root.setProperty("runSelectedLabelText", "Reembed Only This Image With A Much Longer Label")
        root.setProperty("runPendingLabelText", "Reembed Every Pending Image With A Much Longer Label")
        root.setProperty("forceAllLabelText", "Force Reembed Every Image In This Document")
        QApplication.processEvents()

        assert view.chrome_host.minimumHeight() >= int(root.property("implicitHeight"))
        assert float(root.property("implicitHeight")) > 208.0
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
        root = view.chrome_host.rootObject()

        assert view.get_running_operations() == ["Put text back into images"]
        assert root is not None
        assert root.property("progressVisible") is True
        assert root.property("progressCanCancel") is True
        assert root.property("progressText") == "apply"

        root.cancelRequested.emit()
        assert ("cancel_image_reinsertion", ("proj-1", "task-1")) in service.calls
    finally:
        view.deleteLater()


def test_document_images_view_uses_embedded_bytes_and_shows_reembedded_first():
    from context_aware_translation.ui.features.document_images_view import DocumentImagesView

    state = _images_state()
    service = FakeDocumentService(
        workspace=_workspace_state(),
        images=state,
        ocr_page_images={101: None, 102: None},
    )
    view = DocumentImagesView("proj-1", 4, service)
    try:
        view.refresh()
        view._go_next()
        root = view.chrome_host.rootObject()

        assert view.status_label.text() == "Reembedded"
        assert view.right_label.text() == "Reembedded"
        assert root is not None
        assert root.property("statusText") == "Reembedded"
        assert root.property("toggleEnabled") is True
        assert root.property("toggleLabelText") == "Show Text"
        assert not any(name == "get_ocr_page_image" and payload[2] == 102 for name, payload in service.calls)
    finally:
        view.deleteLater()


def test_document_images_view_trims_transparent_preview_padding():
    from context_aware_translation.ui.features.document_images_view import DocumentImagesView

    preview = _transparent_png_with_center_dot()
    state = _images_state().model_copy(
        update={
            "assets": [
                _images_state().assets[0].model_copy(update={"original_image_bytes": preview}),
                _images_state().assets[1].model_copy(update={"original_image_bytes": preview}),
            ]
        }
    )
    service = FakeDocumentService(
        workspace=_workspace_state(),
        images=state,
        ocr_page_images={101: None, 102: None},
    )
    view = DocumentImagesView("proj-1", 4, service)
    try:
        view.refresh()

        assert view.image_viewer.pixmap_item is not None
        assert int(view.image_viewer.pixmap_item.pixmap().width()) == 8
        assert int(view.image_viewer.pixmap_item.pixmap().height()) == 8
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
        workspace=_workspace_state(active_tab=DocumentSection.OCR),
        images=_images_state(asset_blocker=blocker, toolbar_blocker=blocker),
        ocr=DocumentOCRState(
            workspace=_workspace_state(active_tab=DocumentSection.OCR),
            pages=[
                OCRPageState(
                    source_id=101, page_number=1, total_pages=1, status=SurfaceStatus.DONE, extracted_text="hello"
                )
            ],
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
        images_tab = workspace.section_widget(DocumentSection.IMAGES)
        assert images_tab is not None
        root = images_tab.chrome_host.rootObject()
        assert root is not None
        assert root.property("blockerText") == "Image editing needs a shared connection in App Setup."
        assert root.property("blockerActionLabelText") == "Open App Setup"

        root.blockerActionRequested.emit()
        assert requested == ["app"]
    finally:
        workspace.cleanup()
