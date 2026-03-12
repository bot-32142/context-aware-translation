from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from context_aware_translation.application.services.queue import DefaultQueueService
from context_aware_translation.storage.repositories.task_store import TaskRecord


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
