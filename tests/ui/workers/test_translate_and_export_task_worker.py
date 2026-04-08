"""Tests for translate-and-export worker cancellation and batch resume behavior."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

try:
    from PySide6.QtWidgets import QApplication

    HAS_PYSIDE6 = True
except ImportError:
    HAS_PYSIDE6 = False

pytestmark = pytest.mark.skipif(not HAS_PYSIDE6, reason="PySide6 not available")


@pytest.fixture(autouse=True, scope="module")
def _qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class _WorkflowContext:
    def __init__(self, session) -> None:
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _book_manager_with_db(tmp_path: Path) -> MagicMock:
    manager = MagicMock()
    manager.get_book_db_path.return_value = tmp_path / "book.db"
    return manager


def test_request_batch_cancel_calls_executor_request_cancel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from context_aware_translation.adapters.qt.workers.translate_and_export_task_worker import (
        TranslateAndExportTaskWorker,
    )

    task_store = MagicMock()
    worker = TranslateAndExportTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="cancel",
        task_id="task-1",
        document_id=4,
        format_id="txt",
        output_path="/tmp/out.txt",
        use_batch=True,
        use_reembedding=False,
        enable_polish=True,
        options={},
        task_store=task_store,
    )
    worker._persist_payload = MagicMock()

    executor = MagicMock()
    executor.request_cancel = AsyncMock(return_value=SimpleNamespace(task_id="task-1"))
    monkeypatch.setattr(
        "context_aware_translation.adapters.qt.workers.translate_and_export_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowContext(MagicMock()),
    )
    monkeypatch.setattr(
        "context_aware_translation.adapters.qt.workers.translate_and_export_task_worker.BatchTranslationExecutor.from_workflow",
        lambda *_args, **_kwargs: executor,
    )

    worker._request_batch_cancel({"use_batch": True})

    worker._persist_payload.assert_called_once()
    executor.request_cancel.assert_awaited_once_with("task-1")
    executor.close.assert_called_once()


def test_request_batch_cancel_falls_back_to_live_config_when_snapshot_restore_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from context_aware_translation.adapters.qt.workers.translate_and_export_task_worker import (
        TranslateAndExportTaskWorker,
    )

    task_store = MagicMock()
    worker = TranslateAndExportTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="cancel",
        task_id="task-1",
        document_id=4,
        format_id="txt",
        output_path="/tmp/out.txt",
        use_batch=True,
        use_reembedding=False,
        enable_polish=True,
        options={},
        task_store=task_store,
        config_snapshot_json='{"bad":"snapshot"}',
    )
    worker._persist_payload = MagicMock()

    executor = MagicMock()
    executor.request_cancel = AsyncMock(return_value=SimpleNamespace(task_id="task-1"))
    from_book = MagicMock(return_value=_WorkflowContext(MagicMock()))
    monkeypatch.setattr(
        "context_aware_translation.adapters.qt.workers.translate_and_export_task_worker.WorkflowSession.from_snapshot",
        MagicMock(side_effect=RuntimeError("broken snapshot")),
    )
    monkeypatch.setattr(
        "context_aware_translation.adapters.qt.workers.translate_and_export_task_worker.WorkflowSession.from_book",
        from_book,
    )
    monkeypatch.setattr(
        "context_aware_translation.adapters.qt.workers.translate_and_export_task_worker.BatchTranslationExecutor.from_workflow",
        lambda *_args, **_kwargs: executor,
    )

    worker._request_batch_cancel({"use_batch": True})

    from_book.assert_called_once()
    executor.request_cancel.assert_awaited_once_with("task-1")
    executor.close.assert_called_once()


def test_run_short_circuits_to_batch_cancel_when_cancel_requested(tmp_path: Path) -> None:
    from context_aware_translation.adapters.qt.workers.translate_and_export_task_worker import (
        TranslateAndExportTaskWorker,
    )

    task_store = MagicMock()
    task_store.get.return_value = SimpleNamespace(cancel_requested=True, status="cancel_requested", payload_json="{}")
    worker = TranslateAndExportTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-1",
        document_id=4,
        format_id="txt",
        output_path="/tmp/out.txt",
        use_batch=True,
        use_reembedding=False,
        enable_polish=True,
        options={},
        task_store=task_store,
    )
    worker._request_batch_cancel = MagicMock()
    worker._run_pipeline_async = AsyncMock()

    success: list[object] = []
    worker.finished_success.connect(lambda value: success.append(value))

    worker.run()

    worker._request_batch_cancel.assert_called_once()
    worker._run_pipeline_async.assert_not_called()
    assert success == [{"action": "run", "task_id": "task-1"}]
