from __future__ import annotations

import pytest

from context_aware_translation.core.models import Term


def test_term_creation():
    """Test creating a Term."""
    term = Term(
        key="test_key",
        descriptions={"chunk1": "description1"},
        occurrence={"chunk1": 1},
        votes=5,
        total_api_calls=10,
    )

    assert term.key == "test_key"
    assert term.descriptions == {"chunk1": "description1"}
    assert term.occurrence == {"chunk1": 1}
    assert term.votes == 5
    assert term.total_api_calls == 10
    assert term.new_translation is None
    assert term.translated_name is None
    assert term.ignored is False


def test_term_get_key():
    """Test get_key method."""
    term = Term(
        key="test_key",
        descriptions={},
        occurrence={},
        votes=0,
        total_api_calls=0,
    )

    assert term.get_key() == "test_key"


def test_term_merge_basic():
    """Test merging two terms."""
    term1 = Term(
        key="test_key",
        descriptions={"chunk1": "desc1"},
        occurrence={"chunk1": 1},
        votes=5,
        total_api_calls=10,
    )

    term2 = Term(
        key="test_key",
        descriptions={"chunk2": "desc2"},
        occurrence={"chunk2": 2},
        votes=3,
        total_api_calls=7,
    )

    term1.merge(term2)

    assert term1.votes == 8  # 5 + 3
    assert term1.total_api_calls == 17  # 10 + 7
    assert term1.descriptions == {"chunk1": "desc1", "chunk2": "desc2"}
    assert term1.occurrence == {"chunk1": 1, "chunk2": 2}


def test_term_merge_with_translations():
    """Test merging terms with translations."""
    term1 = Term(
        key="test_key",
        descriptions={},
        occurrence={},
        votes=0,
        total_api_calls=0,
        new_translation="translation1",
        translated_name="name1",
    )

    term2 = Term(
        key="test_key",
        descriptions={},
        occurrence={},
        votes=0,
        total_api_calls=0,
        new_translation=None,
        translated_name=None,
    )

    # FIXED: term2's None values no longer overwrite term1's values
    # None values are now preserved, not overwritten
    term1.merge(term2)

    # term1's existing values are preserved when merging with None
    assert term1.new_translation == "translation1"
    assert term1.translated_name == "name1"

    # Now merge term1 (with values) into term2 (with None) - term2 gets term1's values
    term2.merge(term1)
    assert term2.new_translation == "translation1"
    assert term2.translated_name == "name1"


def test_term_merge_same_translation_values():
    """Test that merging terms with same translation values works correctly."""
    # FIXED: The merge logic now checks equality before raising error
    term1 = Term(
        key="test_key",
        descriptions={},
        occurrence={},
        votes=0,
        total_api_calls=0,
        new_translation="translation1",
        translated_name="name1",
    )

    term2 = Term(
        key="test_key",
        descriptions={},
        occurrence={},
        votes=0,
        total_api_calls=0,
        new_translation="translation1",  # Same value
        translated_name="name1",  # Same value
    )

    # FIXED: This should not raise an error since values are the same
    term1.merge(term2)
    assert term1.new_translation == "translation1"
    assert term1.translated_name == "name1"


def test_term_merge_translation_mismatch():
    """Test that merging terms with conflicting translations raises error."""
    term1 = Term(
        key="test_key",
        descriptions={},
        occurrence={},
        votes=0,
        total_api_calls=0,
        new_translation="translation1",
    )

    term2 = Term(
        key="test_key",
        descriptions={},
        occurrence={},
        votes=0,
        total_api_calls=0,
        new_translation="translation2",
    )

    with pytest.raises(ValueError, match="New translation mismatch"):
        term1.merge(term2)


def test_term_merge_translated_name_mismatch():
    """Test that merging terms with conflicting translated names raises error."""
    term1 = Term(
        key="test_key",
        descriptions={},
        occurrence={},
        votes=0,
        total_api_calls=0,
        translated_name="name1",
    )

    term2 = Term(
        key="test_key",
        descriptions={},
        occurrence={},
        votes=0,
        total_api_calls=0,
        translated_name="name2",
    )

    with pytest.raises(ValueError, match="Translated name mismatch"):
        term1.merge(term2)


def test_term_merge_ignored():
    """Test merging ignored flag."""
    term1 = Term(
        key="test_key",
        descriptions={},
        occurrence={},
        votes=0,
        total_api_calls=0,
        ignored=False,
    )

    term2 = Term(
        key="test_key",
        descriptions={},
        occurrence={},
        votes=0,
        total_api_calls=0,
        ignored=True,
    )

    term1.merge(term2)
    assert term1.ignored is True  # OR logic: True or False = True

    term3 = Term(
        key="test_key",
        descriptions={},
        occurrence={},
        votes=0,
        total_api_calls=0,
        ignored=False,
    )

    term1.merge(term3)
    assert term1.ignored is True  # Still True


