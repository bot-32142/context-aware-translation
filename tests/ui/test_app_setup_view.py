from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import patch

import pytest

from context_aware_translation.application.contracts.app_setup import (
    AppSetupState,
    ConnectionDraft,
    ConnectionStatus,
    ConnectionSummary,
    ConnectionTestResult,
    ProviderCard,
    SetupWizardMode,
    SetupWizardState,
    WorkflowProfileDetail,
    WorkflowProfileKind,
    WorkflowStepId,
    WorkflowStepRoute,
)
from context_aware_translation.application.contracts.common import (
    CapabilityCode,
    ProviderKind,
    UserMessage,
    UserMessageSeverity,
)
from context_aware_translation.ui.constants import LANGUAGES
from tests.application.fakes import FakeAppSetupService

try:
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QTableWidget

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


def _profile(
    *,
    profile_id: str = "profile:recommended",
    name: str = "Recommended",
    translator_model: str = "gemini-3-flash-preview",
) -> WorkflowProfileDetail:
    return WorkflowProfileDetail(
        profile_id=profile_id,
        name=name,
        kind=WorkflowProfileKind.SHARED,
        target_language="English",
        routes=[
            WorkflowStepRoute(
                step_id=WorkflowStepId.TRANSLATOR,
                step_label="Translator",
                connection_id="conn-gemini",
                connection_label="Gemini",
                model=translator_model,
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


def _make_state(*, needs_wizard: bool = False) -> AppSetupState:
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
            )
        ]
        if not needs_wizard
        else [],
        shared_profiles=[profile] if not needs_wizard else [],
    )


def _provider_checkbox(dialog, provider: ProviderKind):
    return dialog._provider_inputs[provider][0]


def _provider_api_key_edit(dialog, provider: ProviderKind):
    return dialog._provider_inputs[provider][1]


class _FakeWizardDialog:
    def __init__(self, *args, **kwargs):
        pass

    def exec(self):
        return QDialog.DialogCode.Accepted


def test_setup_wizard_dialog_previews_and_saves_through_service():
    from context_aware_translation.ui.features.app_setup_view import SetupWizardDialog

    wizard_state = SetupWizardState(
        available_providers=[
            ProviderCard(
                provider=ProviderKind.GEMINI,
                label="Gemini",
                helper_text="Good for image text reading and image editing.",
            )
        ],
    )
    preview_state = SetupWizardState(
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
                supported_capabilities=[CapabilityCode.TRANSLATION],
                message=UserMessage(severity=UserMessageSeverity.INFO, text="Connection accepted."),
            )
        ],
        recommendation=_profile(profile_id="recommended", name="Recommended"),
        target_language="English",
    )
    service = FakeAppSetupService(state=_make_state(), wizard_state=wizard_state, preview_state=preview_state)
    dialog = SetupWizardDialog(service, wizard_state)

    _provider_checkbox(dialog, ProviderKind.GEMINI).setChecked(True)
    _provider_api_key_edit(dialog, ProviderKind.GEMINI).setText("secret")
    dialog._go_next()

    assert dialog._page_index == 1
    assert any(call[0] == "preview_setup_wizard" for call in service.calls)
    preview_request = next(call[1] for call in service.calls if call[0] == "preview_setup_wizard")
    assert preview_request.recommendation_mode is SetupWizardMode.BALANCED
    assert dialog._quality_mode_radio is not None
    assert dialog._balanced_mode_radio is not None
    assert dialog._budget_mode_radio is not None
    dialog._quality_mode_radio.setChecked(True)
    QApplication.processEvents()
    assert dialog._profile_name_edit is not None
    assert dialog._target_language_combo is not None
    dialog._profile_name_edit.setText("Team Default")
    dialog._target_language_combo.setEditText("Japanese")

    dialog._finish()

    preview_requests = [call[1] for call in service.calls if call[0] == "preview_setup_wizard"]
    assert preview_requests[-1].recommendation_mode is SetupWizardMode.QUALITY
    assert any(call[0] == "run_setup_wizard" for call in service.calls)
    run_request = next(call[1] for call in service.calls if call[0] == "run_setup_wizard")
    assert run_request.profile_name == "Team Default"
    assert run_request.target_language == "Japanese"
    assert run_request.recommendation_mode is SetupWizardMode.QUALITY


