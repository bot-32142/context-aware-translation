from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from context_aware_translation.application.contracts.app_setup import (
    AppSetupState,
    CapabilityCard,
    ConnectionDraft,
    ConnectionStatus,
    ConnectionSummary,
    ConnectionTestResult,
    ProviderCard,
    SaveConnectionRequest,
    SetupWizardState,
    SetupWizardStep,
    WorkflowProfileDetail,
    WorkflowProfileKind,
    WorkflowStepId,
    WorkflowStepRoute,
)
from context_aware_translation.application.contracts.common import (
    CapabilityAvailability,
    CapabilityCode,
    PresetCode,
    ProviderKind,
    UserMessage,
    UserMessageSeverity,
)
from tests.application.fakes import FakeAppSetupService

try:
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

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


def _profile(*, profile_id: str = "profile:recommended", name: str = "Recommended") -> WorkflowProfileDetail:
    return WorkflowProfileDetail(
        profile_id=profile_id,
        name=name,
        kind=WorkflowProfileKind.SHARED,
        target_language="English",
        preset=PresetCode.BALANCED,
        routes=[
            WorkflowStepRoute(
                step_id=WorkflowStepId.TRANSLATOR,
                step_label="Translator",
                connection_id="conn-gemini",
                connection_label="Gemini",
                model="gemini-3-flash-preview",
            ),
            WorkflowStepRoute(
                step_id=WorkflowStepId.OCR,
                step_label="OCR",
                connection_id="conn-gemini",
                connection_label="Gemini",
                model="gemini-3-flash-preview",
            ),
        ],
        is_default=True,
    )


def _make_state(*, requires_wizard: bool = False) -> AppSetupState:
    profile = _profile()
    return AppSetupState(
        connections=[
            ConnectionSummary(
                connection_id="conn-gemini",
                display_name="Gemini",
                provider=ProviderKind.GEMINI,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                default_model="gemini-3-flash-preview",
                status=ConnectionStatus.READY,
                capabilities=[CapabilityCode.TRANSLATION, CapabilityCode.IMAGE_TEXT_READING],
            )
        ]
        if not requires_wizard
        else [],
        capabilities=[
            CapabilityCard(
                capability=CapabilityCode.TRANSLATION,
                availability=CapabilityAvailability.READY,
                connection_id="conn-gemini",
                connection_label="Gemini",
                message="Using Gemini",
            ),
            CapabilityCard(
                capability=CapabilityCode.IMAGE_EDITING,
                availability=CapabilityAvailability.MISSING,
                message="No configured provider supports this capability.",
            ),
        ],
        shared_profiles=[profile] if not requires_wizard else [],
        default_profile_id=(profile.profile_id if not requires_wizard else None),
        selected_profile=(profile if not requires_wizard else None),
        requires_wizard=requires_wizard,
    )


class _FakeConnectionDialog:
    def __init__(self, *args, **kwargs):
        self._request = SaveConnectionRequest(
            connection=ConnectionDraft(
                display_name="DeepSeek",
                provider=ProviderKind.DEEPSEEK,
                api_key="secret",
                base_url="https://api.deepseek.com",
                default_model="deepseek-chat",
            )
        )

    def exec(self):
        return QDialog.DialogCode.Accepted

    def request(self):
        return self._request


class _FakeProfileEditorDialog:
    def __init__(self, *args, profile: WorkflowProfileDetail, **kwargs):
        self._profile = profile.model_copy(update={"name": "Edited profile"})

    def exec(self):
        return QDialog.DialogCode.Accepted

    def profile(self):
        return self._profile


def test_app_setup_view_renders_backend_state():
    from context_aware_translation.ui.features.app_setup_view import AppSetupView

    service = FakeAppSetupService(state=_make_state())
    view = AppSetupView(service)

    assert view.connections_table.rowCount() == 1
    assert view.profiles_table.rowCount() == 1
    assert view.setup_tabs.count() == 2
    assert view.setup_tabs.tabText(0) == view.tr("Connections")
    assert view.setup_tabs.tabText(1) == view.tr("Workflow Profiles")
    assert "connections configured" in view.summary_label.text()
    assert view.run_wizard_button.text() == view.tr("Open Setup Wizard")


class _FakeWizardDialog:
    def __init__(self, *args, **kwargs):
        pass

    def exec(self):
        return QDialog.DialogCode.Accepted


