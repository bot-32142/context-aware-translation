from __future__ import annotations

import pytest

from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    ActionState,
    BlockerCode,
    BlockerInfo,
    DocumentRef,
    DocumentSection,
    ProgressInfo,
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
from context_aware_translation.application.errors import ApplicationError, ApplicationErrorCode, ApplicationErrorPayload
from tests.application.fakes import FakeDocumentService

try:
    from PySide6.QtWidgets import QApplication, QLabel

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
    return _png(1, 1)


def _png(width: int, height: int) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage

    image = QImage(width, height, QImage.Format.Format_RGBA8888)
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
    )


def _flush() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


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
                save=ActionState(enabled=True),
                run_current=ActionState(enabled=True),
                run_pending=ActionState(enabled=True),
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


def test_document_ocr_tab_uses_distinct_kind_palettes_for_structured_cards():
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
                        OCRTextElement(text="body text", kind="text"),
                        OCRTextElement(text="panel sign", kind="image"),
                        OCRTextElement(text="rows and columns", kind="table"),
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

        card_styles = {card.styleSheet() for card in view.structured_list._cards}
        editor_styles = {card._editor.styleSheet() for card in view.structured_list._cards}

        assert len(card_styles) == 3
        assert len(editor_styles) == 3
    finally:
        view.deleteLater()


def test_document_ocr_tab_loads_qml_chrome_and_qml_navigation_signals() -> None:
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
        root = view.chrome_host.rootObject()
        assert root is not None
        assert root.objectName() == "documentOcrPaneChrome"
        assert root.property("pageLabelText") == "Page 1 of 2"
        assert root.property("pageStatusText") == "OCR Done"
        assert view.chrome_host.minimumHeight() >= int(root.property("implicitHeight"))

        root.nextRequested.emit()
        assert view.page_label.text() == "Page 2 of 2"
        assert root.property("pageStatusText") == "Pending OCR"

        root.setProperty("width", 280)
        root.setProperty("runCurrentLabelText", "Run OCR For The Current Page With A Much Longer Label")
        root.setProperty("runPendingLabelText", "Run OCR For All Pending Pages With A Much Longer Label")
        root.setProperty("messageText", "Queued work is still running in the background.")
        QApplication.processEvents()

        assert view.chrome_host.minimumHeight() >= int(root.property("implicitHeight"))
        assert float(root.property("implicitHeight")) > 168.0
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


def test_document_ocr_tab_qml_save_signal_persists_manual_text_edit():
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
                    extracted_text="line one",
                )
            ],
            current_page_index=0,
            actions=DocumentOCRActions(
                save={"enabled": True},
                run_current={"enabled": True},
                run_pending={"enabled": True},
            ),
        ),
        ocr_page_images={101: _png_1x1()},
    )
    view = DocumentOCRTab(service, "proj-1", 4)
    try:
        view.refresh()
        root = view.chrome_host.rootObject()
        assert root is not None
        assert root.property("runCurrentTooltipText") == "Run or re-run OCR on the current page"
        assert root.property("runPendingTooltipText") == "Run OCR on all pending pages in this document"
        assert root.property("saveTooltipText") == "Save edited OCR text"
        view.text_edit.setPlainText("edited manually")

        root.saveRequested.emit()

        save_request = next(payload for name, payload in service.calls if name == "save_ocr")
        assert save_request.extracted_text == "edited manually"
    finally:
        view.deleteLater()


def test_document_ocr_tab_disables_save_after_terms_or_translation_started():
    from context_aware_translation.ui.features.document_ocr_tab import DocumentOCRTab

    blocker_message = "OCR is locked after terms or translation have started for this document."
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
                    extracted_text="line one",
                )
            ],
            current_page_index=0,
            actions=DocumentOCRActions(
                save=ActionState(
                    enabled=False, blocker=BlockerInfo(code=BlockerCode.NOTHING_TO_DO, message=blocker_message)
                ),
                run_current=ActionState(
                    enabled=False,
                    blocker=BlockerInfo(code=BlockerCode.NOTHING_TO_DO, message=blocker_message),
                ),
                run_pending=ActionState(
                    enabled=False,
                    blocker=BlockerInfo(code=BlockerCode.NOTHING_TO_DO, message=blocker_message),
                ),
            ),
        ),
        ocr_page_images={101: _png_1x1()},
    )
    view = DocumentOCRTab(service, "proj-1", 4)
    try:
        view.refresh()
        root = view.chrome_host.rootObject()
        assert root is not None
        assert view.save_button.isEnabled() is False
        assert root.property("saveTooltipText") == blocker_message
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


