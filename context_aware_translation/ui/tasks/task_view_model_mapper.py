"""Pure mapping from TaskRecord to TaskRowVM."""

from __future__ import annotations

import json

from context_aware_translation.storage.task_store import TaskRecord

from ..i18n import translate_scope_label, translate_task_type
from .task_view_models import TaskRowVM


def _make_title(record: TaskRecord) -> str:
    title = translate_task_type(record.task_type)
    if title == record.task_type:
        raise RuntimeError(f"Unknown task type: {record.task_type}")
    return f"{title} #{record.task_id[:8]}"


_NO_DOCUMENT_TASK_TYPES: frozenset[str] = frozenset({"glossary_export", "glossary_review", "glossary_translation"})


def _make_scope_label(record: TaskRecord) -> str:
    if record.task_type in _NO_DOCUMENT_TASK_TYPES:
        return translate_scope_label(None)
    document_ids_json = record.document_ids_json
    if not document_ids_json:
        return translate_scope_label(0)
    try:
        ids = json.loads(document_ids_json)
    except (json.JSONDecodeError, TypeError):
        return translate_scope_label(0)
    if not isinstance(ids, list) or len(ids) == 0:
        return translate_scope_label(0)
    return translate_scope_label(len(ids))


def _normalize_progress(value: int | float | str | None) -> int:
    """Coerce progress fields to non-negative ints safe for UI rendering."""
    if value is None:
        return 0
    normalized: int
    if isinstance(value, int):
        normalized = value
    elif isinstance(value, float):
        normalized = int(value)
    elif isinstance(value, str):
        try:
            normalized = int(value)
        except ValueError:
            return 0
    else:
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
