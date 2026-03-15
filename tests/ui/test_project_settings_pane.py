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
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtTest import QSignalSpy, QTest
    from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QWidget

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
        shared_profiles=[shared],
        selected_shared_profile_id=shared.profile_id,
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


def _flush() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def _grab_image(widget: QWidget, *, width: int = 980, height: int = 900) -> QImage:
    widget.resize(width, height)
    widget.show()
    _flush()
    return widget.grab().toImage()


def _color_distance(left: QColor, right: QColor) -> int:
    return (
        abs(left.red() - right.red())
        + abs(left.green() - right.green())
        + abs(left.blue() - right.blue())
        + abs(left.alpha() - right.alpha())
    )


def _crop_rect(image: QImage, *, x: int, y: int, width: int, height: int) -> QImage:
    scale = image.devicePixelRatio()
    return image.copy(
        int(x * scale),
        int(y * scale),
        max(1, int(width * scale)),
        max(1, int(height * scale)),
    )


def _ink_ratio(image: QImage, *, background: QColor) -> float:
    if image.isNull():
        return 0.0
    samples = 0
    colored = 0
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            samples += 1
            if _color_distance(image.pixelColor(x, y), background) > 24:
                colored += 1
    return colored / samples if samples else 0.0


def test_project_settings_pane_renders_backend_state():
    from context_aware_translation.ui.features.project_settings_pane import ProjectSettingsPane

    service = FakeProjectSetupService(state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = ProjectSettingsPane("proj-1", service, bus)
    try:
        root = view.chrome_host.rootObject()
        assert root is not None
        assert root.objectName() == "projectSettingsPaneChrome"
        assert root.property("showHeader") is False
        assert view.viewmodel.title_text == "Setup for One Piece"
        assert view.profile_combo.objectName() == "projectWorkflowProfileCombo"
        assert view.profile_combo.currentIndex() == 0
        assert view.profile_combo.currentText() == "Recommended"
        assert view.profile_combo.minimumContentsLength() == 24
        assert view.profile_combo.view().minimumWidth() == view.profile_combo.minimumWidth()
        assert "combobox-popup: 0" in view.styleSheet()
        assert "QComboBox::down-arrow" in view.styleSheet()
        assert view.profile_detail_label.text() == "Shared workflow profile"
        assert view.routes_group.isHidden()
        assert view.chrome_host.minimumHeight() >= int(root.property("implicitHeight"))
        assert service.calls == [("get_state", "proj-1")]
    finally:
        view.cleanup()


def test_project_settings_pane_switching_profiles_does_not_reset_combo_model():
    from context_aware_translation.ui.features.project_settings_pane import ProjectSettingsPane

    service = FakeProjectSetupService(state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = ProjectSettingsPane("proj-1", service, bus)
    try:
        model_reset_spy = QSignalSpy(view.profile_combo.model().modelReset)
        custom_index = next(
            index for index, option in enumerate(view.viewmodel.profile_options) if option["label"] == "Custom profile"
        )

        view.profile_combo.setCurrentIndex(custom_index)
        _flush()
        view.profile_combo.setCurrentIndex(0)
        _flush()

        assert model_reset_spy.count() == 0
    finally:
        view.close()
        view.cleanup()


def test_project_settings_pane_saves_selected_shared_profile():
    from context_aware_translation.ui.features.project_settings_pane import ProjectSettingsPane

    service = FakeProjectSetupService(state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = ProjectSettingsPane("proj-1", service, bus)
    saved: list[str] = []
    view.save_completed.connect(saved.append)
    try:
        view._save()

        assert saved == ["proj-1"]
        call_name, request = service.calls[-1]
        assert call_name == "save"
        assert request.project_id == "proj-1"
        assert request.shared_profile_id == "profile:shared"
        assert request.project_profile is None
    finally:
        view.cleanup()


def test_project_settings_pane_can_select_custom_profile():
    from context_aware_translation.ui.features.project_settings_pane import ProjectSettingsPane

    service = FakeProjectSetupService(state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = ProjectSettingsPane("proj-1", service, bus)
    try:
        custom_index = next(
            index for index, option in enumerate(view.viewmodel.profile_options) if option["label"] == "Custom profile"
        )
        view.profile_combo.setCurrentIndex(custom_index)
        QApplication.processEvents()

        assert view.profile_combo.currentIndex() == custom_index
        assert view.profile_detail_label.text() == "Project-specific overrides"
        assert not view.routes_group.isHidden()
        assert view.routes_table.rowCount() == 2
        assert view.routes_table.columnCount() == 4
        assert view.routes_table.item(0, 0).text() == "Translator"
        assert view.routes_table.item(1, 0).text() == "OCR"
        assert view.viewmodel.show_custom_profile is True
        root = view.chrome_host.rootObject()
        assert root is not None
        assert view.chrome_host.minimumHeight() >= int(root.property("implicitHeight"))

        translator_row = next(
            index for index, row in enumerate(view._custom_rows) if row.route.step_id is WorkflowStepId.TRANSLATOR
        )
        translator = view._custom_rows[translator_row]
        translator.connection_combo.setCurrentIndex(translator.connection_combo.findData("conn-openai"))
        translator.model_edit.setText("gpt-4.1-mini")
        view._save()

        call_name, request = service.calls[-1]
        assert call_name == "save"
        assert request.shared_profile_id == "profile:shared"
        assert request.project_profile is not None
        translator_route = next(
            route for route in request.project_profile.routes if route.step_id is WorkflowStepId.TRANSLATOR
        )
        assert translator_route.connection_id == "conn-openai"
        assert translator_route.model == "gpt-4.1-mini"
    finally:
        view.cleanup()


def test_project_settings_pane_first_popup_click_switches_to_custom_profile():
    from context_aware_translation.ui.features.project_settings_pane import ProjectSettingsPane

    service = FakeProjectSetupService(state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = ProjectSettingsPane("proj-1", service, bus)
    try:
        custom_index = next(
            index for index, option in enumerate(view.viewmodel.profile_options) if option["label"] == "Custom profile"
        )
        view.show()
        _flush()
        view.profile_combo.showPopup()
        _flush()

        popup = view.profile_combo.view()
        model_index = popup.model().index(custom_index, 0)
        rect = popup.visualRect(model_index)
        QTest.mouseClick(popup.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect.center())
        _flush()

        assert view.profile_combo.currentIndex() == custom_index
        assert view.viewmodel.show_custom_profile is True
        assert not view.routes_group.isHidden()
    finally:
        view.close()
        view.cleanup()


def test_project_settings_pane_custom_step_advanced_button_opens_advanced_dialog():
    from context_aware_translation.ui.features import workflow_profile_editor as editor_module
    from context_aware_translation.ui.features.project_settings_pane import ProjectSettingsPane

    service = FakeProjectSetupService(state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = ProjectSettingsPane("proj-1", service, bus)
    try:
        custom_index = next(
            index for index, option in enumerate(view.viewmodel.profile_options) if option["label"] == "Custom profile"
        )
        view._on_profile_index_requested(custom_index)
        _flush()
        translator_row = next(
            index for index, row in enumerate(view._custom_rows) if row.route.step_id is WorkflowStepId.TRANSLATOR
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
        assert view._custom_rows[translator_row].route.step_config["chunk_size"] == 1234
    finally:
        view.cleanup()


def test_project_settings_pane_opens_app_setup_for_blocker():
    from context_aware_translation.ui.features.project_settings_pane import ProjectSettingsPane

    service = FakeProjectSetupService(state=_make_state(blocker="Open App Setup."))
    bus = InMemoryApplicationEventBus()
    view = ProjectSettingsPane("proj-1", service, bus)
    requested: list[bool] = []
    view.open_app_setup_requested.connect(lambda: requested.append(True))
    try:
        root = view.chrome_host.rootObject()
        assert root is not None
        root.openAppSetupRequested.emit()
        assert requested == [True]
    finally:
        view.cleanup()


def test_project_settings_pane_refreshes_on_setup_invalidation():
    from context_aware_translation.ui.features.project_settings_pane import ProjectSettingsPane

    service = FakeProjectSetupService(state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = ProjectSettingsPane("proj-1", service, bus)
    try:
        service.state = _make_state(project_specific=True)
        bus.publish(SetupInvalidatedEvent(project_id="proj-1"))

        assert view.viewmodel.show_custom_profile is True
        assert service.calls == [("get_state", "proj-1"), ("get_state", "proj-1")]
    finally:
        view.cleanup()


def test_project_settings_pane_screenshot_restores_shared_layout_after_custom_round_trip():
    from context_aware_translation.ui.features.project_settings_pane import ProjectSettingsPane

    service = FakeProjectSetupService(state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = ProjectSettingsPane("proj-1", service, bus)
    try:
        root = view.chrome_host.rootObject()
        assert root is not None

        shared_before = _grab_image(view)
        shared_before_height = float(root.property("implicitHeight"))

        custom_index = next(
            index for index, option in enumerate(view.viewmodel.profile_options) if option["label"] == "Custom profile"
        )
        view.profile_combo.setCurrentIndex(custom_index)
        _flush()

        custom_image = _grab_image(view)
        custom_height = float(root.property("implicitHeight"))
        custom_region = view.routes_group.geometry()

        view.profile_combo.setCurrentIndex(0)
        _flush()

        shared_after = _grab_image(view)
        shared_after_height = float(root.property("implicitHeight"))

        shared_before_crop = _crop_rect(
            shared_before,
            x=custom_region.x(),
            y=custom_region.y(),
            width=custom_region.width(),
            height=custom_region.height(),
        )
        custom_crop = _crop_rect(
            custom_image,
            x=custom_region.x(),
            y=custom_region.y(),
            width=custom_region.width(),
            height=custom_region.height(),
        )
        shared_after_crop = _crop_rect(
            shared_after,
            x=custom_region.x(),
            y=custom_region.y(),
            width=custom_region.width(),
            height=custom_region.height(),
        )
        background = shared_before_crop.pixelColor(0, 0)

        assert (
            _ink_ratio(custom_crop, background=background)
            > _ink_ratio(shared_before_crop, background=background) + 0.08
        )
        assert (
            abs(
                _ink_ratio(shared_after_crop, background=background)
                - _ink_ratio(shared_before_crop, background=background)
            )
            <= 0.02
        )
        assert custom_height == shared_before_height
        assert shared_after_height == shared_before_height
        assert view.routes_group.isHidden()
        assert view.routes_group.maximumHeight() == 0
    finally:
        view.close()
        view.cleanup()
