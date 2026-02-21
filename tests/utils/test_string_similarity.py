from __future__ import annotations

from context_aware_translation.utils.string_similarity import string_similarity


def teststring_similarity():
    """Test string similarity computation."""
    # Exact match
    assert string_similarity("John Smith", "John Smith") == 1.0
    assert string_similarity("John Smith", "john smith") == 1.0  # Case insensitive

    # Similar names
    score1 = string_similarity("John Smith", "John Smith Jr.")
    assert 0.7 < score1 < 1.0  # Should be high similarity

    score2 = string_similarity("John Smith", "John Smyth")
    assert 0.7 < score2 < 1.0  # Typo should still be similar

    # Different names
    score3 = string_similarity("John Smith", "Alice Brown")
    assert score3 < 0.5  # Should be low similarity

    # Non-Latin strings (JP): compound vs base term should still be highly similar
    # This guards the glossary clustering assumption used for "オーク肉" vs "オーク".
    score4 = string_similarity("オーク肉", "オーク")
    assert 0.7 < score4 < 1.0

    # Suffix match case (JP): substring at end should be highly similar
    # This tests the reversed string approach for suffix matches.
    score5 = string_similarity("クレセント・ヴォーパル", "ヴォーパル")
    assert 0.7 < score5 < 1.0  # Should be high similarity (reversed comparison)

    # Empty strings
    assert string_similarity("", "John") == 0.0
    assert string_similarity("John", "") == 0.0
