"""Tests for glossary table header explanations."""

from unittest.mock import MagicMock

import pytest

try:
    from PySide6.QtCore import Qt
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


@pytest.fixture
def model():
    from context_aware_translation.ui.models.term_model import TermTableModel

    db = MagicMock()
    db.list_terms.return_value = []
    db.search_terms.return_value = []
    return TermTableModel(db)


def test_header_tooltips_exist_for_all_glossary_columns(model):
    tooltips = [model.headerData(col, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole) for col in range(8)]
    assert all(isinstance(text, str) and text.strip() for text in tooltips)


def test_description_header_tooltip_explains_prior_context_window(model):
    from context_aware_translation.ui.models.term_model import COL_DESCRIPTION

    tooltip = model.headerData(COL_DESCRIPTION, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole)
    assert "only context summaries ending at or before the current chunk are sent" in tooltip


def test_similarity_mechanism_is_explained_in_headers(model):
    from context_aware_translation.ui.models.term_model import COL_TERM, COL_TRANSLATION

    term_tip = model.headerData(COL_TERM, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole)
    translation_tip = model.headerData(COL_TRANSLATION, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole)
    assert "string-similarity" in term_tip
    assert "up to 3 most similar" in translation_tip
    assert "similar untranslated terms" in translation_tip


def test_votes_header_tooltip_explains_llm_recognition_count(model):
    from context_aware_translation.ui.models.term_model import COL_VOTES

    votes_tip = model.headerData(COL_VOTES, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole)
    assert "LLM recognized this as a term" in votes_tip


def test_set_sort_supports_ignored_and_reviewed_columns(model):
    """Sorting is done via a stable sort stack. Verify stack is maintained."""
    from context_aware_translation.ui.models.term_model import COL_IGNORED, COL_OCCURRENCES, COL_REVIEWED

    model.set_sort(COL_OCCURRENCES, descending=False)
    assert model._sort_stack[0] == (COL_OCCURRENCES, False)

    model.set_sort(COL_IGNORED, descending=True)
    assert model._sort_stack[0] == (COL_IGNORED, True)
    # Previous sort is still in the stack
    assert (COL_OCCURRENCES, False) in model._sort_stack

    model.set_sort(COL_REVIEWED, descending=False)
    assert model._sort_stack[0] == (COL_REVIEWED, False)
    assert len(model._sort_stack) == 3
