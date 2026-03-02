"""Tests for OCRTaskWorker run/cancel/progress behavior."""

from __future__ import annotations

import asyncio
import base64
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


class _WorkflowSessionContext:
    def __init__(self, session, exit_error: Exception | None = None) -> None:
        self._session = session
        self._exit_error = exit_error

    def __enter__(self):
        return self._session

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._exit_error is not None:
            raise self._exit_error
        return False


def _capture_signals(worker):
    success: list[object] = []
    cancelled: list[bool] = []
    errors: list[str] = []
    worker.finished_success.connect(lambda value: success.append(value))
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.error.connect(lambda message: errors.append(message))
    return success, cancelled, errors


def _book_manager_with_db(tmp_path: Path) -> MagicMock:
    manager = MagicMock()
    manager.get_book_db_path.return_value = tmp_path / "book.db"
    return manager


def _make_pending_sources(*source_ids: int) -> list[dict]:
    return [{"source_id": sid} for sid in source_ids]


def _tiny_png_bytes() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4//8/AwAI/AL+XJadOQAAAABJRU5ErkJggg=="
    )


# --- run action ---


def test_run_ocr_happy_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """run action calls ocr ops and updates task status to completed."""
    from context_aware_translation.ui.workers.ocr_task_worker import OCRTaskWorker

    task_store = MagicMock()
    worker = OCRTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-1",
        document_id=10,
        task_store=task_store,
    )

    mock_repo = MagicMock()
    mock_repo.get_document_sources_needing_ocr.return_value = _make_pending_sources(1, 2, 3)

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.SQLiteBookDB",
        lambda *_args, **_kwargs: MagicMock(),
    )
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.DocumentRepository",
        lambda *_args, **_kwargs: mock_repo,
    )

    mock_context = MagicMock()

    async def _run_ocr(_context, **_kwargs):
        return None

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowSessionContext(mock_context),
    )
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.ocr_ops.run_ocr",
        _run_ocr,
    )

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert errors == []
    assert cancelled == []
    assert success[0]["action"] == "run"
    assert success[0]["task_id"] == "task-1"
    task_store.update.assert_any_call("task-1", status="running")
    task_store.update.assert_any_call("task-1", status="completed")


def test_run_ocr_with_source_ids_none_resolves_all_pending(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """When source_ids=None, resolves to all pending IDs for the document."""
    from context_aware_translation.ui.workers.ocr_task_worker import OCRTaskWorker

    task_store = MagicMock()
    worker = OCRTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-2",
        document_id=10,
        source_ids=None,
        task_store=task_store,
    )

    mock_repo = MagicMock()
    mock_repo.get_document_sources_needing_ocr.return_value = _make_pending_sources(5, 6, 7)

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.SQLiteBookDB",
        lambda *_args, **_kwargs: MagicMock(),
    )
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.DocumentRepository",
        lambda *_args, **_kwargs: mock_repo,
    )

    captured_source_ids: list = []
    mock_context = MagicMock()

    async def _capture_run_ocr(_context, **kwargs):
        ids = kwargs.get("source_ids", [])
        captured_source_ids.extend(ids or [])

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowSessionContext(mock_context),
    )
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.ocr_ops.run_ocr",
        _capture_run_ocr,
    )

    worker.run()

    assert set(captured_source_ids) == {5, 6, 7}


