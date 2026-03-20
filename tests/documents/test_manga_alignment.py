from __future__ import annotations

import pytest

from context_aware_translation.documents.manga_alignment import (
    align_sources_to_chunks,
    count_nonempty_ocr_sources,
    extract_ocr_text,
    list_nonempty_ocr_source_ids,
)


def test_list_nonempty_ocr_source_ids_orders_by_sequence_and_filters_empty() -> None:
    sources = [
        {"source_id": 3, "sequence_number": 2, "ocr_json": '{"text":"third"}'},
        {"source_id": 1, "sequence_number": 0, "ocr_json": '{"text":"first"}'},
        {"source_id": 2, "sequence_number": 1, "ocr_json": '{"text":"   "}'},
        {"source_id": 4, "sequence_number": 3, "ocr_json": "invalid-json"},
    ]

    assert list_nonempty_ocr_source_ids(sources) == [1, 3]
    assert count_nonempty_ocr_sources(sources) == 2


def test_align_sources_to_chunks_strict_raises_on_mismatch() -> None:
    sources = [
        {"source_id": 1, "sequence_number": 0, "ocr_json": '{"text":"a"}'},
        {"source_id": 2, "sequence_number": 1, "ocr_json": '{"text":"b"}'},
    ]

    with pytest.raises(ValueError, match="alignment mismatch"):
        align_sources_to_chunks(sources, chunk_count=1, strict=True)


def test_align_sources_to_chunks_non_strict_maps_intersection() -> None:
    sources = [
        {"source_id": 1, "sequence_number": 0, "ocr_json": '{"text":"a"}'},
        {"source_id": 2, "sequence_number": 1, "ocr_json": '{"text":"b"}'},
        {"source_id": 3, "sequence_number": 2, "ocr_json": '{"text":"c"}'},
    ]

    mapping = align_sources_to_chunks(sources, chunk_count=2, strict=False)
    assert mapping == {0: 0, 1: 1}


def test_extract_ocr_text_returns_text_when_present() -> None:
    ocr_json = '{"text":"fresh","regions":[{"text":"stale"}]}'

    assert extract_ocr_text(ocr_json) == "fresh"


def test_extract_ocr_text_returns_empty_when_text_missing() -> None:
    ocr_json = '{"regions":[{"text":"A\\nB"},{"text":"C\\r\\nD"},{"text":" E "}]}'

    assert extract_ocr_text(ocr_json) == ""


def test_extract_ocr_text_returns_text_when_regions_missing() -> None:
    assert extract_ocr_text('{"text":"line1\\nline2"}') == "line1\nline2"
