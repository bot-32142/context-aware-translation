from __future__ import annotations

import pytest

from context_aware_translation.application.contracts.app_setup import (
    WorkflowProfileDetail,
    WorkflowProfileKind,
    WorkflowStepId,
    WorkflowStepRoute,
)
from context_aware_translation.ui.features.workflow_profile_editor import ConnectionChoice, WorkflowProfileEditorDialog

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDialog, QScrollArea

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


def test_workflow_profile_editor_uses_scrollable_dialog_layout():
    profile = WorkflowProfileDetail(
        profile_id="profile:recommended",
        name="Recommended",
        kind=WorkflowProfileKind.SHARED,
        target_language="English",
        routes=[
            WorkflowStepRoute(
                step_id=WorkflowStepId.TRANSLATOR,
                step_label="Translator",
                connection_id="conn-gemini",
                connection_label="Gemini",
                model="gemini-3-flash-preview",
            )
        ],
    )
    dialog = WorkflowProfileEditorDialog(
        profile=profile,
        connection_choices=[
            ConnectionChoice(
                connection_id="conn-gemini",
                label="Gemini",
                default_model="gemini-3-flash-preview",
            )
        ],
        allow_name_edit=True,
    )

    assert dialog.findChildren(QScrollArea)
    assert not dialog.general_section.is_expanded()
    assert dialog.width() <= 1240
    assert dialog.routes_table.editTriggers() == dialog.routes_table.EditTrigger.NoEditTriggers
    assert dialog.routes_table.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert dialog.routes_table.columnWidth(1) >= 300
    assert dialog.routes_table.columnWidth(2) >= 250
    assert dialog.routes_table.columnCount() == 4
    assert dialog.routes_table.item(0, 0).text() == "Translator"
    assert dialog.routes_table.cellWidget(0, 3) is not None
    route_row = dialog._rows[0]
    assert route_row.connection_combo is not None
    assert route_row.connection_combo.minimumWidth() >= 250
    assert route_row.model_edit.minimumWidth() >= 220


def test_step_advanced_config_dialog_updates_route_config():
    from context_aware_translation.ui.features.workflow_profile_editor import StepAdvancedConfigDialog

    route = WorkflowStepRoute(
        step_id=WorkflowStepId.OCR,
        step_label="OCR",
        connection_id="conn-gemini",
        connection_label="Gemini",
        model="gemini-3-flash-preview",
        step_config={"ocr_dpi": 150, "strip_llm_artifacts": True},
    )

    dialog = StepAdvancedConfigDialog(route)
    dialog.ocr_dpi_spin.setValue(200)
    dialog.strip_artifacts_check.setChecked(False)

    updated = dialog.route()
    assert updated.step_config == {
        "ocr_dpi": 200,
        "strip_llm_artifacts": False,
    }


def test_workflow_profile_editor_only_shows_advanced_button_for_configurable_steps():
    from context_aware_translation.ui.features import workflow_profile_editor as editor_module

    profile = WorkflowProfileDetail(
        profile_id="profile:recommended",
        name="Recommended",
        kind=WorkflowProfileKind.SHARED,
        target_language="English",
        routes=[
            WorkflowStepRoute(
                step_id=WorkflowStepId.TRANSLATOR,
                step_label="Translator",
                connection_id="conn-openai",
                connection_label="OpenAI",
                model="gpt-4.1-mini",
            ),
            WorkflowStepRoute(
                step_id=WorkflowStepId.IMAGE_REEMBEDDING,
                step_label="Image reembedding",
                connection_id="conn-gemini",
                connection_label="Gemini",
                model="gemini-3.1-flash-image-preview",
            ),
        ],
    )
    dialog = WorkflowProfileEditorDialog(
        profile=profile,
        connection_choices=[
            ConnectionChoice(
                connection_id="conn-openai",
                label="OpenAI",
                default_model="gpt-4.1-mini",
                provider="openai",
                base_url="https://api.openai.com/v1",
            ),
            ConnectionChoice(
                connection_id="conn-gemini",
                label="Gemini",
                default_model="gemini-3.1-flash-image-preview",
                provider="gemini",
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            ),
        ],
        allow_name_edit=True,
    )

    opened: list[WorkflowStepId] = []

    class _FakeStepDialog:
        def __init__(self, route: WorkflowStepRoute, *_args, **_kwargs):
            opened.append(route.step_id)

        def exec(self):
            return QDialog.DialogCode.Rejected

    original = editor_module.StepAdvancedConfigDialog
    editor_module.StepAdvancedConfigDialog = _FakeStepDialog
    try:
        advanced_button = dialog.routes_table.cellWidget(0, 3)
        assert advanced_button is not None
        advanced_button.click()
    finally:
        editor_module.StepAdvancedConfigDialog = original

    assert opened == [WorkflowStepId.TRANSLATOR]
    assert dialog.routes_table.item(1, 3).text() == "—"


def test_workflow_profile_editor_infers_image_backend_from_connection():
    profile = WorkflowProfileDetail(
        profile_id="profile:recommended",
        name="Recommended",
        kind=WorkflowProfileKind.SHARED,
        target_language="English",
        routes=[
            WorkflowStepRoute(
                step_id=WorkflowStepId.IMAGE_REEMBEDDING,
                step_label="Image reembedding",
                connection_id="conn-openai",
                connection_label="OpenAI",
                model="gpt-image-1",
            )
        ],
    )
    dialog = WorkflowProfileEditorDialog(
        profile=profile,
        connection_choices=[
            ConnectionChoice(
                connection_id="conn-openai",
                label="OpenAI",
                default_model="gpt-image-1",
                provider="openai",
                base_url="https://api.openai.com/v1",
            )
        ],
        allow_name_edit=True,
    )

    built = dialog.profile()

    assert built.routes[0].step_config["backend"] == "openai"
    assert dialog.routes_table.item(0, 0).text() == "Image reembedding"
    assert dialog.routes_table.item(0, 3).text() == "—"
