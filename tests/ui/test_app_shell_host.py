from __future__ import annotations

import pytest

from context_aware_translation.ui.shell_hosts.app_shell_host import AppShellHost

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


def test_app_shell_host_loads_qml_chrome_and_tracks_project_state():
    host = AppShellHost()
    projects = QLabel("projects")
    project = QLabel("project")

    host.set_projects_widget(projects)
    host.set_project_widget("project_1", project)
    host.show_project_view("project_1", "project-1", "One Piece")

    root = host.chrome_host.rootObject()
    assert root is not None
    assert root.objectName() == "appShellChrome"
    assert root.property("hasCurrentProject") is True
    assert root.property("surfaceTitle") == "One Piece"
    assert host.current_content_key() == "project_1"
    assert host.chrome_host.isHidden() is True

    host.show_projects_view()
    assert root.property("hasCurrentProject") is False
    assert root.property("surfaceTitle") == "Projects"
    assert host.current_content_key() == "projects"
    assert host.chrome_host.isHidden() is False


def test_app_shell_host_retranslate_updates_live_qml_labels():
    from context_aware_translation.ui import i18n

    app = QApplication.instance()
    assert app is not None

    host = AppShellHost()
    try:
        root = host.chrome_host.rootObject()
        assert root is not None

        assert i18n.load_translation(app, "en") is True
        host.retranslate()
        QApplication.processEvents()
        english_projects = root.property("projectsLabel")

        assert i18n.load_translation(app, "zh_CN") is True
        host.retranslate()
        QApplication.processEvents()
        localized_projects = root.property("projectsLabel")

        assert localized_projects != english_projects

        assert i18n.load_translation(app, "en") is True
        host.retranslate()
        QApplication.processEvents()
        assert root.property("projectsLabel") == english_projects
    finally:
        i18n.load_translation(app, "en")
        host.close()
        host.deleteLater()
        QApplication.processEvents()
