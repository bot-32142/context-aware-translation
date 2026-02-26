from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from context_aware_translation.workflow.tasks.claims import ResourceClaim

# ---------------------------------------------------------------------------
# Status constants (from task_status.py)
# ---------------------------------------------------------------------------

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_CANCEL_REQUESTED = "cancel_requested"
STATUS_CANCELLING = "cancelling"
STATUS_CANCELLED = "cancelled"
STATUS_COMPLETED = "completed"
STATUS_COMPLETED_WITH_ERRORS = "completed_with_errors"
STATUS_FAILED = "failed"

TERMINAL_TASK_STATUSES = frozenset({STATUS_CANCELLED, STATUS_COMPLETED, STATUS_COMPLETED_WITH_ERRORS, STATUS_FAILED})

# ---------------------------------------------------------------------------
# Phase constants
# ---------------------------------------------------------------------------

PHASE_PREPARE = "prepare"
PHASE_TRANSLATION_SUBMIT = "translation_submit"
PHASE_TRANSLATION_POLL = "translation_poll"
PHASE_TRANSLATION_VALIDATE = "translation_validate"
PHASE_TRANSLATION_FALLBACK = "translation_fallback"
PHASE_POLISH_SUBMIT = "polish_submit"
PHASE_POLISH_POLL = "polish_poll"
PHASE_POLISH_VALIDATE = "polish_validate"
PHASE_POLISH_FALLBACK = "polish_fallback"
PHASE_APPLY = "apply"
PHASE_DONE = "done"

# ---------------------------------------------------------------------------
# TaskAction / Decision
# ---------------------------------------------------------------------------


class TaskAction(StrEnum):
    RUN = "run"
    CANCEL = "cancel"
    DELETE = "delete"


@dataclass(frozen=True)
class Decision:
    allowed: bool
    code: str = "ok"
    reason: str = ""
    args: Mapping[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# ActionSnapshot (from action_snapshot.py)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActionSnapshot:
    running_task_ids: frozenset[str]
    active_claims: frozenset[ResourceClaim]
    now_monotonic: float
    retry_after_by_book: Mapping[str, float]
