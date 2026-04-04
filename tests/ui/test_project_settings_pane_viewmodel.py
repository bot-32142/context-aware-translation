from __future__ import annotations

from unittest.mock import patch

import pytest

from context_aware_translation.ui.viewmodels.project_settings_pane import ProjectSettingsPaneViewModel
from context_aware_translation.ui.viewmodels.work_home import WorkHomeViewModel

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


def test_project_settings_pane_viewmodel_tracks_project_content_and_messages():
    viewmodel = ProjectSettingsPaneViewModel()

    viewmodel.apply_state(
        project_name="One Piece",
        blocker_text="Open App Setup.",
        profile_options=[
            {"label": "Recommended", "detail": "Shared workflow profile", "selected": True},
            {"label": "Custom profile", "detail": "Project-specific overrides", "selected": False},
        ],
        custom_profile_text="Editing a project-specific profile based on Recommended.",
        show_custom_profile=False,
        show_open_app_setup=True,
        can_save=True,
    )

    assert viewmodel.title_text == "Setup for One Piece"
    assert "shared workflow profile" in viewmodel.tip_text
    assert viewmodel.workflow_profile_label == "Workflow profile"
    assert viewmodel.has_blocker is True
    assert viewmodel.blocker_text == "Open App Setup."
    assert viewmodel.has_profile_options is True
    assert len(viewmodel.profile_options) == 2
    assert viewmodel.show_open_app_setup is True
    assert viewmodel.can_save is True

    viewmodel.set_message("Project setup saved.", is_error=False)
    assert viewmodel.has_message is True
    assert viewmodel.message_kind == "success"

    viewmodel.set_message("Select a shared workflow profile first.", is_error=True)
    assert viewmodel.message_kind == "error"

    viewmodel.clear_message()
    assert viewmodel.has_message is False


def test_project_settings_pane_viewmodel_retranslate_refreshes_dynamic_profile_labels():
    viewmodel = ProjectSettingsPaneViewModel()
    viewmodel.apply_state(
        project_name="One Piece",
        blocker_text="",
        profile_options=[
            {"label": "Recommended", "detail": "Shared workflow profile", "selected": True},
        ],
        custom_profile_text="",
        show_custom_profile=False,
        show_open_app_setup=False,
        can_save=True,
    )

    notifications: list[str] = []
    viewmodel.content_changed.connect(lambda: notifications.append("content"))

    with patch("context_aware_translation.ui.viewmodels.project_settings_pane.QCoreApplication.translate") as translate:
        translate.side_effect = lambda _context, text: f"T:{text}"
        viewmodel.retranslate()

        assert viewmodel.title_text == "T:Setup for %1".replace("%1", "One Piece")
        assert viewmodel.profile_options == [
            {"label": "Recommended", "detail": "T:Shared workflow profile", "selected": True}
        ]

    assert notifications == ["content"]


def test_project_settings_pane_viewmodel_preserves_user_profile_names_on_retranslate():
    viewmodel = ProjectSettingsPaneViewModel()
    viewmodel.apply_state(
        project_name="One Piece",
        blocker_text="",
        profile_options=[
            {"label": "Save", "detail": "Shared workflow profile", "selected": True},
        ],
        custom_profile_text="",
        show_custom_profile=False,
        show_open_app_setup=False,
        can_save=True,
    )

    with patch("context_aware_translation.ui.viewmodels.project_settings_pane.QCoreApplication.translate") as translate:
        translate.side_effect = lambda _context, text: f"T:{text}"
        viewmodel.retranslate()

    assert viewmodel.profile_options == [{"label": "Save", "detail": "T:Shared workflow profile", "selected": True}]


def test_work_home_viewmodel_retranslate_refreshes_dynamic_content_labels():
    viewmodel = WorkHomeViewModel()
    viewmodel.set_import_state(
        summary="Ready",
        message="Imported",
        is_error=False,
        can_import=True,
        options=[("text", "Text files")],
        selected_import_type="text",
    )

    notifications: list[str] = []
    viewmodel.content_changed.connect(lambda: notifications.append("content"))

    with patch("context_aware_translation.ui.viewmodels.work_home.QCoreApplication.translate") as translate:
        translate.side_effect = lambda _context, text: f"T:{text}"
        viewmodel.retranslate()

        assert viewmodel.tip_text.startswith("T:Import documents here")
        assert viewmodel.remove_hard_wraps_label == "T:Remove hard wraps"
        assert viewmodel.remove_hard_wraps_warning.startswith("T:Warning: experimental")
        assert viewmodel.import_type_options == [{"documentType": "text", "label": "T:Text files", "selected": True}]

    assert notifications == ["content"]
