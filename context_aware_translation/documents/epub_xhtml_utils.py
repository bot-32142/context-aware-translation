"""XHTML text extraction and injection utilities for EPUB documents.

Uses xml.etree.ElementTree (stdlib) to parse XHTML content from EPUB chapters,
extract text from block-level elements, and inject translated text back into
the exact same text slots while preserving DOM structure.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as _ET
from collections.abc import Iterator
from dataclasses import dataclass

import defusedxml.ElementTree as DefusedET

from context_aware_translation.documents.epub_support.inline_markers import (
    BR_RE as _MERGED_BR_RE,
)
from context_aware_translation.documents.epub_support.inline_markers import (
    LENIENT_INLINE_STYLE_TAGS as _LENIENT_INLINE_STYLE_TAGS,
)
from context_aware_translation.documents.epub_support.inline_markers import (
    MERGED_ESCAPE_PREFIX as _MERGED_ESCAPE_PREFIX,
)
from context_aware_translation.documents.epub_support.inline_markers import (
    MERGED_TOKEN_CLOSE as _MERGED_TOKEN_CLOSE,
)
from context_aware_translation.documents.epub_support.inline_markers import (
    MERGED_TOKEN_OPEN as _MERGED_TOKEN_OPEN,
)
from context_aware_translation.documents.epub_support.inline_markers import (
    RUBY_CLOSE_RE as _MERGED_RUBY_CLOSE_RE,
)
from context_aware_translation.documents.epub_support.inline_markers import (
    RUBY_OPEN_RE as _MERGED_RUBY_OPEN_RE,
)
from context_aware_translation.documents.epub_support.inline_markers import (
    extract_inline_markers,
    validate_inline_marker_sanity,
)
from context_aware_translation.documents.epub_support.inline_markers import (
    parse_inline_close as _parse_inline_close_token,
)
from context_aware_translation.documents.epub_support.inline_markers import (
    parse_inline_open as _parse_inline_open_token,
)
from context_aware_translation.documents.epub_support.xml_utils import (
    normalize_xml_header_for_utf8,
    preserve_outer_whitespace,
)
from context_aware_translation.utils.compression_marker import decode_compressed_line

# Register XHTML namespace to avoid ns0: prefixes in serialized output
_ET.register_namespace("", "http://www.w3.org/1999/xhtml")

logger = logging.getLogger(__name__)

BLOCK_TAGS = frozenset(
    {
        "p",
        "title",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "blockquote",
        "div",
        "pre",
        "address",
        "article",
        "aside",
        "section",
        "main",
        "summary",
        "legend",
        "label",
        "option",
        "textarea",
        "td",
        "th",
        "caption",
        "figcaption",
        "dt",
        "dd",
        "text",
    }
)
TRANSLATABLE_ATTR_NAMES = frozenset({"alt", "title", "aria-label", "aria-description"})
HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_RUBY_ANNOTATION_TAGS = frozenset({"rt", "rp", "rtc"})
_RUBY_BASE_WRAPPER_TAGS = frozenset({"rb"})
_ALT_INLINE_MARKER_RE = re.compile(r"[《〈＜]([^《》〈〉＜＞]+)[》〉＞]")
_INLINE_TOKEN_FALLBACK_RE = re.compile(r"⟪[^⟪⟫]*⟫")
_VALID_INLINE_TAG_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9._-]*$")
_INFERABLE_STYLE_INLINE_TAGS = _LENIENT_INLINE_STYLE_TAGS


@dataclass(frozen=True)
class _MergedAnchor:
    node: _ET.Element
    slot_kind: str
    text: str


@dataclass(frozen=True)
class _MergedInlinePlan:
    merged_text: str
    tokens: tuple[str, ...]
    anchors: tuple[_MergedAnchor, ...]


class InlineMergeParseError(ValueError):
    """Raised when merged-inline translation tokens cannot be safely parsed."""

    def __init__(
        self,
        message: str,
        *,
        block_tag: str,
        original_excerpt: str = "",
        translated_excerpt: str = "",
        position: int | None = None,
    ) -> None:
        details = [message, f"block={block_tag}"]
        if position is not None:
            details.append(f"pos={position}")
        if original_excerpt:
            details.append(f"original={original_excerpt!r}")
        if translated_excerpt:
            details.append(f"translated={translated_excerpt!r}")
        super().__init__(" | ".join(details))
        self.block_tag = block_tag
        self.original_excerpt = original_excerpt
        self.translated_excerpt = translated_excerpt
        self.position = position


def _local_tag(tag: str) -> str:
    """Strip namespace from tag: '{http://...}p' -> 'p'."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _local_attr(attr_name: str) -> str:
    if "}" in attr_name:
        return attr_name.split("}", 1)[1]
    return attr_name


def _iter_block_slot_roots(elem: _ET.Element) -> Iterator[tuple[_ET.Element, bool]]:
    """Yield block roots with whether descendant block recursion should be skipped."""
    local = _local_tag(elem.tag)
    child_blocks = [child for child in elem if _local_tag(child.tag) in BLOCK_TAGS]

    if local in BLOCK_TAGS:
        if child_blocks:
            # Translate this container's own slots, but avoid recursing into
            # descendant block elements here (they are yielded separately).
            yield (elem, True)
            # Recurse through all descendants so nested block nodes wrapped by
            # non-block containers are still yielded as roots.
            for child in elem:
                yield from _iter_block_slot_roots(child)
            return
        yield (elem, False)
        return

    for child in elem:
        yield from _iter_block_slot_roots(child)


def _collect_ruby_text(ruby_elem: _ET.Element, *, strip_annotations: bool = False) -> str:
    """Merge <ruby> base text and <rt> annotation into a single string.

    Example: <ruby>泥掘り<rt>マッドディグ</rt></ruby>  →  "泥掘り(マッドディグ)"

    Also handles the <rb> variant:
        <ruby><rb>泥掘り</rb><rt>マッドディグ</rt></ruby>  →  "泥掘り(マッドディグ)"
    """
    base = ruby_elem.text or ""
    rt_text = ""
    for child in ruby_elem:
        tag = _local_tag(child.tag)
        if tag == "rb" and not base.strip():
            base = child.text or ""
        elif tag == "rt":
            rt_text = child.text or ""
            break
    if strip_annotations:
        return base
    if rt_text.strip():
        return f"{base}({rt_text})"
    return base


