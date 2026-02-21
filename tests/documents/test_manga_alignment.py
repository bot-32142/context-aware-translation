from __future__ import annotations

import pytest

from context_aware_translation.documents.manga_alignment import (
    align_sources_to_chunks,
    count_nonempty_ocr_sources,
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
