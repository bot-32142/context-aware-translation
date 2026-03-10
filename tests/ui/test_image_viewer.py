"""Tests for ImageViewer zoom clamping behavior."""

import pytest

try:
    from PySide6.QtWidgets import QApplication

    HAS_PYSIDE6 = True
except ImportError:
    HAS_PYSIDE6 = False

pytestmark = pytest.mark.skipif(not HAS_PYSIDE6, reason="PySide6 not available")

# Minimal valid 1x1 PNG.
_VALID_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff"
    b"?\x00\x05\xfe\x02\xfe\r\xefF\xb8\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture(autouse=True, scope="module")
def _qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_zoom_respects_upper_and_lower_bounds():
    from context_aware_translation.ui.widgets.image_viewer import ImageViewer

    viewer = ImageViewer()
    viewer.reset_zoom()

    viewer._zoom(1000.0)
    assert viewer._zoom_factor == pytest.approx(50.0)
    assert viewer.transform().m11() == pytest.approx(50.0)

    viewer._zoom(1e-6)
    assert viewer._zoom_factor == pytest.approx(0.05)
    assert viewer.transform().m11() == pytest.approx(0.05)


def test_set_image_invalid_data_clears_previous_pixmap():
    from context_aware_translation.ui.widgets.image_viewer import ImageViewer

    viewer = ImageViewer()
    viewer.set_image(_VALID_PNG)
    assert viewer.pixmap_item is not None

    viewer.set_image(b"not-an-image")
    assert viewer.pixmap_item is None


def test_deferred_auto_fit_remains_pending_until_post_layout_fit():
    from context_aware_translation.ui.widgets.image_viewer import ImageViewer

    viewer = ImageViewer()
    viewer.resize(400, 300)
    viewer.set_image(_VALID_PNG)

    assert viewer.pixmap_item is not None
    assert viewer._auto_fit_pending is True

    viewer._fit_pending_image()

    assert viewer._auto_fit_pending is False
