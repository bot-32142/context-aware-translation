from __future__ import annotations

import json
import time

from context_aware_translation.storage.repositories.task_store import TaskRecord
from context_aware_translation.workflow.tasks.claims import ClaimMode, ResourceClaim
from context_aware_translation.workflow.tasks.handlers.image_reembedding import ImageReembeddingHandler
from context_aware_translation.workflow.tasks.models import STATUS_QUEUED, ActionSnapshot


def _make_record(
    *,
    document_ids: list[int] | None = None,
    payload: dict | None = None,
    status: str = STATUS_QUEUED,
    task_id: str = "task-image-reembedding",
    book_id: str = "book-1",
) -> TaskRecord:
    now = time.time()
    return TaskRecord(
        task_id=task_id,
        book_id=book_id,
        task_type="image_reembedding",
        status=status,
        phase=None,
        document_ids_json=json.dumps(document_ids) if document_ids is not None else None,
        payload_json=json.dumps(payload) if payload is not None else None,
        config_snapshot_json=None,
        cancel_requested=False,
        total_items=0,
        completed_items=0,
        failed_items=0,
        last_error=None,
        created_at=now,
        updated_at=now,
    )


def _make_snapshot(
    *,
    active_claims: frozenset[ResourceClaim] | None = None,
) -> ActionSnapshot:
    return ActionSnapshot(
        running_task_ids=frozenset(),
        active_claims=active_claims or frozenset(),
        now_monotonic=time.monotonic(),
        retry_after_by_book={},
    )


handler = ImageReembeddingHandler()


def test_claims_with_explicit_source_ids_use_cooperative_doc_claim_and_source_claims():
    record = _make_record(document_ids=[7], payload={"source_ids": [101, 102], "force": True})
    payload = handler.decode_payload(record)

    claims = handler.claims(record, payload)

    assert ResourceClaim("doc", "book-1", "7", ClaimMode.WRITE_COOPERATIVE) in claims
    assert ResourceClaim("source", "book-1", "101", ClaimMode.WRITE_EXCLUSIVE) in claims
    assert ResourceClaim("source", "book-1", "102", ClaimMode.WRITE_EXCLUSIVE) in claims
    assert ResourceClaim("translation_snapshot", "book-1", "7", ClaimMode.READ_SHARED) in claims


def test_can_autorun_allows_different_source_in_same_document():
    running = _make_record(
        task_id="running",
        document_ids=[7],
        payload={"source_ids": [101], "force": True},
    )
    queued = _make_record(
        task_id="queued",
        document_ids=[7],
        payload={"source_ids": [102], "force": True},
    )

    running_payload = handler.decode_payload(running)
    queued_payload = handler.decode_payload(queued)
    snapshot = _make_snapshot(active_claims=handler.claims(running, running_payload))

    result = handler.can_autorun(queued, queued_payload, snapshot)

    assert result.allowed


def test_can_autorun_blocks_same_source_in_same_document():
    running = _make_record(
        task_id="running",
        document_ids=[7],
        payload={"source_ids": [101], "force": True},
    )
    queued = _make_record(
        task_id="queued",
        document_ids=[7],
        payload={"source_ids": [101], "force": True},
    )

    running_payload = handler.decode_payload(running)
    queued_payload = handler.decode_payload(queued)
    snapshot = _make_snapshot(active_claims=handler.claims(running, running_payload))

    result = handler.can_autorun(queued, queued_payload, snapshot)

    assert not result.allowed
    assert "conflict" in (result.reason or "").lower()
