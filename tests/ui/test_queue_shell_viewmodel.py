from __future__ import annotations

import pytest

from context_aware_translation.ui.viewmodels.queue_shell import QueueShellViewModel

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


def test_queue_shell_viewmodel_tracks_scope_and_subtitle() -> None:
    viewmodel = QueueShellViewModel()

    assert viewmodel.title == "Queue"
    assert viewmodel.has_project_scope is False
    assert "all projects" in viewmodel.subtitle

    viewmodel.set_scope("proj-1", project_name="One Piece")

    assert viewmodel.has_project_scope is True
    assert "One Piece" in viewmodel.subtitle

    viewmodel.clear_scope()

    assert viewmodel.has_project_scope is False
    assert "all projects" in viewmodel.subtitle
