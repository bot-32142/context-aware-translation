"""Shared EPUB inline marker utilities.

Markers are embedded in extracted text to preserve inline XHTML structure
across translation and reinjection.

Marker grammar:
- inline open: ``⟪tag:path⟫``
- inline close: ``⟪/tag:path⟫``
- ruby open/close: ``⟪RUBY:path⟫`` / ``⟪/RUBY:path⟫``
- line break: ``⟪BR:path⟫``
"""

from __future__ import annotations

import re

MERGED_TOKEN_OPEN = "⟪"
MERGED_TOKEN_CLOSE = "⟫"
MERGED_ESCAPE_PREFIX = "\ue000"
_ALT_INLINE_MARKER_RE = re.compile(r"[《〈＜]([^《》〈〉＜＞]+)[》〉＞]")

_INLINE_OPEN_RE = re.compile(r"^([A-Za-z][A-Za-z0-9._-]*):(\d+(?:/\d+)*)$")
_INLINE_CLOSE_RE = re.compile(r"^/([A-Za-z][A-Za-z0-9._-]*):(\d+(?:/\d+)*)$")
BR_RE = re.compile(r"^BR:(\d+(?:/\d+)*)$")
RUBY_OPEN_RE = re.compile(r"^RUBY:(\d+(?:/\d+)*)$")
RUBY_CLOSE_RE = re.compile(r"^/RUBY:(\d+(?:/\d+)*)$")
LENIENT_INLINE_STYLE_TAGS = frozenset(
    {
        "b",
        "big",
        "code",
        "del",
        "dfn",
        "em",
        "i",
        "ins",
        "kbd",
        "mark",
        "q",
        "s",
        "samp",
        "small",
        "strong",
        "sub",
        "sup",
        "u",
        "var",
    }
)


def parse_inline_open(token: str) -> tuple[str, str] | None:
    """Parse inline open marker token and return ``(tag, path)``."""
    match = _INLINE_OPEN_RE.match(token)
    if not match:
        return None
    tag = match.group(1).lower()
    if tag in {"ruby", "br"}:
        return None
    return tag, match.group(2)


def parse_inline_close(token: str) -> tuple[str, str] | None:
    """Parse inline close marker token and return ``(tag, path)``."""
    match = _INLINE_CLOSE_RE.match(token)
    if not match:
        return None
    tag = match.group(1).lower()
    if tag in {"ruby", "br"}:
        return None
    return tag, match.group(2)


def normalize_alt_inline_marker_delimiters(text: str) -> str:
    """Normalize known marker tokens wrapped in 《》/〈〉/＜＞ to canonical ⟪⟫."""

    def _replace(match: re.Match[str]) -> str:
        token = match.group(1).strip()
        if not is_inline_marker_token(token):
            return match.group(0)
        return f"{MERGED_TOKEN_OPEN}{token}{MERGED_TOKEN_CLOSE}"

    return _ALT_INLINE_MARKER_RE.sub(_replace, text)


def is_inline_marker_token(token: str) -> bool:
    """Return True if token is a known inline marker token."""
    return bool(
        parse_inline_open(token)
        or parse_inline_close(token)
        or BR_RE.match(token)
        or RUBY_OPEN_RE.match(token)
        or RUBY_CLOSE_RE.match(token)
    )


def is_lenient_inline_marker_token(token: str) -> bool:
    """Return True for optional markers (BR/RUBY/lenient style wrappers)."""
    if BR_RE.match(token) or RUBY_OPEN_RE.match(token) or RUBY_CLOSE_RE.match(token):
        return True
    inline_open = parse_inline_open(token)
    if inline_open:
        return inline_open[0] in LENIENT_INLINE_STYLE_TAGS
    inline_close = parse_inline_close(token)
    if inline_close:
        return inline_close[0] in LENIENT_INLINE_STYLE_TAGS
    return False


def strict_inline_markers(tokens: list[str] | tuple[str, ...]) -> list[str]:
    """Return markers that must be preserved strictly.

    BR/RUBY are always lenient. Inline open/close pairs are lenient when tag is
    in ``LENIENT_INLINE_STYLE_TAGS``.
    """
    strict: list[str] = []
    inline_stack: list[tuple[str, str, bool]] = []  # (tag, path, is_lenient_style_tag)

    for token in tokens:
        inline_open = parse_inline_open(token)
        if inline_open:
            tag, path = inline_open
            is_lenient = tag in LENIENT_INLINE_STYLE_TAGS
            inline_stack.append((tag, path, is_lenient))
            if not is_lenient:
                strict.append(f"{tag}:{path}")
            continue

        inline_close = parse_inline_close(token)
        if inline_close:
            close_tag, close_path = inline_close
            if inline_stack and inline_stack[-1][0] == close_tag and inline_stack[-1][1] == close_path:
                _open_tag, _open_path, is_lenient = inline_stack.pop()
                if not is_lenient:
                    strict.append(f"/{close_tag}:{close_path}")
            else:
                # Keep malformed closes strict; sanity validation should already
                # reject malformed streams, but this avoids false leniency.
                strict.append(f"/{close_tag}:{close_path}")
            continue

        if is_lenient_inline_marker_token(token):
            continue
        strict.append(token)

    return strict


