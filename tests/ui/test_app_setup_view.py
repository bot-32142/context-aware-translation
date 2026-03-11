from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from context_aware_translation.application.contracts.app_setup import (
    AppSetupState,
    ConnectionDraft,
    ConnectionStatus,
    ConnectionSummary,
    ConnectionTestResult,
    ProviderCard,
    SaveConnectionRequest,
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
            supported_capabilities=[CapabilityCode.TRANSLATION],
            message=UserMessage(severity=UserMessageSeverity.INFO, text="Connection accepted."),
        ),
    )
    view = AppSetupView(service)
    view.connections_table.selectRow(0)
    view.profiles_table.selectRow(0)

    with (
        patch("context_aware_translation.ui.features.app_setup_view.ConnectionEditorDialog", _FakeConnectionDialog),
        patch(
            "context_aware_translation.ui.features.app_setup_view.WorkflowProfileEditorDialog", _FakeProfileEditorDialog
        ),
        patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
    ):
        view._on_add_connection()
        view.connections_table.selectRow(0)
        view._on_duplicate_connection()
        view.connections_table.selectRow(0)
        view._on_delete_connection()
        view.profiles_table.selectRow(0)
        view._edit_profile()
        view.profiles_table.selectRow(0)
        view._on_duplicate_profile()
        view.profiles_table.selectRow(0)
        view._on_delete_profile()

    assert any(call[0] == "save_connection" for call in service.calls)
    assert any(call[0] == "duplicate_connection" for call in service.calls)
    assert any(call[0] == "delete_connection" for call in service.calls)
    assert any(call[0] == "save_workflow_profile" for call in service.calls)
    assert any(call[0] == "duplicate_workflow_profile" for call in service.calls)
    assert any(call[0] == "delete_workflow_profile" for call in service.calls)


def test_app_setup_view_opens_connection_dialog_on_double_click():
    from context_aware_translation.ui.features.app_setup_view import AppSetupView

    service = FakeAppSetupService(state=_make_state())
    view = AppSetupView(service)
    opened: list[bool] = []
    try:
        with patch.object(view, "_edit_connection", side_effect=lambda *_args: opened.append(True)):
            view.connections_table.selectRow(0)
            view._on_connection_double_clicked(0, 0)
        assert opened == [True]
    finally:
        view.deleteLater()


def test_app_setup_view_disables_managed_connection_edits():
    from context_aware_translation.ui.features.app_setup_view import AppSetupView

    managed_state = _make_state()
    managed_state = managed_state.model_copy(
        update={"connections": [managed_state.connections[0].model_copy(update={"is_managed": True})]}
    )
    service = FakeAppSetupService(state=managed_state)
    view = AppSetupView(service)
    opened: list[bool] = []
    try:
        view.connections_table.selectRow(0)
        assert view.duplicate_connection_button.isEnabled()
        assert not view.delete_connection_button.isEnabled()
        with patch.object(view, "_edit_connection", side_effect=lambda *_args: opened.append(True)):
            view._on_connection_double_clicked(0, 0)
        assert opened == []
    finally:
        view.deleteLater()


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
    )
    service = FakeAppSetupService(state=_make_state(), wizard_state=wizard_state, preview_state=preview_state)
    dialog = SetupWizardDialog(service, wizard_state)

    _provider_checkbox(dialog, ProviderKind.GEMINI).setChecked(True)
    _provider_api_key_edit(dialog, ProviderKind.GEMINI).setText("secret")
    dialog._go_next()

    assert dialog._page_index == 1
    assert any(call[0] == "preview_setup_wizard" for call in service.calls)
    assert dialog._profile_name_edit is not None
    dialog._profile_name_edit.setText("Team Default")

    dialog._finish()

    assert any(call[0] == "run_setup_wizard" for call in service.calls)
    run_request = next(call[1] for call in service.calls if call[0] == "run_setup_wizard")
    assert run_request.profile_name == "Team Default"


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
    )
    service = FakeAppSetupService(state=_make_state(), wizard_state=wizard_state, preview_state=preview_state)
    dialog = SetupWizardDialog(service, wizard_state)

    _provider_checkbox(dialog, ProviderKind.GEMINI).setChecked(True)
    _provider_api_key_edit(dialog, ProviderKind.GEMINI).setText("secret")
    dialog._go_next()
    assert dialog._page_index == 1

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


def test_app_setup_view_refreshes_wizard_prompt_state():
    from context_aware_translation.ui.features.app_setup_view import AppSetupView

    service = FakeAppSetupService(state=_make_state(needs_wizard=True))
    view = AppSetupView(service)

    assert view.run_wizard_button.text() == view.tr("Run Setup Wizard")
    assert view.connections_table.rowCount() == 0
    assert view.profiles_table.rowCount() == 0


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


def test_connection_editor_dialog_uses_scrollable_form_layout():
    from superqt import QCollapsible

    from context_aware_translation.ui.features.app_setup_view import ConnectionEditorDialog

    dialog = ConnectionEditorDialog()

    assert isinstance(dialog.form.advanced_section, QCollapsible)
    assert dialog.form.tabs.count() == 2
    assert 620 <= dialog.width() <= 860
    assert dialog.height() <= 360


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

    dialog._on_test()

    assert len(seen) == 1
    assert seen[0].display_name == "Gemini"


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