def test_setup_wizard_dialog_switches_recommended_model_when_mode_changes():
    from context_aware_translation.ui.features.app_setup_view import SetupWizardDialog

    @dataclass
    class _ModePreviewService(FakeAppSetupService):
        def preview_setup_wizard(self, request):  # noqa: ANN001
            self.calls.append(("preview_setup_wizard", request))
            translator_model = "gpt-5.4"
            polish_model = "gpt-5.4"
            recommendation = WorkflowProfileDetail(
                profile_id="recommended",
                name=request.profile_name or "Recommended",
                kind=WorkflowProfileKind.SHARED,
                target_language=request.target_language or "English",
                routes=[
                    WorkflowStepRoute(
                        step_id=WorkflowStepId.TRANSLATOR,
                        step_label="Translator",
                        connection_id="conn-openai",
                        connection_label="OpenAI",
                        model=translator_model,
                    ),
                    WorkflowStepRoute(
                        step_id=WorkflowStepId.POLISH,
                        step_label="Polish",
                        connection_id="conn-openai",
                        connection_label="OpenAI",
                        model=polish_model,
                    ),
                ],
                is_default=True,
            )
            return SetupWizardState(
                available_providers=self.wizard_state.available_providers if self.wizard_state is not None else [],
                selected_providers=request.providers,
                drafts=request.connections,
                recommendation=recommendation,
                profile_name=request.profile_name,
                target_language=request.target_language or "English",
                recommendation_mode=request.recommendation_mode,
            )

    wizard_state = SetupWizardState(
        available_providers=[
            ProviderCard(
                provider=ProviderKind.OPENAI,
                label="OpenAI",
                helper_text="General-purpose text and image-capable provider.",
            )
        ]
    )
    service = _ModePreviewService(state=_make_state(needs_wizard=True), wizard_state=wizard_state)
    dialog = SetupWizardDialog(service, wizard_state)

    dialog._provider_inputs[ProviderKind.OPENAI][0].setChecked(True)
    dialog._provider_inputs[ProviderKind.OPENAI][1].setText("secret")
    dialog._go_next()

    assert dialog._provider_inputs == {}
    table = dialog.findChild(QTableWidget)
    assert table is not None
    assert table.item(0, 2).text() == "gpt-5.4"
    assert table.item(1, 2).text() == "gpt-5.4"

    assert dialog._quality_mode_radio is not None
    dialog._quality_mode_radio.setChecked(True)
    QApplication.processEvents()

    table = dialog.findChild(QTableWidget)
    assert table is not None
    assert table.item(0, 2).text() == "gpt-5.4"
    assert table.item(1, 2).text() == "gpt-5.4"

    assert dialog._balanced_mode_radio is not None
    dialog._balanced_mode_radio.setChecked(True)
    QApplication.processEvents()

    table = dialog.findChild(QTableWidget)
    assert table is not None
    assert table.item(0, 2).text() == "gpt-5.4"
    assert table.item(1, 2).text() == "gpt-5.4"

    assert dialog._budget_mode_radio is not None
    dialog._budget_mode_radio.setChecked(True)
    QApplication.processEvents()

    assert dialog._profile_name_edit is not None
    table = dialog.findChild(QTableWidget)
    assert table is not None
    assert table.item(0, 2).text() == "gpt-5.4"
    assert table.item(1, 2).text() == "gpt-5.4"
    preview_requests = [call[1] for call in service.calls if call[0] == "preview_setup_wizard"]
    assert [request.recommendation_mode for request in preview_requests] == [
        SetupWizardMode.BALANCED,
        SetupWizardMode.QUALITY,
        SetupWizardMode.BALANCED,
        SetupWizardMode.BUDGET,
    ]


def test_connection_draft_form_prefills_curated_defaults_for_supported_providers():
    from context_aware_translation.ui.features.app_setup_view import ConnectionDraftForm

    form = ConnectionDraftForm()

    def _select_provider(provider: ProviderKind) -> None:
        index = form.provider_combo.findData(provider.value)
        assert index >= 0
        form.provider_combo.setCurrentIndex(index)

    _select_provider(ProviderKind.GEMINI)
    assert form.base_url_edit.text() == "https://generativelanguage.googleapis.com/v1beta/openai/"
    assert form.default_model_edit.text() == "gemini-3.1-pro"

    _select_provider(ProviderKind.OPENAI)
    assert form.base_url_edit.text() == "https://api.openai.com/v1"
    assert form.default_model_edit.text() == "gpt-5.4"
    assert form.concurrency_spin.value() == 5

    _select_provider(ProviderKind.DEEPSEEK)
    assert form.base_url_edit.text() == "https://api.deepseek.com"
    assert form.default_model_edit.text() == "deepseek-chat"
    assert form.concurrency_spin.value() == 15

    _select_provider(ProviderKind.ANTHROPIC)
    assert form.base_url_edit.text() == "https://api.anthropic.com/v1"
    assert form.default_model_edit.text() == "claude-opus-4-6"
    assert form.concurrency_spin.value() == 5