def validate_inline_marker_sanity(tokens: list[str] | tuple[str, ...]) -> None:
    """Validate marker sequence shape (balanced open/close; no unknown tokens)."""
    strict_stack: list[tuple[str, str]] = []
    ruby_stack: list[str] = []

    for index, token in enumerate(tokens):
        inline_open = parse_inline_open(token)
        inline_close = parse_inline_close(token)
        ruby_open = RUBY_OPEN_RE.match(token)
        ruby_close = RUBY_CLOSE_RE.match(token)
        br = BR_RE.match(token)

        if inline_open:
            strict_stack.append(inline_open)
            continue

        if inline_close:
            close_tag, close_path = inline_close
            if not strict_stack or strict_stack[-1] != inline_close:
                expected = f"/{strict_stack[-1][0]}:{strict_stack[-1][1]}" if strict_stack else "<none>"
                raise ValueError(
                    f"mismatched strict marker at token index {index}: expected {expected!r}, got {f'/{close_tag}:{close_path}'!r}"
                )
            strict_stack.pop()
            continue

        if ruby_open:
            ruby_stack.append(ruby_open.group(1))
            continue

        if ruby_close:
            close_path = ruby_close.group(1)
            if not ruby_stack or ruby_stack[-1] != close_path:
                expected = ruby_stack[-1] if ruby_stack else "<none>"
                raise ValueError(
                    f"mismatched ruby marker at token index {index}: expected '/RUBY:{expected}', got '/RUBY:{close_path}'"
                )
            ruby_stack.pop()
            continue

        if br:
            continue

        raise ValueError(f"unknown inline marker token at index {index}: {token!r}")

    if strict_stack:
        unclosed = [f"{tag}:{path}" for tag, path in strict_stack]
        raise ValueError(f"unclosed strict marker(s): {unclosed!r}")
    if ruby_stack:
        raise ValueError(f"unclosed ruby marker(s): {ruby_stack!r}")


def validate_inline_marker_fragment_sanity(tokens: list[str] | tuple[str, ...]) -> None:
    """Validate a marker fragment that may start/end inside an inline span.

    Unlike ``validate_inline_marker_sanity()``, this accepts leading close
    markers and trailing open markers so translation chunks can begin or end
    inside a valid EPUB inline wrapper. The interior ordering must still be
    structurally valid.
    """

    strict_stack: list[tuple[str, str]] = []
    ruby_stack: list[str] = []

    for index, token in enumerate(tokens):
        inline_open = parse_inline_open(token)
        inline_close = parse_inline_close(token)
        ruby_open = RUBY_OPEN_RE.match(token)
        ruby_close = RUBY_CLOSE_RE.match(token)
        br = BR_RE.match(token)

        if inline_open:
            strict_stack.append(inline_open)
            continue

        if inline_close:
            close_tag, close_path = inline_close
            if strict_stack:
                if strict_stack[-1] != inline_close:
                    expected = f"/{strict_stack[-1][0]}:{strict_stack[-1][1]}"
                    raise ValueError(
                        "mismatched strict marker at token index "
                        f"{index}: expected {expected!r}, got {f'/{close_tag}:{close_path}'!r}"
                    )
                strict_stack.pop()
            continue

        if ruby_open:
            ruby_stack.append(ruby_open.group(1))
            continue

        if ruby_close:
            close_path = ruby_close.group(1)
            if ruby_stack:
                if ruby_stack[-1] != close_path:
                    expected = ruby_stack[-1]
                    raise ValueError(
                        "mismatched ruby marker at token index "
                        f"{index}: expected '/RUBY:{expected}', got '/RUBY:{close_path}'"
                    )
                ruby_stack.pop()
            continue

        if br:
            continue

        raise ValueError(f"unknown inline marker token at index {index}: {token!r}")


def ruby_pair_count(tokens: list[str] | tuple[str, ...]) -> int:
    """Return the number of ruby marker pairs (counted by open markers)."""
    return sum(1 for token in tokens if RUBY_OPEN_RE.match(token))


def extract_inline_markers(text: str, *, include_unknown: bool = False) -> list[str]:
    """Extract unescaped inline marker tokens from text in order."""
    text = normalize_alt_inline_marker_delimiters(text)
    tokens: list[str] = []
    pos = 0
    while pos < len(text):
        ch = text[pos]
        if ch == MERGED_ESCAPE_PREFIX:
            pos += 2 if pos + 1 < len(text) else 1
            continue
        if ch != MERGED_TOKEN_OPEN:
            pos += 1
            continue

        end = text.find(MERGED_TOKEN_CLOSE, pos + 1)
        if end == -1:
            break
        token = text[pos + 1 : end]
        if include_unknown or is_inline_marker_token(token):
            tokens.append(token)
        pos = end + 1

    return tokens