def test_run_ocr_filters_cross_document_source_ids(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Explicit source_ids from a different document are filtered out."""
    from context_aware_translation.ui.workers.ocr_task_worker import OCRTaskWorker

    task_store = MagicMock()
    # Provide source_ids 10, 20, 30 but only 10 and 20 belong to this document
    worker = OCRTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-3",
        document_id=10,
        source_ids=[10, 20, 30],  # 30 belongs to another document
        task_store=task_store,
    )

    mock_repo = MagicMock()
    # Only IDs 10 and 20 are pending for document 10
    mock_repo.get_document_sources_needing_ocr.return_value = _make_pending_sources(10, 20)

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.SQLiteBookDB",
        lambda *_args, **_kwargs: MagicMock(),
    )
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.DocumentRepository",
        lambda *_args, **_kwargs: mock_repo,
    )

    captured_source_ids: list = []
    mock_context = MagicMock()

    async def _capture_run_ocr(_context, **kwargs):
        ids = kwargs.get("source_ids", [])
        captured_source_ids.extend(ids or [])

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowSessionContext(mock_context),
    )
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.ocr_ops.run_ocr",
        _capture_run_ocr,
    )

    worker.run()

    assert 30 not in captured_source_ids
    assert 10 in captured_source_ids
    assert 20 in captured_source_ids


def test_run_ocr_loader_targets_selected_document_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """OCR worker should load only the selected document, not all book documents."""
    from context_aware_translation.ui.workers.ocr_task_worker import OCRTaskWorker

    task_store = MagicMock()
    worker = OCRTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-single-doc",
        document_id=99,
        task_store=task_store,
    )

    monkeypatch.setattr(worker, "_resolve_source_ids_for_document", lambda: [1001])

    fake_loaded_doc = MagicMock()
    load_by_id_calls: list[tuple[int, object]] = []

    def _load_by_id(_repo, document_id, ocr_config):
        load_by_id_calls.append((document_id, ocr_config))
        return fake_loaded_doc

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.Document.load_by_id",
        _load_by_id,
    )

    mock_context = MagicMock()
    loaded_docs: list[object] = []

    async def _capture_run_ocr(_context, **kwargs):
        loader = kwargs["document_loader"]
        loaded_docs.extend(loader(MagicMock(), MagicMock()))
        return 0

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowSessionContext(mock_context),
    )
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.ocr_ops.run_ocr",
        _capture_run_ocr,
    )

    worker.run()

    assert load_by_id_calls
    assert load_by_id_calls[0][0] == 99
    assert loaded_docs == [fake_loaded_doc]


def test_run_ocr_for_manga_uses_manga_ocr_pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """A manga OCR task must execute MangaDocument.process_ocr -> ocr_manga_image."""
    from context_aware_translation.config import OCRConfig
    from context_aware_translation.storage.book_db import SQLiteBookDB
    from context_aware_translation.storage.document_repository import DocumentRepository
    from context_aware_translation.ui.workers.ocr_task_worker import OCRTaskWorker

    db = SQLiteBookDB(tmp_path / "book.db")
    repo = DocumentRepository(db)
    document_id = repo.insert_document("manga")
    source_id = repo.insert_document_source(
        document_id,
        0,
        "image",
        binary_content=_tiny_png_bytes(),
        mime_type="image/png",
        is_ocr_completed=False,
    )
    db.commit()

    task_store = MagicMock()
    worker = OCRTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-manga-pipeline",
        document_id=document_id,
        source_ids=[source_id],
        task_store=task_store,
    )

    mock_context = SimpleNamespace(
        document_repo=repo,
        config=SimpleNamespace(ocr_config=OCRConfig(concurrency=1, max_retries=0)),
        llm_client=MagicMock(),
    )

    mock_manga_ocr = AsyncMock(return_value="hello manga")
    mock_epub_ocr = AsyncMock(return_value=None)
    monkeypatch.setattr("context_aware_translation.llm.manga_ocr.ocr_manga_image", mock_manga_ocr)
    monkeypatch.setattr("context_aware_translation.llm.epub_ocr.ocr_epub_images", mock_epub_ocr)
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowSessionContext(mock_context),
    )

    worker.run()

    assert mock_manga_ocr.await_count == 1
    assert mock_epub_ocr.await_count == 0

    db.refresh()
    saved = repo.get_source_ocr_json(source_id) or ""
    assert '"text"' in saved
    assert '"embedded_text"' not in saved
    db.close()


def test_run_ocr_cancellation_marks_cancelled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Cancellation during run catches OperationCancelledError and marks cancelled."""
    from context_aware_translation.core.cancellation import OperationCancelledError
    from context_aware_translation.ui.workers.ocr_task_worker import OCRTaskWorker

    task_store = MagicMock()
    worker = OCRTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-cancel",
        document_id=10,
        task_store=task_store,
    )

    mock_repo = MagicMock()
    mock_repo.get_document_sources_needing_ocr.return_value = _make_pending_sources(1)

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.SQLiteBookDB",
        lambda *_args, **_kwargs: MagicMock(),
    )
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.DocumentRepository",
        lambda *_args, **_kwargs: mock_repo,
    )

    mock_context = MagicMock()

    async def _run_ocr(_context, **_kwargs):
        raise OperationCancelledError("cancelled")

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowSessionContext(mock_context),
    )
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.ocr_ops.run_ocr",
        _run_ocr,
    )

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert success == []
    assert cancelled == [True]
    assert errors == []
    task_store.update.assert_any_call("task-cancel", status="cancelled", cancel_requested=False)