def _child_path(path: str, child_index: int) -> str:
    return f"{path}/{child_index}" if path else str(child_index)


def _escape_merged_text(text: str) -> str:
    escaped = text.replace(_MERGED_ESCAPE_PREFIX, _MERGED_ESCAPE_PREFIX * 2)
    escaped = escaped.replace(_MERGED_TOKEN_OPEN, _MERGED_ESCAPE_PREFIX + _MERGED_TOKEN_OPEN)
    escaped = escaped.replace(_MERGED_TOKEN_CLOSE, _MERGED_ESCAPE_PREFIX + _MERGED_TOKEN_CLOSE)
    return escaped


def _token_text(token: str) -> str:
    return f"{_MERGED_TOKEN_OPEN}{token}{_MERGED_TOKEN_CLOSE}"


def _is_known_inline_token(token: str) -> bool:
    return bool(
        _parse_inline_open_token(token)
        or _parse_inline_close_token(token)
        or _MERGED_BR_RE.match(token)
        or _MERGED_RUBY_OPEN_RE.match(token)
        or _MERGED_RUBY_CLOSE_RE.match(token)
    )


def _normalize_alt_inline_marker_delimiters(text: str) -> str:
    """Normalize known marker tokens wrapped in 《》/〈〉/＜＞ to canonical ⟪⟫."""

    def _replace(match: re.Match[str]) -> str:
        token = match.group(1).strip()
        if not _is_known_inline_token(token):
            return match.group(0)
        return _token_text(token)

    return _ALT_INLINE_MARKER_RE.sub(_replace, text)


def _decode_merged_escapes(text: str) -> str:
    out: list[str] = []
    pos = 0
    while pos < len(text):
        ch = text[pos]
        if ch == _MERGED_ESCAPE_PREFIX:
            if pos + 1 < len(text):
                out.append(text[pos + 1])
                pos += 2
                continue
            pos += 1
            continue
        out.append(ch)
        pos += 1
    return "".join(out)


def _plain_text_from_marker_string(value: str, *, block_tag: str, original_merged: str) -> str:
    normalized = _normalize_alt_inline_marker_delimiters(value)
    try:
        tokens, segments = _scan_merged_translation(
            normalized,
            block_tag=block_tag,
            original_merged=original_merged,
        )
        plain_parts: list[str] = [segments[0]]
        for token, segment in zip(tokens, segments[1:], strict=True):
            if not _is_known_inline_token(token):
                plain_parts.append(_token_text(token))
            plain_parts.append(segment)
        return "".join(plain_parts)
    except InlineMergeParseError:
        decoded = _decode_merged_escapes(normalized)

        def _replace(match: re.Match[str]) -> str:
            token = match.group(0)[1:-1]
            return "" if _is_known_inline_token(token) else match.group(0)

        return _INLINE_TOKEN_FALLBACK_RE.sub(_replace, decoded)


def _qualified_inline_tag(node: _ET.Element, tag_name: str) -> str:
    local = tag_name if _VALID_INLINE_TAG_RE.match(tag_name) else "span"
    if "}" in node.tag:
        namespace = node.tag.split("}", 1)[0][1:]
        return f"{{{namespace}}}{local}"
    return local