def test_setup_wizard_dialog_renders_provider_cards_on_first_page():
    from context_aware_translation.ui.features.app_setup_view import SetupWizardDialog

    wizard_state = SetupWizardState(
        available_providers=[
            ProviderCard(
                provider=ProviderKind.GEMINI,
                label="Gemini",
                helper_text="Good for image text reading and image editing.",
            ),
            ProviderCard(
                provider=ProviderKind.DEEPSEEK,
                label="DeepSeek",
                helper_text="Good for text translation.",
            ),
        ],
        selected_providers=[ProviderKind.GEMINI],
    )
    service = FakeAppSetupService(state=_make_state(needs_wizard=True), wizard_state=wizard_state)

    dialog = SetupWizardDialog(service, wizard_state)

    provider_checkboxes = dialog.page_content.findChildren(type(_provider_checkbox(dialog, ProviderKind.GEMINI)))
    assert len(provider_checkboxes) == 2
    assert _provider_checkbox(dialog, ProviderKind.GEMINI).isChecked() is True


def test_setup_wizard_dialog_defaults_target_language_to_first_dropdown_entry():
    from context_aware_translation.ui.features.app_setup_view import SetupWizardDialog

    @dataclass
    class _EchoPreviewService(FakeAppSetupService):
        def preview_setup_wizard(self, request):  # noqa: ANN001
            self.calls.append(("preview_setup_wizard", request))
            recommendation = _profile(profile_id="recommended", name=request.profile_name or "Recommended").model_copy(
                update={"target_language": request.target_language or LANGUAGES[0][0]}
            )
            return SetupWizardState(
                available_providers=self.wizard_state.available_providers if self.wizard_state is not None else [],
                selected_providers=request.providers,
                drafts=request.connections,
                recommendation=recommendation,
                profile_name=request.profile_name,
                target_language=request.target_language or LANGUAGES[0][0],
            )

    wizard_state = SetupWizardState(
        available_providers=[
            ProviderCard(
                provider=ProviderKind.GEMINI,
                label="Gemini",
                helper_text="Good for image text reading and image editing.",
            )
        ]
    )
    service = _EchoPreviewService(state=_make_state(needs_wizard=True), wizard_state=wizard_state)
    dialog = SetupWizardDialog(service, wizard_state)

    _provider_checkbox(dialog, ProviderKind.GEMINI).setChecked(True)
    _provider_api_key_edit(dialog, ProviderKind.GEMINI).setText("secret")
    dialog._go_next()

    assert dialog._target_language_combo is not None
    assert dialog._target_language_combo.currentText() == LANGUAGES[0][0]
    assert dialog._target_language_combo.itemText(0) == LANGUAGES[0][0]


def test_setup_wizard_dialog_collects_api_keys_on_provider_page():
    from context_aware_translation.ui.features.app_setup_view import SetupWizardDialog

    wizard_state = SetupWizardState(
        available_providers=[
            ProviderCard(
                provider=ProviderKind.GEMINI,
                label="Gemini",
                helper_text="Good for image text reading and image editing.",
            )
        ],
    )
    service = FakeAppSetupService(state=_make_state(needs_wizard=True), wizard_state=wizard_state)
    dialog = SetupWizardDialog(service, wizard_state)

    assert ProviderKind.GEMINI in dialog._provider_inputs
    assert _provider_api_key_edit(dialog, ProviderKind.GEMINI).isEnabled() is False

    _provider_checkbox(dialog, ProviderKind.GEMINI).setChecked(True)
    assert _provider_api_key_edit(dialog, ProviderKind.GEMINI).isEnabled() is True


def test_setup_wizard_dialog_preserves_draft_when_going_back():
    from context_aware_translation.ui.features.app_setup_view import SetupWizardDialog

    wizard_state = SetupWizardState(
        available_providers=[
            ProviderCard(
                provider=ProviderKind.GEMINI,
                label="Gemini",
                helper_text="Good for image text reading and image editing.",
            )
        ],
    )
    service = FakeAppSetupService(state=_make_state(needs_wizard=True), wizard_state=wizard_state)
    dialog = SetupWizardDialog(service, wizard_state)

    _provider_checkbox(dialog, ProviderKind.GEMINI).setChecked(True)
    _provider_api_key_edit(dialog, ProviderKind.GEMINI).setText("secret")

    dialog._go_next()
    assert dialog._page_index == 1
    dialog._go_back()

    assert dialog._page_index == 0
    assert _provider_checkbox(dialog, ProviderKind.GEMINI).isChecked() is True
    assert _provider_api_key_edit(dialog, ProviderKind.GEMINI).text() == "secret"


