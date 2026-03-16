"""Tests for TranslationMangaTaskWorker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_worker(
    action: str = "run",
    task_id: str = "task-manga-1",
    book_id: str = "book-1",
    document_ids: list[int] | None = None,
    source_ids: list[int] | None = None,
    config_snapshot_json: str | None = None,
):
    from context_aware_translation.adapters.qt.workers.translation_manga_task_worker import TranslationMangaTaskWorker

    book_manager = MagicMock()
    task_store = MagicMock()
    notify_task_changed = MagicMock()

    return TranslationMangaTaskWorker(
        book_manager,
        book_id,
        action=action,
        task_id=task_id,
        document_ids=document_ids,
        source_ids=source_ids,
        task_store=task_store,
        notify_task_changed=notify_task_changed,
        config_snapshot_json=config_snapshot_json,
    )


def test_worker_run_sets_running_status():
    worker = _make_worker(action="run")

    fake_context = MagicMock()
    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_context)
    fake_session.__exit__ = MagicMock(return_value=False)

    with (
        patch(
            "context_aware_translation.adapters.qt.workers.translation_manga_task_worker.WorkflowSession"
        ) as mock_session_cls,
        patch(
            "context_aware_translation.adapters.qt.workers.translation_manga_task_worker.translation_ops.translate",
            new=_async_none,
        ),
    ):
        mock_session_cls.from_book.return_value = fake_session
        worker._run_translation()

    worker._task_store.update.assert_any_call(worker._task_id, status="running")


def test_worker_run_sets_completed_status():
    worker = _make_worker(action="run")

    fake_context = MagicMock()
    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_context)
    fake_session.__exit__ = MagicMock(return_value=False)

    with (
        patch(
            "context_aware_translation.adapters.qt.workers.translation_manga_task_worker.WorkflowSession"
        ) as mock_session_cls,
        patch(
            "context_aware_translation.adapters.qt.workers.translation_manga_task_worker.translation_ops.translate",
            new=_async_none,
        ),
    ):
        mock_session_cls.from_book.return_value = fake_session
        worker._run_translation()

    worker._task_store.update.assert_any_call(worker._task_id, status="completed")


def test_worker_run_does_not_auto_enqueue_reembedding():
    worker = _make_worker(action="run")
    worker._enqueue_followup = MagicMock()

    fake_context = MagicMock()
    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_context)
    fake_session.__exit__ = MagicMock(return_value=False)

    with (
        patch(
            "context_aware_translation.adapters.qt.workers.translation_manga_task_worker.WorkflowSession"
        ) as mock_session_cls,
        patch(
            "context_aware_translation.adapters.qt.workers.translation_manga_task_worker.translation_ops.translate",
            new=_async_none,
        ),
    ):
        mock_session_cls.from_book.return_value = fake_session
        worker._run_translation()

    worker._enqueue_followup.assert_not_called()


def test_worker_run_uses_snapshot_when_provided():
    import json

    snapshot = json.dumps({"snapshot_version": 1, "config": {}})
    worker = _make_worker(action="run", config_snapshot_json=snapshot)

    fake_context = MagicMock()
    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_context)
    fake_session.__exit__ = MagicMock(return_value=False)

    with (
        patch(
            "context_aware_translation.adapters.qt.workers.translation_manga_task_worker.WorkflowSession"
        ) as mock_session_cls,
        patch(
            "context_aware_translation.adapters.qt.workers.translation_manga_task_worker.translation_ops.translate",
            new=_async_none,
        ),
    ):
        mock_session_cls.from_snapshot.return_value = fake_session
        worker._run_translation()

    mock_session_cls.from_snapshot.assert_called_once_with(snapshot, "book-1")
    mock_session_cls.from_book.assert_not_called()


def test_worker_run_uses_from_book_when_no_snapshot():
    worker = _make_worker(action="run", config_snapshot_json=None)

    fake_context = MagicMock()
    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_context)
    fake_session.__exit__ = MagicMock(return_value=False)

    with (
        patch(
            "context_aware_translation.adapters.qt.workers.translation_manga_task_worker.WorkflowSession"
        ) as mock_session_cls,
        patch(
            "context_aware_translation.adapters.qt.workers.translation_manga_task_worker.translation_ops.translate",
            new=_async_none,
        ),
    ):
        mock_session_cls.from_book.return_value = fake_session
        worker._run_translation()

    mock_session_cls.from_book.assert_called_once_with(worker._book_manager, "book-1")
    mock_session_cls.from_snapshot.assert_not_called()


def test_worker_run_passes_document_ids():
    worker = _make_worker(action="run", document_ids=[1, 2, 3])

    fake_context = MagicMock()
    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_context)
    fake_session.__exit__ = MagicMock(return_value=False)
    calls: list[tuple[tuple, dict]] = []

    async def _translate(*args, **kwargs):
        calls.append((args, kwargs))

    with (
        patch(
            "context_aware_translation.adapters.qt.workers.translation_manga_task_worker.WorkflowSession"
        ) as mock_session_cls,
        patch(
            "context_aware_translation.adapters.qt.workers.translation_manga_task_worker.translation_ops.translate",
            new=_translate,
        ),
    ):
        mock_session_cls.from_book.return_value = fake_session
        worker._run_translation()

    assert len(calls) == 1
    assert calls[0][1].get("document_ids") == [1, 2, 3]


def test_worker_run_passes_source_ids():
    worker = _make_worker(action="run", document_ids=[2], source_ids=[101])

    fake_context = MagicMock()
    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_context)
    fake_session.__exit__ = MagicMock(return_value=False)
    calls: list[tuple[tuple, dict]] = []

    async def _translate(*args, **kwargs):
        calls.append((args, kwargs))

    with (
        patch(
            "context_aware_translation.adapters.qt.workers.translation_manga_task_worker.WorkflowSession"
        ) as mock_session_cls,
        patch(
            "context_aware_translation.adapters.qt.workers.translation_manga_task_worker.translation_ops.translate",
            new=_translate,
        ),
    ):
        mock_session_cls.from_book.return_value = fake_session
        worker._run_translation()

    assert len(calls) == 1
    assert calls[0][1].get("source_ids") == [101]


def test_worker_run_sets_failed_status_on_exception():
    worker = _make_worker(action="run")

    fake_context = MagicMock()
    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_context)
    fake_session.__exit__ = MagicMock(return_value=False)

    with (
        patch(
            "context_aware_translation.adapters.qt.workers.translation_manga_task_worker.WorkflowSession"
        ) as mock_session_cls,
        patch(
            "context_aware_translation.adapters.qt.workers.translation_manga_task_worker.translation_ops.translate",
            new=_raise_runtime_error,
        ),
    ):
        mock_session_cls.from_book.return_value = fake_session
        import contextlib

        with contextlib.suppress(RuntimeError):
            worker._run_translation()

    worker._task_store.update.assert_any_call(worker._task_id, status="failed", last_error="test error")


def test_worker_run_sets_cancelled_status_on_cancel():
    from context_aware_translation.core.cancellation import OperationCancelledError

    worker = _make_worker(action="run")

    fake_context = MagicMock()
    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_context)
    fake_session.__exit__ = MagicMock(return_value=False)

    with (
        patch(
            "context_aware_translation.adapters.qt.workers.translation_manga_task_worker.WorkflowSession"
        ) as mock_session_cls,
        patch(
            "context_aware_translation.adapters.qt.workers.translation_manga_task_worker.translation_ops.translate",
            new=_raise_cancelled,
        ),
    ):
        mock_session_cls.from_book.return_value = fake_session
        import contextlib

        with contextlib.suppress(OperationCancelledError):
            worker._run_translation()

    worker._task_store.update.assert_any_call(worker._task_id, status="cancelled", cancel_requested=False)


def test_worker_cancel_sets_cancelled_status():
    worker = _make_worker(action="cancel")
    worker._run_cancel()

    worker._task_store.update.assert_called_once_with(worker._task_id, status="cancelled", cancel_requested=False)


def test_worker_cancel_notifies():
    worker = _make_worker(action="cancel")
    worker._run_cancel()
    worker._notify_task_changed.assert_called_with("book-1")


def test_on_progress_updates_task_store():
    from context_aware_translation.core.progress import ProgressUpdate, WorkflowStep

    worker = _make_worker(action="run")
    update = ProgressUpdate(step=WorkflowStep.TRANSLATE_CHUNKS, current=5, total=20, message="translating")

    worker._on_progress(update)

    worker._task_store.update.assert_called_with(
        worker._task_id,
        completed_items=5,
        total_items=20,
    )


def test_on_progress_notifies():
    from context_aware_translation.core.progress import ProgressUpdate, WorkflowStep

    worker = _make_worker(action="run")
    update = ProgressUpdate(step=WorkflowStep.TRANSLATE_CHUNKS, current=3, total=10, message="")

    worker._on_progress(update)

    worker._notify_task_changed.assert_called_with("book-1")


def test_notify_calls_callback():
    worker = _make_worker()
    worker._notify()
    worker._notify_task_changed.assert_called_with("book-1")


def test_notify_no_callback():
    from context_aware_translation.adapters.qt.workers.translation_manga_task_worker import TranslationMangaTaskWorker

    worker = TranslationMangaTaskWorker(
        MagicMock(),
        "book-1",
        action="run",
        notify_task_changed=None,
    )
    # Should not raise
    worker._notify()


def test_unknown_action_raises():
    worker = _make_worker(action="unknown")
    try:
        worker._execute()
        raise AssertionError("Expected ValueError")
    except ValueError as e:
        assert "unknown" in str(e).lower() or "Unknown" in str(e)


# ---------------------------------------------------------------------------
# Helpers for async coroutine mocking
# ---------------------------------------------------------------------------


async def _async_none(*_args, **_kwargs):
    return None


async def _raise_runtime_error(*_args, **_kwargs):
    raise RuntimeError("test error")


async def _raise_cancelled(*_args, **_kwargs):
    from context_aware_translation.core.cancellation import OperationCancelledError

    raise OperationCancelledError("cancelled")
