from __future__ import annotations

import pytest

from context_aware_translation.ui.viewmodels.router import RouteStateViewModel

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel, QWidget

    from context_aware_translation.ui.shell_hosts import HybridDialogHost, HybridShellHost

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


class _CleanupWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.cleanup_calls = 0

    def cleanup(self) -> None:
        self.cleanup_calls += 1


def test_hybrid_shell_host_loads_qml_chrome_and_swaps_content_widgets():
    route_model = RouteStateViewModel()
    host = HybridShellHost(
        "BootstrapProbe.qml",
        orientation=Qt.Orientation.Horizontal,
        context_objects={"routeModel": route_model},
    )
    left = QLabel("left")
    right = QLabel("right")
    changed: list[str] = []
    host.current_content_changed.connect(changed.append)

    host.register_content("left", left)
    host.register_content("right", right)
    host.show_content("right")

    assert host.chrome_host.rootObject() is not None
    assert host.current_content_key() == "right"
    assert host.content_stack.currentWidget() is right
    assert host.content_widget("left") is left
    assert changed[-1] == "right"


def test_hybrid_shell_host_cleanup_calls_child_cleanup_hooks():
    host = HybridShellHost("BootstrapProbe.qml")
    child = _CleanupWidget()
    host.register_content("cleanup", child)

    host.cleanup()

    assert child.cleanup_calls == 1
    assert host.current_content_key() is None


def test_hybrid_dialog_host_replaces_body_widget():
    dialog = HybridDialogHost("BootstrapProbe.qml")
    first = QLabel("first")
    second = QLabel("second")

    dialog.set_body_widget(first)
    dialog.set_body_widget(second)

    assert dialog.chrome_host.rootObject() is not None
    assert dialog.body_widget is second