def test_setup_wizard_dialog_excludes_custom_provider():
    from context_aware_translation.ui.features.app_setup_view import SetupWizardDialog

    wizard_state = SetupWizardState(
        available_providers=[
            ProviderCard(
                provider=ProviderKind.OPENAI_COMPATIBLE,
                label="OpenAI-compatible / Custom",
                helper_text="Use a custom base URL and model names.",
            )
        ],
    )
    service = FakeAppSetupService(state=_make_state(needs_wizard=True), wizard_state=wizard_state)
    dialog = SetupWizardDialog(service, wizard_state)

    assert dialog._provider_inputs == {}


def test_setup_wizard_dialog_preserves_target_language_when_going_back():
    from context_aware_translation.ui.features.app_setup_view import SetupWizardDialog

    @dataclass
    class _EchoPreviewService(FakeAppSetupService):
        def preview_setup_wizard(self, request):  # noqa: ANN001
            self.calls.append(("preview_setup_wizard", request))
            recommendation = _profile(profile_id="recommended", name=request.profile_name or "Recommended").model_copy(
                update={"target_language": request.target_language or "English"}
            )
            return SetupWizardState(
                available_providers=self.wizard_state.available_providers if self.wizard_state is not None else [],
                selected_providers=request.providers,
                drafts=request.connections,
                recommendation=recommendation,
                profile_name=request.profile_name,
                target_language=request.target_language or "English",
            )

    wizard_state = SetupWizardState(
        available_providers=[
            ProviderCard(
                provider=ProviderKind.GEMINI,
                label="Gemini",
                helper_text="Good for image text reading and image editing.",
            )
        ],
        target_language="English",
    )
    service = _EchoPreviewService(state=_make_state(needs_wizard=True), wizard_state=wizard_state)
    dialog = SetupWizardDialog(service, wizard_state)

    _provider_checkbox(dialog, ProviderKind.GEMINI).setChecked(True)
    _provider_api_key_edit(dialog, ProviderKind.GEMINI).setText("secret")
    dialog._go_next()
    assert dialog._target_language_combo is not None
    dialog._target_language_combo.setEditText("Japanese")

    dialog._go_back()
    dialog._go_next()

    assert dialog._target_language_combo is not None
    assert dialog._target_language_combo.currentText() == "Japanese"


def test_setup_wizard_dialog_displays_internal_target_language_labels():
    from context_aware_translation.ui.features.app_setup_view import SetupWizardDialog

    wizard_state = SetupWizardState(
        available_providers=[
            ProviderCard(
                provider=ProviderKind.GEMINI,
                label="Gemini",
                helper_text="Good for image text reading and image editing.",
            )
        ],
        target_language="英语",
    )
    preview_state = SetupWizardState(
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
        recommendation=_profile(profile_id="recommended", name="Recommended"),
        target_language="英语",
    )
    service = FakeAppSetupService(state=_make_state(needs_wizard=True), wizard_state=wizard_state, preview_state=preview_state)
    dialog = SetupWizardDialog(service, wizard_state)

    _provider_checkbox(dialog, ProviderKind.GEMINI).setChecked(True)
    _provider_api_key_edit(dialog, ProviderKind.GEMINI).setText("secret")
    dialog._go_next()

    assert dialog._target_language_combo is not None
    assert dialog._target_language_combo.currentText() == "English"


def test_setup_wizard_dialog_back_from_review_rebuilds_provider_page():
    from context_aware_translation.ui.features.app_setup_view import SetupWizardDialog

    wizard_state = SetupWizardState(
        available_providers=[
            ProviderCard(
                provider=ProviderKind.GEMINI,
                label="Gemini",
                helper_text="Good for image text reading and image editing.",
            )
        ],
    )
    preview_state = SetupWizardState(
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
                supported_capabilities=[CapabilityCode.TRANSLATION],
                message=UserMessage(severity=UserMessageSeverity.INFO, text="Connection accepted."),
            )
        ],
        recommendation=_profile(profile_id="recommended", name="Recommended"),
        target_language="English",
    )
    service = FakeAppSetupService(state=_make_state(), wizard_state=wizard_state, preview_state=preview_state)
    dialog = SetupWizardDialog(service, wizard_state)

    _provider_checkbox(dialog, ProviderKind.GEMINI).setChecked(True)
    _provider_api_key_edit(dialog, ProviderKind.GEMINI).setText("secret")
    dialog._go_next()
    assert dialog._page_index == 1
    assert dialog._target_language_combo is not None
    dialog._target_language_combo.setEditText("Japanese")

    dialog._go_back()
    assert dialog._page_index == 0

    card_host = dialog.page_layout.itemAt(0).widget()
    assert card_host is not None
    assert card_host.layout() is not None
    assert card_host.layout().count() >= 1
    first_item_widget = card_host.layout().itemAt(0).widget()
    assert first_item_widget is not None
    assert _provider_checkbox(dialog, ProviderKind.GEMINI).isChecked() is True
    assert _provider_api_key_edit(dialog, ProviderKind.GEMINI).text() == "secret"


