from __future__ import annotations

import pytest

from context_aware_translation.ui.viewmodels.terms_pane import TermsPaneViewModel

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


def test_terms_pane_viewmodel_tracks_labels_and_toolbar_state():
    viewmodel = TermsPaneViewModel(document_scope=False, embedded=False)

    assert viewmodel.title == "Terms"
    assert "shared across the project" in viewmodel.tip_text
    assert viewmodel.show_title is True
    assert viewmodel.show_build is False
    assert viewmodel.can_translate is False
    assert viewmodel.can_review is False

    viewmodel.apply_toolbar_state(
        can_build=False,
        can_translate=True,
        can_review=True,
        can_filter=True,
        can_import=True,
        can_export=False,
    )

    assert viewmodel.can_translate is True
    assert viewmodel.can_review is True
    assert viewmodel.can_filter is True
    assert viewmodel.can_import is True
    assert viewmodel.can_export is False


def test_terms_pane_viewmodel_tracks_document_scope_labels_and_build_state():
    viewmodel = TermsPaneViewModel(document_scope=True, embedded=True)

    assert "current document" in viewmodel.tip_text
    assert viewmodel.show_title is False
    assert viewmodel.show_build is True
    assert viewmodel.show_import is False
    assert viewmodel.show_export is False

    viewmodel.apply_toolbar_state(
        can_build=True,
        can_translate=True,
        can_review=False,
        can_filter=True,
        can_import=False,
        can_export=False,
    )

    assert viewmodel.can_build is True
    assert viewmodel.can_translate is True
    assert viewmodel.can_review is False
