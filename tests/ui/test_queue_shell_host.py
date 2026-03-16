from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from context_aware_translation.ui.shell_hosts.queue_shell_host import QueueShellHost

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


def test_queue_shell_host_loads_qml_chrome_and_tracks_scope() -> None:
    host = QueueShellHost()
    queue_widget = QLabel("queue")

    host.set_queue_widget(queue_widget)
    host.set_scope("proj-1", project_name="One Piece")

    root = host.chrome_host.rootObject()
    assert root is not None
    assert root.objectName() == "queueShellChrome"
    assert root.property("titleText") == "Queue"
    assert "One Piece" in root.property("subtitleText")
    assert host.current_content_key() == "queue"

    host.clear_scope()
    assert "all projects" in root.property("subtitleText")


def test_queue_shell_host_replacing_widget_cleans_up_old_content() -> None:
    host = QueueShellHost()
    old_widget = QLabel("old")
    old_widget.cleanup = MagicMock()  # type: ignore[attr-defined]
    new_widget = QLabel("new")

    host.set_queue_widget(old_widget)
    host.set_queue_widget(new_widget)

    old_widget.cleanup.assert_called_once()
