from __future__ import annotations

import pytest

from context_aware_translation.application.contracts.common import (
    BindingSource,
    BlockerCode,
    CapabilityAvailability,
    CapabilityCode,
    NavigationTarget,
    NavigationTargetKind,
    PresetCode,
    ProjectRef,
)
from context_aware_translation.application.contracts.project_setup import (
    ProjectCapabilityBinding,
    ProjectCapabilityCard,
    ProjectConnectionOption,
    ProjectSetupState,
)
from context_aware_translation.application.events import InMemoryApplicationEventBus, SetupInvalidatedEvent
from tests.application.fakes import FakeProjectSetupService

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


def _make_state(*, translation_source: BindingSource = BindingSource.APP_DEFAULT, missing_image_editing: bool = False) -> ProjectSetupState:
    shared_option = ProjectConnectionOption(connection_id="conn-gemini", connection_label="Gemini Shared")
    override_option = ProjectConnectionOption(connection_id="conn-openai", connection_label="OpenAI Shared")

    image_blocker = None
    image_options: list[ProjectConnectionOption] = [shared_option] if not missing_image_editing else []
    image_connection_id = "conn-gemini" if not missing_image_editing else None
    image_source = BindingSource.APP_DEFAULT if not missing_image_editing else BindingSource.MISSING
    image_availability = CapabilityAvailability.READY if not missing_image_editing else CapabilityAvailability.MISSING
    if missing_image_editing:
        from context_aware_translation.application.contracts.common import BlockerInfo

        image_blocker = BlockerInfo(
            code=BlockerCode.NEEDS_SETUP,
            message="Image editing needs a shared connection in App Setup.",
            target=NavigationTarget(kind=NavigationTargetKind.APP_SETUP),
        )

    translation_connection_id = "conn-gemini" if translation_source is not BindingSource.PROJECT_OVERRIDE else "conn-openai"
    translation_connection_label = "Gemini Shared" if translation_source is not BindingSource.PROJECT_OVERRIDE else "OpenAI Shared"

    return ProjectSetupState(
        project=ProjectRef(project_id="proj-1", name="One Piece"),
        target_language="English",
        preset=PresetCode.BALANCED,
        bindings=[
            ProjectCapabilityBinding(
                capability=CapabilityCode.TRANSLATION,
                availability=CapabilityAvailability.READY,
                source=translation_source,
                connection_id=translation_connection_id,
                connection_label=translation_connection_label,
            ),
            ProjectCapabilityBinding(
                capability=CapabilityCode.IMAGE_EDITING,
                availability=image_availability,
                source=image_source,
                connection_id=image_connection_id,
                connection_label="Gemini Shared" if image_connection_id else None,
                blocker=image_blocker,
            ),
        ],
        capability_cards=[
            ProjectCapabilityCard(
                capability=CapabilityCode.TRANSLATION,
                availability=CapabilityAvailability.READY,
                source=translation_source,
                connection_id=translation_connection_id,
                connection_label=translation_connection_label,
                options=[shared_option, override_option],
            ),
            ProjectCapabilityCard(
                capability=CapabilityCode.IMAGE_EDITING,
                availability=image_availability,
                source=image_source,
                connection_id=image_connection_id,
                connection_label="Gemini Shared" if image_connection_id else None,
                options=image_options,
                blocker=image_blocker,
            ),
        ],
    )


def test_project_setup_view_renders_backend_state():
    from context_aware_translation.ui.features.project_setup_view import ProjectSetupView

    service = FakeProjectSetupService(state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = ProjectSetupView("proj-1", service, bus)
    try:
        assert view.title_label.text() == view.tr("Setup for One Piece")
        assert view.target_language_combo.currentText() == "English"
        assert view.preset_combo.currentData() == PresetCode.BALANCED.value
        assert "Using app defaults" in view.summary_label.text()
        assert service.calls == [("get_state", "proj-1")]
    finally:
        view.cleanup()


def test_project_setup_view_saves_overrides_and_emits_completion():
    from context_aware_translation.ui.features.project_setup_view import ProjectSetupView

    service = FakeProjectSetupService(state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = ProjectSetupView("proj-1", service, bus)
    saved: list[str] = []
    view.save_completed.connect(saved.append)
    try:
        translation_card = view._card_widgets[CapabilityCode.TRANSLATION]
        translation_card.override_checkbox.setChecked(True)
        option_index = translation_card.connection_combo.findData("conn-openai")
        translation_card.connection_combo.setCurrentIndex(option_index)

        view.save_button.click()

        assert saved == ["proj-1"]
        call_name, request = service.calls[-1]
        assert call_name == "save"
        assert request.project_id == "proj-1"
        assert request.target_language == "English"
        assert request.preset is PresetCode.BALANCED
        assert len(request.overrides) == 1
        assert request.overrides[0].capability is CapabilityCode.TRANSLATION
        assert request.overrides[0].connection_id == "conn-openai"
    finally:
        view.cleanup()


def test_project_setup_view_opens_app_setup_for_missing_capability():
    from context_aware_translation.ui.features.project_setup_view import ProjectSetupView

    service = FakeProjectSetupService(state=_make_state(missing_image_editing=True))
    bus = InMemoryApplicationEventBus()
    view = ProjectSetupView("proj-1", service, bus)
    requested: list[bool] = []
    view.open_app_setup_requested.connect(lambda: requested.append(True))
    try:
        image_card = view._card_widgets[CapabilityCode.IMAGE_EDITING]
        assert not image_card.open_app_setup_button.isHidden()

        image_card.open_app_setup_button.clicked.emit()

        assert requested == [True]
    finally:
        view.cleanup()


def test_project_setup_view_refreshes_on_setup_invalidation():
    from context_aware_translation.ui.features.project_setup_view import ProjectSetupView

    service = FakeProjectSetupService(state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = ProjectSetupView("proj-1", service, bus)
    try:
        service.state = _make_state(translation_source=BindingSource.PROJECT_OVERRIDE)
        bus.publish(SetupInvalidatedEvent(project_id="proj-1"))
        QApplication.processEvents()

        translation_card = view._card_widgets[CapabilityCode.TRANSLATION]
        assert translation_card.override_checkbox.isChecked()
        assert service.calls == [("get_state", "proj-1"), ("get_state", "proj-1")]
    finally:
        view.cleanup()
