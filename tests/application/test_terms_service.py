from __future__ import annotations

from unittest.mock import MagicMock

from context_aware_translation.application.services.terms import DefaultTermsService
from context_aware_translation.storage.schema.book_db import TermRecord


def _service() -> DefaultTermsService:
    return DefaultTermsService(MagicMock())


def test_term_record_to_row_counts_occurrence_by_unique_chunks() -> None:
    service = _service()
    record = TermRecord(
        key="王位継承戦",
        descriptions={"1": "desc"},
        occurrence={"1": 7, "2": 3, "imported": 99},
        votes=1,
        total_api_calls=1,
    )

    row = service._term_record_to_row(record)

    assert row.occurrences == 2


def test_is_structurally_rare_uses_chunk_count_instead_of_total_hits() -> None:
    record = TermRecord(
        key="王位継承戦",
        descriptions={"1": "desc"},
        occurrence={"1": 7},
        votes=1,
        total_api_calls=1,
    )

    assert DefaultTermsService._is_structurally_rare(record) is True
