from __future__ import annotations

import jellyfish


def string_similarity(name_a: str, name_b: str) -> float:
    """
    Compute string similarity between two names using Jaro-Winkler similarity.

    Uses both forward and reversed string comparisons to handle both prefix
    and suffix matches effectively, taking the maximum score.
    """
    if not name_a or not name_b:
        return 0.0

    # Normalize to lowercase for comparison
    a_lower = name_a.lower().strip()
    b_lower = name_b.lower().strip()

    # Exact match (case-insensitive)
    if a_lower == b_lower:
        return 1.0

    # Use Jaro-Winkler similarity in both directions
    # Forward comparison (handles prefix matches well)
    forward_score = jellyfish.jaro_winkler_similarity(a_lower, b_lower)

    # Reversed comparison (handles suffix matches well)
    # Reversing both strings converts suffix matches to prefix matches
    reversed_score = jellyfish.jaro_winkler_similarity(a_lower[::-1], b_lower[::-1])

    # Take the maximum to handle both prefix and suffix cases
    return max(forward_score, reversed_score)
