from __future__ import annotations

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
    BlockerCode,
    BlockerInfo,
    CapabilityCode,
    NavigationTarget,
    NavigationTargetKind,
    ProjectRef,
    ProviderKind,
)
from context_aware_translation.application.contracts.project_setup import ProjectSetupState
from context_aware_translation.application.events import InMemoryApplicationEventBus, SetupInvalidatedEvent
from tests.application.fakes import FakeProjectSetupService

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDialog, QPushButton

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


def _profile(*, profile_id: str, name: str, kind: WorkflowProfileKind) -> WorkflowProfileDetail:
    return WorkflowProfileDetail(
        profile_id=profile_id,
        name=name,
        kind=kind,
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
        is_default=(kind is WorkflowProfileKind.SHARED),
    )


def _make_state(*, blocker: str | None = None, project_specific: bool = False) -> ProjectSetupState:
    shared = _profile(profile_id="profile:shared", name="Recommended", kind=WorkflowProfileKind.SHARED)
    project_profile = (
        _profile(profile_id="project:proj-1", name="Project profile", kind=WorkflowProfileKind.PROJECT_SPECIFIC)
        if project_specific
        else None
    )
    return ProjectSetupState(
        project=ProjectRef(project_id="proj-1", name="One Piece"),
        available_connections=[
            ConnectionSummary(
                connection_id="conn-gemini",
                display_name="Gemini Shared",
                provider=ProviderKind.GEMINI,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                default_model="gemini-3-flash-preview",
                status=ConnectionStatus.READY,
                capabilities=[CapabilityCode.TRANSLATION],
            ),
            ConnectionSummary(
                connection_id="conn-openai",
                display_name="OpenAI Shared",
                provider=ProviderKind.OPENAI,
                base_url="https://api.openai.com/v1",
                default_model="gpt-4.1-mini",
                status=ConnectionStatus.READY,
                capabilities=[CapabilityCode.TRANSLATION],
            ),
        ],
        shared_profiles=[shared],
        selected_shared_profile_id=shared.profile_id,
        selected_shared_profile=shared,
        project_profile=project_profile,
        blocker=(
            None
            if blocker is None
            else BlockerInfo(
                code=BlockerCode.NEEDS_SETUP,
                message=blocker,
                target=NavigationTarget(kind=NavigationTargetKind.APP_SETUP),
            )
        ),
    )