def test_run_ocr_failure_marks_failed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Exception during run marks task as failed with error message."""
    from context_aware_translation.ui.workers.ocr_task_worker import OCRTaskWorker

    task_store = MagicMock()
    worker = OCRTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-fail",
        document_id=10,
        task_store=task_store,
    )

    mock_repo = MagicMock()
    mock_repo.get_document_sources_needing_ocr.return_value = _make_pending_sources(1)

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.SQLiteBookDB",
        lambda *_args, **_kwargs: MagicMock(),
    )
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.DocumentRepository",
        lambda *_args, **_kwargs: mock_repo,
    )

    mock_context = MagicMock()

    async def _run_ocr(_context, **_kwargs):
        raise RuntimeError("ocr failed")

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowSessionContext(mock_context),
    )
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.ocr_ops.run_ocr",
        _run_ocr,
    )

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert success == []
    assert cancelled == []
    assert len(errors) == 1
    assert "ocr failed" in errors[0]
    task_store.update.assert_any_call("task-fail", status="failed", last_error="ocr failed")


# --- cancel action ---


def test_cancel_action_marks_cancelled(tmp_path: Path):
    """cancel action sets cancelled status in task store immediately."""
    from context_aware_translation.ui.workers.ocr_task_worker import OCRTaskWorker

    task_store = MagicMock()
    worker = OCRTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="cancel",
        task_id="task-cancel",
        document_id=10,
        task_store=task_store,
    )

    worker.run()

    task_store.update.assert_called_once_with("task-cancel", status="cancelled", cancel_requested=False)


def test_cancel_action_calls_notify_task_changed(tmp_path: Path):
    """cancel action calls notify_task_changed callback."""
    from context_aware_translation.ui.workers.ocr_task_worker import OCRTaskWorker

    task_store = MagicMock()
    notify = MagicMock()
    worker = OCRTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="cancel",
        task_id="task-cancel",
        document_id=10,
        task_store=task_store,
        notify_task_changed=notify,
    )

    worker.run()

    notify.assert_called_with("book-id")


# --- progress callback ---


def test_progress_callback_updates_task_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Progress callback updates task_store with completed/total items."""
    from context_aware_translation.core.progress import ProgressUpdate
    from context_aware_translation.ui.workers.ocr_task_worker import OCRTaskWorker

    task_store = MagicMock()
    worker = OCRTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-progress",
        document_id=10,
        task_store=task_store,
    )

    mock_repo = MagicMock()
    mock_repo.get_document_sources_needing_ocr.return_value = _make_pending_sources(1)

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.SQLiteBookDB",
        lambda *_args, **_kwargs: MagicMock(),
    )
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.DocumentRepository",
        lambda *_args, **_kwargs: mock_repo,
    )

    mock_context = MagicMock()

    async def _emit_progress_then_done(_context, **kwargs):
        cb = kwargs.get("progress_callback")
        if cb:
            cb(ProgressUpdate(step="ocr", current=1, total=5))

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowSessionContext(mock_context),
    )
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.ocr_ops.run_ocr",
        _emit_progress_then_done,
    )

    worker.run()

    task_store.update.assert_any_call("task-progress", completed_items=1, total_items=5)


def test_run_ocr_reports_incremental_item_progress(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """run action should report item count during OCR, not only at completion."""
    from context_aware_translation.core.progress import ProgressUpdate
    from context_aware_translation.ui.workers.ocr_task_worker import OCRTaskWorker

    task_store = MagicMock()
    worker = OCRTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-live-progress",
        document_id=10,
        task_store=task_store,
    )

    monkeypatch.setattr(worker, "_resolve_source_ids_for_document", lambda: [1, 2, 3])

    mock_context = MagicMock()

    async def _run_ocr(_context, **kwargs):
        cb = kwargs.get("progress_callback")
        if cb:
            cb(ProgressUpdate(step="ocr", current=1, total=3))
            cb(ProgressUpdate(step="ocr", current=2, total=3))
            cb(ProgressUpdate(step="ocr", current=3, total=3))
            await asyncio.sleep(0.01)
        return 3

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _WorkflowSessionContext(mock_context),
    )
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.ocr_ops.run_ocr",
        _run_ocr,
    )

    worker.run()

    completed_values = [
        int(call.kwargs["completed_items"])
        for call in task_store.update.call_args_list
        if "completed_items" in call.kwargs and int(call.kwargs.get("total_items", -1)) == 3
    ]
    assert any(0 < value < 3 for value in completed_values)
    assert 3 in completed_values


# --- config snapshot ---


def test_run_uses_config_snapshot_when_provided(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """When config_snapshot_json is set, WorkflowSession.from_snapshot is used."""
    import json as _json

    from context_aware_translation.ui.workers.ocr_task_worker import OCRTaskWorker

    snapshot = _json.dumps({"snapshot_version": 1})
    task_store = MagicMock()
    worker = OCRTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-snap",
        document_id=10,
        task_store=task_store,
        config_snapshot_json=snapshot,
    )

    mock_repo = MagicMock()
    mock_repo.get_document_sources_needing_ocr.return_value = _make_pending_sources(1)

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.SQLiteBookDB",
        lambda *_args, **_kwargs: MagicMock(),
    )
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.DocumentRepository",
        lambda *_args, **_kwargs: mock_repo,
    )

    mock_context = MagicMock()
    from_snapshot_calls: list = []

    async def _run_ocr(_context, **_kwargs):
        return None

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.WorkflowSession.from_snapshot",
        lambda snap, book_id: (from_snapshot_calls.append((snap, book_id)) or _WorkflowSessionContext(mock_context)),
    )
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_task_worker.ocr_ops.run_ocr",
        _run_ocr,
    )

    worker.run()

    assert len(from_snapshot_calls) == 1
    assert from_snapshot_calls[0][0] == snapshot
    assert from_snapshot_calls[0][1] == "book-id"


# --- unknown action ---


def test_unknown_action_raises(tmp_path: Path):
    """Unknown action raises an error signal."""
    from context_aware_translation.ui.workers.ocr_task_worker import OCRTaskWorker

    worker = OCRTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="unknown_action",
        task_id="task-x",
        document_id=10,
    )

    errors: list[str] = []
    worker.error.connect(lambda msg: errors.append(msg))
    worker.run()

    assert len(errors) == 1
    assert "unknown_action" in errors[0]


# --- helpers ---


async def _async_noop(**kwargs):
    pass


async def _async_raise(exc: Exception, **_kwargs):
    raise exc
