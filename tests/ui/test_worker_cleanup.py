"""Unit tests for worker cleanup behavior in UI views."""

from unittest.mock import MagicMock, patch

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


def _noop_init(self, *_args, **_kwargs):  # noqa: ANN001
    """No-op replacement for view __init__."""


class _FakeWorker:
    def __init__(self) -> None:
        self.interruption_requested = False
        self.wait_calls: list[tuple] = []

    def isRunning(self) -> bool:  # noqa: N802
        return True

    def requestInterruption(self) -> None:  # noqa: N802
        self.interruption_requested = True

    def wait(self, *args) -> bool:  # noqa: ANN002
        self.wait_calls.append(args)
        return True


class _FakeBatchWorker(_FakeWorker):
    def __init__(self, *, action: str) -> None:
        super().__init__()
        self.action = action


def test_import_view_cleanup_waits_without_timeout():
    from context_aware_translation.ui.views.import_view import ImportView

    with patch.object(ImportView, "__init__", _noop_init):
        view = ImportView(None, "")

    worker = _FakeWorker()
    view.worker = worker
    view.cleanup()

    assert worker.interruption_requested
    assert worker.wait_calls == [()]


def test_export_view_cleanup_waits_without_timeout():
    from context_aware_translation.ui.views.export_view import ExportView

    with patch.object(ExportView, "__init__", _noop_init):
        view = ExportView(None, "")

    worker = _FakeWorker()
    view.worker = worker
    view.cleanup()

    assert worker.interruption_requested
    assert worker.wait_calls == [()]


def test_translation_view_cleanup_does_not_cancel_engine_tasks():
    """Engine-managed tasks continue in background — cleanup must NOT cancel them."""
    from context_aware_translation.ui.views.translation_view import TranslationView

    with patch.object(TranslationView, "__init__", _noop_init):
        view = TranslationView(None, "")

    from context_aware_translation.workflow.tasks.models import STATUS_RUNNING

    task_engine = MagicMock()
    running_record = MagicMock()
    running_record.status = STATUS_RUNNING
    task_engine.get_task.return_value = running_record

    view._is_cleaned_up = False
    view._task_engine = task_engine
    view.term_db = MagicMock()
    view.cleanup()

    task_engine.cancel.assert_not_called()
    view.term_db.close.assert_called_once()


def test_translation_view_cleanup_with_task_console_calls_console_cleanup():
    """task_console.cleanup() is called when the console attribute exists."""
    from context_aware_translation.ui.views.translation_view import TranslationView

    with patch.object(TranslationView, "__init__", _noop_init):
        view = TranslationView(None, "")

    view._is_cleaned_up = False
    view._task_engine = MagicMock()
    view.task_status_strip = MagicMock()
    view.term_db = MagicMock()
    view.cleanup()

    view.task_status_strip.cleanup.assert_called_once()
    view.term_db.close.assert_called_once()


def test_translation_view_cleanup_closes_term_db():
    from context_aware_translation.ui.views.translation_view import TranslationView

    with patch.object(TranslationView, "__init__", _noop_init):
        view = TranslationView(None, "")

    view._is_cleaned_up = False
    view._task_engine = MagicMock()
    view.term_db = MagicMock()

    view.cleanup()

    view.term_db.close.assert_called_once()


def test_ocr_review_view_cleanup_waits_without_timeout():
    from context_aware_translation.ui.views.ocr_review_view import OCRReviewView

    with patch.object(OCRReviewView, "__init__", _noop_init):
        view = OCRReviewView(None, "")

    worker = _FakeWorker()
    view.ocr_worker = worker
    view.term_db = MagicMock()
    view.cleanup()

    assert worker.interruption_requested
    assert worker.wait_calls == [()]
    view.term_db.close.assert_called_once()
