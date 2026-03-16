from __future__ import annotations

from typing import Protocol

from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    BlockerCode,
    QueueActionKind,
    UserMessage,
    UserMessageSeverity,
)
from context_aware_translation.application.contracts.queue import QueueActionRequest, QueueState
from context_aware_translation.application.errors import ApplicationErrorCode
from context_aware_translation.application.runtime import (
    ApplicationRuntime,
    make_blocker,
    queue_item_from_record,
    raise_application_error,
)
from context_aware_translation.workflow.tasks.models import TERMINAL_TASK_STATUSES, TaskAction


class QueueService(Protocol):
    def get_queue(self, *, project_id: str | None = None) -> QueueState: ...

    def apply_action(self, request: QueueActionRequest) -> AcceptedCommand: ...


class DefaultQueueService:
    def __init__(self, runtime: ApplicationRuntime) -> None:
        self._runtime = runtime

    def get_queue(self, *, project_id: str | None = None) -> QueueState:
        records = self._runtime.task_store.list_tasks(
            book_id=project_id,
            include_payload=True,
            include_config_snapshot=False,
        )
        return QueueState(items=[queue_item_from_record(record) for record in records])

    def apply_action(self, request: QueueActionRequest) -> AcceptedCommand:
        if request.action is QueueActionKind.OPEN_RELATED_ITEM:
            raise_application_error(ApplicationErrorCode.UNSUPPORTED, "Open-related-item is handled by UI navigation.")
        command_name = request.action.value
        record = self._runtime.task_store.get(request.queue_item_id)
        if record is None:
            raise_application_error(
                ApplicationErrorCode.NOT_FOUND,
                f"Queue item not found: {request.queue_item_id}",
                queue_item_id=request.queue_item_id,
            )

        if request.action is QueueActionKind.RETRY and record.status not in TERMINAL_TASK_STATUSES:
            raise_application_error(
                ApplicationErrorCode.BLOCKED,
                f"Queue action '{command_name}' is unavailable.",
                queue_item_id=request.queue_item_id,
                project_id=record.book_id,
                decision_code="invalid_state",
            )

        action = self._task_action_for_request(request.action)
        decision = self._runtime.task_engine.preflight_task(request.queue_item_id, action)
        if not decision.allowed:
            blocker = make_blocker(
                BlockerCode.ALREADY_RUNNING_ELSEWHERE
                if decision.code == "blocked_claim_conflict"
                else BlockerCode.NOTHING_TO_DO,
                decision.reason or f"Queue action '{command_name}' is unavailable.",
                project_id=record.book_id,
                document_id=queue_item_from_record(record).document_id,
            )
            raise_application_error(
                ApplicationErrorCode.BLOCKED,
                blocker.message,
                queue_item_id=request.queue_item_id,
                project_id=record.book_id,
                decision_code=decision.code,
            )

        try:
            if request.action is QueueActionKind.RUN:
                record = self._runtime.task_engine.run_task(request.queue_item_id)
            elif request.action is QueueActionKind.RETRY:
                record = self._runtime.task_engine.rerun(request.queue_item_id)
            elif request.action is QueueActionKind.CANCEL:
                self._runtime.task_engine.cancel(request.queue_item_id)
                record = self._runtime.task_store.get(request.queue_item_id) or record
            elif request.action is QueueActionKind.DELETE:
                self._runtime.task_engine.delete(request.queue_item_id)
                record = None
            else:
                raise_application_error(ApplicationErrorCode.UNSUPPORTED, f"Unsupported queue action: {request.action}")
        except Exception as exc:
            project_id = record.book_id if record is not None else None
            raise_application_error(
                ApplicationErrorCode.CONFLICT,
                f"Queue action '{command_name}' could not be applied.",
                queue_item_id=request.queue_item_id,
                project_id=project_id,
                reason=str(exc),
            )
        return AcceptedCommand(
            command_name=command_name,
            command_id=request.queue_item_id,
            queue_item_id=record.task_id if record is not None else request.queue_item_id,
            message=UserMessage(severity=UserMessageSeverity.INFO, text=f"Queue action '{command_name}' applied."),
        )

    @staticmethod
    def _task_action_for_request(action: QueueActionKind) -> TaskAction:
        if action in {QueueActionKind.RUN, QueueActionKind.RETRY}:
            return TaskAction.RUN
        if action is QueueActionKind.CANCEL:
            return TaskAction.CANCEL
        if action is QueueActionKind.DELETE:
            return TaskAction.DELETE
        raise_application_error(ApplicationErrorCode.UNSUPPORTED, f"Unsupported queue action: {action}")