def test_document_ocr_tab_updates_run_current_action_when_switching_pages() -> None:
    from context_aware_translation.ui.features.document_ocr_tab import DocumentOCRTab

    service = FakeDocumentService(
        workspace=_workspace_state(),
        ocr=DocumentOCRState(
            workspace=_workspace_state(),
            pages=[
                OCRPageState(
                    source_id=101,
                    page_number=1,
                    total_pages=2,
                    status=SurfaceStatus.RUNNING,
                    run_action=ActionState(
                        enabled=False,
                        blocker=BlockerInfo(code=BlockerCode.ALREADY_RUNNING_ELSEWHERE, message="Page 1 running."),
                    ),
                ),
                OCRPageState(
                    source_id=102,
                    page_number=2,
                    total_pages=2,
                    status=SurfaceStatus.READY,
                    run_action=ActionState(enabled=True),
                ),
            ],
            current_page_index=0,
            actions=DocumentOCRActions(
                save={"enabled": False},
                run_current=ActionState(
                    enabled=False,
                    blocker=BlockerInfo(code=BlockerCode.ALREADY_RUNNING_ELSEWHERE, message="Page 1 running."),
                ),
                run_pending={"enabled": False},
            ),
        ),
        ocr_page_images={101: _png_1x1(), 102: _png_1x1()},
    )
    view = DocumentOCRTab(service, "proj-1", 4)
    try:
        view.refresh()
        assert not view.run_current_button.isEnabled()

        view._go_next()

        assert view.run_current_button.isEnabled()
        assert view.run_current_button.toolTip() == "Run or re-run OCR on the current page"
    finally:
        view.deleteLater()


def test_document_ocr_tab_cancels_all_active_tasks():
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
            active_task_ids=["ocr-task-1", "ocr-task-2"],
            progress=ProgressInfo(current=3, total=7),
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
        view.request_cancel_running_operations(include_engine_tasks=True)
        cancel_requests = [payload for name, payload in service.calls if name == "cancel_ocr"]
        assert [request.task_id for request in cancel_requests] == ["ocr-task-1", "ocr-task-2"]
    finally:
        view.deleteLater()


def test_document_ocr_tab_empty_state_stays_embedded_and_renders_in_screenshot():
    from context_aware_translation.ui.features.document_ocr_tab import DocumentOCRTab

    service = FakeDocumentService(
        workspace=_workspace_state(),
        ocr=DocumentOCRState(
            workspace=_workspace_state(),
            pages=[],
            current_page_index=None,
            actions=DocumentOCRActions(
                save={"enabled": False},
                run_current={"enabled": False},
                run_pending={"enabled": False},
            ),
        ),
        ocr_page_images={},
    )
    view = DocumentOCRTab(service, "proj-1", 4)
    try:
        view.resize(960, 720)
        view.show()
        view.refresh()
        _flush()

        assert view.empty_label.parentWidget() is view
        assert view.empty_label.isVisible()
        assert not view.empty_label.isWindow()
        stray_empty_labels = [
            widget
            for widget in QApplication.topLevelWidgets()
            if widget is not view
            and widget.isVisible()
            and isinstance(widget, QLabel)
            and widget.text() == "No image pages are available for OCR in this document."
        ]
        assert not stray_empty_labels

        screenshot = view.grab().toImage()
        assert not screenshot.isNull()
        assert round(screenshot.deviceIndependentSize().width()) == view.width()
        assert round(screenshot.deviceIndependentSize().height()) == view.height()
    finally:
        view.close()
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


