from __future__ import annotations

import pytest

from context_aware_translation.core.models import (
    Term,
    description_index,
    ordered_description_entries,
    ordered_description_values,
)


def _make_term(*, votes: int = 1, term_type: str = "other") -> Term:
    return Term(
        key="test_key",
        descriptions={},
        occurrence={},
        votes=votes,
        total_api_calls=1,
        term_type=term_type,
    )


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


def test_term_defaults_term_type_to_other() -> None:
    term = _make_term()

    assert term.term_type == "other"


def test_term_without_chunk_evidence_does_not_backfill_other_votes() -> None:
    term = Term(
        key="imported_only",
        descriptions={"imported": "stable import"},
        occurrence={},
        votes=3,
        total_api_calls=3,
        term_type="other",
        term_type_votes={},
    )

    assert term.term_type == "other"
    assert term.term_type_votes == {}


@pytest.mark.parametrize(
    ("raw_term_type", "expected_term_type"),
    [
        (None, "other"),
        ("", "other"),
        ("unknown", "other"),
        ("character_name", "other"),
        ("organization-name", "other"),
        (" CHARACTER ", "character"),
    ],
)
def test_term_normalizes_term_type_values(raw_term_type: str | None, expected_term_type: str) -> None:
    term = _make_term(term_type=raw_term_type)

    assert term.term_type == expected_term_type


def test_description_index_recognizes_imported_and_numeric_keys() -> None:
    assert description_index("imported") == -1
    assert description_index("5") == 5
    assert description_index(7) == 7
    assert description_index("legacy_key") is None


def test_ordered_description_helpers_ignore_unrecognized_keys_and_future_entries() -> None:
    descriptions = {
        "legacy_key": "legacy desc",
        "12": "future desc",
        "imported": "imported desc",
        "5": "chunk 5 desc",
        "0": "chunk 0 desc",
    }

    assert ordered_description_entries(descriptions) == [
        ("imported", "imported desc"),
        ("0", "chunk 0 desc"),
        ("5", "chunk 5 desc"),
        ("12", "future desc"),
    ]
    assert ordered_description_values(descriptions, query_index=10) == [
        "imported desc",
        "chunk 0 desc",
        "chunk 5 desc",
    ]


def test_term_merge_prefers_summary_worthy_type_over_other() -> None:
    term = _make_term(votes=1, term_type="other")
    other = _make_term(votes=1, term_type="organization")

    term.merge(other)

    assert term.term_type == "organization"


def test_term_merge_prefers_higher_vote_summary_worthy_type() -> None:
    term = _make_term(votes=2, term_type="organization")
    other = _make_term(votes=5, term_type="character")

    term.merge(other)

    assert term.term_type == "character"


def test_term_merge_tie_breaks_character_over_organization() -> None:
    term = _make_term(votes=3, term_type="organization")
    other = _make_term(votes=3, term_type="character")

    term.merge(other)

    assert term.term_type == "character"


def test_term_merge_preserves_per_type_vote_totals_across_multiple_merges() -> None:
    term = _make_term(votes=2, term_type="character")

    term.merge(_make_term(votes=1, term_type="organization"))
    term.merge(_make_term(votes=1, term_type="organization"))

    assert term.term_type == "character"
    assert term.term_type_votes == {"character": 2, "organization": 2}


def test_term_merge_changes_type_once_competing_type_overtakes_total_votes() -> None:
    term = _make_term(votes=2, term_type="character")

    term.merge(_make_term(votes=1, term_type="organization"))
    term.merge(_make_term(votes=2, term_type="organization"))

    assert term.term_type == "organization"
    assert term.term_type_votes == {"character": 2, "organization": 3}


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
