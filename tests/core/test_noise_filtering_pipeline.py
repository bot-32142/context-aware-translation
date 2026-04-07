from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_aware_translation.core.context_manager import TranslationContextManager
from context_aware_translation.storage.schema.book_db import TermRecord


@pytest.mark.asyncio
async def test_mark_noise_terms_deletes_zero_occurrence_terms_and_marks_symbol_noise() -> None:
    term_repo = MagicMock()
    term_repo.get_last_noise_filtered_at.return_value = None
    term_repo.list_term_records.return_value = [
        TermRecord(
            key="noise_term",
            descriptions={"12": "desc"},
            occurrence={},
            votes=1,
            total_api_calls=1,
            created_at=10.0,
        ),
        TermRecord(
            key="imported_term",
            descriptions={"imported": "desc"},
            occurrence={},
            votes=1,
            total_api_calls=1,
            created_at=20.0,
        ),
        TermRecord(
            key="matched_term",
            descriptions={"30": "desc"},
            occurrence={"30": 1},
            votes=1,
            total_api_calls=1,
            created_at=30.0,
        ),
        TermRecord(
            key="!!!",
            descriptions={"40": "desc"},
            occurrence={"40": 1},
            votes=1,
            total_api_calls=1,
            created_at=40.0,
        ),
    ]

    manager = SimpleNamespace(term_repo=term_repo)

    count = await TranslationContextManager.mark_noise_terms(manager)

    assert count == 2
    term_repo.delete_terms.assert_called_once_with(["noise_term"])
    term_repo.update_terms_bulk.assert_called_once_with(["!!!"], ignored=True, is_reviewed=True)
    term_repo.set_last_noise_filtered_at.assert_called_once_with(40.0)


@pytest.mark.asyncio
async def test_review_terms_runs_noise_filter_before_loading_pending_terms() -> None:
    events: list[str] = []

    async def _mark_noise_terms(*, cancel_check=None, term_keys=None) -> int:  # noqa: ANN001
        _ = cancel_check
        _ = term_keys
        events.append("noise")
        return 1

    term_repo = MagicMock()
    term_repo.get_terms_pending_review.side_effect = lambda: events.append("pending") or []

    manager = SimpleNamespace(
        term_reviewer=object(),
        term_repo=term_repo,
        mark_noise_terms=AsyncMock(side_effect=_mark_noise_terms),
    )

    await TranslationContextManager.review_terms(manager)

    assert events == ["noise", "pending"]
    manager.mark_noise_terms.assert_awaited_once()


def test_get_term_keys_for_documents_only_returns_terms_linked_to_selected_chunks() -> None:
    term_repo = MagicMock()
    term_repo.list_chunks.return_value = [SimpleNamespace(chunk_id=12), SimpleNamespace(chunk_id=13)]
    term_repo.list_term_records.return_value = [
        TermRecord(key="selected", descriptions={"12": "desc"}, occurrence={}, votes=1, total_api_calls=1),
        TermRecord(key="occurs-here", descriptions={"99": "desc"}, occurrence={"13": 2}, votes=1, total_api_calls=1),
        TermRecord(key="other-doc", descriptions={"44": "desc"}, occurrence={"44": 1}, votes=1, total_api_calls=1),
    ]

    manager = SimpleNamespace(term_repo=term_repo)

    result = TranslationContextManager.get_term_keys_for_documents(manager, [7])

    assert result == {"selected", "occurs-here"}