def test_project_setup_view_renders_backend_state():
    from context_aware_translation.ui.features.project_setup_view import ProjectSetupView

    service = FakeProjectSetupService(state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = ProjectSetupView("proj-1", service, bus)
    try:
        assert view.title_label.text() == view.tr("Setup for One Piece")
        assert "shared workflow profile" in view.summary_label.text().lower()
        assert view.custom_profile_group.isHidden()
        assert view.layout().alignment() == Qt.AlignmentFlag.AlignTop
        assert service.calls == [("get_state", "proj-1")]
    finally:
        view.cleanup()


def test_project_setup_view_saves_selected_shared_profile():
    from context_aware_translation.ui.features.project_setup_view import ProjectSetupView

    service = FakeProjectSetupService(state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = ProjectSetupView("proj-1", service, bus)
    saved: list[str] = []
    view.save_completed.connect(saved.append)
    try:
        view.save_button.click()

        assert saved == ["proj-1"]
        call_name, request = service.calls[-1]
        assert call_name == "save"
        assert request.project_id == "proj-1"
        assert request.shared_profile_id == "profile:shared"
        assert request.project_profile is None
    finally:
        view.cleanup()


def test_project_setup_view_can_select_custom_profile():
    from context_aware_translation.ui.features.project_setup_view import ProjectSetupView

    service = FakeProjectSetupService(state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = ProjectSetupView("proj-1", service, bus)
    try:
        custom_index = view.shared_profile_combo.findData("__custom__")
        assert custom_index >= 0
        view.shared_profile_combo.setCurrentIndex(custom_index)

        assert not view.custom_profile_group.isHidden()
        assert view.routes_table.rowCount() == 2
        assert view.routes_table.columnCount() == 4
        assert view.routes_table.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert view.routes_table.columnWidth(1) >= 300
        assert view.routes_table.columnWidth(2) >= 250
        assert view.routes_table.item(0, 0).text() == "Translator"
        assert view.routes_table.item(1, 0).text() == "OCR"
        assert view.routes_table.cellWidget(0, 3) is not None
        assert view.routes_table.cellWidget(1, 3) is not None

        translator_row = next(
            index for index, row in enumerate(view._custom_rows) if row.step_id is WorkflowStepId.TRANSLATOR
        )
        translator = view._custom_rows[translator_row]
        assert translator.connection_combo.minimumWidth() >= 250
        assert translator.model_edit.minimumWidth() >= 220
        translator.connection_combo.setCurrentIndex(translator.connection_combo.findData("conn-openai"))
        translator.model_edit.setText("gpt-4.1-mini")
        view.save_button.click()

        call_name, request = service.calls[-1]
        assert call_name == "save"
        assert request.shared_profile_id == "profile:shared"
        assert request.project_profile is not None
        assert request.project_profile.kind is WorkflowProfileKind.PROJECT_SPECIFIC
        translator_route = next(
            route for route in request.project_profile.routes if route.step_id is WorkflowStepId.TRANSLATOR
        )
        assert translator_route.connection_id == "conn-openai"
        assert translator_route.model == "gpt-4.1-mini"
    finally:
        view.cleanup()


def test_project_setup_view_custom_step_advanced_button_opens_advanced_dialog():
    from context_aware_translation.ui.features import workflow_profile_editor as editor_module
    from context_aware_translation.ui.features.project_setup_view import ProjectSetupView

    service = FakeProjectSetupService(state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = ProjectSetupView("proj-1", service, bus)
    try:
        custom_index = view.shared_profile_combo.findData("__custom__")
        view.shared_profile_combo.setCurrentIndex(custom_index)
        translator_row = next(
            index for index, row in enumerate(view._custom_rows) if row.step_id is WorkflowStepId.TRANSLATOR
        )

        opened: list[WorkflowStepId] = []

        class _FakeStepDialog:
            def __init__(self, route: WorkflowStepRoute, *_args, **_kwargs):
                opened.append(route.step_id)
                self._route = route.model_copy(update={"step_config": {"chunk_size": 1234}})

            def exec(self):
                return QDialog.DialogCode.Accepted

            def route(self):
                return self._route

        original = editor_module.StepAdvancedConfigDialog
        editor_module.StepAdvancedConfigDialog = _FakeStepDialog
        try:
            translator_cell = view.routes_table.cellWidget(translator_row, 3)
            assert translator_cell is not None
            translator_button = translator_cell.findChild(QPushButton)
            assert translator_button is not None
            translator_button.click()
        finally:
            editor_module.StepAdvancedConfigDialog = original

        assert opened == [WorkflowStepId.TRANSLATOR]
        assert view._custom_rows[translator_row].step_config["chunk_size"] == 1234
        assert view.routes_table.cellWidget(translator_row, 3) is not None
    finally:
        view.cleanup()


def test_project_setup_view_opens_app_setup_for_blocker():
    from context_aware_translation.ui.features.project_setup_view import ProjectSetupView

    service = FakeProjectSetupService(state=_make_state(blocker="Open App Setup."))
    bus = InMemoryApplicationEventBus()
    view = ProjectSetupView("proj-1", service, bus)
    requested: list[bool] = []
    view.open_app_setup_requested.connect(lambda: requested.append(True))
    try:
        assert not view.open_app_setup_button.isHidden()
        view.open_app_setup_button.clicked.emit()
        assert requested == [True]
    finally:
        view.cleanup()


def test_project_setup_view_refreshes_on_setup_invalidation():
    from context_aware_translation.ui.features.project_setup_view import ProjectSetupView

    service = FakeProjectSetupService(state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = ProjectSetupView("proj-1", service, bus)
    try:
        service.state = _make_state(project_specific=True)
        bus.publish(SetupInvalidatedEvent(project_id="proj-1"))

        assert "project-specific workflow profile" in view.summary_label.text().lower()
        assert not view.custom_profile_group.isHidden()
        assert service.calls == [("get_state", "proj-1"), ("get_state", "proj-1")]
    finally:
        view.cleanup()
