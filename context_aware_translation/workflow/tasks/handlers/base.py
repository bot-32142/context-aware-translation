from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from context_aware_translation.storage.task_store import TaskRecord
    from context_aware_translation.workflow.tasks.claims import DocumentScope, ResourceClaim
    from context_aware_translation.workflow.tasks.models import ActionSnapshot, Decision, TaskAction
    from context_aware_translation.workflow.tasks.worker_deps import WorkerDeps


class CancelDispatchPolicy(StrEnum):
    LOCAL_TERMINALIZE = "local_terminalize"
    REQUIRE_REMOTE_CONFIRMATION = "require_remote_confirmation"


class CancelOutcome(StrEnum):
    CONFIRMED_CANCELLED = "confirmed_cancelled"
    PROVIDER_TERMINAL_COMPLETED = "provider_terminal_completed"
    PROVIDER_TERMINAL_FAILED = "provider_terminal_failed"
    RETRYABLE_TRANSIENT = "retryable_transient"
    INDETERMINATE_PROVIDER_RESPONSE = "indeterminate_provider_response"


@runtime_checkable
class TaskTypeHandler(Protocol):
    task_type: str

    def decode_payload(self, record: TaskRecord) -> dict[str, object]: ...
    def scope(self, record: TaskRecord, payload: object) -> DocumentScope: ...
    def claims(self, record: TaskRecord, payload: object) -> frozenset[ResourceClaim]: ...
    def can(self, action: TaskAction, record: TaskRecord, payload: object, snapshot: ActionSnapshot) -> Decision: ...
    def can_autorun(self, record: TaskRecord, payload: object, snapshot: ActionSnapshot) -> Decision: ...
    def validate_submit(self, book_id: str, params: dict[str, object], deps: WorkerDeps) -> Decision: ...
    def pre_delete(self, record: TaskRecord, payload: object, deps: WorkerDeps) -> list[str]: ...
    def build_worker(self, action: TaskAction, record: TaskRecord, payload: object, deps: WorkerDeps) -> object: ...
    def validate_run(self, record: TaskRecord, payload: object, deps: WorkerDeps) -> Decision: ...
    def cancel_dispatch_policy(self, record: TaskRecord, payload: object) -> CancelDispatchPolicy: ...
    def classify_cancel_outcome(
        self, record: TaskRecord, payload: object, provider_result: object
    ) -> CancelOutcome: ...
