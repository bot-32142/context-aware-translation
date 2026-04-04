from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from context_aware_translation.application.contracts.common import ProjectRef
from context_aware_translation.application.contracts.terms import (
    TermsScope,
    TermsScopeKind,
    TermsTableState,
    UpsertProjectTermRequest,
)
from context_aware_translation.application.errors import BlockedOperationError
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


def test_upsert_project_term_creates_reviewed_unignored_term() -> None:
    runtime = MagicMock()
    runtime.task_engine.has_active_claims.return_value = False
    runtime.invalidate_terms = MagicMock()
    runtime.get_project_ref.return_value = ProjectRef(project_id="proj-1", name="One Piece")
    db = MagicMock()
    db.get_term.return_value = None
    term_repo = MagicMock()
    term_repo.upsert_terms = MagicMock()

    @contextmanager
    def open_book_db(_project_id: str):
        yield MagicMock(db=db, term_repo=term_repo)

    runtime.open_book_db.side_effect = open_book_db
    service = DefaultTermsService(runtime)
    refreshed_state = TermsTableState(
        scope=TermsScope(kind=TermsScopeKind.PROJECT, project=ProjectRef(project_id="proj-1", name="One Piece"))
    )
    service.get_project_terms = MagicMock(return_value=refreshed_state)

    result = service.upsert_project_term(
        UpsertProjectTermRequest(project_id="proj-1", term="  ルフィ  ", translation="  Luffy  ")
    )

    assert result.updated_existing is False
    assert result.state == refreshed_state
    inserted = term_repo.upsert_terms.call_args.args[0][0]
    assert inserted.key == "ルフィ"
    assert inserted.translated_name == "Luffy"
    assert inserted.ignored is False
    assert inserted.is_reviewed is True
    runtime.invalidate_terms.assert_called_once_with("proj-1")


def test_upsert_project_term_updates_existing_term() -> None:
    runtime = MagicMock()
    runtime.task_engine.has_active_claims.return_value = False
    runtime.invalidate_terms = MagicMock()
    existing = TermRecord(
        key="ルフィ",
        descriptions={"0": "desc"},
        occurrence={"0": 1},
        votes=3,
        total_api_calls=2,
        translated_name="Monkey D. Luffy",
        ignored=True,
        is_reviewed=False,
        updated_at=10.0,
    )
    db = MagicMock()
    db.get_term.return_value = existing
    term_repo = MagicMock()
    term_repo.upsert_terms = MagicMock()

    @contextmanager
    def open_book_db(_project_id: str):
        yield MagicMock(db=db, term_repo=term_repo)

    runtime.open_book_db.side_effect = open_book_db
    service = DefaultTermsService(runtime)
    refreshed_state = TermsTableState(
        scope=TermsScope(kind=TermsScopeKind.PROJECT, project=ProjectRef(project_id="proj-1", name="One Piece"))
    )
    service.get_project_terms = MagicMock(return_value=refreshed_state)

    result = service.upsert_project_term(
        UpsertProjectTermRequest(project_id="proj-1", term="ルフィ", translation="Luffy")
    )

    assert result.updated_existing is True
    updated = term_repo.upsert_terms.call_args.args[0][0]
    assert updated is existing
    assert updated.translated_name == "Luffy"
    assert updated.ignored is False
    assert updated.is_reviewed is True
    assert updated.updated_at is not None
    assert updated.updated_at > 10.0


def test_upsert_project_term_respects_glossary_mutation_blocker() -> None:
    runtime = MagicMock()
    runtime.task_engine.has_active_claims.return_value = True
    service = DefaultTermsService(runtime)

    with pytest.raises(BlockedOperationError):
        service.upsert_project_term(UpsertProjectTermRequest(project_id="proj-1", term="ルフィ", translation="Luffy"))
