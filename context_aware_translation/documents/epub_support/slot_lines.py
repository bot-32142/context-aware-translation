"""Line/slot mapping helpers for EPUB translation text flow."""

from __future__ import annotations

from context_aware_translation.documents.epub_support.container_model import TocEntry


def split_text_to_lines(text: str) -> list[str]:
    lines = text.splitlines()
    return lines if lines else [text]


def flatten_slot_texts_to_lines(slot_texts: list[str]) -> list[str]:
    lines: list[str] = []
    for slot in slot_texts:
        lines.extend(split_text_to_lines(slot))
    return lines


def consume_slot_texts_from_lines(
    slot_templates: list[str],
    lines: list[str],
    offset: int,
) -> tuple[list[str], int]:
    translated_slots: list[str] = []
    pos = offset
    for slot in slot_templates:
        count = len(split_text_to_lines(slot))
        translated_slots.append("\n".join(lines[pos : pos + count]))
        pos += count
    return translated_slots, pos


def flatten_toc_title_lines(entries: list[TocEntry]) -> list[str]:
    lines: list[str] = []
    for entry in entries:
        if entry.title:
            lines.extend(split_text_to_lines(entry.title))
        if entry.children:
            lines.extend(flatten_toc_title_lines(entry.children))
    return lines


def apply_toc_title_lines(
    entries: list[TocEntry],
    lines: list[str],
    offset: int = 0,
) -> tuple[list[TocEntry], int]:
    updated: list[TocEntry] = []
    pos = offset
    for entry in entries:
        new_title = entry.title
        if entry.title:
            count = len(split_text_to_lines(entry.title))
            new_title = "\n".join(lines[pos : pos + count])
            pos += count
        new_children = None
        if entry.children:
            new_children, pos = apply_toc_title_lines(entry.children, lines, pos)
        updated.append(TocEntry(title=new_title, href=entry.href, children=new_children))
    return updated, pos
