"""Shared XML/text helper utilities for EPUB processing."""

from __future__ import annotations

import re

XML_DECL_RE = re.compile(r"<\?xml[^?]*\?>", flags=re.IGNORECASE)


def normalize_xml_header_for_utf8(text: str) -> str:
    """Normalize XML declaration encoding to utf-8 when declaration exists."""

    def _rewrite_xml_decl(match: re.Match[str]) -> str:
        decl = match.group(0)
        if re.search(r"encoding\s*=", decl, flags=re.IGNORECASE):
            return re.sub(
                r"encoding\s*=\s*(['\"])[^'\"]*\1",
                'encoding="utf-8"',
                decl,
                count=1,
                flags=re.IGNORECASE,
            )
        return decl[:-2] + ' encoding="utf-8"?>'

    return XML_DECL_RE.sub(_rewrite_xml_decl, text, count=1)


def preserve_outer_whitespace(original: str, translated: str) -> str:
    """Preserve leading/trailing whitespace from original around translated text."""
    match = re.match(r"^(\s*)(.*?)(\s*)$", original, re.DOTALL)
    if not match:
        return translated
    leading, _core, trailing = match.groups()
    if not leading and not trailing:
        return translated
    if translated == translated.strip():
        return f"{leading}{translated}{trailing}"
    return translated
