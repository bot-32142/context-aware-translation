from __future__ import annotations

import re

_KEEP_PARAGRAPH_RE = re.compile(
    r"""
    ^\s*(
        [-*+•]
        |\d+[.)]
        |[A-Za-z][.)]
        |[#>`|]
        |\[[ xX]\]
        |:::
        |```
        |~~~
    )(\s+|$)
    """,
    re.VERBOSE,
)
_MULTISPACE_RE = re.compile(r"\S\s{2,}\S")


def _should_keep_paragraph(lines: list[str]) -> bool:
    if len(lines) < 2:
        return True
    if any(
        line.rstrip().endswith("-")
        and len(line.rstrip()) >= 2
        and line.rstrip()[-2].isalpha()
        and next_line.lstrip()
        and next_line.lstrip()[0].isalpha()
        for line, next_line in zip(lines, lines[1:], strict=False)
    ):
        return False
    if any(_KEEP_PARAGRAPH_RE.match(line) for line in lines):
        return True
    if any("\t" in line or _MULTISPACE_RE.search(line) for line in lines):
        return True

    average_length = sum(len(line) for line in lines) / len(lines)
    return average_length < 32


def _merge_lines(lines: list[str]) -> str:
    merged = lines[0].strip()
    for raw_line in lines[1:]:
        line = raw_line.strip()
        if not line:
            continue
        if merged.endswith("-") and len(merged) >= 2 and merged[-2].isalpha() and line[0].isalpha():
            merged = f"{merged[:-1]}{line}"
            continue
        if not merged:
            merged = line
            continue
        merged = f"{merged.rstrip()} {line}"
    return merged


def unwrap_hard_wrapped_text(text: str) -> str:
    """Collapse likely prose hard wraps while preserving obvious structured blocks."""
    if "\n" not in text and "\r" not in text:
        return text

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    result_lines: list[str] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if not paragraph:
            return
        if _should_keep_paragraph(paragraph):
            result_lines.extend(paragraph)
        else:
            result_lines.append(_merge_lines(paragraph))
        paragraph = []

    for raw_line in normalized.split("\n"):
        if raw_line.strip():
            paragraph.append(raw_line)
            continue
        flush_paragraph()
        result_lines.append(raw_line)

    flush_paragraph()
    return "\n".join(result_lines)
