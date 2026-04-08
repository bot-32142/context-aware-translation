"""Tests for shared EPUB inline marker utilities."""

from __future__ import annotations

import pytest

from context_aware_translation.documents.epub_support.inline_markers import (
    extract_inline_markers,
    is_inline_marker_token,
    ruby_pair_count,
    strict_inline_markers,
    validate_inline_marker_fragment_sanity,
    validate_inline_marker_sanity,
)


def test_extract_inline_markers_returns_known_tokens_in_order() -> None:
    text = "A \ue000⟪literal token opener\ue000⟫ ⟪em:0⟫x⟪/em:0⟫ ⟪RUBY:1⟫y⟪/RUBY:1⟫⟪BR:2⟫"
    assert extract_inline_markers(text) == [
        "em:0",
        "/em:0",
        "RUBY:1",
        "/RUBY:1",
        "BR:2",
    ]


def test_extract_inline_markers_ignores_unknown_tokens() -> None:
    text = "⟪UNKNOWN⟫x⟪em:0⟫y⟪/em:0⟫"
    assert extract_inline_markers(text) == ["em:0", "/em:0"]
    assert is_inline_marker_token("UNKNOWN") is False


def test_extract_inline_markers_can_include_unknown_tokens() -> None:
    text = "⟪UNKNOWN⟫x⟪em:0⟫y⟪/em:0⟫"
    assert extract_inline_markers(text, include_unknown=True) == ["UNKNOWN", "em:0", "/em:0"]


def test_extract_inline_markers_accepts_fullwidth_delimiters_for_known_tokens() -> None:
    text = "A 《a:0》x《/a:0》 and 〈RUBY:1〉y〈/RUBY:1〉 plus ＜BR:2＞"
    assert extract_inline_markers(text) == ["a:0", "/a:0", "RUBY:1", "/RUBY:1", "BR:2"]


def test_validate_inline_marker_sanity_accepts_balanced_ruby() -> None:
    tokens = ["RUBY:0", "/RUBY:0", "em:1", "/em:1", "BR:2"]
    validate_inline_marker_sanity(tokens)


def test_validate_inline_marker_sanity_rejects_unclosed_ruby() -> None:
    with pytest.raises(ValueError, match="unclosed ruby marker"):
        validate_inline_marker_sanity(["RUBY:0", "em:1", "/em:1"])


def test_validate_inline_marker_sanity_rejects_unopened_ruby_close() -> None:
    with pytest.raises(ValueError, match="mismatched ruby marker"):
        validate_inline_marker_sanity(["/RUBY:0"])


def test_validate_inline_marker_fragment_sanity_accepts_edge_fragments() -> None:
    validate_inline_marker_fragment_sanity(["span:8", "i:8/0"])
    validate_inline_marker_fragment_sanity(["/i:8/0", "/span:8", "BR:9", "span:10", "i:10/0"])


def test_validate_inline_marker_fragment_sanity_rejects_invalid_interior_nesting() -> None:
    with pytest.raises(ValueError, match="mismatched strict marker"):
        validate_inline_marker_fragment_sanity(["span:0", "/a:0"])


def test_ruby_pair_count_counts_open_markers() -> None:
    tokens = ["RUBY:0", "/RUBY:0", "RUBY:9", "/RUBY:9", "em:1", "/em:1"]
    assert ruby_pair_count(tokens) == 2


def test_strict_inline_markers_drop_lenient_style_wrappers() -> None:
    tokens = ["em:0", "/em:0", "strong:1", "/strong:1", "RUBY:2", "/RUBY:2", "BR:3"]
    assert strict_inline_markers(tokens) == []


def test_strict_inline_markers_keep_metadata_sensitive_wrappers() -> None:
    tokens = ["a:0", "/a:0", "abbr:1", "/abbr:1", "em:2", "/em:2"]
    assert strict_inline_markers(tokens) == ["a:0", "/a:0", "abbr:1", "/abbr:1"]


def test_strict_inline_markers_handle_nested_lenient_inside_strict() -> None:
    tokens = ["a:0", "em:0/0", "/em:0/0", "/a:0"]
    assert strict_inline_markers(tokens) == ["a:0", "/a:0"]
