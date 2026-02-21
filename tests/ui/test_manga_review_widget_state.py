"""Regression tests for MangaReviewWidget detail-panel state handling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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


def _noop_init(self, *_args, **_kwargs):  # noqa: ANN001
    """No-op replacement for MangaReviewWidget.__init__."""


def _make_widget():
    from context_aware_translation.ui.views.manga_review_widget import MangaReviewWidget

    with patch.object(MangaReviewWidget, "__init__", _noop_init):
        widget = MangaReviewWidget(None, None)
    return widget


def _attach_control_mocks(widget) -> None:  # noqa: ANN001
    widget.manga_page_list = MagicMock()
    widget.manga_page_label = MagicMock()
    widget.manga_image_viewer = MagicMock()
    widget.manga_translation_text = MagicMock()
    widget.manga_prev_btn = MagicMock()
    widget.manga_next_btn = MagicMock()
    widget.manga_save_btn = MagicMock()


def test_reset_manga_detail_state_clears_image_and_disables_controls():
    widget = _make_widget()
    _attach_control_mocks(widget)

    widget._reset_manga_detail_state()

    widget.manga_page_label.setText.assert_called_once_with(widget.tr("No page selected"))
    widget.manga_image_viewer.clear_image.assert_called_once()
    widget.manga_translation_text.clear.assert_called_once()
    widget.manga_translation_text.setReadOnly.assert_called_once_with(True)
    widget.manga_prev_btn.setEnabled.assert_called_once_with(False)
    widget.manga_next_btn.setEnabled.assert_called_once_with(False)
    widget.manga_save_btn.setEnabled.assert_called_once_with(False)


def test_on_manga_page_selected_invalid_row_resets_detail_state():
    widget = _make_widget()
    _attach_control_mocks(widget)
    widget._manga_sources = []
    widget._reset_manga_detail_state = MagicMock()

    widget._on_manga_page_selected(-1)

    assert widget._manga_current_index == -1
    widget._reset_manga_detail_state.assert_called_once()


def test_on_manga_page_selected_without_image_or_chunk_clears_preview_and_disables_save():
    widget = _make_widget()
    _attach_control_mocks(widget)
    widget._manga_sources = [{"binary_content": None}]
    widget._manga_chunks = []
    widget._source_to_chunk = {}
    widget._manga_current_index = -1

    widget._on_manga_page_selected(0)

    assert widget._manga_current_index == 0
    widget.manga_image_viewer.clear_image.assert_called_once()
    widget.manga_translation_text.setReadOnly.assert_called_once_with(True)
    widget.manga_save_btn.setEnabled.assert_called_once_with(False)
    widget.manga_prev_btn.setEnabled.assert_called_once_with(False)
    widget.manga_next_btn.setEnabled.assert_called_once_with(False)
