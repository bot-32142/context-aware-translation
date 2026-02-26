"""Pure mapping from TaskRecord to TaskRowVM."""

from __future__ import annotations

import json

from context_aware_translation.storage.task_store import TaskRecord

from .task_view_models import TaskRowVM

_TASK_TYPE_TITLES: dict[str, str] = {
    "batch_translation": "Batch Translation",
    "glossary_extraction": "Glossary Extraction",
    "glossary_export": "Glossary Export",
    "glossary_review": "Glossary Review",
    "glossary_translation": "Glossary Translation",
    "sync_translation": "Sync Translation",
    "chunk_retranslation": "Chunk Retranslation",
}


def _make_title(record: TaskRecord) -> str:
    title = _TASK_TYPE_TITLES.get(record.task_type)
    if title is None:
        raise RuntimeError(f"Unknown task type: {record.task_type!r}")
    return f"{title} #{record.task_id[:8]}"


_NO_DOCUMENT_TASK_TYPES: frozenset[str] = frozenset({"glossary_export", "glossary_review", "glossary_translation"})


def _make_scope_label(record: TaskRecord) -> str:
    if record.task_type in _NO_DOCUMENT_TASK_TYPES:
        return "No document scope"
    document_ids_json = record.document_ids_json
    if not document_ids_json:
        return "All documents"
    try:
        ids = json.loads(document_ids_json)
    except (json.JSONDecodeError, TypeError):
        return "All documents"
    if not isinstance(ids, list) or len(ids) == 0:
        return "All documents"
    count = len(ids)
    if count == 1:
        return "1 document"
    return f"{count} documents"


def _normalize_progress(value: object) -> int:
    """Coerce progress fields to non-negative ints safe for UI rendering."""
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, normalized)


def map_task_to_row_vm(record: TaskRecord) -> TaskRowVM:
    """Map a single TaskRecord to a TaskRowVM.

    Pure function — no side effects, no engine dependency.
    """
    return TaskRowVM(
        task_id=record.task_id,
        book_id=record.book_id,
        task_type=record.task_type,
        title=_make_title(record),
        scope_label=_make_scope_label(record),
        status=record.status,
        phase=record.phase,
        completed_items=_normalize_progress(record.completed_items),
        total_items=_normalize_progress(record.total_items),
        failed_items=_normalize_progress(record.failed_items),
        last_error=record.last_error,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def map_tasks_to_row_vms(records: list[TaskRecord]) -> list[TaskRowVM]:
    """Map a batch of TaskRecords to TaskRowVMs."""
    return [map_task_to_row_vm(r) for r in records]
