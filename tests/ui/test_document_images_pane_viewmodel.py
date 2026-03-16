from __future__ import annotations

import pytest

from context_aware_translation.ui.viewmodels.document_images_pane import DocumentImagesPaneViewModel

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


def test_document_images_pane_viewmodel_tracks_chrome_state():
    viewmodel = DocumentImagesPaneViewModel()

    assert viewmodel.tip_text
    assert viewmodel.run_selected_enabled is False
    assert viewmodel.progress_visible is False

    viewmodel.apply_state(
        blocker_text="Needs app setup.",
        has_blocker=True,
        blocker_action_label="Open App Setup",
        has_blocker_action=True,
        page_label="Image 2 of 5",
        page_input_text="2",
        status_text="Reembedded",
        status_color="#15803d",
        toggle_label="Show Text",
        toggle_enabled=True,
        first_enabled=True,
        previous_enabled=True,
        next_enabled=True,
        last_enabled=True,
        go_enabled=True,
        run_selected_enabled=True,
        run_pending_enabled=True,
        force_all_enabled=False,
        message_text="Queued.",
        progress_visible=True,
        progress_text="apply",
        progress_can_cancel=True,
        empty_visible=False,
    )

    assert viewmodel.has_blocker is True
    assert viewmodel.blocker_action_label == "Open App Setup"
    assert viewmodel.page_label == "Image 2 of 5"
    assert viewmodel.page_input_text == "2"
    assert viewmodel.status_text == "Reembedded"
    assert viewmodel.status_color == "#15803d"
    assert viewmodel.toggle_label == "Show Text"
    assert viewmodel.toggle_enabled is True
    assert viewmodel.run_selected_enabled is True
    assert viewmodel.run_pending_enabled is True
    assert viewmodel.force_all_enabled is False
    assert viewmodel.has_message is True
    assert viewmodel.message_text == "Queued."
    assert viewmodel.progress_visible is True
    assert viewmodel.progress_text == "apply"
    assert viewmodel.progress_can_cancel is True
    assert viewmodel.empty_visible is False
