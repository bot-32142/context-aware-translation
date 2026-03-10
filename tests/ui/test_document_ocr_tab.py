from __future__ import annotations

import pytest

from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    DocumentRef,
    DocumentSection,
    ProjectRef,
    SurfaceStatus,
    UserMessage,
    UserMessageSeverity,
)
from context_aware_translation.application.contracts.document import (
    DocumentOCRActions,
    DocumentOCRState,
    DocumentWorkspaceState,
    OCRBoundingBox,
    OCRPageState,
    OCRTextElement,
)
from tests.application.fakes import FakeDocumentService

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


def _png_1x1() -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage

    image = QImage(1, 1, QImage.Format.Format_RGBA8888)
    image.fill(QColor("white"))
    payload = QByteArray()
    buffer = QBuffer(payload)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(payload)


def _workspace_state() -> DocumentWorkspaceState:
    return DocumentWorkspaceState(
        project=ProjectRef(project_id="proj-1", name="One Piece"),
        document=DocumentRef(document_id=4, order_index=4, label="04.png"),
        active_tab=DocumentSection.OCR,
        available_tabs=[
            DocumentSection.OCR,
            DocumentSection.TERMS,
            DocumentSection.TRANSLATION,
            DocumentSection.IMAGES,
            DocumentSection.EXPORT,
        ],
    )


def test_document_ocr_tab_uses_structured_editor_and_bbox_overlay():
    from context_aware_translation.ui.features.document_ocr_tab import DocumentOCRTab

    service = FakeDocumentService(
        workspace=_workspace_state(),
        ocr=DocumentOCRState(
            workspace=_workspace_state(),
            pages=[
                OCRPageState(
                    source_id=101,
                    page_number=1,
                    total_pages=1,
                    status=SurfaceStatus.DONE,
                    elements=[
                        OCRTextElement(
                            element_id=0,
                            text="ルフィ",
                            bbox_id=0,
                            bbox=OCRBoundingBox(x=0.1, y=0.2, width=0.3, height=0.1),
                            kind="text",
                        )
                    ],
                )
            ],
            current_page_index=0,
            actions=DocumentOCRActions(
                save={"enabled": True}, run_current={"enabled": True}, run_pending={"enabled": True}
            ),
        ),
        ocr_page_images={101: _png_1x1()},
    )
    view = DocumentOCRTab(service, "proj-1", 4)
    try:
        view.refresh()
        assert view._right_stack.currentWidget() is view.structured_list
        assert len(view.image_viewer._bbox_rects) == 1
        view._on_bbox_clicked(0)
        assert view.structured_list._selected_index == 0
    finally:
        view.deleteLater()


def test_document_ocr_tab_saves_structured_elements():
    from context_aware_translation.ui.features.document_ocr_tab import DocumentOCRTab

    page = OCRPageState(
        source_id=101,
        page_number=1,
        total_pages=1,
        status=SurfaceStatus.DONE,
        elements=[
            OCRTextElement(text="one", bbox_id=0, bbox=OCRBoundingBox(x=0.1, y=0.1, width=0.2, height=0.1)),
            OCRTextElement(text="two", bbox_id=1, bbox=OCRBoundingBox(x=0.2, y=0.2, width=0.2, height=0.1)),
        ],
    )
    service = FakeDocumentService(
        workspace=_workspace_state(),
        ocr=DocumentOCRState(
            workspace=_workspace_state(),
            pages=[page],
            current_page_index=0,
            actions=DocumentOCRActions(
                save={"enabled": True}, run_current={"enabled": True}, run_pending={"enabled": True}
            ),
        ),
        ocr_page_images={101: _png_1x1()},
        command_result=AcceptedCommand(
            command_name="run_ocr",
            message=UserMessage(severity=UserMessageSeverity.INFO, text="Queued."),
        ),
    )
    view = DocumentOCRTab(service, "proj-1", 4)
    try:
        view.refresh()
        first = view.structured_list._cards[0]
        first._editor.setPlainText("updated")
        view.save_button.click()

        save_request = next(payload for name, payload in service.calls if name == "save_ocr")
        assert [element.text for element in save_request.elements] == ["updated", "two"]
        assert save_request.extracted_text == "updated\ntwo"
    finally:
        view.deleteLater()


