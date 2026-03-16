from __future__ import annotations

import pytest

from context_aware_translation.ui.viewmodels.document_translation_pane import DocumentTranslationPaneViewModel

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


def test_document_translation_pane_viewmodel_tracks_toolbar_state():
    viewmodel = DocumentTranslationPaneViewModel()

    assert viewmodel.translate_label == "Translate"
    assert viewmodel.can_translate is False
    assert viewmodel.supports_batch is False

    viewmodel.apply_state(
        progress_text="Queued.",
        message_text="",
        polish_enabled=False,
        can_translate=True,
        supports_batch=True,
        can_batch=True,
    )

    assert viewmodel.progress_text == "Queued."
    assert viewmodel.polish_enabled is False
    assert viewmodel.can_translate is True
    assert viewmodel.supports_batch is True
    assert viewmodel.can_batch is True


def test_document_translation_pane_viewmodel_prefers_message_over_progress_when_present():
    viewmodel = DocumentTranslationPaneViewModel()

    viewmodel.apply_state(
        progress_text="Progress: 2/5 | Active task: task-42",
        message_text="Translation queued.",
        polish_enabled=True,
        can_translate=True,
        supports_batch=True,
        can_batch=True,
    )

    assert viewmodel.progress_text == "Translation queued."

    viewmodel.apply_state(
        progress_text="",
        message_text="Translation queued.",
        polish_enabled=True,
        can_translate=True,
        supports_batch=True,
        can_batch=True,
    )

    assert viewmodel.progress_text == "Translation queued."
