from __future__ import annotations

import json
import time

from context_aware_translation.storage.repositories.task_store import TaskRecord
from context_aware_translation.workflow.tasks.claims import ClaimMode, ResourceClaim
from context_aware_translation.workflow.tasks.handlers.glossary_extraction import GlossaryExtractionHandler
from context_aware_translation.workflow.tasks.models import ActionSnapshot

handler = GlossaryExtractionHandler()


def _make_record(
    *,
    status: str = "queued",
    task_id: str = "task-glossary-extraction",
    book_id: str = "book-1",
    document_ids_json: str | None = None,
    payload_json: str | None = None,
) -> TaskRecord:
    now = time.time()
    return TaskRecord(
        task_id=task_id,
        book_id=book_id,
        task_type="glossary_extraction",
        status=status,
        phase=None,
        document_ids_json=document_ids_json,
        payload_json=payload_json,
        config_snapshot_json=None,
        cancel_requested=False,
        total_items=0,
        completed_items=0,
        failed_items=0,
        last_error=None,
        created_at=now,
        updated_at=now,
    )


def _make_snapshot(*, active_claims: frozenset[ResourceClaim] | None = None) -> ActionSnapshot:
    return ActionSnapshot(
        running_task_ids=frozenset(),
        active_claims=active_claims or frozenset(),
        now_monotonic=time.monotonic(),
        retry_after_by_book={},
    )


def test_claims_all_docs_when_scope_is_all():
    record = _make_record(document_ids_json=None)
    claims = handler.claims(record, {})
    assert ResourceClaim("glossary_state", "book-1", "*", ClaimMode.WRITE_EXCLUSIVE) in claims
    assert ResourceClaim("doc", "book-1", "*", ClaimMode.WRITE_EXCLUSIVE) in claims


def test_claims_specific_docs_when_scope_is_some():
    record = _make_record(document_ids_json=json.dumps([5, 6]))
    claims = handler.claims(record, {})
    assert ResourceClaim("glossary_state", "book-1", "*", ClaimMode.WRITE_EXCLUSIVE) in claims
    assert ResourceClaim("doc", "book-1", "5", ClaimMode.WRITE_EXCLUSIVE) in claims
    assert ResourceClaim("doc", "book-1", "6", ClaimMode.WRITE_EXCLUSIVE) in claims
    assert ResourceClaim("doc", "book-1", "*", ClaimMode.WRITE_EXCLUSIVE) not in claims


def test_can_autorun_blocks_when_document_claim_conflicts():
    record = _make_record(document_ids_json=json.dumps([5]))
    snapshot = _make_snapshot(active_claims=frozenset({ResourceClaim("doc", "book-1", "5", ClaimMode.WRITE_EXCLUSIVE)}))
    decision = handler.can_autorun(record, {}, snapshot)
    assert not decision.allowed
    assert "claims conflict" in (decision.reason or "").lower()
