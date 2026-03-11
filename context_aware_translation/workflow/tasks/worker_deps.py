from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

# Imported at runtime (not under TYPE_CHECKING) because frozen-dataclass
# field type annotations are evaluated eagerly by dataclasses and must
# resolve to real classes at import time.
from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.repositories.task_store import TaskStore

if TYPE_CHECKING:
    from context_aware_translation.workflow.runtime import WorkflowContext


class FollowupEnqueue(Protocol):
    def __call__(self, task_type: str, book_id: str, **params: object) -> None: ...


@dataclass(frozen=True)
class WorkerDeps:
    book_manager: BookManager
    task_store: TaskStore
    create_workflow_session: Callable[[str], AbstractContextManager[WorkflowContext]]
    notify_task_changed: Callable[[str], None]
    enqueue_followup: FollowupEnqueue | None = None
