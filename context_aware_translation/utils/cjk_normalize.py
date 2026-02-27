from __future__ import annotations

import json
import os
import unicodedata
from collections.abc import Iterable
from functools import lru_cache

from opencc import OpenCC


def _ensure_jp2s_config() -> None:
    """Generate jp2s OpenCC config if it doesn't exist.

    The opencc-python-reimplemented package ships JPVariants.txt (Traditional->JP)
    but no jp2s config. We generate:
    - JPVariantsRev.txt: reversed mapping (JP->Traditional)
    - jp2s.json: config chaining JP->Traditional->Simplified
    """
    opencc_file = __import__("opencc").__file__
    assert opencc_file is not None, "opencc package __file__ is None"
    pkg_dir = os.path.dirname(os.path.abspath(opencc_file))
    config_dir = os.path.join(pkg_dir, "config")
    dict_dir = os.path.join(pkg_dir, "dictionary")

    jp2s_path = os.path.join(config_dir, "jp2s.json")
    if os.path.exists(jp2s_path):
        return

    # Generate reversed JP dictionary
    jp_rev_path = os.path.join(dict_dir, "JPVariantsRev.txt")
    if not os.path.exists(jp_rev_path):
        jp_path = os.path.join(dict_dir, "JPVariants.txt")
        with open(jp_path) as f:
            lines = f.readlines()
        reversed_lines = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) == 2:
                reversed_lines.append(f"{parts[1]}\t{parts[0]}")
        with open(jp_rev_path, "w") as f:
            f.write("\n".join(sorted(reversed_lines)) + "\n")

    # Generate jp2s config (JP shinjitai -> Traditional -> Simplified)
    config = {
        "name": "Japanese Shinjitai + Traditional to Simplified Chinese",
        "segmentation": {
            "type": "mmseg",
            "dict": {"type": "txt", "file": "TSPhrases.txt"},
        },
        "conversion_chain": [
            {"dict": {"type": "txt", "file": "JPVariantsRev.txt"}},
            {
                "dict": {
                    "type": "group",
                    "dicts": [
                        {"type": "txt", "file": "TSPhrases.txt"},
                        {"type": "txt", "file": "TSCharacters.txt"},
                    ],
                }
            },
        ],
    }
    with open(jp2s_path, "w") as f:
        json.dump(config, f, indent=2)


@lru_cache(maxsize=1)
def _get_converter() -> OpenCC:
    _ensure_jp2s_config()
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