def test_document_ocr_tab_first_page_image_starts_at_stable_fit_scale():
    from context_aware_translation.ui.features.document_ocr_tab import DocumentOCRTab

    large_page = _png(1200, 1800)
    service = FakeDocumentService(
        workspace=_workspace_state(),
        ocr=DocumentOCRState(
            workspace=_workspace_state(),
            pages=[
                OCRPageState(source_id=101, page_number=1, total_pages=2, status=SurfaceStatus.DONE),
                OCRPageState(source_id=102, page_number=2, total_pages=2, status=SurfaceStatus.DONE),
            ],
            current_page_index=0,
            actions=DocumentOCRActions(
                save={"enabled": True}, run_current={"enabled": True}, run_pending={"enabled": True}
            ),
        ),
        ocr_page_images={101: large_page, 102: large_page},
    )
    view = DocumentOCRTab(service, "proj-1", 4)
    try:
        view.resize(1200, 800)
        view.refresh()
        view.show()
        _flush()

        initial_zoom = view.image_viewer.transform().m11()

        view._go_next()
        _flush()
        view._go_previous()
        _flush()

        roundtrip_zoom = view.image_viewer.transform().m11()
        assert roundtrip_zoom > 0
        assert abs(initial_zoom - roundtrip_zoom) < 0.01
    finally:
        view.close()
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


