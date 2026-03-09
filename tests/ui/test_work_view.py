from __future__ import annotations

from unittest.mock import patch

import pytest

from context_aware_translation.application.contracts.common import (
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
    DocumentOverviewState,
    DocumentSectionCard,
    DocumentWorkspaceState,
)
from context_aware_translation.application.contracts.terms import (
    TermsScope,
    TermsScopeKind,
    TermsTableState,
    TermsToolbarState,
)
from context_aware_translation.application.contracts.work import (
    ContextFrontierState,
    DocumentRowAction,
    ExportDialogState,
    WorkboardState,
    WorkDocumentRow,
)
from context_aware_translation.application.events import InMemoryApplicationEventBus, WorkboardInvalidatedEvent
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


def _make_workspace_state(active_tab: DocumentSection = DocumentSection.OVERVIEW) -> DocumentWorkspaceState:
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


def _make_workboard(*, action: DocumentRowAction, setup_blocker: BlockerInfo | None = None, summary: str = "Open Translation") -> WorkboardState:
    return WorkboardState(
        project=ProjectRef(project_id="proj-1", name="One Piece"),
        context_frontier=ContextFrontierState(summary="Context ready through 03"),
        rows=[
            WorkDocumentRow(
                document=DocumentRef(document_id=4, order_index=4, label="04.png"),
                status=SurfaceStatus.READY,
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
    document_service = FakeDocumentService(
        workspace=_make_workspace_state(),
        overview=DocumentOverviewState(
            workspace=_make_workspace_state(),
            sections=[
                DocumentSectionCard(
                    section=DocumentSection.TRANSLATION,
                    status=SurfaceStatus.READY,
                    summary="Open Translation",
                )
            ],
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
        assert view.context_label.text() == "Context ready through 03"
        assert view.rows_table.rowCount() == 1
        assert view.rows_table.item(0, 1).text() == "04.png"
        assert view.rows_table.cellWidget(0, 4).text() == "Open Translation"
        assert work_service.calls == [("get_workboard", "proj-1")]
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
        assert not view.setup_strip.isHidden()
        view.setup_action_button.click()
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
        view.rows_table.cellWidget(0, 4).click()
        assert view._document_view is not None
        assert view.stack.currentWidget() is view._document_view
        assert view._document_view.tab_widget.tabText(view._document_view.tab_widget.currentIndex()) == "Translation"
    finally:
        view.cleanup()


def test_work_view_refreshes_on_invalidation():
    first_action = DocumentRowAction(kind=DocumentRowActionKind.OPEN, label="Open", target=NavigationTarget(kind=NavigationTargetKind.DOCUMENT_OVERVIEW, project_id="proj-1", document_id=4))
    second_action = DocumentRowAction(kind=DocumentRowActionKind.OPEN_TERMS, label="Open Terms", target=NavigationTarget(kind=NavigationTargetKind.DOCUMENT_TERMS, project_id="proj-1", document_id=4))
    view, bus, work_service, _document_service, _terms_service = _make_view(work_state=_make_workboard(action=first_action, summary="Open"))
    try:
        work_service.state_by_project["proj-1"] = _make_workboard(action=second_action, summary="Open Terms")
        bus.publish(WorkboardInvalidatedEvent(project_id="proj-1"))
        QApplication.processEvents()

        assert view.rows_table.cellWidget(0, 4).text() == "Open Terms"
        assert work_service.calls == [("get_workboard", "proj-1"), ("get_workboard", "proj-1")]
    finally:
        view.cleanup()


def test_work_view_export_action_prepares_dialog():
    action = DocumentRowAction(kind=DocumentRowActionKind.EXPORT, label="Export")
    view, _bus, work_service, _document_service, _terms_service = _make_view(work_state=_make_workboard(action=action, summary="Ready to export"))
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
            view.rows_table.cellWidget(0, 4).click()
        mock_open_export_dialog.assert_called_once_with(4)
    finally:
        view.cleanup()
