from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from functools import lru_cache

from opencc import OpenCC


@lru_cache(maxsize=1)
def _get_converter() -> OpenCC:
    """Return OpenCC converter for JP/CJK normalization.

    Uses built-in ``jp2s`` config from opencc package data.
    """
    return OpenCC("jp2s")


def _katakana_to_hiragana(text: str) -> str:
    """Convert katakana to hiragana (U+30A1..U+30F6 -> U+3041..U+3096)."""
    result = []
    for c in text:
        cp = ord(c)
        if 0x30A1 <= cp <= 0x30F6:
            result.append(chr(cp - 0x60))
        else:
            result.append(c)
    return "".join(result)


def _strip_diacritics(text: str) -> str:
    """Remove combining diacritical marks: e->e, n->n, u->u."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_for_matching(text: str) -> str:
    """Normalize text for fuzzy glossary key matching.

    Pipeline:
    1. NFKC: fullwidth->ASCII, compatibility chars
    2. OpenCC jp2s: JP shinjitai->simplified, Chinese trad->simplified
    3. Strip diacritics
    """
    text = unicodedata.normalize("NFKC", text)
    result: str = _get_converter().convert(text)
    result = _strip_diacritics(result)
    return result


def build_normalized_key_mapping(
    llm_keys: Iterable[str],
    expected_keys: set[str],
) -> dict[str, str]:
    """Build a mapping from expected keys to LLM keys using CJK normalization.

    For each expected key, tries exact match first, then falls back to
    normalized matching (CJK variants, fullwidth chars, diacritics).

    When multiple expected keys share the same normalized form (e.g.,
    ``résumé`` and ``resume``), normalized matching is skipped for those
    keys to avoid ambiguous mappings — only exact matches are accepted.

    Returns:
        Dict mapping expected_key -> llm_key for matched keys.
        Expected keys with no match are omitted.
    """
    llm_key_set = set(llm_keys)
    # Fast path: all exact matches
    if expected_keys <= llm_key_set:
        return {k: k for k in expected_keys}

    # Build normalized(llm_key) -> llm_key index
    norm_to_llm = {normalize_for_matching(k): k for k in llm_key_set}

    # Detect ambiguous normalized forms among expected keys
    from collections import Counter

    expected_norms = Counter(normalize_for_matching(k) for k in expected_keys)
    ambiguous_norms = {norm for norm, count in expected_norms.items() if count > 1}

    result: dict[str, str] = {}
    for expected in expected_keys:
        if expected in llm_key_set:
            result[expected] = expected
        elif normalize_for_matching(expected) not in ambiguous_norms:
            llm_key = norm_to_llm.get(normalize_for_matching(expected))
            if llm_key is not None:
                result[expected] = llm_key

    return result
