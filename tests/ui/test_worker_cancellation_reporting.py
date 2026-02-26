"""Regression tests for worker cancellation/success signaling semantics."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from context_aware_translation.core.progress import ProgressUpdate, WorkflowStep

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


class _TranslatorContext:
    def __init__(self, session, exit_error: Exception | None = None) -> None:  # noqa: ANN001
        self._session = session
        self._exit_error = exit_error

    def __enter__(self):  # noqa: ANN204
        return self._session

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001, ANN204
        _ = (exc_type, exc, tb)
        if self._exit_error is not None:
            raise self._exit_error
        return False


def _capture_signals(worker):  # noqa: ANN001
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


def test_sync_translation_task_worker_late_interrupt_still_emits_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from context_aware_translation.ui.workers.sync_translation_task_worker import SyncTranslationTaskWorker

    task_store = MagicMock()
    task_store.update = MagicMock()
    worker = SyncTranslationTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-1",
        task_store=task_store,
    )

    class _Session:
        async def translate(self, **kwargs) -> None:  # noqa: ANN003
            _ = kwargs
            worker.requestInterruption()

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.sync_translation_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _TranslatorContext(_Session()),
    )

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert cancelled == []
    assert success[0]["action"] == "run"
    assert errors == []


def test_import_worker_late_interrupt_still_emits_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from context_aware_translation.ui.workers.import_worker import ImportWorker

    source_path = tmp_path / "sample.txt"
    source_path.write_text("hello", encoding="utf-8")
    book_manager = MagicMock()
    book_manager.get_book_db_path.return_value = tmp_path / "book.db"
    worker = ImportWorker(book_manager, "book-id", source_path, "text")

    class _TextDoc:
        document_type = "text"

        @staticmethod
        def can_import(_path: Path) -> bool:
            return True

        @staticmethod
        def do_import(_repo, _path: Path, cancel_check=None):  # noqa: ANN001
            _ = cancel_check
            worker.requestInterruption()
            return {"imported": 1, "skipped": 0, "document_id": 1}

    fake_db = MagicMock()
    fake_repo = MagicMock()
    fake_repo.list_documents.side_effect = [[], [{"document_id": 1}]]

    monkeypatch.setattr("context_aware_translation.ui.workers.import_worker.SQLiteBookDB", lambda *_a, **_k: fake_db)
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.import_worker.DocumentRepository",
        lambda *_a, **_k: fake_repo,
    )
    monkeypatch.setattr("context_aware_translation.ui.workers.import_worker.get_document_classes", lambda: [_TextDoc])

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert cancelled == []
    assert success == [{"imported": 1, "skipped": 0, "document_id": 1}]
    assert errors == []
    fake_db.close.assert_called_once()


def test_export_worker_late_interrupt_still_emits_success(monkeypatch: pytest.MonkeyPatch):
    from context_aware_translation.ui.workers.export_worker import ExportWorker

    worker = ExportWorker(
        book_manager=MagicMock(),
        book_id="book-id",
        output_path=Path("/tmp/output.txt"),
        export_format="txt",
        document_ids=[1],
        preserve_structure=False,
    )

    class _Session:
        async def export(self, *_args, **_kwargs) -> None:  # noqa: ANN003
            worker.requestInterruption()

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.export_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _TranslatorContext(_Session()),
    )

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert cancelled == []
    assert success == ["/tmp/output.txt"]
    assert errors == []


def test_sync_translation_task_worker_does_not_emit_success_when_session_exit_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from context_aware_translation.ui.workers.sync_translation_task_worker import SyncTranslationTaskWorker

    task_store = MagicMock()
    task_store.update = MagicMock()
    worker = SyncTranslationTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-2",
        task_store=task_store,
    )

    class _Session:
        async def translate(self, **kwargs) -> None:  # noqa: ANN003
            _ = kwargs

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.sync_translation_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _TranslatorContext(_Session(), exit_error=RuntimeError("close failed")),
    )

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert success == []
    assert cancelled == []
    assert len(errors) == 1
    assert "RuntimeError: close failed" in errors[0]


def test_sync_translation_task_worker_forwards_skip_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from context_aware_translation.ui.workers.sync_translation_task_worker import SyncTranslationTaskWorker

    task_store = MagicMock()
    task_store.update = MagicMock()
    worker = SyncTranslationTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-3",
        skip_context=True,
        task_store=task_store,
    )
    captured: dict[str, object] = {}

    class _Session:
        async def translate(self, **kwargs) -> None:  # noqa: ANN003
            captured.update(kwargs)

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.sync_translation_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _TranslatorContext(_Session()),
    )

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert success[0]["action"] == "run"
    assert cancelled == []
    assert errors == []
    assert captured.get("skip_context") is True


def test_import_worker_does_not_emit_success_when_import_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from context_aware_translation.ui.workers.import_worker import ImportWorker

    source_path = tmp_path / "sample.txt"
    source_path.write_text("hello", encoding="utf-8")
    book_manager = MagicMock()
    book_manager.get_book_db_path.return_value = tmp_path / "book.db"
    worker = ImportWorker(book_manager, "book-id", source_path, "text")

    class _TextDoc:
        document_type = "text"

        @staticmethod
        def can_import(_path: Path) -> bool:
            return True

        @staticmethod
        def do_import(_repo, _path: Path, cancel_check=None):  # noqa: ANN001
            _ = cancel_check
            raise RuntimeError("import failed")

    fake_db = MagicMock()
    fake_repo = MagicMock()
    fake_repo.list_documents.return_value = []

    monkeypatch.setattr("context_aware_translation.ui.workers.import_worker.SQLiteBookDB", lambda *_a, **_k: fake_db)
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.import_worker.DocumentRepository",
        lambda *_a, **_k: fake_repo,
    )
    monkeypatch.setattr("context_aware_translation.ui.workers.import_worker.get_document_classes", lambda: [_TextDoc])

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert success == []
    assert cancelled == []
    assert len(errors) == 1
    assert "RuntimeError: import failed" in errors[0]


def test_import_worker_forwards_progress_callback_when_supported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from context_aware_translation.ui.workers.import_worker import ImportWorker

    source_path = tmp_path / "sample.pdf"
    source_path.write_bytes(b"fake")
    book_manager = MagicMock()
    book_manager.get_book_db_path.return_value = tmp_path / "book.db"
    worker = ImportWorker(book_manager, "book-id", source_path, "pdf")

    class _PDFDoc:
        document_type = "pdf"

        @staticmethod
        def can_import(_path: Path) -> bool:
            return True

        @staticmethod
        def do_import(_repo, _path: Path, cancel_check=None, progress_callback=None):  # noqa: ANN001
            _ = cancel_check
            assert progress_callback is not None
            progress_callback(ProgressUpdate(step=WorkflowStep.EXPORT, current=1, total=2, message="page 1"))
            progress_callback(ProgressUpdate(step=WorkflowStep.EXPORT, current=2, total=2, message="page 2"))
            return {"imported": 1, "skipped": 0, "document_id": 1}

    fake_db = MagicMock()
    fake_repo = MagicMock()
    fake_repo.list_documents.side_effect = [[], [{"document_id": 1}]]

    monkeypatch.setattr("context_aware_translation.ui.workers.import_worker.SQLiteBookDB", lambda *_a, **_k: fake_db)
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.import_worker.DocumentRepository",
        lambda *_a, **_k: fake_repo,
    )
    monkeypatch.setattr("context_aware_translation.ui.workers.import_worker.get_document_classes", lambda: [_PDFDoc])

    progress_events: list[tuple[int, int, str]] = []
    worker.progress.connect(lambda c, t, m: progress_events.append((c, t, m)))
    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert cancelled == []
    assert errors == []
    assert success == [{"imported": 1, "skipped": 0, "document_id": 1}]
    assert progress_events[0] == (0, 1, "Importing...")
    assert (1, 2, "page 1") in progress_events
    assert (2, 2, "page 2") in progress_events
    assert progress_events[-1] == (1, 1, "Import complete")


def test_ocr_worker_does_not_emit_success_when_session_exit_fails(monkeypatch: pytest.MonkeyPatch):
    from context_aware_translation.ui.workers.ocr_worker import OCRWorker

    worker = OCRWorker(MagicMock(), "book-id", source_ids=[1])

    class _Session:
        async def run_ocr(self, **kwargs) -> int:  # noqa: ANN003
            _ = kwargs
            return 1

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.ocr_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _TranslatorContext(_Session(), exit_error=RuntimeError("close failed")),
    )

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert success == []
    assert cancelled == []
    assert len(errors) == 1
    assert "RuntimeError: close failed" in errors[0]


def test_glossary_translate_task_worker_does_not_emit_success_when_session_exit_fails(monkeypatch: pytest.MonkeyPatch):
    from context_aware_translation.ui.workers.glossary_translation_task_worker import GlossaryTranslationTaskWorker

    class _TranslateSession:
        async def translate_glossary(self, **kwargs) -> None:  # noqa: ANN003
            _ = kwargs

    worker = GlossaryTranslationTaskWorker(MagicMock(), "book-id", action="run")
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.glossary_translation_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _TranslatorContext(_TranslateSession(), exit_error=RuntimeError("close failed")),
    )

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert success == []
    assert cancelled == []
    assert len(errors) == 1
    assert "RuntimeError: close failed" in errors[0]


def test_glossary_review_task_worker_does_not_emit_success_when_session_exit_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from context_aware_translation.ui.workers.glossary_review_task_worker import GlossaryReviewTaskWorker

    class _ReviewSession:
        async def review_terms(self, **kwargs) -> None:  # noqa: ANN003
            _ = kwargs

    book_manager = MagicMock()
    book_manager.get_book_db_path.return_value = tmp_path / "book.db"
    worker = GlossaryReviewTaskWorker(book_manager, "book-id", action="run", task_id="task-1")
    monkeypatch.setattr(
        "context_aware_translation.ui.workers.glossary_review_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _TranslatorContext(_ReviewSession(), exit_error=RuntimeError("close failed")),
    )

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert success == []
    assert cancelled == []
    assert len(errors) == 1
    assert "RuntimeError: close failed" in errors[0]


# ------------------------------------------------------------------
# Sync translation worker: manga document passthrough
# ------------------------------------------------------------------


def test_sync_translation_task_worker_passes_manga_document_ids(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sync translation worker passes document_ids through to session.translate unchanged.

    Manga documents must not be filtered — session.translate dispatches per doc_type internally.
    """
    from context_aware_translation.ui.workers.sync_translation_task_worker import SyncTranslationTaskWorker

    task_store = MagicMock()
    manga_doc_ids = [10, 20]  # simulate manga document IDs
    worker = SyncTranslationTaskWorker(
        _book_manager_with_db(tmp_path),
        "book-id",
        action="run",
        task_id="task-manga",
        document_ids=manga_doc_ids,
        task_store=task_store,
    )

    captured_kwargs: dict = {}

    class _Session:
        async def translate(self, **kwargs) -> None:  # noqa: ANN003
            captured_kwargs.update(kwargs)

    monkeypatch.setattr(
        "context_aware_translation.ui.workers.sync_translation_task_worker.WorkflowSession.from_book",
        lambda *_args, **_kwargs: _TranslatorContext(_Session()),
    )

    success, cancelled, errors = _capture_signals(worker)
    worker.run()

    assert success[0]["action"] == "run"
    assert cancelled == []
    assert errors == []
    assert captured_kwargs["document_ids"] == manga_doc_ids
    task_store.update.assert_any_call("task-manga", status="completed")
