from __future__ import annotations

import pytest

from context_aware_translation.ui.viewmodels.project_settings_dialog import ProjectSettingsDialogViewModel

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


def test_project_settings_dialog_viewmodel_tracks_labels_and_visibility():
    viewmodel = ProjectSettingsDialogViewModel()

    assert viewmodel.title == "Project Settings"
    assert "shared workflow profile" in viewmodel.subtitle
    assert viewmodel.is_presented is False

    viewmodel.present()
    assert viewmodel.is_presented is True

    viewmodel.dismiss()
    assert viewmodel.is_presented is False
