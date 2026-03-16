from __future__ import annotations

import pytest

from context_aware_translation.ui.viewmodels.app_shell import AppShellViewModel
from context_aware_translation.ui.viewmodels.router import ModalRoute, PrimaryRoute

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


def test_app_shell_viewmodel_tracks_active_project_and_surface_title():
    viewmodel = AppShellViewModel()

    assert viewmodel.has_current_project is False
    assert viewmodel.surface_title == "Projects"

    viewmodel.set_active_project("proj-1", "One Piece", primary=PrimaryRoute.WORK)

    assert viewmodel.has_current_project is True
    assert viewmodel.current_project_name == "One Piece"
    assert viewmodel.surface_title == "One Piece"
    assert viewmodel.primary_route == "work"

    viewmodel.show_projects_home()

    assert viewmodel.has_current_project is False
    assert viewmodel.surface_title == "Projects"
    assert viewmodel.primary_route == "projects"


def test_app_shell_viewmodel_tracks_modal_routes():
    viewmodel = AppShellViewModel()
    viewmodel.set_active_project("proj-1", "One Piece")

    viewmodel.present_app_settings()
    assert viewmodel.modal_route == ModalRoute.APP_SETTINGS.value

    viewmodel.present_queue(project_id="proj-1")
    assert viewmodel.modal_route == ModalRoute.QUEUE.value

    viewmodel.dismiss_modal()
    assert viewmodel.modal_route == ModalRoute.APP_SETTINGS.value

    viewmodel.dismiss_modal()
    assert viewmodel.modal_route == ""
