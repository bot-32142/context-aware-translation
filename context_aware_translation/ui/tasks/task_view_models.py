"""View-model contracts for task list UI rendering."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskRowVM:
    """Display-only view-model for a single task row.

    Pure data contract — no action decisions, no engine dependency.
    """

    task_id: str
    book_id: str
    task_type: str
    title: str
    scope_label: str
    status: str
    phase: str | None
    completed_items: int
    total_items: int
    failed_items: int
    last_error: str | None
    created_at: float
    updated_at: float