def test_document_ocr_tab_can_cancel_active_task():
    from context_aware_translation.ui.features.document_ocr_tab import DocumentOCRTab

    service = FakeDocumentService(
        workspace=_workspace_state(),
        ocr=DocumentOCRState(
            workspace=_workspace_state(),
            pages=[
                OCRPageState(
                    source_id=101,
                    page_number=1,
                    total_pages=1,
                    status=SurfaceStatus.RUNNING,
                    extracted_text="hello",
                )
            ],
            current_page_index=0,
            actions=DocumentOCRActions(
                save={"enabled": False},
                run_current={"enabled": False},
                run_pending={"enabled": False},
            ),
            active_task_id="ocr-task-1",
        ),
        ocr_page_images={101: _png_1x1()},
        command_result=AcceptedCommand(
            command_name="cancel_ocr",
            message=UserMessage(severity=UserMessageSeverity.INFO, text="Cancel requested."),
        ),
    )
    view = DocumentOCRTab(service, "proj-1", 4)
    try:
        view.refresh()
        assert view._state is not None and view._state.active_task_id == "ocr-task-1"
        view.request_cancel_running_operations(include_engine_tasks=True)
        cancel_request = next(payload for name, payload in service.calls if name == "cancel_ocr")
        assert cancel_request.task_id == "ocr-task-1"
    finally:
        view.deleteLater()


def test_document_ocr_tab_uses_old_compact_navigation_and_boundary_enablement():
    from context_aware_translation.ui.features.document_ocr_tab import DocumentOCRTab

    service = FakeDocumentService(
        workspace=_workspace_state(),
        ocr=DocumentOCRState(
            workspace=_workspace_state(),
            pages=[
                OCRPageState(source_id=101, page_number=1, total_pages=2, status=SurfaceStatus.DONE),
                OCRPageState(source_id=102, page_number=2, total_pages=2, status=SurfaceStatus.READY),
            ],
            current_page_index=0,
            actions=DocumentOCRActions(
                save={"enabled": True}, run_current={"enabled": True}, run_pending={"enabled": True}
            ),
        ),
        ocr_page_images={101: _png_1x1(), 102: _png_1x1()},
    )
    view = DocumentOCRTab(service, "proj-1", 4)
    try:
        view.refresh()
        assert view.prev_button.text() == "<"
        assert view.next_button.text() == ">"
        assert view.first_button.isEnabled() is False
        assert view.prev_button.isEnabled() is False
        assert view.next_button.isEnabled() is True
        assert view.last_button.isEnabled() is True
        assert view.page_status_label.text() == "OCR Done"

        view._go_last()
        assert view.first_button.isEnabled() is True
        assert view.prev_button.isEnabled() is True
        assert view.next_button.isEnabled() is False
        assert view.last_button.isEnabled() is False
        assert view.page_status_label.text() == "Pending OCR"
    finally:
        view.deleteLater()


def test_document_ocr_tab_disables_navigation_and_actions_when_no_pages():
    from context_aware_translation.ui.features.document_ocr_tab import DocumentOCRTab

    service = FakeDocumentService(
        workspace=_workspace_state(),
        ocr=DocumentOCRState(
            workspace=_workspace_state(),
            pages=[],
            current_page_index=None,
            actions=DocumentOCRActions(
                save={"enabled": True}, run_current={"enabled": True}, run_pending={"enabled": True}
            ),
        ),
    )
    view = DocumentOCRTab(service, "proj-1", 4)
    try:
        view.refresh()
        assert view.empty_label.isHidden() is False
        assert view.first_button.isEnabled() is False
        assert view.prev_button.isEnabled() is False
        assert view.next_button.isEnabled() is False
        assert view.last_button.isEnabled() is False
        assert view.go_to_label.isEnabled() is False
        assert view.page_spinbox.isEnabled() is False
        assert view.go_button.isEnabled() is False
        assert view.save_button.isEnabled() is False
        assert view.run_current_button.isEnabled() is False
        assert view.run_pending_button.isEnabled() is False
    finally:
        view.deleteLater()