def test_document_ocr_tab_preserves_unsaved_draft_across_page_switch_and_refresh():
    from context_aware_translation.ui.features.document_ocr_tab import DocumentOCRTab

    service = FakeDocumentService(
        workspace=_workspace_state(),
        ocr=DocumentOCRState(
            workspace=_workspace_state(),
            pages=[
                OCRPageState(
                    source_id=101, page_number=1, total_pages=2, status=SurfaceStatus.DONE, extracted_text="one"
                ),
                OCRPageState(
                    source_id=102, page_number=2, total_pages=2, status=SurfaceStatus.DONE, extracted_text="two"
                ),
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
        view.text_edit.setPlainText("draft one")

        view._go_next()
        assert view.text_edit.toPlainText() == "two"

        view._go_previous()
        assert view.text_edit.toPlainText() == "draft one"

        view.refresh()
        assert view.text_edit.toPlainText() == "draft one"
    finally:
        view.deleteLater()


def test_document_ocr_tab_run_and_cancel_refresh_state_immediately():
    from context_aware_translation.ui.features.document_ocr_tab import DocumentOCRTab

    initial_state = DocumentOCRState(
        workspace=_workspace_state(),
        pages=[
            OCRPageState(source_id=101, page_number=1, total_pages=1, status=SurfaceStatus.DONE, extracted_text="hello")
        ],
        current_page_index=0,
        actions=DocumentOCRActions(
            save=ActionState(enabled=True),
            run_current=ActionState(enabled=True),
            run_pending=ActionState(enabled=True),
        ),
        active_task_id=None,
    )
    queued_state = DocumentOCRState(
        workspace=_workspace_state(),
        pages=[
            OCRPageState(
                source_id=101, page_number=1, total_pages=1, status=SurfaceStatus.RUNNING, extracted_text="hello"
            )
        ],
        current_page_index=0,
        actions=DocumentOCRActions(
            save=ActionState(enabled=False),
            run_current=ActionState(enabled=False),
            run_pending=ActionState(enabled=False),
        ),
        active_task_id="ocr-task-1",
    )
    idle_state = queued_state.model_copy(
        update={
            "pages": [queued_state.pages[0].model_copy(update={"status": SurfaceStatus.DONE})],
            "actions": DocumentOCRActions(
                save=ActionState(enabled=True),
                run_current=ActionState(enabled=True),
                run_pending=ActionState(enabled=True),
            ),
            "active_task_id": None,
        }
    )
    service = FakeDocumentService(
        workspace=_workspace_state(),
        ocr=initial_state,
        ocr_page_images={101: _png_1x1()},
    )
    run_calls = {"count": 0}
    cancel_calls = {"count": 0}

    def _run(request):  # noqa: ANN001
        service.calls.append(("run_ocr", request))
        run_calls["count"] += 1
        service.ocr = queued_state
        return AcceptedCommand(
            command_name="run_ocr", message=UserMessage(severity=UserMessageSeverity.INFO, text="Queued.")
        )

    def _cancel(request):  # noqa: ANN001
        service.calls.append(("cancel_ocr", request))
        cancel_calls["count"] += 1
        service.ocr = idle_state
        return AcceptedCommand(
            command_name="cancel_ocr",
            message=UserMessage(severity=UserMessageSeverity.INFO, text="Cancel requested."),
        )

    service.run_ocr = _run
    service.cancel_ocr = _cancel
    view = DocumentOCRTab(service, "proj-1", 4)
    try:
        view.refresh()
        view.run_current_button.click()
        assert run_calls["count"] == 1
        assert view._state is not None and view._state.active_task_id == "ocr-task-1"
        assert view.progress_widget.isHidden() is False
        assert view.run_current_button.isEnabled() is False

        view.request_cancel_running_operations(include_engine_tasks=True)
        assert cancel_calls["count"] == 1
        assert view._state is not None and view._state.active_task_id is None
        assert view.progress_widget.isHidden() is True
        assert view.run_current_button.isEnabled() is True
        assert view.page_status_label.text() == "OCR Done"
    finally:
        view.deleteLater()


def test_document_ocr_tab_rerun_current_page_discards_local_draft_on_refresh():
    from context_aware_translation.ui.features.document_ocr_tab import DocumentOCRTab

    initial_state = DocumentOCRState(
        workspace=_workspace_state(),
        pages=[
            OCRPageState(source_id=101, page_number=1, total_pages=1, status=SurfaceStatus.DONE, extracted_text="stale")
        ],
        current_page_index=0,
        actions=DocumentOCRActions(
            save=ActionState(enabled=True),
            run_current=ActionState(enabled=True),
            run_pending=ActionState(enabled=True),
        ),
    )
    refreshed_state = initial_state.model_copy(
        update={
            "pages": [
                initial_state.pages[0].model_copy(
                    update={"status": SurfaceStatus.RUNNING, "extracted_text": "fresh ocr"}
                )
            ],
            "actions": DocumentOCRActions(
                save=ActionState(enabled=False),
                run_current=ActionState(enabled=False),
                run_pending=ActionState(enabled=False),
            ),
            "active_task_id": "ocr-task-1",
        }
    )
    service = FakeDocumentService(
        workspace=_workspace_state(),
        ocr=initial_state,
        ocr_page_images={101: _png_1x1()},
        command_result=AcceptedCommand(
            command_name="run_ocr",
            message=UserMessage(severity=UserMessageSeverity.INFO, text="Queued."),
        ),
    )

    def _run(request):  # noqa: ANN001
        service.calls.append(("run_ocr", request))
        service.ocr = refreshed_state
        return service.command_result or AcceptedCommand(command_name="run_ocr")

    service.run_ocr = _run
    view = DocumentOCRTab(service, "proj-1", 4)
    try:
        view.refresh()
        view.text_edit.setPlainText("local draft")

        view.run_current_button.click()

        assert view.text_edit.toPlainText() == "fresh ocr"
        assert 101 not in view._page_drafts
    finally:
        view.deleteLater()


def test_document_ocr_tab_clears_transient_queue_message_on_refresh():
    from context_aware_translation.ui.features.document_ocr_tab import DocumentOCRTab

    initial_state = DocumentOCRState(
        workspace=_workspace_state(),
        pages=[
            OCRPageState(source_id=101, page_number=1, total_pages=1, status=SurfaceStatus.READY, extracted_text="")
        ],
        current_page_index=0,
        actions=DocumentOCRActions(
            save=ActionState(enabled=True),
            run_current=ActionState(enabled=True),
            run_pending=ActionState(enabled=True),
        ),
    )
    queued_state = initial_state.model_copy(
        update={
            "pages": [initial_state.pages[0].model_copy(update={"status": SurfaceStatus.RUNNING})],
            "actions": DocumentOCRActions(
                save=ActionState(enabled=False),
                run_current=ActionState(enabled=False),
                run_pending=ActionState(enabled=False),
            ),
            "active_task_id": "ocr-task-1",
        }
    )
    refreshed_state = queued_state.model_copy(update={"progress": ProgressInfo(current=1, total=3, label="ocr")})
    service = FakeDocumentService(
        workspace=_workspace_state(),
        ocr=initial_state,
        ocr_page_images={101: _png_1x1()},
    )

    def _run(request):  # noqa: ANN001
        service.calls.append(("run_ocr", request))
        service.ocr = queued_state
        return AcceptedCommand(
            command_name="run_ocr", message=UserMessage(severity=UserMessageSeverity.INFO, text="Queued.")
        )

    service.run_ocr = _run
    view = DocumentOCRTab(service, "proj-1", 4)
    try:
        view.refresh()
        root = view.chrome_host.rootObject()

        view.run_current_button.click()

        assert root is not None
        assert root.property("messageText") == "Queued."

        service.ocr = refreshed_state
        view.refresh()

        assert root.property("messageText") == ""
        assert root.property("progressVisible") is True
    finally:
        view.deleteLater()


def test_document_ocr_tab_pending_rerun_only_clears_affected_page_drafts():
    from context_aware_translation.ui.features.document_ocr_tab import DocumentOCRTab

    initial_state = DocumentOCRState(
        workspace=_workspace_state(),
        pages=[
            OCRPageState(
                source_id=101, page_number=1, total_pages=3, status=SurfaceStatus.READY, extracted_text="pending one"
            ),
            OCRPageState(
                source_id=102, page_number=2, total_pages=3, status=SurfaceStatus.DONE, extracted_text="done two"
            ),
            OCRPageState(
                source_id=103,
                page_number=3,
                total_pages=3,
                status=SurfaceStatus.READY,
                elements=[OCRTextElement(text="pending three")],
            ),
        ],
        current_page_index=0,
        actions=DocumentOCRActions(
            save=ActionState(enabled=True),
            run_current=ActionState(enabled=True),
            run_pending=ActionState(enabled=True),
        ),
    )
    refreshed_state = initial_state.model_copy(
        update={
            "pages": [
                initial_state.pages[0].model_copy(
                    update={"status": SurfaceStatus.RUNNING, "extracted_text": "fresh one"}
                ),
                initial_state.pages[1].model_copy(update={"extracted_text": "done two"}),
                initial_state.pages[2].model_copy(
                    update={
                        "status": SurfaceStatus.RUNNING,
                        "elements": [OCRTextElement(text="fresh three")],
                    }
                ),
            ],
            "actions": DocumentOCRActions(
                save=ActionState(enabled=False),
                run_current=ActionState(enabled=False),
                run_pending=ActionState(enabled=False),
            ),
            "active_task_id": "ocr-task-1",
        }
    )
    service = FakeDocumentService(
        workspace=_workspace_state(),
        ocr=initial_state,
        ocr_page_images={101: _png_1x1(), 102: _png_1x1(), 103: _png_1x1()},
        command_result=AcceptedCommand(
            command_name="run_ocr",
            message=UserMessage(severity=UserMessageSeverity.INFO, text="Queued."),
        ),
    )

    def _run(request):  # noqa: ANN001
        service.calls.append(("run_ocr", request))
        service.ocr = refreshed_state
        return service.command_result or AcceptedCommand(command_name="run_ocr")

    service.run_ocr = _run
    view = DocumentOCRTab(service, "proj-1", 4)
    try:
        view.refresh()
        view.text_edit.setPlainText("draft one")
        view._go_next()
        view.text_edit.setPlainText("draft two")
        view._go_next()
        view.structured_list._cards[0]._editor.setPlainText("draft three")

        view._go_to_page_number(1)
        view.run_pending_button.click()

        assert view.text_edit.toPlainText() == "fresh one"
        assert 101 not in view._page_drafts
        assert 103 not in view._page_drafts
        assert view._page_drafts[102].extracted_text == "draft two"

        view._go_to_page_number(2)
        assert view.text_edit.toPlainText() == "draft two"

        view._go_to_page_number(3)
        assert view.structured_list._cards[0].text() == "fresh three"
    finally:
        view.deleteLater()


def test_document_ocr_tab_refresh_handles_service_error_without_raising():
    from context_aware_translation.ui.features.document_ocr_tab import DocumentOCRTab

    service = FakeDocumentService(workspace=_workspace_state(), ocr=None)

    def _raise(_project_id: str, _document_id: int):
        raise ApplicationError(
            ApplicationErrorPayload(code=ApplicationErrorCode.INTERNAL, message="ocr refresh failed")
        )

    service.get_ocr = _raise
    view = DocumentOCRTab(service, "proj-1", 4)
    try:
        view.refresh()
        assert view.message_label.text() == "ocr refresh failed"
    finally:
        view.deleteLater()
