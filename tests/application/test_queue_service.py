from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from context_aware_translation.application.contracts.common import QueueActionKind
from context_aware_translation.application.contracts.queue import QueueActionRequest
from context_aware_translation.application.errors import ApplicationError
from context_aware_translation.application.services.queue import DefaultQueueService
from context_aware_translation.storage.repositories.task_store import TaskRecord
from context_aware_translation.workflow.tasks.models import Decision


def test_queue_service_uses_lightweight_task_rows() -> None:
    record = TaskRecord(
        task_id="task-1",
        book_id="proj-1",
        task_type="ocr",
        status="queued",
        phase="queued",
        document_ids_json="[4]",
        payload_json=None,
        config_snapshot_json=None,
        cancel_requested=False,
        total_items=0,
        completed_items=0,
        failed_items=0,
        last_error=None,
        created_at=1.0,
        updated_at=2.0,
    )
    task_store = SimpleNamespace(list_tasks=MagicMock(return_value=[record]))
    runtime = SimpleNamespace(task_store=task_store)

    service = DefaultQueueService(runtime)  # type: ignore[arg-type]
    state = service.get_queue(project_id="proj-1")

    task_store.list_tasks.assert_called_once_with(
        book_id="proj-1",
        include_payload=True,
        include_config_snapshot=False,
    )
    assert state.items[0].queue_item_id == "task-1"
    assert state.items[0].document_id == 4


def test_queue_service_recovers_document_target_from_chunk_retranslation_payload() -> None:
    record = TaskRecord(
        task_id="task-2",
        book_id="proj-2",
        task_type="chunk_retranslation",
        status="done",
        phase="completed",
        document_ids_json=None,
        payload_json='{"chunk_id": 7, "document_id": 9}',
        config_snapshot_json=None,
        cancel_requested=False,
        total_items=1,
        completed_items=1,
        failed_items=0,
        last_error=None,
        created_at=1.0,
        updated_at=2.0,
    )
    task_store = SimpleNamespace(list_tasks=MagicMock(return_value=[record]))
    runtime = SimpleNamespace(task_store=task_store)

    service = DefaultQueueService(runtime)  # type: ignore[arg-type]
    state = service.get_queue(project_id="proj-2")

    task_store.list_tasks.assert_called_once_with(
        book_id="proj-2",
        include_payload=True,
        include_config_snapshot=False,
    )
    assert state.items[0].document_id == 9
    assert state.items[0].related_target is not None
    assert state.items[0].related_target.project_id == "proj-2"
    assert state.items[0].related_target.document_id == 9
    assert state.items[0].related_target.kind == "document_translation"


def test_queue_service_blocks_noop_action_instead_of_reporting_success() -> None:
    record = TaskRecord(
        task_id="task-3",
        book_id="proj-3",
        task_type="ocr",
        status="running",
        phase="running",
        document_ids_json="[4]",
        payload_json=None,
        config_snapshot_json=None,
        cancel_requested=False,
        total_items=1,
        completed_items=0,
        failed_items=0,
        last_error=None,
        created_at=1.0,
        updated_at=2.0,
    )
    runtime = SimpleNamespace(
        task_store=SimpleNamespace(get=MagicMock(return_value=record)),
        task_engine=SimpleNamespace(
            preflight_task=MagicMock(return_value=Decision(allowed=False, code="invalid_state", reason="Cannot run"))
        ),
    )

    service = DefaultQueueService(runtime)  # type: ignore[arg-type]

    with pytest.raises(ApplicationError) as exc_info:
        service.apply_action(QueueActionRequest(queue_item_id="task-3", action=QueueActionKind.RUN))

    assert exc_info.value.payload.code == "blocked"


def test_queue_service_wraps_engine_errors() -> None:
    record = TaskRecord(
        task_id="task-4",
        book_id="proj-4",
        task_type="ocr",
        status="failed",
        phase="failed",
        document_ids_json="[4]",
        payload_json=None,
        config_snapshot_json=None,
        cancel_requested=False,
        total_items=1,
        completed_items=0,
        failed_items=1,
        last_error="boom",
        created_at=1.0,
        updated_at=2.0,
    )
    runtime = SimpleNamespace(
        task_store=SimpleNamespace(get=MagicMock(return_value=record)),
        task_engine=SimpleNamespace(
            preflight_task=MagicMock(return_value=Decision(allowed=True)),
            rerun=MagicMock(side_effect=RuntimeError("engine exploded")),
        ),
    )

    service = DefaultQueueService(runtime)  # type: ignore[arg-type]

    with pytest.raises(ApplicationError) as exc_info:
        service.apply_action(QueueActionRequest(queue_item_id="task-4", action=QueueActionKind.RETRY))

    assert exc_info.value.payload.code == "conflict"
    assert exc_info.value.payload.message == "Queue action 'retry' could not be applied."


def test_queue_service_blocks_retry_for_non_terminal_task_before_engine_call() -> None:
    record = TaskRecord(
        task_id="task-5",
        book_id="proj-5",
        task_type="ocr",
        status="running",
        phase="running",
        document_ids_json="[4]",
        payload_json=None,
        config_snapshot_json=None,
        cancel_requested=False,
        total_items=1,
        completed_items=0,
        failed_items=0,
        last_error=None,
        created_at=1.0,
        updated_at=2.0,
    )
    preflight_task = MagicMock(return_value=Decision(allowed=True))
    runtime = SimpleNamespace(
        task_store=SimpleNamespace(get=MagicMock(return_value=record)),
        task_engine=SimpleNamespace(preflight_task=preflight_task),
    )

    service = DefaultQueueService(runtime)  # type: ignore[arg-type]

    with pytest.raises(ApplicationError) as exc_info:
        service.apply_action(QueueActionRequest(queue_item_id="task-5", action=QueueActionKind.RETRY))

    assert exc_info.value.payload.code == "blocked"
    preflight_task.assert_not_called()