def test_app_setup_view_add_delete_test_and_edit_profile_calls_service():
    from context_aware_translation.ui.features.app_setup_view import AppSetupView

    state = _make_state()
    service = FakeAppSetupService(
        state=state,
        test_result=ConnectionTestResult(
            connection_label="Gemini",
            capabilities=[
                CapabilityCard(
                    capability=CapabilityCode.TRANSLATION,
                    availability=CapabilityAvailability.READY,
                    message="Supported by gemini",
                )
            ],
            message=UserMessage(severity=UserMessageSeverity.INFO, text="Connection accepted."),
        ),
    )
    view = AppSetupView(service)
    view.connections_table.selectRow(0)
    view.profiles_table.selectRow(0)

    with (
        patch("context_aware_translation.ui.features.app_setup_view.ConnectionEditorDialog", _FakeConnectionDialog),
        patch("context_aware_translation.ui.features.app_setup_view.WorkflowProfileEditorDialog", _FakeProfileEditorDialog),
        patch.object(QMessageBox, "information") as info_mock,
        patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
    ):
        view._on_add_connection()
        view.connections_table.selectRow(0)
        view._on_test_connection()
        view.connections_table.selectRow(0)
        view._on_delete_connection()
        view.profiles_table.selectRow(0)
        view._on_edit_profile()

    assert any(call[0] == "save_connection" for call in service.calls)
    assert any(call[0] == "test_connection" for call in service.calls)
    assert any(call[0] == "delete_connection" for call in service.calls)
    assert any(call[0] == "save_workflow_profile" for call in service.calls)
    assert info_mock.called


def test_setup_wizard_dialog_previews_and_saves_through_service():
    from context_aware_translation.ui.features.app_setup_view import SetupWizardDialog

    wizard_state = SetupWizardState(
        step=SetupWizardStep.CHOOSE_PROVIDERS,
        available_providers=[
            ProviderCard(
                provider=ProviderKind.GEMINI,
                label="Gemini",
                helper_text="Good for image text reading and image editing.",
                recommended_for=[CapabilityCode.TRANSLATION, CapabilityCode.IMAGE_TEXT_READING],
            )
        ],
    )
    preview_state = SetupWizardState(
        step=SetupWizardStep.REVIEW_PROFILE,
        available_providers=wizard_state.available_providers,
        selected_providers=[ProviderKind.GEMINI],
        drafts=[
            ConnectionDraft(
                display_name="Gemini",
                provider=ProviderKind.GEMINI,
                api_key="secret",
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                default_model="gemini-3-flash-preview",
            )
        ],
        test_results=[
            ConnectionTestResult(
                connection_label="Gemini",
                capabilities=[
                    CapabilityCard(
                        capability=CapabilityCode.TRANSLATION,
                        availability=CapabilityAvailability.READY,
                        message="Supported by gemini",
                    )
                ],
                message=UserMessage(severity=UserMessageSeverity.INFO, text="Connection accepted."),
            )
        ],
        recommendation=_profile(profile_id="recommended", name="Recommended"),
    )
    service = FakeAppSetupService(state=_make_state(), wizard_state=wizard_state, preview_state=preview_state)
    dialog = SetupWizardDialog(service, wizard_state)

    dialog._provider_checks[ProviderKind.GEMINI].setChecked(True)
    dialog._go_next()
    assert dialog._page_index == 1

    form = dialog._draft_forms[0]
    form.api_key_edit.setText("secret")
    dialog._go_next()

    assert dialog._page_index == 2
    assert any(call[0] == "preview_setup_wizard" for call in service.calls)

    dialog._finish()

    assert any(call[0] == "run_setup_wizard" for call in service.calls)


def test_setup_wizard_dialog_renders_provider_cards_on_first_page():
    from context_aware_translation.ui.features.app_setup_view import SetupWizardDialog

    wizard_state = SetupWizardState(
        step=SetupWizardStep.CHOOSE_PROVIDERS,
        available_providers=[
            ProviderCard(
                provider=ProviderKind.GEMINI,
                label="Gemini",
                helper_text="Good for image text reading and image editing.",
                recommended_for=[CapabilityCode.TRANSLATION, CapabilityCode.IMAGE_TEXT_READING],
            ),
            ProviderCard(
                provider=ProviderKind.DEEPSEEK,
                label="DeepSeek",
                helper_text="Good for text translation.",
                recommended_for=[CapabilityCode.TRANSLATION],
            ),
        ],
        selected_providers=[ProviderKind.GEMINI],
    )
    service = FakeAppSetupService(state=_make_state(requires_wizard=True), wizard_state=wizard_state)

    dialog = SetupWizardDialog(service, wizard_state)

    provider_checkboxes = dialog.page_content.findChildren(type(dialog._provider_checks[ProviderKind.GEMINI]))
    assert len(provider_checkboxes) == 2
    assert dialog._provider_checks[ProviderKind.GEMINI].isChecked() is True


