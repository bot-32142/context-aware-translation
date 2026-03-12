from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from context_aware_translation.application.contracts.app_setup import (
    ConnectionStatus,
    ConnectionSummary,
    WorkflowProfileDetail,
    WorkflowProfileKind,
    WorkflowStepId,
    WorkflowStepRoute,
)
from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    ActionState,
    DocumentRef,
    DocumentRowActionKind,
    DocumentSection,
    ExportOption,
    NavigationTarget,
    NavigationTargetKind,
    ProgressInfo,
    ProjectRef,
    ProviderKind,
    QueueActionKind,
    QueueStatus,
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
    OCRBoundingBox,
    OCRPageState,
    OCRTextElement,
    TranslationUnitActionState,
    TranslationUnitKind,
    TranslationUnitState,
)
from context_aware_translation.application.contracts.project_setup import ProjectSetupState
from context_aware_translation.application.contracts.projects import ProjectsScreenState, ProjectSummary
from context_aware_translation.application.contracts.queue import QueueItem, QueueState
from context_aware_translation.application.contracts.terms import (
    TermsScope,
    TermsScopeKind,
    TermsTableState,
    TermStatus,
    TermsToolbarState,
    TermTableRow,
)
from context_aware_translation.application.contracts.work import (
    ContextFrontierState,
    DocumentRowAction,
    ExportDialogState,
    ImportDocumentTypeOption,
    ImportInspectionState,
    WorkboardState,
    WorkDocumentRow,
    WorkMutationResult,
)
from context_aware_translation.application.events import InMemoryApplicationEventBus
from context_aware_translation.ui.shell_hosts.hybrid import QmlChromeHost
from tests.application.fakes import (
    FakeDocumentService,
    FakeProjectSetupService,
    FakeProjectsService,
    FakeQueueService,
    FakeTermsService,
    FakeWorkService,
)

try:
    from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (
        QAbstractButton,
        QApplication,
        QComboBox,
        QDockWidget,
        QGroupBox,
        QLabel,
        QLineEdit,
        QMenu,
        QPushButton,
        QWidget,
    )

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


class _FakeTaskEngine(QObject):
    tasks_changed = Signal(str)
    error_occurred = Signal(str)
    running_work_changed = Signal(bool)
    enqueue_task_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._has_running_work = False
        self.start_autorun_calls = 0
        self.close_calls = 0

    def has_running_work(self) -> bool:
        return self._has_running_work

    def start_autorun(self, interval_ms: int = 3000) -> None:  # noqa: ARG002
        self.start_autorun_calls += 1

    def close(self) -> None:
        self.close_calls += 1


class _DummySleepInhibitor:
    def __init__(self) -> None:
        self.acquire_calls = 0
        self.release_calls = 0

    def acquire(self) -> None:
        self.acquire_calls += 1

    def release(self) -> None:
        self.release_calls += 1


