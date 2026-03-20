from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any


def extract_ocr_text(ocr_json: str | None) -> str:
    """Extract plain text from OCR JSON payload.

    Returns an empty string for missing/invalid payloads.
    """
    if not ocr_json:
        return ""
    try:
        parsed = json.loads(ocr_json)
    except (TypeError, ValueError):
        return ""
    if not isinstance(parsed, dict):
        return ""

    text = parsed.get("text")
    if isinstance(text, str):
        return text
    if text is None:
        return ""
    return str(text)


def get_sources_with_nonempty_ocr_text(
    sources: Sequence[dict[str, Any]],
) -> list[tuple[int, dict[str, Any], str]]:
    """Return (source_index, source_row, text) for pages with OCR text.

    Sources are sorted by sequence_number to ensure consistent positional mapping.
    """
    sorted_sources = sorted(sources, key=lambda s: s["sequence_number"])
    result: list[tuple[int, dict[str, Any], str]] = []
    for source_idx, source in enumerate(sorted_sources):
        text = extract_ocr_text(source.get("ocr_json"))
        if text.strip():
            result.append((source_idx, source, text))
    return result


def list_nonempty_ocr_source_ids(sources: Sequence[dict[str, Any]]) -> list[int]:
    """Return source_ids for non-empty OCR pages in sequence order."""
    return [int(source["source_id"]) for _, source, _ in get_sources_with_nonempty_ocr_text(sources)]


def count_nonempty_ocr_sources(sources: Sequence[dict[str, Any]]) -> int:
    """Count how many sources contain non-empty OCR text."""
    return len(get_sources_with_nonempty_ocr_text(sources))


def align_sources_to_chunks(
    sources: Sequence[dict[str, Any]],
    chunk_count: int,
    *,
    strict: bool,
) -> dict[int, int]:
    """Build source_index -> chunk_index mapping.

    In strict mode, raises ValueError on any count mismatch.
    In non-strict mode, maps the intersection and leaves extras unmapped.
    """
    source_indexes = [source_idx for source_idx, _, _ in get_sources_with_nonempty_ocr_text(sources)]
    source_count = len(source_indexes)
    if strict and source_count != chunk_count:
        raise ValueError(
            f"Manga source/chunk alignment mismatch: {source_count} non-empty OCR pages vs {chunk_count} chunks"
        )

    mapping_limit = min(source_count, chunk_count)
    return {source_indexes[i]: i for i in range(mapping_limit)}
