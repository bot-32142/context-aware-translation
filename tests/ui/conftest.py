from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication

    HAS_PYSIDE6 = True
except ImportError:  # pragma: no cover - environment dependent
    QApplication = None
    HAS_PYSIDE6 = False


@pytest.fixture(autouse=True, scope="session")
def _ui_qapplication():
    """Ensure all UI tests share a QApplication, not a bare QCoreApplication."""
    if not HAS_PYSIDE6:
        yield None
        return

    assert QApplication is not None
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
