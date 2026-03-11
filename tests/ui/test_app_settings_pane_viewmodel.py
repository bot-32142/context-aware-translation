from __future__ import annotations

import pytest

from context_aware_translation.ui.viewmodels.app_settings_pane import AppSettingsPaneViewModel

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


def test_app_settings_pane_viewmodel_tracks_tabs_and_actions():
    viewmodel = AppSettingsPaneViewModel()

    viewmodel.apply_state(
        current_tab="profiles",
        action_buttons=[
            {"action": "add_profile", "label": "Add Profile", "enabled": True, "primary": True},
            {"action": "delete_profile", "label": "Delete", "enabled": False, "primary": False},
        ],
    )

    assert "shared workflow profiles" in viewmodel.tip_text
    assert viewmodel.connections_tab_label == "Connections"
    assert viewmodel.profiles_tab_label == "Workflow Profiles"
    assert viewmodel.current_tab == "profiles"
    assert viewmodel.showing_connections is False
    assert viewmodel.showing_profiles is True
    assert len(viewmodel.action_buttons) == 2
