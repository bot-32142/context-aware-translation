from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context_aware_translation.storage.book_manager import BookManager
    from context_aware_translation.storage.task_store import TaskStore
    from context_aware_translation.workflow.service import WorkflowService


@dataclass(frozen=True)
class WorkerDeps:
    book_manager: BookManager
    task_store: TaskStore
    create_workflow_session: Callable[[str], AbstractContextManager[WorkflowService]]
    notify_task_changed: Callable[[str], None]
