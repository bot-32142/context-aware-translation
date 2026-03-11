from __future__ import annotations

import pytest

from context_aware_translation.ui.viewmodels.document_export_pane import DocumentExportPaneViewModel

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


def test_document_export_pane_viewmodel_tracks_action_state_and_result():
    viewmodel = DocumentExportPaneViewModel()

    assert viewmodel.export_label == "Export This Document"
    assert viewmodel.can_export is False
    assert viewmodel.has_result is False

    viewmodel.apply_state(can_export=True, result_text="Export complete.")

    assert viewmodel.can_export is True
    assert viewmodel.has_result is True
    assert viewmodel.result_text == "Export complete."
