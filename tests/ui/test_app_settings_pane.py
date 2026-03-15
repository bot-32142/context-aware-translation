from __future__ import annotations

from unittest.mock import patch

import pytest

from context_aware_translation.application.contracts.app_setup import (
    AppSetupState,
    ConnectionDraft,
    ConnectionStatus,
    ConnectionSummary,
    ConnectionTestResult,
    SaveConnectionRequest,
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
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget

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


class _FakeWizardDialog:
    def __init__(self, *args, **kwargs):
        pass

    def exec(self):
        return QDialog.DialogCode.Accepted


def test_app_settings_pane_renders_backend_state():
    from context_aware_translation.ui.features.app_settings_pane import AppSettingsPane

    service = FakeAppSetupService(state=_make_state())
    view = AppSettingsPane(service)

    root = view.chrome_host.rootObject()
    assert root is not None
    assert root.objectName() == "appSettingsPaneChrome"
    assert view.connections_table.rowCount() == 1
    assert view.profiles_table.rowCount() == 1
    assert view.viewmodel.current_tab == "connections"
    assert view.viewmodel.action_buttons[0]["label"] == "Open Setup Wizard"
    assert view.chrome_host.minimumHeight() >= int(root.property("implicitHeight"))


def test_app_settings_pane_switches_tabs_and_updates_actions():
    from context_aware_translation.ui.features.app_settings_pane import AppSettingsPane

    service = FakeAppSetupService(state=_make_state())
    view = AppSettingsPane(service)

    view._on_tab_requested("profiles")

    assert view.viewmodel.current_tab == "profiles"
    assert view.content_stack.currentWidget() is view.profiles_page
    assert view.viewmodel.action_buttons[0]["action"] == "add_profile"
    root = view.chrome_host.rootObject()
    assert root is not None
    assert view.chrome_host.minimumHeight() >= int(root.property("implicitHeight"))


def test_app_settings_pane_add_delete_test_and_edit_profile_calls_service():
    from context_aware_translation.ui.features.app_settings_pane import AppSettingsPane

    state = _make_state()
    service = FakeAppSetupService(
        state=state,
        test_result=ConnectionTestResult(
            connection_label="Gemini",
            supported_capabilities=[CapabilityCode.TRANSLATION],
            message=UserMessage(severity=UserMessageSeverity.INFO, text="Connection accepted."),
        ),
    )
    view = AppSettingsPane(service)
    view.connections_table.selectRow(0)
    view._on_tab_requested("profiles")
    view.profiles_table.selectRow(0)

    with (
        patch("context_aware_translation.ui.features.app_settings_pane.ConnectionEditorDialog", _FakeConnectionDialog),
        patch(
            "context_aware_translation.ui.features.app_settings_pane.WorkflowProfileEditorDialog",
            _FakeProfileEditorDialog,
        ),
        patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
    ):
        view._on_tab_requested("connections")
        view.connections_table.selectRow(0)
        view._on_add_connection()
        view.connections_table.selectRow(0)
        view._on_duplicate_connection()
        view.connections_table.selectRow(0)
        view._on_delete_connection()
        view._on_tab_requested("profiles")
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


def test_app_settings_pane_opens_connection_dialog_on_double_click():
    from context_aware_translation.ui.features.app_settings_pane import AppSettingsPane

    service = FakeAppSetupService(state=_make_state())
    view = AppSettingsPane(service)
    opened: list[bool] = []
    with patch.object(view, "_edit_connection", side_effect=lambda *_args: opened.append(True)):
        view.connections_table.selectRow(0)
        view._on_connection_double_clicked(0, 0)
    assert opened == [True]


def test_app_settings_pane_refreshes_wizard_prompt_state():
    from context_aware_translation.ui.features.app_settings_pane import AppSettingsPane

    service = FakeAppSetupService(state=_make_state(needs_wizard=True))
    view = AppSettingsPane(service)

    assert view.connections_table.rowCount() == 0
    assert view.profiles_table.rowCount() == 0
    assert view.viewmodel.action_buttons[0]["label"] == "Run Setup Wizard"


def test_app_settings_pane_runs_wizard_through_service():
    from context_aware_translation.ui.features.app_settings_pane import AppSettingsPane

    service = FakeAppSetupService(state=_make_state())
    view = AppSettingsPane(service)

    with patch("context_aware_translation.ui.features.app_settings_pane.SetupWizardDialog", _FakeWizardDialog):
        view._on_run_wizard()

    assert any(call[0] == "get_wizard_state" for call in service.calls)


def test_app_settings_pane_parents_child_dialogs_to_host_window():
    from context_aware_translation.ui.features.app_settings_pane import AppSettingsPane
    from context_aware_translation.ui.shell_hosts.app_settings_dialog_host import AppSettingsDialogHost

    class _CaptureConnectionDialog:
        parent_widget: QWidget | None = None

        def __init__(self, *args, parent=None, **kwargs):
            type(self).parent_widget = parent

        def exec(self):
            return QDialog.DialogCode.Rejected

    class _CaptureProfileDialog:
        parent_widget: QWidget | None = None

        def __init__(self, *args, parent=None, profile=None, **kwargs):
            type(self).parent_widget = parent

        def exec(self):
            return QDialog.DialogCode.Rejected

    class _CaptureWizardDialog:
        parent_widget: QWidget | None = None

        def __init__(self, *args, parent=None, **kwargs):
            type(self).parent_widget = parent

        def exec(self):
            return QDialog.DialogCode.Rejected

    service = FakeAppSetupService(state=_make_state())
    host = AppSettingsDialogHost()
    try:
        view = AppSettingsPane(service, parent=host)
        host.set_app_settings_widget(view)
        host.show()
        QApplication.processEvents()

        with (
            patch(
                "context_aware_translation.ui.features.app_settings_pane.ConnectionEditorDialog",
                _CaptureConnectionDialog,
            ),
            patch(
                "context_aware_translation.ui.features.app_settings_pane.WorkflowProfileEditorDialog",
                _CaptureProfileDialog,
            ),
            patch("context_aware_translation.ui.features.app_settings_pane.SetupWizardDialog", _CaptureWizardDialog),
        ):
            view.connections_table.selectRow(0)
            view._on_add_connection()
            view._on_run_wizard()
            view._on_tab_requested("profiles")
            view.profiles_table.selectRow(0)
            view._edit_profile()

        assert _CaptureConnectionDialog.parent_widget is host
        assert _CaptureWizardDialog.parent_widget is host
        assert _CaptureProfileDialog.parent_widget is host
    finally:
        host.close()
        host.deleteLater()
        QApplication.processEvents()