def test_setup_wizard_dialog_renders_connection_form_after_provider_step():
    from context_aware_translation.ui.features.app_setup_view import SetupWizardDialog

    wizard_state = SetupWizardState(
        step=SetupWizardStep.CHOOSE_PROVIDERS,
        available_providers=[
            ProviderCard(
                provider=ProviderKind.GEMINI,
                label="Gemini",
                helper_text="Good for image text reading and image editing.",
                recommended_for=[CapabilityCode.TRANSLATION, CapabilityCode.IMAGE_TEXT_READING],
            )
        ],
    )
    service = FakeAppSetupService(state=_make_state(requires_wizard=True), wizard_state=wizard_state)
    dialog = SetupWizardDialog(service, wizard_state)

    dialog._provider_checks[ProviderKind.GEMINI].setChecked(True)
    dialog._go_next()

    assert dialog._page_index == 1
    assert len(dialog._draft_forms) == 1
    assert dialog._draft_forms[0].current_provider() is ProviderKind.GEMINI


def test_setup_wizard_dialog_preserves_draft_when_going_back():
    from context_aware_translation.ui.features.app_setup_view import SetupWizardDialog

    wizard_state = SetupWizardState(
        step=SetupWizardStep.CHOOSE_PROVIDERS,
        available_providers=[
            ProviderCard(
                provider=ProviderKind.GEMINI,
                label="Gemini",
                helper_text="Good for image text reading and image editing.",
                recommended_for=[CapabilityCode.TRANSLATION, CapabilityCode.IMAGE_TEXT_READING],
            )
        ],
    )
    service = FakeAppSetupService(state=_make_state(requires_wizard=True), wizard_state=wizard_state)
    dialog = SetupWizardDialog(service, wizard_state)

    dialog._provider_checks[ProviderKind.GEMINI].setChecked(True)
    dialog._go_next()
    form = dialog._draft_forms[0]
    form.api_key_edit.setText("secret")
    form.display_name_edit.setText("Gemini A")

    dialog._go_back()
    assert dialog._page_index == 0
    assert dialog._provider_checks[ProviderKind.GEMINI].isChecked() is True

    dialog._go_next()
    assert dialog._draft_forms[0].api_key_edit.text() == "secret"
    assert dialog._draft_forms[0].display_name_edit.text() == "Gemini A"


def test_setup_wizard_dialog_custom_provider_requires_endpoint_and_model():
    from context_aware_translation.ui.features.app_setup_view import SetupWizardDialog

    wizard_state = SetupWizardState(
        step=SetupWizardStep.CHOOSE_PROVIDERS,
        available_providers=[
            ProviderCard(
                provider=ProviderKind.OPENAI_COMPATIBLE,
                label="OpenAI-compatible / Custom",
                helper_text="Use a custom base URL and model names.",
                supports_custom_endpoint=True,
                recommended_for=[CapabilityCode.TRANSLATION],
            )
        ],
    )
    service = FakeAppSetupService(state=_make_state(requires_wizard=True), wizard_state=wizard_state)
    dialog = SetupWizardDialog(service, wizard_state)

    dialog._provider_checks[ProviderKind.OPENAI_COMPATIBLE].setChecked(True)
    dialog._go_next()

    form = dialog._draft_forms[0]
    assert form.current_provider() is ProviderKind.OPENAI_COMPATIBLE
    assert form.advanced_section.is_expanded() is True

    form.api_key_edit.setText("secret")
    assert form.validate(require_api_key=True) == (
        False,
        form.tr("Custom connections require base URL and default model."),
    )

    form.base_url_edit.setText("https://example.com/v1")
    form.default_model_edit.setText("test-model")
    assert form.validate(require_api_key=True) == (True, None)


