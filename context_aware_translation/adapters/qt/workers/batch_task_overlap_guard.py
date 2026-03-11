"""DB-backed overlap guard for batch task reservations."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context_aware_translation.storage.task_store import TaskStore

logger = logging.getLogger(__name__)


def has_any_batch_task_overlap(
    task_store: TaskStore,
    book_id: str,
    document_ids: list[int] | None,
    *,
    exclude_task_ids: set[str] | None = None,
) -> bool:
    """Return True when any existing batch task overlaps selected docs.

    Rules:
    - Overlap semantics match DocumentOperationTracker (None = all docs overlaps everything).
    - exclude_task_ids: skip these task IDs (e.g. the task being run itself).
    - No status filtering: all task rows are considered blockers.
    """
    tasks = task_store.list_tasks(book_id=book_id, task_type="batch_translation")
    for task in tasks:
        if exclude_task_ids and task.task_id in exclude_task_ids:
            continue
        task_doc_ids = _parse_task_document_ids(task)
        if _ids_overlap(task_doc_ids, document_ids):
            return True
    return False


def _parse_task_document_ids(task: object) -> list[int] | None:
    """Extract document_ids from a batch task record."""
    raw = getattr(task, "document_ids_json", None)
    if raw is None or raw == "" or raw == "null":
        return None
    try:
        parsed = json.loads(raw)
        if parsed is None:
            return None
        return [int(doc_id) for doc_id in parsed]
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _ids_overlap(a: list[int] | None, b: list[int] | None) -> bool:
    """Check if two document ID sets overlap. None means 'all docs'."""
    if a is None or b is None:
        return True
    return bool(set(a) & set(b))
