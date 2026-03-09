from __future__ import annotations

from unittest.mock import patch

import pytest

from context_aware_translation.application.contracts.app_setup import (
    AppSetupState,
    CapabilityCard,
    ConnectionDraft,
    ConnectionStatus,
    ConnectionSummary,
    ConnectionTestResult,
    DefaultRoute,
    ProviderCard,
    RoutingRecommendation,
    SaveConnectionRequest,
    SetupWizardState,
    SetupWizardStep,
)
from context_aware_translation.application.contracts.common import (
    CapabilityAvailability,
    CapabilityCode,
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


def _make_state(*, requires_wizard: bool = False) -> AppSetupState:
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
        default_routes=[
            DefaultRoute(
                capability=CapabilityCode.TRANSLATION,
                connection_id="conn-gemini",
                connection_label="Gemini",
            )
        ],
        requires_wizard=requires_wizard,
    )


def test_app_setup_view_renders_backend_state():
    from context_aware_translation.ui.features.app_setup_view import AppSetupView

    service = FakeAppSetupService(state=_make_state())
    view = AppSetupView(service)

    assert view.connections_table.rowCount() == 1
    assert view.capabilities_table.rowCount() == 2
    assert view.routes_table.rowCount() == 1
    assert "connections configured" in view.summary_label.text()
    assert view.run_wizard_button.text() == view.tr("Open Setup Wizard")


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


class _FakeWizardDialog:
    def __init__(self, *args, **kwargs):
        pass

    def exec(self):
        return QDialog.DialogCode.Accepted


def test_app_setup_view_add_delete_and_test_connection_calls_service():
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
            recommendation=RoutingRecommendation(
                routes=[
                    DefaultRoute(
                        capability=CapabilityCode.TRANSLATION,
                        connection_id="conn-gemini",
                        connection_label="Gemini",
                    )
                ]
            ),
            message=UserMessage(severity=UserMessageSeverity.INFO, text="Connection accepted."),
        ),
    )
    view = AppSetupView(service)
    view.connections_table.selectRow(0)

    with (
        patch("context_aware_translation.ui.features.app_setup_view.ConnectionEditorDialog", _FakeConnectionDialog),
        patch.object(QMessageBox, "information") as info_mock,
        patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
    ):
        view._on_add_connection()
        view.connections_table.selectRow(0)
        view._on_test_connection()
        view.connections_table.selectRow(0)
        view._on_delete_connection()

    assert service.calls[1][0] == "save_connection"
    assert any(call[0] == "test_connection" for call in service.calls)
    assert any(call[0] == "delete_connection" for call in service.calls)
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
        step=SetupWizardStep.REVIEW_ROUTING,
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
                recommendation=RoutingRecommendation(
                    routes=[
                        DefaultRoute(
                            capability=CapabilityCode.TRANSLATION,
                            connection_id="Gemini",
                            connection_label="Gemini",
                        )
                    ]
                ),
                message=UserMessage(severity=UserMessageSeverity.INFO, text="Connection accepted."),
            )
        ],
        recommendation=RoutingRecommendation(
            routes=[
                DefaultRoute(
                    capability=CapabilityCode.TRANSLATION,
                    connection_id="Gemini",
                    connection_label="Gemini",
                )
            ],
            notes=["Recommended routing prefers the first selected provider that supports each capability."],
        ),
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


def test_app_setup_view_refreshes_wizard_prompt_state():
    from context_aware_translation.ui.features.app_setup_view import AppSetupView

    service = FakeAppSetupService(state=_make_state(requires_wizard=True))
    view = AppSetupView(service)

    assert view.run_wizard_button.text() == view.tr("Run Setup Wizard")
    assert "Run the setup wizard" in view.summary_label.text()
