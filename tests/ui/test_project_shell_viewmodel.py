from __future__ import annotations

import pytest

from context_aware_translation.ui.viewmodels.project_shell import ProjectShellViewModel
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


def test_project_shell_viewmodel_tracks_primary_routes_and_project_context():
    viewmodel = ProjectShellViewModel()

    viewmodel.set_project_context("proj-1", "One Piece")
    assert viewmodel.current_project_name == "One Piece"
    assert viewmodel.surface_title == "One Piece"
    assert viewmodel.work_selected is True
    assert viewmodel.terms_selected is False
    assert viewmodel.primary_route == PrimaryRoute.WORK.value

    viewmodel.show_terms()
    assert viewmodel.work_selected is False
    assert viewmodel.terms_selected is True
    assert viewmodel.primary_route == PrimaryRoute.TERMS.value

    viewmodel.show_work()
    assert viewmodel.work_selected is True
    assert viewmodel.terms_selected is False
    assert viewmodel.primary_route == PrimaryRoute.WORK.value


def test_project_shell_viewmodel_tracks_secondary_modal_routes():
    viewmodel = ProjectShellViewModel()
    viewmodel.set_project_context("proj-1", "One Piece")

    viewmodel.present_project_settings()
    assert viewmodel.modal_route == ModalRoute.PROJECT_SETTINGS.value

    viewmodel.present_queue()
    assert viewmodel.modal_route == ModalRoute.QUEUE.value

    viewmodel.dismiss_modal()
    assert viewmodel.modal_route == ""
