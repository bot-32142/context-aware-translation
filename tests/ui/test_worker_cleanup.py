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


def test_translation_view_cleanup_waits_without_timeout():
    from context_aware_translation.ui.views.translation_view import TranslationView

    with patch.object(TranslationView, "__init__", _noop_init):
        view = TranslationView(None, "")

    worker = _FakeWorker()
    view._is_cleaned_up = False
    view._batch_auto_timer = None
    view._active_batch_task_id = None
    view._batch_task_store = MagicMock()
    view.worker = worker
    view.batch_task_worker = None
    view.retranslate_worker = None
    view.term_db = MagicMock()
    view.cleanup()

    assert worker.interruption_requested
    assert worker.wait_calls == [()]
    view.term_db.close.assert_called_once()


def test_translation_view_cleanup_does_not_interrupt_running_batch_run_worker():
    from context_aware_translation.ui.views.translation_view import TranslationView

    with patch.object(TranslationView, "__init__", _noop_init):
        view = TranslationView(None, "")

    batch_worker = _FakeBatchWorker(action="run")
    view._is_cleaned_up = False
    view._batch_auto_timer = None
    view._active_batch_task_id = None
    view._batch_task_store = MagicMock()
    view.worker = None
    view.batch_task_worker = batch_worker
    view.retranslate_worker = None
    view.term_db = MagicMock()
    view.cleanup()

    assert batch_worker.interruption_requested is False
    assert batch_worker.wait_calls == []
    view.term_db.close.assert_called_once()


def test_translation_view_cleanup_interrupts_non_run_batch_worker():
    from context_aware_translation.ui.views.translation_view import TranslationView

    with patch.object(TranslationView, "__init__", _noop_init):
        view = TranslationView(None, "")

    batch_worker = _FakeBatchWorker(action="cancel")
    view._is_cleaned_up = False
    view._batch_auto_timer = None
    view._active_batch_task_id = None
    view._batch_task_store = MagicMock()
    view.worker = None
    view.batch_task_worker = batch_worker
    view.retranslate_worker = None
    view.term_db = MagicMock()
    view.cleanup()

    assert batch_worker.interruption_requested is True
    assert batch_worker.wait_calls == [()]
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


def test_glossary_view_cleanup_waits_without_timeout():
    from context_aware_translation.ui.views.glossary_view import GlossaryView

    with patch.object(GlossaryView, "__init__", _noop_init):
        view = GlossaryView(None, "")

    build_worker = _FakeWorker()
    translate_worker = _FakeWorker()
    review_worker = _FakeWorker()
    export_worker = _FakeWorker()
    view._build_worker = build_worker
    view._translate_worker = translate_worker
    view._review_worker = review_worker
    view._export_worker = export_worker
    view.term_db = MagicMock()
    view.cleanup()

    assert build_worker.interruption_requested
    assert translate_worker.interruption_requested
    assert review_worker.interruption_requested
    assert export_worker.interruption_requested
    assert build_worker.wait_calls == [()]
    assert translate_worker.wait_calls == [()]
    assert review_worker.wait_calls == [()]
    assert export_worker.wait_calls == [()]
    view.term_db.close.assert_called_once()
