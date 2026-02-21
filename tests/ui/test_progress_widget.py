"""Tests for ProgressWidget behavior."""

import pytest

try:
    from PySide6.QtWidgets import QApplication

    HAS_PYSIDE6 = True
except ImportError:
    HAS_PYSIDE6 = False

pytestmark = pytest.mark.skipif(not HAS_PYSIDE6, reason="PySide6 not available")


@pytest.fixture(autouse=True, scope="module")
def _qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_reset_restores_determinate_progress_mode():
    from context_aware_translation.ui.widgets.progress_widget import ProgressWidget

    widget = ProgressWidget()
    widget.progress_bar.setMaximum(0)  # Indeterminate mode
    widget.progress_bar.setValue(42)

    widget.reset()

    assert widget.progress_bar.minimum() == 0
    assert widget.progress_bar.maximum() == 100
    assert widget.progress_bar.value() == 0
