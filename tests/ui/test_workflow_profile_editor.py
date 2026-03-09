from __future__ import annotations

import pytest

from context_aware_translation.application.contracts.app_setup import (
    WorkflowProfileDetail,
    WorkflowProfileKind,
    WorkflowStepId,
    WorkflowStepRoute,
)
from context_aware_translation.application.contracts.common import PresetCode
from context_aware_translation.ui.features.workflow_profile_editor import ConnectionChoice, WorkflowProfileEditorDialog

try:
    from PySide6.QtWidgets import QApplication, QScrollArea

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
        preset=PresetCode.BALANCED,
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
    assert dialog.width() <= 750