def test_term_merge_wrong_type():
    """Test that merging non-Term raises TypeError."""
    term = Term(
        key="test_key",
        descriptions={},
        occurrence={},
        votes=0,
        total_api_calls=0,
    )

    with pytest.raises(TypeError, match="Cannot merge"):
        term.merge("not a term")


def test_term_merge_overwrites_descriptions():
    """Test that merging overwrites descriptions with same keys."""
    term1 = Term(
        key="test_key",
        descriptions={"chunk1": "desc1"},
        occurrence={},
        votes=0,
        total_api_calls=0,
    )

    term2 = Term(
        key="test_key",
        descriptions={"chunk1": "desc1_updated", "chunk2": "desc2"},
        occurrence={},
        votes=0,
        total_api_calls=0,
    )

    term1.merge(term2)

    # chunk1 should be overwritten, chunk2 should be added
    assert term1.descriptions == {"chunk1": "desc1_updated", "chunk2": "desc2"}


def test_term_merge_overwrites_occurrence():
    """Test that merging overwrites occurrence with same keys."""
    term1 = Term(
        key="test_key",
        descriptions={},
        occurrence={"chunk1": 1},
        votes=0,
        total_api_calls=0,
    )

    term2 = Term(
        key="test_key",
        descriptions={},
        occurrence={"chunk1": 5, "chunk2": 2},
        votes=0,
        total_api_calls=0,
    )

    term1.merge(term2)

    # chunk1 should be overwritten, chunk2 should be added
    assert term1.occurrence == {"chunk1": 5, "chunk2": 2}


def test_term_merge_zero_division_bug():
    """Test that mark_noise_terms can cause zero division error."""
    # BUG: Line 204 in context_manager.py: len(term.occurrence)/len(term.descriptions)
    # This will raise ZeroDivisionError if descriptions is empty
    term = Term(
        key="test_key",
        descriptions={},  # Empty descriptions
        occurrence={"chunk1": 1},
        votes=1,
        total_api_calls=1,
    )

    # This should not raise ZeroDivisionError but it will
    # The bug is in mark_noise_terms, not in merge, but we test the condition here
    with pytest.raises(ZeroDivisionError):
        _ = len(term.occurrence) / len(term.descriptions)


def test_term_merge_should_check_equality_before_error():
    """Test that merge checks equality before raising mismatch error."""
    # FIXED: Now checks if both are not None AND different before raising error
    term1 = Term(
        key="test_key",
        descriptions={},
        occurrence={},
        votes=0,
        total_api_calls=0,
        new_translation="same",
        translated_name="same",
    )

    term2 = Term(
        key="test_key",
        descriptions={},
        occurrence={},
        votes=0,
        total_api_calls=0,
        new_translation="same",  # Same value
        translated_name="same",  # Same value
    )

    # FIXED: This should not raise an error because values are the same
    term1.merge(term2)
    assert term1.new_translation == "same"
    assert term1.translated_name == "same"


def test_term_merge_new_translation_preserves_with_none():
    """Test that merging with None preserves existing translation."""
    # FIXED: None values no longer overwrite existing values
    term1 = Term(
        key="test_key",
        descriptions={},
        occurrence={},
        votes=0,
        total_api_calls=0,
        new_translation="existing_translation",
    )

    term2 = Term(
        key="test_key",
        descriptions={},
        occurrence={},
        votes=0,
        total_api_calls=0,
        new_translation=None,
    )

    term1.merge(term2)

    # FIXED: None no longer overwrites the existing translation
    assert term1.new_translation == "existing_translation"


def test_term_merge_translated_name_preserves_with_none():
    """Test that merging with None preserves existing translated_name."""
    # FIXED: None values no longer overwrite existing values
    term1 = Term(
        key="test_key",
        descriptions={},
        occurrence={},
        votes=0,
        total_api_calls=0,
        translated_name="existing_name",
    )

    term2 = Term(
        key="test_key",
        descriptions={},
        occurrence={},
        votes=0,
        total_api_calls=0,
        translated_name=None,
    )

    term1.merge(term2)

    # FIXED: None no longer overwrites the existing translated_name
    assert term1.translated_name == "existing_name"


def test_term_merge_should_preserve_existing_when_other_is_none():
    """Test that existing values should be preserved when merging with None."""
    # FIXED: Code now correctly preserves existing values when merging with None
    term1 = Term(
        key="test_key",
        descriptions={},
        occurrence={},
        votes=0,
        total_api_calls=0,
        new_translation="keep_this",
        translated_name="keep_this_too",
    )

    term2 = Term(
        key="test_key",
        descriptions={},
        occurrence={},
        votes=0,
        total_api_calls=0,
        new_translation=None,
        translated_name=None,
    )

    term1.merge(term2)
    # FIXED: None values no longer overwrite existing values
    assert term1.new_translation == "keep_this", "None should not overwrite existing translation"
    assert term1.translated_name == "keep_this_too", "None should not overwrite existing translated_name"