def test_setup_wizard_dialog_clearing_all_providers_does_not_reuse_stale_selection():
    from context_aware_translation.ui.features.app_setup_view import SetupWizardDialog

    wizard_state = SetupWizardState(
        available_providers=[
            ProviderCard(
                provider=ProviderKind.GEMINI,
                label="Gemini",
                helper_text="Good for image text reading and image editing.",
            )
        ],
        selected_providers=[ProviderKind.GEMINI],
    )
    service = FakeAppSetupService(state=_make_state(needs_wizard=True), wizard_state=wizard_state)
    dialog = SetupWizardDialog(service, wizard_state)

    assert dialog.selected_providers() == [ProviderKind.GEMINI]
    _provider_checkbox(dialog, ProviderKind.GEMINI).setChecked(False)

    assert dialog.selected_providers() == []

    with patch.object(QMessageBox, "warning") as warning_mock:
        dialog._go_next()

    warning_mock.assert_called_once()
    assert dialog._page_index == 0


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
            default_model="gemini-3-pro-image-preview",
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


def test_connection_editor_dialog_uses_scrollable_form_layout():
    from PySide6.QtWidgets import QScrollArea
    from superqt import QCollapsible

    from context_aware_translation.ui.features.app_setup_view import ConnectionEditorDialog

    dialog = ConnectionEditorDialog()

    assert isinstance(dialog.form.advanced_section, QCollapsible)
    assert isinstance(dialog.scroll_area, QScrollArea)
    assert dialog.scroll_area.widget() is dialog.form
    assert dialog.scroll_area.widgetResizable() is True
    assert dialog.form.tabs.count() == 2
    assert dialog.width() >= 820
    assert dialog.height() >= 480
    assert dialog.maximumWidth() > dialog.width()
    assert dialog.maximumHeight() > dialog.height()


def test_connection_editor_dialog_tests_inside_dialog():
    from context_aware_translation.ui.features.app_setup_view import ConnectionEditorDialog

    seen: list[ConnectionDraft] = []
    dialog = ConnectionEditorDialog(
        test_callback=lambda draft: (
            seen.append(draft),
            ConnectionTestResult(
                connection_label=draft.display_name, supported_capabilities=[CapabilityCode.TRANSLATION]
            ),
        )[1]
    )
    dialog.form.display_name_edit.setText("Gemini")
    dialog.form.api_key_edit.setText("secret")

    with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Ok) as exec_mock:
        dialog._on_test()

    assert len(seen) == 1
    assert seen[0].display_name == "Gemini"
    exec_mock.assert_called_once()


def test_connection_editor_dialog_resets_token_usage_inside_dialog():
    from context_aware_translation.ui.features.app_setup_view import ConnectionEditorDialog

    summary = ConnectionSummary(
        connection_id="conn-gemini",
        display_name="Gemini",
        provider=ProviderKind.GEMINI,
        tokens_used=1200,
        input_tokens_used=900,
        output_tokens_used=300,
        cached_input_tokens_used=100,
        uncached_input_tokens_used=800,
    )
    dialog = ConnectionEditorDialog(
        draft=ConnectionDraft(display_name="Gemini", provider=ProviderKind.GEMINI),
        connection_id="conn-gemini",
        connection_summary=summary,
        reset_tokens_callback=lambda _cid: summary.model_copy(
            update={
                "tokens_used": 0,
                "input_tokens_used": 0,
                "output_tokens_used": 0,
                "cached_input_tokens_used": 0,
                "uncached_input_tokens_used": 0,
            }
        ),
    )

    assert dialog.form.tabs.tabText(1) == "Token Meter"
    assert dialog.total_used_label.text() == "1,200"
    dialog._on_reset_tokens()
    assert dialog.total_used_label.text() == "0"
    assert dialog.input_used_label.text() == "0"