def _append_inline_text(parent: _ET.Element, text: str) -> None:
    if not text:
        return
    if len(parent):
        last = parent[-1]
        last.tail = (last.tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def _nearest_render_parent(stack: list[_ET.Element | None]) -> _ET.Element | None:
    for candidate in reversed(stack):
        if candidate is not None:
            return candidate
    return None


def _set_text_slot_from_inline_markers_source_truth(
    node: _ET.Element,
    value: str,
    *,
    strip_ruby_annotations: bool = False,
) -> None:
    normalized = _normalize_alt_inline_marker_delimiters(value)
    try:
        tokens, segments = _scan_merged_translation(
            normalized,
            block_tag=_local_tag(node.tag),
            original_merged=value,
        )
    except InlineMergeParseError:
        node.text = _plain_text_from_marker_string(value, block_tag=_local_tag(node.tag), original_merged=value)
        return
    try:
        validate_inline_marker_sanity(tokens)
    except ValueError:
        node.text = _plain_text_from_marker_string(value, block_tag=_local_tag(node.tag), original_merged=value)
        return

    # This renderer is only safe for empty inline containers.
    if list(node):
        node.text = _plain_text_from_marker_string(value, block_tag=_local_tag(node.tag), original_merged=value)
        return

    node.text = ""
    stack: list[_ET.Element | None] = [node]
    _append_inline_text(node, segments[0])

    for token, seg in zip(tokens, segments[1:], strict=True):
        inline_open = _parse_inline_open_token(token)
        if inline_open:
            tag_name, _path = inline_open
            parent = _nearest_render_parent(stack)
            if parent is None:
                stack.append(None)
                continue
            if tag_name in _INFERABLE_STYLE_INLINE_TAGS:
                child = _ET.Element(_qualified_inline_tag(node, tag_name))
                parent.append(child)
                stack.append(child)
                _append_inline_text(child, seg)
            else:
                # Metadata-bearing/unknown wrappers are dropped; keep text payload.
                stack.append(None)
                _append_inline_text(parent, seg)
            continue

        if _parse_inline_close_token(token):
            if len(stack) > 1:
                stack.pop()
            parent = _nearest_render_parent(stack)
            if parent is not None:
                _append_inline_text(parent, seg)
            continue

        if _MERGED_BR_RE.match(token):
            parent = _nearest_render_parent(stack)
            if parent is None:
                continue
            br = _ET.Element(_qualified_inline_tag(node, "br"))
            parent.append(br)
            _append_inline_text(parent, seg)
            continue

        if _MERGED_RUBY_OPEN_RE.match(token):
            parent = _nearest_render_parent(stack)
            if parent is None:
                continue
            ruby = _ET.Element(_qualified_inline_tag(node, "ruby"))
            parent.append(ruby)
            _set_ruby_text(ruby, seg, strip_annotations=strip_ruby_annotations)
            continue

        if _MERGED_RUBY_CLOSE_RE.match(token):
            parent = _nearest_render_parent(stack)
            if parent is not None:
                _append_inline_text(parent, seg)
            continue

        # RUBY/unknown markers: ignore token, keep payload text.
        parent = _nearest_render_parent(stack)
        if parent is not None:
            _append_inline_text(parent, seg)


def _iter_translatable_attrs(
    elem: _ET.Element,
    *,
    skip_block_descendants: bool = False,
) -> Iterator[tuple[_ET.Element, str, str | None, str]]:
    for attr_name, attr_value in elem.attrib.items():
        if _local_attr(attr_name) in TRANSLATABLE_ATTR_NAMES and attr_value.strip():
            yield (elem, "attr", attr_name, attr_value)

    for child in elem:
        child_local = _local_tag(child.tag)
        if child_local in _RUBY_ANNOTATION_TAGS:
            continue
        child_is_block = child_local in BLOCK_TAGS
        if not (skip_block_descendants and child_is_block):
            yield from _iter_translatable_attrs(child, skip_block_descendants=skip_block_descendants)


def _iter_translatable_slots(
    elem: _ET.Element,
    *,
    skip_block_descendants: bool = False,
    strip_ruby_annotations: bool = False,
) -> Iterator[tuple[_ET.Element, str, str | None, str]]:
    """Yield translatable slots (text/tail/attribute) in document order."""
    text = elem.text
    if text is not None and text.strip():
        yield (elem, "text", None, text)

    for attr_name, attr_value in elem.attrib.items():
        if _local_attr(attr_name) in TRANSLATABLE_ATTR_NAMES and attr_value.strip():
            yield (elem, "attr", attr_name, attr_value)

    for child in elem:
        child_local = _local_tag(child.tag)
        if child_local == "ruby":
            # Merge base text + <rt> annotation into one slot so that ruby
            # annotations don't fragment sentences into extra translation blocks.
            combined = _collect_ruby_text(child, strip_annotations=strip_ruby_annotations)
            if combined.strip():
                yield (child, "ruby", None, combined)
            tail = child.tail
            if tail is not None and tail.strip():
                yield (child, "tail", None, tail)
            continue
        if child_local in _RUBY_ANNOTATION_TAGS:
            continue
        child_is_block = child_local in BLOCK_TAGS
        if not (skip_block_descendants and child_is_block):
            yield from _iter_translatable_slots(
                child,
                skip_block_descendants=skip_block_descendants,
                strip_ruby_annotations=strip_ruby_annotations,
            )
        tail = child.tail
        if tail is not None and tail.strip():
            yield (child, "tail", None, tail)


_RUBY_SPLIT_RE = re.compile(r"^(?P<base>.*?)(?:\((?P<rt_ascii>[^)]+)\)|（(?P<rt_full>[^）]+)）)$")
_EMPTY_TRAILING_BRACKET_PAIRS: tuple[tuple[str, str], ...] = (
    ("(", ")"),
    ("（", "）"),
    ("[", "]"),
    ("［", "］"),
    ("{", "}"),
    ("｛", "｝"),
    ("【", "】"),
    ("〈", "〉"),
    ("《", "》"),
    ("「", "」"),
    ("『", "』"),
    ("〔", "〕"),
    ("〖", "〗"),
    ("〘", "〙"),
    ("〚", "〛"),
    ("⟨", "⟩"),
    ("⟪", "⟫"),
    ("⟬", "⟭"),
    ("⟮", "⟯"),
)


def _strip_trailing_empty_bracket_pairs(text: str) -> str:
    """Drop empty trailing bracket shells like ()/（）/《》 left by some readers."""
    result = text.rstrip()
    while result:
        removed = False
        for open_char, close_char in _EMPTY_TRAILING_BRACKET_PAIRS:
            if not result.endswith(close_char):
                continue
            close_start = len(result) - len(close_char)
            open_end = close_start
            while open_end > 0 and result[open_end - 1].isspace():
                open_end -= 1
            open_start = open_end - len(open_char)
            if open_start < 0 or result[open_start:open_end] != open_char:
                continue
            result = result[:open_start].rstrip()
            removed = True
            break
        if not removed:
            break
    return result


def _has_descendant_block(elem: _ET.Element) -> bool:
    for child in elem:
        child_local = _local_tag(child.tag)
        if child_local in BLOCK_TAGS:
            return True
        if _has_descendant_block(child):
            return True
    return False


def _has_non_whitespace_inline_text(elem: _ET.Element, *, strip_ruby_annotations: bool = False) -> bool:
    text = elem.text
    if text is not None and text.strip():
        return True

    for child in elem:
        child_local = _local_tag(child.tag)
        if child_local in _RUBY_ANNOTATION_TAGS:
            continue
        if child_local == "ruby" and _collect_ruby_text(child, strip_annotations=strip_ruby_annotations).strip():
            return True
        if _has_non_whitespace_inline_text(child, strip_ruby_annotations=strip_ruby_annotations):
            return True
        tail = child.tail
        if tail is not None and tail.strip():
            return True

    return False


def _is_merge_inline_candidate(
    block: _ET.Element,
    *,
    skip_block_descendants: bool,
    strip_ruby_annotations: bool = False,
) -> bool:
    if skip_block_descendants:
        return False
    if _local_tag(block.tag) == "pre":
        return False
    if _has_descendant_block(block):
        return False

    # Merge only when it reduces multi-slot inline fragmentation to one line.
    # If block content already maps to a single text slot, keep it plain.
    content_slots = [
        (node, slot_kind, text)
        for node, slot_kind, _attr_name, text in _iter_translatable_slots(
            block,
            skip_block_descendants=False,
            strip_ruby_annotations=strip_ruby_annotations,
        )
        if slot_kind != "attr"
    ]
    if len(content_slots) <= 1:
        return False

    for child in block:
        child_local = _local_tag(child.tag)
        if child_local in _RUBY_ANNOTATION_TAGS:
            continue
        if child_local in BLOCK_TAGS:
            return False

        if child_local == "br":
            return True
        if child_local == "ruby":
            if _collect_ruby_text(child, strip_annotations=strip_ruby_annotations).strip():
                return True
        elif _has_non_whitespace_inline_text(child, strip_ruby_annotations=strip_ruby_annotations):
            return True
        tail = child.tail
        if tail is not None and tail.strip():
            return True

    return False


def _build_merged_inline_plan(block: _ET.Element, *, strip_ruby_annotations: bool = False) -> _MergedInlinePlan:
    tokens: list[str] = []
    anchors: list[_MergedAnchor] = []
    parts: list[str] = []

    def append_token(token: str) -> None:
        tokens.append(token)
        parts.append(_token_text(token))

    def append_anchor(node: _ET.Element, slot_kind: str, text: str | None) -> None:
        anchor_text = text or ""
        anchors.append(_MergedAnchor(node=node, slot_kind=slot_kind, text=anchor_text))
        parts.append(_escape_merged_text(anchor_text))

    def walk(elem: _ET.Element, path: str) -> None:
        for idx, child in enumerate(elem):
            child_local = _local_tag(child.tag)
            child_path = _child_path(path, idx)

            if child_local in _RUBY_ANNOTATION_TAGS:
                continue

            if child_local == "ruby":
                append_token(f"RUBY:{child_path}")
                append_anchor(child, "ruby", _collect_ruby_text(child, strip_annotations=strip_ruby_annotations))
                append_token(f"/RUBY:{child_path}")
                append_anchor(child, "tail", child.tail)
                continue

            if child_local == "br":
                append_token(f"BR:{child_path}")
                append_anchor(child, "tail", child.tail)
                continue

            inline_tag = child_local.lower()
            append_token(f"{inline_tag}:{child_path}")
            append_anchor(child, "text", child.text)
            walk(child, child_path)
            append_token(f"/{inline_tag}:{child_path}")
            append_anchor(child, "tail", child.tail)

    append_anchor(block, "text", block.text)
    walk(block, "")

    if len(anchors) != len(tokens) + 1:  # pragma: no cover - internal safety guard
        raise RuntimeError("Invalid merged-inline plan shape")

    return _MergedInlinePlan(
        merged_text="".join(parts),
        tokens=tuple(tokens),
        anchors=tuple(anchors),
    )


def _scan_merged_translation(
    value: str,
    *,
    block_tag: str,
    original_merged: str,
) -> tuple[list[str], list[str]]:
    value = _normalize_alt_inline_marker_delimiters(value)
    tokens: list[str] = []
    segments: list[str] = [""]
    pos = 0
    while pos < len(value):
        ch = value[pos]

        if ch == _MERGED_ESCAPE_PREFIX:
            if pos + 1 >= len(value):
                segments[-1] += _MERGED_ESCAPE_PREFIX
                pos += 1
                continue
            segments[-1] += value[pos + 1]
            pos += 2
            continue

        if ch == _MERGED_TOKEN_OPEN:
            end = value.find(_MERGED_TOKEN_CLOSE, pos + 1)
            if end == -1:
                raise InlineMergeParseError(
                    "Unclosed merged-inline token.",
                    block_tag=block_tag,
                    original_excerpt=original_merged[:180],
                    translated_excerpt=value[:180],
                    position=pos,
                )
            token = value[pos + 1 : end]
            if not token:
                raise InlineMergeParseError(
                    "Empty merged-inline token.",
                    block_tag=block_tag,
                    original_excerpt=original_merged[:180],
                    translated_excerpt=value[:180],
                    position=pos,
                )
            if inline_open := _parse_inline_open_token(token):
                tag, path = inline_open
                token = f"{tag}:{path}"
            elif inline_close := _parse_inline_close_token(token):
                tag, path = inline_close
                token = f"/{tag}:{path}"
            elif ruby_open := _MERGED_RUBY_OPEN_RE.match(token):
                token = f"RUBY:{ruby_open.group(1)}"
            elif ruby_close := _MERGED_RUBY_CLOSE_RE.match(token):
                token = f"/RUBY:{ruby_close.group(1)}"
            elif br_match := _MERGED_BR_RE.match(token):
                token = f"BR:{br_match.group(1)}"
            tokens.append(token)
            segments.append("")
            pos = end + 1
            continue

        segments[-1] += ch
        pos += 1

    return tokens, segments


def _lenient_token_kind_and_path(token: str) -> tuple[str, str] | None:
    if match := _MERGED_RUBY_OPEN_RE.match(token):
        return ("ruby_open", match.group(1))
    if match := _MERGED_RUBY_CLOSE_RE.match(token):
        return ("ruby_close", match.group(1))
    if match := _MERGED_BR_RE.match(token):
        return ("br", match.group(1))
    if inline_open := _parse_inline_open_token(token):
        tag, path = inline_open
        if tag in _LENIENT_INLINE_STYLE_TAGS:
            return (f"style_open:{tag}", path)
    if inline_close := _parse_inline_close_token(token):
        tag, path = inline_close
        if tag in _LENIENT_INLINE_STYLE_TAGS:
            return (f"style_close:{tag}", path)
    return None


def _is_strict_inline_token(token: str) -> bool:
    return _lenient_token_kind_and_path(token) is None


def _parse_child_path(path: str) -> tuple[int, ...]:
    if not path:
        return ()
    return tuple(int(part) for part in path.split("/"))


def _resolve_child_path(root: _ET.Element, path: tuple[int, ...]) -> _ET.Element | None:
    node = root
    for index in path:
        children = list(node)
        if index < 0 or index >= len(children):
            return None
        node = children[index]
    return node


def _remove_lenient_nodes(block: _ET.Element, drops: set[tuple[str, tuple[int, ...]]]) -> None:
    for kind, path in sorted(drops, key=lambda item: (len(item[1]), item[1]), reverse=True):
        if not path:
            continue
        parent = _resolve_child_path(block, path[:-1])
        if parent is None:
            continue
        child_index = path[-1]
        children = list(parent)
        if child_index < 0 or child_index >= len(children):
            continue
        child = children[child_index]
        if _local_tag(child.tag) != kind:
            continue
        # Preserve dropped node tail text by attaching it to the previous sibling
        # or parent text so we never lose translated content when removing lenient nodes.
        tail = child.tail or ""
        if tail:
            if child_index > 0:
                prev = children[child_index - 1]
                prev.tail = (prev.tail or "") + tail
            else:
                parent.text = (parent.text or "") + tail
        parent.remove(child)


def _align_lenient_token_run(
    expected_run: list[str],
    actual_run: list[str],
) -> list[tuple[int, int]]:
    """Return lenient-token LCS matches by token kind (ignore path/index)."""
    expected_kinds = [_lenient_token_kind_and_path(token)[0] for token in expected_run]  # type: ignore[index]
    actual_kinds = [_lenient_token_kind_and_path(token)[0] for token in actual_run]  # type: ignore[index]

    rows = len(expected_run)
    cols = len(actual_run)
    lcs = [[0] * (cols + 1) for _ in range(rows + 1)]
    for row in range(rows - 1, -1, -1):
        for col in range(cols - 1, -1, -1):
            if expected_kinds[row] == actual_kinds[col]:
                lcs[row][col] = 1 + lcs[row + 1][col + 1]
            else:
                lcs[row][col] = max(lcs[row + 1][col], lcs[row][col + 1])

    matches: list[tuple[int, int]] = []
    row = 0
    col = 0
    while row < rows and col < cols:
        if expected_kinds[row] == actual_kinds[col] and lcs[row][col] == 1 + lcs[row + 1][col + 1]:
            matches.append((row, col))
            row += 1
            col += 1
            continue
        if lcs[row + 1][col] >= lcs[row][col + 1]:
            row += 1
        else:
            col += 1
    return matches


def _build_token_alignment(
    *,
    expected_tokens: tuple[str, ...],
    tokens: list[str],
    block_tag: str,
    original_merged: str,
    translated: str,
) -> tuple[list[int | None], list[int | None]]:
    expected_to_actual: list[int | None] = [None] * len(expected_tokens)
    actual_to_expected: list[int | None] = [None] * len(tokens)

    expected_strict_indices = [idx for idx, token in enumerate(expected_tokens) if _is_strict_inline_token(token)]
    actual_strict_indices = [idx for idx, token in enumerate(tokens) if _is_strict_inline_token(token)]
    if len(expected_strict_indices) != len(actual_strict_indices):
        raise InlineMergeParseError(
            "Strict inline token count mismatch during lenient alignment.",
            block_tag=block_tag,
            original_excerpt=original_merged[:180],
            translated_excerpt=translated[:180],
        )

    expected_cursor = 0
    actual_cursor = 0
    strict_count = len(expected_strict_indices)
    for strict_pos in range(strict_count + 1):
        expected_end = expected_strict_indices[strict_pos] if strict_pos < strict_count else len(expected_tokens)
        actual_end = actual_strict_indices[strict_pos] if strict_pos < strict_count else len(tokens)

        expected_run = list(expected_tokens[expected_cursor:expected_end])
        actual_run = tokens[actual_cursor:actual_end]
        if any(_is_strict_inline_token(token) for token in expected_run) or any(
            _is_strict_inline_token(token) for token in actual_run
        ):
            raise InlineMergeParseError(
                "Unexpected strict inline token inside lenient alignment run.",
                block_tag=block_tag,
                original_excerpt=original_merged[:180],
                translated_excerpt=translated[:180],
            )

        for expected_local, actual_local in _align_lenient_token_run(expected_run, actual_run):
            expected_index = expected_cursor + expected_local
            actual_index = actual_cursor + actual_local
            expected_to_actual[expected_index] = actual_index
            actual_to_expected[actual_index] = expected_index

        if strict_pos == strict_count:
            break

        expected_strict_index = expected_strict_indices[strict_pos]
        actual_strict_index = actual_strict_indices[strict_pos]
        if expected_tokens[expected_strict_index] != tokens[actual_strict_index]:
            raise InlineMergeParseError(
                "Strict inline token mismatch during alignment.",
                block_tag=block_tag,
                original_excerpt=original_merged[:180],
                translated_excerpt=translated[:180],
            )
        expected_to_actual[expected_strict_index] = actual_strict_index
        actual_to_expected[actual_strict_index] = expected_strict_index

        expected_cursor = expected_strict_index + 1
        actual_cursor = actual_strict_index + 1

    return expected_to_actual, actual_to_expected


def _align_lenient_segments_to_expected(
    *,
    expected_tokens: tuple[str, ...],
    tokens: list[str],
    segments: list[str],
    block_tag: str,
    original_merged: str,
    translated: str,
) -> tuple[list[str], set[tuple[str, tuple[int, ...]]]]:
    expected_to_actual, actual_to_expected = _build_token_alignment(
        expected_tokens=expected_tokens,
        tokens=tokens,
        block_tag=block_tag,
        original_merged=original_merged,
        translated=translated,
    )

    aligned_segments: list[str] = [segments[0]]
    actual_token_index = 0
    ruby_open_omitted: set[str] = set()
    ruby_close_omitted: set[str] = set()
    br_omitted: set[str] = set()
    style_open_omitted: set[tuple[str, str]] = set()
    style_close_omitted: set[tuple[str, str]] = set()

    for expected_index, expected_token in enumerate(expected_tokens):
        mapped_actual_index = expected_to_actual[expected_index]
        if mapped_actual_index is None:
            expected_lenient = _lenient_token_kind_and_path(expected_token)
            if expected_lenient is None:
                raise InlineMergeParseError(
                    "Strict inline token alignment failed while applying lenient merged segments.",
                    block_tag=block_tag,
                    original_excerpt=original_merged[:180],
                    translated_excerpt=translated[:180],
                )
            kind, path = expected_lenient
            if kind == "ruby_open":
                ruby_open_omitted.add(path)
            elif kind == "ruby_close":
                ruby_close_omitted.add(path)
            elif kind == "br":
                br_omitted.add(path)
            elif kind.startswith("style_open:"):
                style_open_omitted.add((kind.split(":", 1)[1], path))
            elif kind.startswith("style_close:"):
                style_close_omitted.add((kind.split(":", 1)[1], path))
            aligned_segments.append("")
            continue

        while actual_token_index < mapped_actual_index:
            if actual_to_expected[actual_token_index] is not None:
                raise InlineMergeParseError(
                    "Unexpected matched token ordering during lenient segment alignment.",
                    block_tag=block_tag,
                    original_excerpt=original_merged[:180],
                    translated_excerpt=translated[:180],
                )
            aligned_segments[-1] += segments[actual_token_index + 1]
            actual_token_index += 1

        aligned_segments.append(segments[actual_token_index + 1])
        actual_token_index += 1

    while actual_token_index < len(tokens):
        if actual_to_expected[actual_token_index] is not None:
            raise InlineMergeParseError(
                "Unexpected matched token remained after lenient segment alignment.",
                block_tag=block_tag,
                original_excerpt=original_merged[:180],
                translated_excerpt=translated[:180],
            )
        aligned_segments[-1] += segments[actual_token_index + 1]
        actual_token_index += 1

    ruby_drop_paths = ruby_open_omitted & ruby_close_omitted
    drops: set[tuple[str, tuple[int, ...]]] = {("ruby", _parse_child_path(path)) for path in ruby_drop_paths}
    drops.update(("br", _parse_child_path(path)) for path in br_omitted)
    style_drop_keys = style_open_omitted & style_close_omitted
    drops.update((tag, _parse_child_path(path)) for tag, path in style_drop_keys)
    return aligned_segments, drops


def _collect_lenient_drops_from_tokens(tokens: tuple[str, ...]) -> set[tuple[str, tuple[int, ...]]]:
    ruby_open_paths: set[str] = set()
    ruby_close_paths: set[str] = set()
    br_paths: set[str] = set()
    style_open_paths: set[tuple[str, str]] = set()
    style_close_paths: set[tuple[str, str]] = set()

    for token in tokens:
        lenient = _lenient_token_kind_and_path(token)
        if lenient is None:
            continue
        kind, path = lenient
        if kind == "ruby_open":
            ruby_open_paths.add(path)
        elif kind == "ruby_close":
            ruby_close_paths.add(path)
        elif kind == "br":
            br_paths.add(path)
        elif kind.startswith("style_open:"):
            style_open_paths.add((kind.split(":", 1)[1], path))
        elif kind.startswith("style_close:"):
            style_close_paths.add((kind.split(":", 1)[1], path))

    drops: set[tuple[str, tuple[int, ...]]] = set()
    drops.update(("ruby", _parse_child_path(path)) for path in (ruby_open_paths & ruby_close_paths))
    drops.update(("br", _parse_child_path(path)) for path in br_paths)
    drops.update((tag, _parse_child_path(path)) for tag, path in (style_open_paths & style_close_paths))
    return drops


def _apply_aligned_merged_segments(
    plan: _MergedInlinePlan,
    tokens: list[str],
    segments: list[str],
    *,
    block_tag: str,
    original_merged: str,
    translated: str,
    strip_ruby_annotations: bool = False,
) -> None:
    """Apply translated merged-inline segments using deterministic token alignment."""
    assigned, drops = _align_lenient_segments_to_expected(
        expected_tokens=plan.tokens,
        tokens=tokens,
        segments=segments,
        block_tag=block_tag,
        original_merged=original_merged,
        translated=translated,
    )
    if len(assigned) != len(plan.anchors):
        raise InlineMergeParseError(
            "Aligned merged-inline segment count did not match expected anchors.",
            block_tag=block_tag,
            original_excerpt=original_merged[:180],
            translated_excerpt=translated[:180],
        )

    for anchor, replacement in zip(plan.anchors, assigned, strict=True):
        if anchor.slot_kind == "text":
            anchor.node.text = replacement
        elif anchor.slot_kind == "tail":
            anchor.node.tail = replacement
        elif anchor.slot_kind == "ruby":
            _set_slot_text(anchor.node, "ruby", None, replacement, strip_ruby_annotations=strip_ruby_annotations)

    _remove_lenient_nodes(plan.anchors[0].node, drops)


def _clear_merged_inline_content(plan: _MergedInlinePlan, *, strip_ruby_annotations: bool = False) -> None:
    """Clear all translatable text in a merged-inline block.

    Used when the translated line is intentionally compressed into an empty
    placeholder (""), so strict inline marker structure should be ignored.
    """
    for anchor in plan.anchors:
        if anchor.slot_kind == "text":
            anchor.node.text = ""
        elif anchor.slot_kind == "tail":
            anchor.node.tail = ""
        elif anchor.slot_kind == "ruby":
            _set_slot_text(anchor.node, "ruby", None, "", strip_ruby_annotations=strip_ruby_annotations)

    # For compressed lines, prune lenient wrappers (<ruby>/<br>/style tags)
    # while preserving strict semantic/media nodes (e.g. <a>, <img>, <abbr>).
    drops = _collect_lenient_drops_from_tokens(plan.tokens)
    if drops:
        _remove_lenient_nodes(plan.anchors[0].node, drops)


def _apply_merged_inline_translation(
    block: _ET.Element,
    translated: str,
    original_merged: str,
    *,
    strip_ruby_annotations: bool = False,
) -> None:
    plan = _build_merged_inline_plan(block, strip_ruby_annotations=strip_ruby_annotations)
    if not translated.strip():
        _clear_merged_inline_content(plan, strip_ruby_annotations=strip_ruby_annotations)
        return

    try:
        tokens, segments = _scan_merged_translation(
            translated,
            block_tag=_local_tag(block.tag),
            original_merged=original_merged or plan.merged_text,
        )
        # Best-effort mode: do not enforce expected token identity/order, but
        # still reject malformed token streams and fall back to plain text.
        try:
            validate_inline_marker_sanity(tokens)
        except ValueError as exc:
            raise InlineMergeParseError(
                f"Malformed merged-inline marker sequence: {exc}",
                block_tag=_local_tag(block.tag),
                original_excerpt=(original_merged or plan.merged_text)[:180],
                translated_excerpt=translated[:180],
            ) from exc
        _apply_aligned_merged_segments(
            plan,
            tokens,
            segments,
            block_tag=_local_tag(block.tag),
            original_merged=original_merged or plan.merged_text,
            translated=translated,
            strip_ruby_annotations=strip_ruby_annotations,
        )
    except InlineMergeParseError as exc:
        has_strict_structure = any(_is_strict_inline_token(token) for token in plan.tokens)
        block_root = plan.anchors[0].node
        if has_strict_structure:
            logger.warning(
                "Merged-inline reinjection failed; degrading strict inline structure to plain text: %s",
                exc,
            )
            block_root.text = ""
            for child in list(block_root):
                block_root.remove(child)
            block_root.text = _plain_text_from_marker_string(
                translated,
                block_tag=_local_tag(block_root.tag),
                original_merged=original_merged or plan.merged_text,
            )
            return

        logger.warning("Merged-inline reinjection fallback to source text (lenient-only block): %s", exc)
        block_root.text = ""
        for child in list(block_root):
            block_root.remove(child)
        _set_text_slot_from_inline_markers_source_truth(
            block_root,
            translated,
            strip_ruby_annotations=strip_ruby_annotations,
        )


def _set_ruby_text(node: _ET.Element, value: str, *, strip_annotations: bool = False) -> None:
    """Write translated ruby text to <ruby>, normalizing to a single <rt> annotation.

    Note: some EPUBs include alternative annotation containers like <rtc>.
    We drop <rtc> during writeback to avoid leaking stale source-language
    annotations in downstream HTML conversion (e.g., pandoc choosing <rtc>).
    """
    normalized = _normalize_alt_inline_marker_delimiters(value)
    normalized = re.sub(r"⟪/?RUBY:[^⟫]+⟫", "", normalized)

    match = _RUBY_SPLIT_RE.match(normalized)
    if match:
        base_text = match.group("base")
        rt_text = match.group("rt_ascii") or match.group("rt_full") or ""
    else:
        base_text = _strip_trailing_empty_bracket_pairs(normalized)
        rt_text = ""
    if strip_annotations:
        rt_text = ""
    if not rt_text.strip():
        rt_text = ""

    def _clear_children(elem: _ET.Element) -> None:
        for child in list(elem):
            elem.remove(child)

    rb_children = [child for child in node if _local_tag(child.tag) == "rb"]
    if rb_children:
        _clear_children(rb_children[0])
        rb_children[0].text = base_text
        for rb in rb_children[1:]:
            _clear_children(rb)
            rb.text = ""
        # Keep base text in <rb> when rb nodes are present.
        node.text = ""
    else:
        node.text = base_text

    rt_children = [child for child in node if _local_tag(child.tag) == "rt"]
    if rt_children:
        _clear_children(rt_children[0])
        rt_children[0].text = rt_text
        for rt in rt_children[1:]:
            _clear_children(rt)
            rt.text = ""
    elif rt_text:
        rt = _ET.Element(_qualified_inline_tag(node, "rt"))
        rt.text = rt_text
        node.append(rt)

    # Always clear <rp> fallback text because some EPUB readers render it
    # even when ruby is supported, causing visible brackets like "()" or "《》".
    for child in node:
        if _local_tag(child.tag) == "rp":
            _clear_children(child)
            child.text = ""

    # Remove alternate ruby annotation containers to prevent stale source
    # readings from surviving conversion pipelines that prefer <rtc>.
    for child in list(node):
        if _local_tag(child.tag) == "rtc":
            node.remove(child)


def _set_slot_text(
    node: _ET.Element,
    slot_kind: str,
    attr_name: str | None,
    value: str,
    *,
    source_text: str | None = None,
    strip_ruby_annotations: bool = False,
) -> None:
    if slot_kind == "merged_inline":
        _apply_merged_inline_translation(
            node,
            value,
            source_text or "",
            strip_ruby_annotations=strip_ruby_annotations,
        )
    elif slot_kind == "ruby":
        _set_ruby_text(node, value, strip_annotations=strip_ruby_annotations)
    elif slot_kind == "tail":
        node.tail = _plain_text_from_marker_string(
            value,
            block_tag=_local_tag(node.tag),
            original_merged=source_text or value,
        )
    elif slot_kind == "text":
        if extract_inline_markers(value, include_unknown=True):
            _set_text_slot_from_inline_markers_source_truth(
                node,
                value,
                strip_ruby_annotations=strip_ruby_annotations,
            )
        else:
            node.text = value
    elif slot_kind == "attr" and attr_name is not None:
        node.set(
            attr_name,
            _plain_text_from_marker_string(
                value,
                block_tag=_local_tag(node.tag),
                original_merged=source_text or value,
            ),
        )


def _iter_elements(elem: _ET.Element) -> Iterator[_ET.Element]:
    """Yield element tree in document order (preorder traversal)."""
    yield elem
    for child in elem:
        yield from _iter_elements(child)


def _collect_translatable_slots(
    root: _ET.Element,
    *,
    strip_ruby_annotations: bool = False,
) -> list[tuple[_ET.Element, str, str | None, str]]:
    """Collect all translatable slots in stable order.

    Primary pass uses block roots to preserve existing block/inline behavior.
    Secondary pass appends any translatable attributes that were not visited in
    the primary pass (for non-block elements outside block roots).
    """
    slots: list[tuple[_ET.Element, str, str | None, str]] = []
    seen_attr_slots: set[tuple[int, str]] = set()

    for block, skip_block_descendants in _iter_block_slot_roots(root):
        if _is_merge_inline_candidate(
            block,
            skip_block_descendants=skip_block_descendants,
            strip_ruby_annotations=strip_ruby_annotations,
        ):
            merged_plan = _build_merged_inline_plan(block, strip_ruby_annotations=strip_ruby_annotations)
            if any(anchor.text.strip() for anchor in merged_plan.anchors):
                slots.append((block, "merged_inline", None, merged_plan.merged_text))
            for node, slot_kind, attr_name, slot_text in _iter_translatable_attrs(
                block,
                skip_block_descendants=skip_block_descendants,
            ):
                slots.append((node, slot_kind, attr_name, slot_text))
                if attr_name is not None:
                    seen_attr_slots.add((id(node), attr_name))
            continue

        for node, slot_kind, attr_name, slot_text in _iter_translatable_slots(
            block,
            skip_block_descendants=skip_block_descendants,
            strip_ruby_annotations=strip_ruby_annotations,
        ):
            slots.append((node, slot_kind, attr_name, slot_text))
            if slot_kind == "attr" and attr_name is not None:
                seen_attr_slots.add((id(node), attr_name))

    for elem in _iter_elements(root):
        for attr_name, attr_value in elem.attrib.items():
            if _local_attr(attr_name) not in TRANSLATABLE_ATTR_NAMES or not attr_value.strip():
                continue
            key = (id(elem), attr_name)
            if key in seen_attr_slots:
                continue
            slots.append((elem, "attr", attr_name, attr_value))
            seen_attr_slots.add(key)

    return slots


def _extract_xml_header(xhtml_content: str) -> str:
    """Extract the XML declaration and DOCTYPE from the original XHTML."""
    match = re.match(r"((?:\s*<\?xml[^?]*\?>\s*)?(?:\s*<!DOCTYPE[^>]*>\s*)?)", xhtml_content, re.DOTALL)
    if match:
        return match.group(1)
    return ""


def _itertext_skip_ruby_annotations(elem: _ET.Element) -> Iterator[str]:
    """Like ``Element.itertext()`` but skips <rt>/<rp>/<rtc> descendant text."""
    tag = _local_tag(elem.tag)
    if tag in _RUBY_ANNOTATION_TAGS:
        return
    if elem.text:
        yield elem.text
    for child in elem:
        yield from _itertext_skip_ruby_annotations(child)
        if child.tail:
            yield child.tail


def _ruby_has_annotation_text(ruby_elem: _ET.Element) -> bool:
    for descendant in ruby_elem.iter():
        if descendant is ruby_elem:
            continue
        if _local_tag(descendant.tag) not in _RUBY_ANNOTATION_TAGS:
            continue
        if any(text.strip() for text in descendant.itertext()):
            return True
    return False


def _iter_unwrapped_ruby_parts(elem: _ET.Element) -> Iterator[str | _ET.Element]:
    if elem.text:
        yield elem.text

    for child in list(elem):
        child_local = _local_tag(child.tag)
        child_tail = child.tail or ""
        child.tail = None
        elem.remove(child)

        if child_local in _RUBY_ANNOTATION_TAGS:
            if child_tail:
                yield child_tail
            continue

        if child_local in _RUBY_BASE_WRAPPER_TAGS:
            yield from _iter_unwrapped_ruby_parts(child)
        else:
            yield child

        if child_tail:
            yield child_tail


def _splice_parts_into_parent(
    parent: _ET.Element,
    insert_at: int,
    parts: list[str | _ET.Element],
) -> int:
    previous = parent[insert_at - 1] if insert_at > 0 else None
    inserted_elements = 0

    for part in parts:
        if isinstance(part, str):
            if not part:
                continue
            if previous is None:
                parent.text = (parent.text or "") + part
            else:
                previous.tail = (previous.tail or "") + part
            continue

        parent.insert(insert_at, part)
        previous = part
        insert_at += 1
        inserted_elements += 1

    return inserted_elements


def _flatten_annotationless_ruby_nodes(parent: _ET.Element) -> None:
    child_index = 0
    while child_index < len(parent):
        child = parent[child_index]
        _flatten_annotationless_ruby_nodes(child)
        if _local_tag(child.tag) != "ruby" or _ruby_has_annotation_text(child):
            child_index += 1
            continue

        tail = child.tail or ""
        child.tail = None
        replacement_parts = list(_iter_unwrapped_ruby_parts(child))
        if tail:
            replacement_parts.append(tail)
        parent.remove(child)
        inserted_elements = _splice_parts_into_parent(parent, child_index, replacement_parts)
        child_index += inserted_elements


def flatten_annotationless_ruby_in_xhtml(xhtml_content: str) -> str:
    """Collapse ruby wrappers that no longer have any annotation text.

    This is mainly useful before converting EPUB XHTML to Markdown. Some EPUB
    readers render ``<ruby>base<rt></rt></ruby>`` as plain base text, but
    pandoc preserves the raw HTML wrapper in Markdown output.
    """
    root = DefusedET.fromstring(xhtml_content)
    _flatten_annotationless_ruby_nodes(root)
    modified = _ET.tostring(root, encoding="unicode", xml_declaration=False)
    header = normalize_xml_header_for_utf8(_extract_xml_header(xhtml_content))
    return header + modified


def extract_heading_texts(xhtml_content: str) -> list[str]:
    """Extract full text content of heading elements (h1-h6) in document order.

    Returns one entry per heading element, using the concatenated text of all
    inline children (skipping ruby annotations).  Empty headings are included
    so that positional pairing between original and translated documents stays
    stable.
    """
    root = DefusedET.fromstring(xhtml_content)
    headings: list[str] = []
    for elem in root.iter():
        if _local_tag(elem.tag) in HEADING_TAGS:
            headings.append("".join(_itertext_skip_ruby_annotations(elem)).strip())
    return headings


def extract_text_from_xhtml(xhtml_content: str, *, strip_ruby_annotations: bool = False) -> list[str]:
    """Extract translatable text slots from XHTML.

    Most blocks use slot-level extraction (``.text``/``.tail``/attributes).
    Inline-heavy leaf blocks are merged into one tokenized slot so sentence
    context is preserved while reinjection remains deterministic.
    """
    root = DefusedET.fromstring(xhtml_content)

    return [
        slot_text
        for _node, _slot_kind, _attr_name, slot_text in _collect_translatable_slots(
            root,
            strip_ruby_annotations=strip_ruby_annotations,
        )
    ]


def inject_translations_into_xhtml(
    xhtml_content: str,
    translations: list[str],
    offset: int = 0,
    *,
    strip_ruby_annotations: bool = False,
) -> tuple[str, int]:
    """Replace slot values with translations in original extraction order.

    Each extracted slot consumes one translated entry. For merged-inline slots,
    deterministic token parsing validates structure before applying text so DOM
    elements and inline formatting are preserved.
    """
    root = DefusedET.fromstring(xhtml_content)

    pos = offset
    for node, slot_kind, attr_name, slot_text in _collect_translatable_slots(
        root,
        strip_ruby_annotations=strip_ruby_annotations,
    ):
        if pos >= len(translations):
            break
        translated = preserve_outer_whitespace(slot_text, decode_compressed_line(translations[pos]))
        _set_slot_text(
            node,
            slot_kind,
            attr_name,
            translated,
            source_text=slot_text,
            strip_ruby_annotations=strip_ruby_annotations,
        )
        pos += 1

    consumed = pos - offset

    # Serialize back to string (XHTML namespace registered at module level)
    modified = _ET.tostring(root, encoding="unicode", xml_declaration=False)

    # Re-add original XML declaration and DOCTYPE if present
    header = normalize_xml_header_for_utf8(_extract_xml_header(xhtml_content))
    return header + modified, consumed