def test_setup_wizard_dialog_back_from_review_rebuilds_provider_page():
    from context_aware_translation.ui.features.app_setup_view import SetupWizardDialog

    wizard_state = SetupWizardState(
        step=SetupWizardStep.CHOOSE_PROVIDERS,
        available_providers=[
            ProviderCard(
                provider=ProviderKind.GEMINI,
                label="Gemini",
                helper_text="Good for image text reading and image editing.",
                recommended_for=[CapabilityCode.TRANSLATION, CapabilityCode.IMAGE_TEXT_READING],
            )
        ],
    )
    preview_state = SetupWizardState(
        step=SetupWizardStep.REVIEW_PROFILE,
        available_providers=wizard_state.available_providers,
        selected_providers=[ProviderKind.GEMINI],
        drafts=[
            ConnectionDraft(
                display_name="Gemini",
                provider=ProviderKind.GEMINI,
                api_key="secret",
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                default_model="gemini-3-flash-preview",
            )
        ],
        test_results=[
            ConnectionTestResult(
                connection_label="Gemini",
                capabilities=[
                    CapabilityCard(
                        capability=CapabilityCode.TRANSLATION,
                        availability=CapabilityAvailability.READY,
                        message="Supported by gemini",
                    )
                ],
                message=UserMessage(severity=UserMessageSeverity.INFO, text="Connection accepted."),
            )
        ],
        recommendation=_profile(profile_id="recommended", name="Recommended"),
    )
    service = FakeAppSetupService(state=_make_state(), wizard_state=wizard_state, preview_state=preview_state)
    dialog = SetupWizardDialog(service, wizard_state)

    dialog._provider_checks[ProviderKind.GEMINI].setChecked(True)
    dialog._go_next()
    dialog._draft_forms[0].api_key_edit.setText("secret")
    dialog._go_next()
    assert dialog._page_index == 2

    dialog._go_back()
    assert dialog._page_index == 1
    dialog._go_back()
    assert dialog._page_index == 0

    card_host = dialog.page_layout.itemAt(0).widget()
    assert card_host is not None
    assert card_host.layout() is not None
    assert card_host.layout().count() >= 1
    first_item_widget = card_host.layout().itemAt(0).widget()
    assert first_item_widget is dialog._provider_checks[ProviderKind.GEMINI]
    assert dialog._provider_checks[ProviderKind.GEMINI].isChecked() is True


def test_app_setup_view_refreshes_wizard_prompt_state():
    from context_aware_translation.ui.features.app_setup_view import AppSetupView

    service = FakeAppSetupService(state=_make_state(requires_wizard=True))
    view = AppSetupView(service)

    assert view.run_wizard_button.text() == view.tr("Run Setup Wizard")
    assert "Run the setup wizard" in view.summary_label.text()


def test_connection_draft_form_round_trips_advanced_fields():
    from context_aware_translation.ui.features.app_setup_view import ConnectionDraftForm

    form = ConnectionDraftForm()
    form.set_draft(
        ConnectionDraft(
            display_name="Gemini Advanced",
            provider=ProviderKind.GEMINI,
            description="Image-heavy manga setup",
            api_key="secret",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            default_model="gemini-3.1-flash-image-preview",
            temperature=0.2,
            timeout=180,
            max_retries=5,
            concurrency=3,
            token_limit=120000,
            input_token_limit=80000,
            output_token_limit=40000,
            custom_parameters_json=json.dumps({"reasoning_effort": "medium"}, ensure_ascii=False),
        )
    )

    round_tripped = form.to_draft()

    assert round_tripped.description == "Image-heavy manga setup"
    assert round_tripped.temperature == pytest.approx(0.2)
    assert round_tripped.timeout == 180
    assert round_tripped.max_retries == 5
    assert round_tripped.concurrency == 3
    assert round_tripped.token_limit == 120000
    assert round_tripped.input_token_limit == 80000
    assert round_tripped.output_token_limit == 40000
    assert json.loads(round_tripped.custom_parameters_json or "{}") == {"reasoning_effort": "medium"}


def test_connection_draft_form_rejects_invalid_custom_json():
    from context_aware_translation.ui.features.app_setup_view import ConnectionDraftForm

    form = ConnectionDraftForm()
    form.set_draft(
        ConnectionDraft(
            display_name="Gemini",
            provider=ProviderKind.GEMINI,
            api_key="secret",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            default_model="gemini-3-flash-preview",
        )
    )
    form.custom_parameters_edit.setPlainText("{invalid")

    assert form.validate(require_api_key=True) == (
        False,
        form.tr("Custom parameters must be valid JSON."),
    )
