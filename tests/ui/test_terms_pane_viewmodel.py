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
    assert viewmodel.show_add is True
    assert viewmodel.can_translate is False
    assert viewmodel.can_review is False

    viewmodel.apply_toolbar_state(
        can_build=False,
        can_translate=True,
        can_review=True,
        can_filter=True,
        can_add=True,
        can_import=True,
        can_export=False,
        build_tooltip="",
        translate_tooltip="Ready to translate untranslated terms.",
        review_tooltip="Ready to review extracted terms.",
        filter_tooltip="Filter out unlikely glossary entries.",
        add_tooltip="Add or update shared project terms.",
        import_tooltip="Import terms from a glossary file.",
        export_tooltip="",
    )

    assert viewmodel.can_add is True
    assert viewmodel.can_translate is True
    assert viewmodel.can_review is True
    assert viewmodel.can_filter is True
    assert viewmodel.can_import is True
    assert viewmodel.can_export is False
    assert viewmodel.add_tooltip == "Add or update shared project terms."
    assert viewmodel.translate_tooltip == "Ready to translate untranslated terms."
    assert viewmodel.review_tooltip == "Ready to review extracted terms."


def test_terms_pane_viewmodel_tracks_document_scope_labels_and_build_state():
    viewmodel = TermsPaneViewModel(document_scope=True, embedded=True)

    assert "current document" in viewmodel.tip_text
    assert viewmodel.show_title is False
    assert viewmodel.show_build is True
    assert viewmodel.show_add is False
    assert viewmodel.show_import is False
    assert viewmodel.show_export is False

    viewmodel.apply_toolbar_state(
        can_build=True,
        can_translate=True,
        can_review=False,
        can_filter=True,
        can_add=False,
        can_import=False,
        can_export=False,
        build_tooltip="Build terms from the current document.",
        translate_tooltip="Translate document-scoped terms.",
        review_tooltip="Review is unavailable until translation finishes.",
        filter_tooltip="Filter rare terms in this document.",
        add_tooltip="",
        import_tooltip="",
        export_tooltip="",
    )

    assert viewmodel.can_build is True
    assert viewmodel.can_translate is True
    assert viewmodel.can_review is False
    assert viewmodel.build_tooltip == "Build terms from the current document."
    assert viewmodel.translate_tooltip == "Translate document-scoped terms."