class _PlaceholderAppSettingsPane(QWidget):
    def __init__(self, _service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.refresh_calls = 0

    def refresh(self) -> None:
        self.refresh_calls += 1


def _project_ref() -> ProjectRef:
    return ProjectRef(project_id="proj-1", name="One Piece")


def _document_ref() -> DocumentRef:
    return DocumentRef(document_id=4, order_index=4, label="04.png")


def _workspace_state(active_tab: DocumentSection = DocumentSection.OCR) -> DocumentWorkspaceState:
    return DocumentWorkspaceState(project=_project_ref(), document=_document_ref(), active_tab=active_tab)


def _png(width: int = 200, height: int = 200) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage

    image = QImage(width, height, QImage.Format.Format_RGBA8888)
    image.fill(QColor("white"))
    payload = QByteArray()
    buffer = QBuffer(payload)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(payload)


def _make_project_summary() -> ProjectSummary:
    return ProjectSummary(
        project=_project_ref(),
        target_language="English",
        progress_summary="33% (1/3)",
        modified_at=1_710_000_000.0,
    )


def _make_project_setup_state() -> ProjectSetupState:
    shared_profile = WorkflowProfileDetail(
        profile_id="profile:shared",
        name="Recommended",
        kind=WorkflowProfileKind.SHARED,
        target_language="English",
        routes=[
            WorkflowStepRoute(
                step_id=WorkflowStepId.TRANSLATOR,
                step_label="Translator",
                connection_id="conn-gemini",
                connection_label="Gemini Shared",
                model="gemini-3-flash-preview",
            ),
            WorkflowStepRoute(
                step_id=WorkflowStepId.OCR,
                step_label="OCR",
                connection_id="conn-gemini",
                connection_label="Gemini Shared",
                model="gemini-3-flash-preview",
            ),
        ],
        is_default=True,
    )
    return ProjectSetupState(
        project=_project_ref(),
        available_connections=[
            ConnectionSummary(
                connection_id="conn-gemini",
                display_name="Gemini Shared",
                provider=ProviderKind.GEMINI,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                default_model="gemini-3-flash-preview",
                status=ConnectionStatus.READY,
            ),
            ConnectionSummary(
                connection_id="conn-openai",
                display_name="OpenAI Shared",
                provider=ProviderKind.OPENAI,
                base_url="https://api.openai.com/v1",
                default_model="gpt-4.1-mini",
                status=ConnectionStatus.READY,
            ),
        ],
        shared_profiles=[shared_profile],
        selected_shared_profile_id=shared_profile.profile_id,
    )


def _make_terms_state(*, document_scope: bool) -> TermsTableState:
    return TermsTableState(
        scope=TermsScope(
            kind=TermsScopeKind.DOCUMENT if document_scope else TermsScopeKind.PROJECT,
            project=_project_ref(),
            document=_document_ref() if document_scope else None,
        ),
        toolbar=TermsToolbarState(
            can_build=document_scope,
            can_translate_pending=True,
            can_review=True,
            can_filter_noise=True,
            can_import=not document_scope,
            can_export=not document_scope,
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
            ),
            TermTableRow(
                term_id=2,
                term_key="ニカ",
                term="ニカ",
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


def _make_translation_state() -> DocumentTranslationState:
    return DocumentTranslationState(
        workspace=_workspace_state(DocumentSection.TRANSLATION),
        run_action=ActionState(enabled=True),
        batch_action=ActionState(enabled=True),
        supports_batch=True,
        units=[
            TranslationUnitState(
                unit_id="chunk-1",
                unit_kind=TranslationUnitKind.CHUNK,
                label="Chunk 1",
                status=SurfaceStatus.READY,
                source_text="全員さっさと降りろ!!!",
                translated_text="Everyone, get down now!!!",
                line_count=1,
                actions=TranslationUnitActionState(can_save=True, can_retranslate=True),
            )
        ],
        current_unit_id="chunk-1",
    )


def _make_ocr_state() -> DocumentOCRState:
    return DocumentOCRState(
        workspace=_workspace_state(DocumentSection.OCR),
        pages=[
            OCRPageState(
                source_id=101,
                page_number=1,
                total_pages=2,
                status=SurfaceStatus.DONE,
                extracted_text="hello\nworld",
                elements=[
                    OCRTextElement(
                        element_id=0,
                        text="hello",
                        bbox_id=0,
                        bbox=OCRBoundingBox(x=0.1, y=0.1, width=0.2, height=0.1),
                        kind="text",
                    )
                ],
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


def _make_images_state() -> DocumentImagesState:
    sample_png = _png()
    return DocumentImagesState(
        workspace=_workspace_state(DocumentSection.IMAGES),
        assets=[
            ImageAssetState(
                asset_id="asset-1",
                label="Image 1",
                status=SurfaceStatus.READY,
                source_id=101,
                translated_text="Everyone, get down now!!!",
                original_image_bytes=sample_png,
                can_run=True,
            ),
            ImageAssetState(
                asset_id="asset-2",
                label="Image 2",
                status=SurfaceStatus.DONE,
                source_id=102,
                translated_text="Luffy!",
                original_image_bytes=sample_png,
                reembedded_image_bytes=sample_png,
                can_run=True,
            ),
        ],
        toolbar=DocumentImagesToolbarState(
            can_run_pending=True,
            can_force_all=True,
        ),
    )


def _make_export_state() -> DocumentExportState:
    return DocumentExportState(
        workspace=_workspace_state(DocumentSection.EXPORT),
        can_export=True,
        available_formats=[ExportOption(format_id="txt", label="TXT", is_default=True)],
        default_output_path="/tmp/04.txt",
    )


def _make_workboard_state() -> WorkboardState:
    return WorkboardState(
        project=_project_ref(),
        context_frontier=ContextFrontierState(summary="Context ready through 03"),
        rows=[
            WorkDocumentRow(
                document=_document_ref(),
                status=SurfaceStatus.READY,
                source_count=2,
                ocr_status="Complete",
                terms_status="In progress (1/2)",
                translation_status="Ready",
                state_summary="Open Translation",
                primary_action=DocumentRowAction(
                    kind=DocumentRowActionKind.OPEN_TRANSLATION,
                    label="Open Translation",
                    target=NavigationTarget(
                        kind=NavigationTargetKind.DOCUMENT_TRANSLATION,
                        project_id="proj-1",
                        document_id=4,
                    ),
                ),
            )
        ],
    )


def _make_queue_state() -> QueueState:
    return QueueState(
        items=[
            QueueItem(
                queue_item_id="task-1",
                title="Read text from images",
                project_id="proj-1",
                document_id=4,
                status=QueueStatus.RUNNING,
                stage="ocr",
                progress=ProgressInfo(current=1, total=2, label="apply"),
                related_target=NavigationTarget(
                    kind=NavigationTargetKind.DOCUMENT_OCR,
                    project_id="proj-1",
                    document_id=4,
                ),
                available_actions=[QueueActionKind.OPEN_RELATED_ITEM, QueueActionKind.CANCEL],
            )
        ]
    )


def _make_context():
    book_manager = MagicMock()
    book_manager.library_root = Path("/tmp/context-aware-translation-ui-smoke")
    task_store = MagicMock()
    task_engine = _FakeTaskEngine()
    work_service = FakeWorkService(state_by_project={"proj-1": _make_workboard_state()})
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
        message=UserMessage(severity=UserMessageSeverity.SUCCESS, text="Reset complete."),
    )
    work_service.delete_result = WorkMutationResult(
        message=UserMessage(severity=UserMessageSeverity.SUCCESS, text="Delete complete."),
    )
    work_service.export_state = ExportDialogState(
        project_id="proj-1",
        document_ids=[4],
        document_labels=["04.png"],
        available_formats=[ExportOption(format_id="txt", label="TXT", is_default=True)],
        default_output_path="/tmp/project-export.txt",
    )
    work_service.export_result = SimpleNamespace(
        output_path="/tmp/project-export.txt",
        message=UserMessage(severity=UserMessageSeverity.SUCCESS, text="Export complete."),
    )

    document_service = FakeDocumentService(
        workspace=_workspace_state(),
        ocr=_make_ocr_state(),
        ocr_page_images={101: _png(), 102: _png()},
        translation=_make_translation_state(),
        images=_make_images_state(),
        export=_make_export_state(),
    )
    terms_service = FakeTermsService(
        project_state=_make_terms_state(document_scope=False),
        document_state=_make_terms_state(document_scope=True),
        command_result=AcceptedCommand(
            command_name="terms-task",
            message=UserMessage(severity=UserMessageSeverity.INFO, text="Queued."),
        ),
    )
    queue_service = FakeQueueService(state=_make_queue_state())
    return SimpleNamespace(
        runtime=SimpleNamespace(
            book_manager=book_manager,
            task_store=task_store,
            task_engine=task_engine,
            worker_deps=object(),
        ),
        services=SimpleNamespace(
            projects=FakeProjectsService(
                list_state=ProjectsScreenState(items=[_make_project_summary()]),
                project_summary=_make_project_summary(),
            ),
            app_setup=MagicMock(),
            project_setup=FakeProjectSetupService(state=_make_project_setup_state()),
            work=work_service,
            document=document_service,
            terms=terms_service,
            queue=queue_service,
        ),
        events=InMemoryApplicationEventBus(),
    )


def _make_window():
    from context_aware_translation.ui.main_window import MainWindow

    context = _make_context()
    patch_stack = ExitStack()
    patch_stack.enter_context(
        patch("context_aware_translation.ui.main_window.build_application_context", return_value=context),
    )
    patch_stack.enter_context(
        patch("context_aware_translation.ui.main_window.AppSettingsPane", _PlaceholderAppSettingsPane),
    )
    patch_stack.enter_context(
        patch("context_aware_translation.ui.main_window.SleepInhibitor", _DummySleepInhibitor),
    )
    try:
        window = MainWindow()
    except Exception:
        patch_stack.close()
        raise
    return window, context, patch_stack


def _flush(wait_ms: int = 50) -> None:
    QApplication.processEvents()
    QTest.qWait(wait_ms)
    QApplication.processEvents()


def _widget_text(widget: QWidget) -> str:
    if isinstance(widget, (QAbstractButton, QLabel)):
        return widget.text().strip()
    if isinstance(widget, QGroupBox):
        return widget.title().strip()
    if isinstance(widget, QLineEdit):
        return widget.placeholderText().strip()
    window_title = widget.windowTitle().strip()
    if window_title:
        return window_title
    return widget.objectName().strip()


def _collect_visible_widget_texts(root: QWidget) -> list[str]:
    texts: list[str] = []
    for widget in [root, *root.findChildren(QWidget)]:
        if not widget.isVisible():
            continue
        text = _widget_text(widget)
        if text:
            texts.append(text)
    return texts


def _collect_visible_qml_texts(root: QWidget) -> list[str]:
    texts: list[str] = []
    for host in [root, *root.findChildren(QmlChromeHost)]:
        if not isinstance(host, QmlChromeHost) or not host.isVisible():
            continue
        root_object = host.rootObject()
        if root_object is None:
            continue
        texts.extend(_walk_qml_texts(root_object))
    return texts


def _walk_qml_texts(
    obj: QObject,
    *,
    ancestors_visible: bool = True,
    visited: set[int] | None = None,
) -> list[str]:
    if visited is None:
        visited = set()
    object_id = id(obj)
    if object_id in visited:
        return []
    visited.add(object_id)

    visible_property = obj.property("visible")
    is_visible = ancestors_visible if visible_property is None else ancestors_visible and bool(visible_property)
    texts: list[str] = []
    text_value = obj.property("text")
    if is_visible and isinstance(text_value, str):
        normalized = text_value.strip()
        if normalized:
            texts.append(normalized)

    child_objects = [child for child in obj.children() if isinstance(child, QObject)]
    if isinstance(obj, QQuickItem):
        child_objects.extend(child for child in obj.childItems() if isinstance(child, QObject))

    for child in child_objects:
        texts.extend(_walk_qml_texts(child, ancestors_visible=is_visible, visited=visited))
    return texts


def _count_visible_text(root: QWidget, needle: str) -> int:
    return sum(text == needle for text in [*_collect_visible_widget_texts(root), *_collect_visible_qml_texts(root)])


def _qml_root(widget: QWidget, *, object_name: str) -> QQuickItem:
    host = widget.findChild(QmlChromeHost)
    assert host is not None
    root = host.rootObject()
    assert isinstance(root, QQuickItem)
    assert root.objectName() == object_name
    return root


def _global_rect(widget: QWidget) -> QRect:
    top_left = widget.mapToGlobal(QPoint(0, 0))
    return QRect(top_left, widget.size())


def _assert_widget_inside(widget: QWidget, ancestor: QWidget, *, tolerance: int = 2) -> None:
    widget_rect = _global_rect(widget)
    ancestor_rect = _global_rect(ancestor).adjusted(-tolerance, -tolerance, tolerance, tolerance)
    assert ancestor_rect.contains(widget_rect), (
        f"{widget.__class__.__name__} {_widget_text(widget)!r} escaped {ancestor.__class__.__name__}: "
        f"{widget_rect.getRect()} not inside {ancestor_rect.getRect()}"
    )


def _assert_no_unexpected_top_levels(*allowed: QWidget) -> None:
    allowed_set = set(allowed)
    unexpected: list[str] = []
    for widget in QApplication.topLevelWidgets():
        if not widget.isVisible() or widget in allowed_set:
            continue
        if isinstance(widget, QMenu):
            continue
        if widget.__class__.__name__ in {"QComboBoxPrivateContainer"}:
            continue
        unexpected.append(f"{widget.__class__.__name__}:{_widget_text(widget) or '<untitled>'}")
    assert not unexpected, f"Unexpected visible top-level widgets: {unexpected}"


def _open_project(window) -> None:  # noqa: ANN001
    window.show()
    window.resize(1440, 980)
    _flush(80)
    window.projects_view.table_view.selectRow(0)
    _flush()
    QTest.mouseClick(window.projects_view.open_button, Qt.MouseButton.LeftButton)
    _flush(120)


def test_main_window_clickthrough_smoke_has_no_stray_windows_or_duplicate_queue_title():
    window, _context, patch_stack = _make_window()
    try:
        _open_project(window)

        shell = window._current_project_shell()
        assert shell is not None
        assert window._current_book_id == "proj-1"
        assert window._app_shell.chrome_host.isHidden()
        assert shell.chrome_host.isVisible()
        assert _count_visible_text(shell, "Projects") == 0
        _assert_no_unexpected_top_levels(window)

        shell.queue_requested.emit()
        _flush(80)
        assert window._queue_dock.isVisible()
        assert isinstance(window._queue_dock, QDockWidget)
        assert _count_visible_text(window._queue_shell, "Queue") == 1
        _assert_no_unexpected_top_levels(window, window._queue_dock)
    finally:
        window.close()
        patch_stack.close()


def test_project_surface_smoke_keeps_controls_in_bounds_and_project_setup_dropdown_behavior():
    window, _context, patch_stack = _make_window()
    try:
        _open_project(window)

        shell = window._current_project_shell()
        assert shell is not None
        work_view = shell.work_widget
        assert work_view is not None

        _flush(80)
        chrome_root = _qml_root(work_view, object_name="workHomeChrome")
        assert chrome_root.property("selectFilesLabelText") == "Select Files"
        assert chrome_root.property("selectFolderLabelText") == "Select Folder"
        assert chrome_root.property("importLabelText") == "Import"
        assert int(chrome_root.property("implicitHeight")) > 120
        assert _count_visible_text(work_view, "Context is not ready") <= 1
        action_button = work_view.rows_table.cellWidget(0, 7)
        assert isinstance(action_button, QPushButton)
        _assert_widget_inside(action_button, work_view.rows_table.viewport())

        window._open_project_settings(shell)
        _flush(80)
        settings_dialog = window._project_settings_dialog
        settings_view = shell.project_settings_widget
        assert settings_dialog is not None
        assert settings_dialog.isVisible()
        assert settings_view is not None
        assert isinstance(settings_view.profile_combo, QComboBox)
        assert settings_view.profile_combo.currentText() == "Recommended"
        _assert_widget_inside(settings_view.profile_combo, settings_view.profile_section)
        assert _count_visible_text(settings_view, "Workflow profile") == 1
        _assert_no_unexpected_top_levels(window, settings_dialog)
    finally:
        window.close()
        patch_stack.close()


def test_document_workspace_clickthrough_smoke_keeps_ocr_images_terms_and_export_stable():
    window, _context, patch_stack = _make_window()
    try:
        _open_project(window)

        shell = window._current_project_shell()
        assert shell is not None
        work_view = shell.work_widget
        assert work_view is not None

        work_view._open_document_workspace(4, DocumentSection.OCR)
        _flush(120)
        document_view = work_view._document_view
        assert document_view is not None

        document_view.show_section(DocumentSection.OCR)
        _flush(80)
        ocr_view = document_view.section_widget(DocumentSection.OCR)
        assert ocr_view is not None
        ocr_root = _qml_root(ocr_view, object_name="documentOcrPaneChrome")
        assert ocr_view.image_viewer.height() > 160
        assert ocr_view._right_stack.height() > 160
        assert 0 < ocr_view.chrome_host.height() < ocr_view.height() // 2
        assert ocr_view.chrome_host.minimumHeight() >= int(ocr_root.property("implicitHeight"))
        assert ocr_root.property("runPendingLabelText") == "Run OCR for Pending Pages"
        assert ocr_root.property("runCurrentLabelText") == "(Re)run OCR (Current Page)"
        assert ocr_root.property("saveLabelText") == "Save"

        document_view.show_section(DocumentSection.IMAGES)
        _flush(80)
        images_view = document_view.section_widget(DocumentSection.IMAGES)
        assert images_view is not None
        images_root = _qml_root(images_view, object_name="documentImagesPaneChrome")
        assert images_view.image_viewer.height() > 160
        assert images_view.right_stack.height() > 160
        assert 0 < images_view.chrome_host.height() < images_view.height() // 2
        assert images_view.chrome_host.minimumHeight() >= int(images_root.property("implicitHeight"))
        assert images_root.property("runPendingLabelText") == "Reembed Pending"
        assert images_root.property("runSelectedLabelText") == "Reembed This Image"
        assert images_root.property("forceAllLabelText") == "Force Reembed All"

        document_view.show_section(DocumentSection.TERMS)
        _flush(80)
        terms_view = document_view.section_widget(DocumentSection.TERMS)
        assert terms_view is not None
        assert terms_view.export_button.isVisible() is False
        assert terms_view.export_button.isWindow() is False

        document_view.show_section(DocumentSection.TRANSLATION)
        _flush(80)
        translation_view = document_view.section_widget(DocumentSection.TRANSLATION)
        assert translation_view is not None
        translation_root = _qml_root(translation_view, object_name="documentTranslationPaneChrome")
        assert translation_root.property("translateLabelText") == "Translate"
        assert translation_root.property("batchLabelText") == "Submit Batch Task"
        assert translation_root.property("supportsBatch") is True
        assert translation_view.batch_translate_button.isHidden()
        assert translation_view.batch_translate_button.parent() is translation_view

        document_view.show_section(DocumentSection.EXPORT)
        _flush(80)
        export_view = document_view.section_widget(DocumentSection.EXPORT)
        assert export_view is not None
        export_root = _qml_root(export_view, object_name="documentExportPaneChrome")
        assert export_root.property("exportLabelText") == "Export This Document"
        _assert_no_unexpected_top_levels(window)
    finally:
        window.close()
        patch_stack.close()
