from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from context_aware_translation.ui.shell_hosts.project_shell_host import ProjectShellHost
from context_aware_translation.ui.viewmodels.router import ModalRoute, PrimaryRoute, RouteState

try:
    from PySide6.QtWidgets import QApplication, QLabel

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


def test_project_shell_host_loads_qml_chrome_and_switches_work_and_terms():
    host = ProjectShellHost()
    work = QLabel("work")
    terms = QLabel("terms")

    host.set_work_widget(work)
    host.set_terms_widget(terms)
    host.set_project_context("proj-1", "One Piece")

    root = host.chrome_host.rootObject()
    assert root is not None
    assert root.objectName() == "projectShellChrome"
    assert root.property("currentProjectName") == "One Piece"
    assert root.property("workSelected") is True
    assert host.current_content_key() == "work"

    host.show_terms_view()
    assert root.property("termsSelected") is True
    assert host.current_content_key() == "terms"


def test_project_shell_host_emits_secondary_actions_and_tracks_modal_state():
    host = ProjectShellHost()
    host.set_work_widget(QLabel("work"))
    host.set_terms_widget(QLabel("terms"))
    host.set_project_context("proj-1", "One Piece")

    queued: list[bool] = []
    settings: list[bool] = []
    backs: list[bool] = []
    host.queue_requested.connect(lambda: queued.append(True))
    host.project_settings_requested.connect(lambda: settings.append(True))
    host.back_requested.connect(lambda: backs.append(True))

    root = host.chrome_host.rootObject()
    assert root is not None
    root.queueRequested.emit()
    root.projectSettingsRequested.emit()
    root.backRequested.emit()

    assert queued == [True]
    assert settings == [True]
    assert backs == [True]
    assert host.viewmodel.modal_route == "project_settings"


def test_project_shell_host_replacing_work_widget_cleans_up_old_content() -> None:
    host = ProjectShellHost()
    old_work = QLabel("old work")
    old_work.cleanup = MagicMock()  # type: ignore[attr-defined]
    host.set_work_widget(old_work)

    new_work = QLabel("new work")
    host.set_work_widget(new_work)

    old_work.cleanup.assert_called_once()


def test_project_shell_host_modal_close_restores_previous_modal_route() -> None:
    host = ProjectShellHost()
    host.set_work_widget(QLabel("work"))
    host.set_terms_widget(QLabel("terms"))
    host.set_project_context("proj-1", "One Piece")

    host.present_project_settings()
    host.present_queue()
    host.dismiss_modal()

    assert host.viewmodel.route_state() == RouteState(
        primary=PrimaryRoute.WORK,
        project_id="proj-1",
        modal=ModalRoute.PROJECT_SETTINGS,
    )
