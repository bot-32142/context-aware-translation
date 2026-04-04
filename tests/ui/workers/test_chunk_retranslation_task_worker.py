"""Tests for ChunkRetranslationTaskWorker progress and terminal state handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from context_aware_translation.core.progress import ProgressUpdate, WorkflowStep


def _make_worker(action: str = "run", task_id: str = "task-chunk-1"):
    from context_aware_translation.adapters.qt.workers.chunk_retranslation_task_worker import (
        ChunkRetranslationTaskWorker,
    )

    return ChunkRetranslationTaskWorker(
        MagicMock(),
        "book-1",
        action=action,
        task_id=task_id,
        chunk_id=42,
        document_id=7,
        task_store=MagicMock(),
        notify_task_changed=MagicMock(),
    )


def test_worker_run_passes_progress_callback_and_marks_completed():
    worker = _make_worker()
    fake_context = MagicMock()
    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_context)
    fake_session.__exit__ = MagicMock(return_value=False)

    with (
        patch(
            "context_aware_translation.adapters.qt.workers.chunk_retranslation_task_worker.WorkflowSession.from_book",
            return_value=fake_session,
        ),
        patch(
            "context_aware_translation.adapters.qt.workers.chunk_retranslation_task_worker.translation_ops.retranslate_chunk",
            new=AsyncMock(return_value="translated"),
        ) as mock_retranslate,
    ):
        worker._run_retranslation()

    assert mock_retranslate.await_args.kwargs["progress_callback"] == worker._on_progress
    worker._task_store.update.assert_any_call(
        worker._task_id,
        status="completed",
        phase="done",
        last_error=None,
    )


def test_worker_run_marks_cancelled_with_done_phase():
    from context_aware_translation.core.cancellation import OperationCancelledError

    worker = _make_worker()
    fake_context = MagicMock()
    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_context)
    fake_session.__exit__ = MagicMock(return_value=False)

    with (
        patch(
            "context_aware_translation.adapters.qt.workers.chunk_retranslation_task_worker.WorkflowSession.from_book",
            return_value=fake_session,
        ),
        patch(
            "context_aware_translation.adapters.qt.workers.chunk_retranslation_task_worker.translation_ops.retranslate_chunk",
            new=AsyncMock(side_effect=OperationCancelledError("cancelled")),
        ),
    ):
        try:
            worker._run_retranslation()
            raise AssertionError("Expected OperationCancelledError")
        except OperationCancelledError:
            pass

    worker._task_store.update.assert_any_call(
        worker._task_id,
        status="cancelled",
        phase="done",
        cancel_requested=False,
    )


def test_worker_run_marks_failed_with_done_phase():
    worker = _make_worker()
    fake_context = MagicMock()
    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_context)
    fake_session.__exit__ = MagicMock(return_value=False)

    with (
        patch(
            "context_aware_translation.adapters.qt.workers.chunk_retranslation_task_worker.WorkflowSession.from_book",
            return_value=fake_session,
        ),
        patch(
            "context_aware_translation.adapters.qt.workers.chunk_retranslation_task_worker.translation_ops.retranslate_chunk",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
    ):
        try:
            worker._run_retranslation()
            raise AssertionError("Expected RuntimeError")
        except RuntimeError:
            pass

    worker._task_store.update.assert_any_call(
        worker._task_id,
        status="failed",
        phase="done",
        last_error="boom",
    )


def test_worker_cancel_marks_done_phase():
    worker = _make_worker(action="cancel")

    worker._run_cancel()

    worker._task_store.update.assert_called_once_with(
        worker._task_id,
        status="cancelled",
        phase="done",
        cancel_requested=False,
    )


def test_on_progress_updates_task_store_with_phase_and_counts():
    worker = _make_worker()

    worker._on_progress(
        ProgressUpdate(
            step=WorkflowStep.TERM_MEMORY,
            current=1,
            total=3,
            message="Summarizing term memory 1/3",
        )
    )

    worker._task_store.update.assert_called_once_with(
        worker._task_id,
        phase="term_memory",
        completed_items=1,
        total_items=3,
    )
    worker._notify_task_changed.assert_called_with("book-1")
