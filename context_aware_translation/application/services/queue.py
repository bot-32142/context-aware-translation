from __future__ import annotations

from typing import Protocol

from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    QueueActionKind,
    UserMessage,
    UserMessageSeverity,
)
from context_aware_translation.application.contracts.queue import QueueActionRequest, QueueState
from context_aware_translation.application.errors import ApplicationErrorCode
from context_aware_translation.application.runtime import (
    ApplicationRuntime,
    queue_item_from_record,
    raise_application_error,
)


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
        record = None
        if request.action is QueueActionKind.RUN:
            record = self._runtime.task_engine.run_task(request.queue_item_id)
            command_name = "run"
        elif request.action is QueueActionKind.RETRY:
            record = self._runtime.task_engine.rerun(request.queue_item_id)
            command_name = "retry"
        elif request.action is QueueActionKind.CANCEL:
            self._runtime.task_engine.cancel(request.queue_item_id)
            record = self._runtime.task_store.get(request.queue_item_id)
            command_name = "cancel"
        elif request.action is QueueActionKind.DELETE:
            self._runtime.task_engine.delete(request.queue_item_id)
            record = None
            command_name = "delete"
        else:
            raise_application_error(ApplicationErrorCode.UNSUPPORTED, f"Unsupported queue action: {request.action}")
        return AcceptedCommand(
            command_name=command_name,
            command_id=request.queue_item_id,
            queue_item_id=record.task_id if record is not None else request.queue_item_id,
            message=UserMessage(severity=UserMessageSeverity.INFO, text=f"Queue action '{command_name}' applied."),
        )
