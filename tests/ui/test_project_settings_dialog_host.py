from __future__ import annotations

import pytest

from context_aware_translation.ui.shell_hosts.project_settings_dialog_host import ProjectSettingsDialogHost

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


def test_project_settings_dialog_host_loads_qml_chrome_and_wraps_body_widget():
    host = ProjectSettingsDialogHost()
    try:
        body = QLabel("project-setup")
        host.set_project_settings_widget(body)

        root = host.chrome_host.rootObject()
        assert root is not None
        assert root.objectName() == "projectSettingsDialogChrome"
        assert host.body_widget is body
        assert host.viewmodel.title == "Project Settings"
    finally:
        host.close()
        host.deleteLater()
        QApplication.processEvents()


def test_project_settings_dialog_host_present_and_qml_close_update_dialog_state():
    host = ProjectSettingsDialogHost()
    try:
        close_calls: list[bool] = []
        host.close_requested.connect(lambda: close_calls.append(True))

        host.present()
        assert host.viewmodel.is_presented is True

        root = host.chrome_host.rootObject()
        assert root is not None
        root.closeRequested.emit()

        assert close_calls == [True]
        assert host.viewmodel.is_presented is False
    finally:
        host.close()
        host.deleteLater()
        QApplication.processEvents()
