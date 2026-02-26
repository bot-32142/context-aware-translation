"""Regression tests for glossary view control-state behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

try:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QMessageBox, QPushButton, QTableView

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
    """No-op replacement for GlossaryView.__init__."""


def _make_view():
    from context_aware_translation.ui.views.glossary_view import GlossaryView

    with patch.object(GlossaryView, "__init__", _noop_init):
        view = GlossaryView(None, "")

    view.search_input = QLineEdit()
    view.filter_combo = QComboBox()
    view.doc_combo = QComboBox()
    view.build_button = QPushButton()
    view.translate_button = QPushButton()
    view.review_button = QPushButton()
    view.filter_rare_button = QPushButton()
    view.refresh_button = QPushButton()
    view.export_button = QPushButton()
    view.import_button = QPushButton()
    view.table_view = QTableView()
    view._task_engine = MagicMock()
    view.book_id = "test-book"
    view.term_db = MagicMock()
    view.term_db.list_terms.return_value = []
    view.document_repo = MagicMock()
    view.document_repo.list_documents.return_value = []
    view.document_repo.get_documents_with_status.return_value = []
    view.document_repo.list_documents_pending_glossary.return_value = []
    return view


def test_set_controls_enabled_keeps_build_disabled_when_no_pending_documents():
    view = _make_view()
    view.doc_combo.addItem("All Documents", None)

    view._set_controls_enabled(True)

    assert not view.build_button.isEnabled()
    assert not view.doc_combo.isEnabled()


def test_update_action_button_states_keeps_glossary_actions_available():
    view = _make_view()
    view.translate_button.setEnabled(False)
    view.review_button.setEnabled(False)
    view.filter_rare_button.setEnabled(False)

    view._update_action_button_states()

    assert view.translate_button.isEnabled()
    assert view.review_button.isEnabled()
    assert view.filter_rare_button.isEnabled()


def test_set_controls_enabled_respects_pending_documents_state():
    view = _make_view()
    view.doc_combo.addItem("All Documents", None)
    view.doc_combo.addItem("Document 1", 1)

    view._set_controls_enabled(True)

    assert view.build_button.isEnabled()
    assert view.doc_combo.isEnabled()


def test_apply_button_tooltips_sets_hover_explanations():
    view = _make_view()

    view._apply_button_tooltips()

    buttons = [
        ("build", view.build_button),
        ("translate", view.translate_button),
        ("review", view.review_button),
        ("filter_rare", view.filter_rare_button),
        ("refresh", view.refresh_button),
        ("export", view.export_button),
        ("import", view.import_button),
    ]
    missing = [name for name, button in buttons if not button.toolTip().strip()]
    assert missing == []


def test_populate_documents_translates_document_type_labels():
    view = _make_view()
    view.doc_combo = QComboBox()
    view.document_repo = type(
        "_Repo",
        (),
        {
            "list_documents_pending_glossary": staticmethod(
                lambda: [{"document_id": 9, "document_type": "scanned_book"}]
            )
        },
    )()

    view._populate_documents()

    assert view.doc_combo.count() == 1
    assert view.doc_combo.itemData(0) == 9
    assert view.doc_combo.itemText(0) == f"Document 9 ({QCoreApplication.translate('ExportView', 'Scanned Book')})"
    assert "scanned_book" not in view.doc_combo.itemText(0)


def test_filter_rare_ignores_terms_occurring_once_or_recognized_in_one_chunk():
    from context_aware_translation.storage.book_db import TermRecord

    view = _make_view()
    view.term_db = MagicMock()
    view.term_db.list_terms.return_value = [
        # multiple occurrences and multiple chunk descriptions → keep
        TermRecord(
            key="keep",
            descriptions={"1": "desc", "2": "desc"},
            occurrence={"1": 2, "2": 1},
            votes=3,
            total_api_calls=1,
        ),
        # total_occurrences = 1 → rare
        TermRecord(key="rare_once", descriptions={"1": "desc"}, occurrence={"1": 1}, votes=1, total_api_calls=1),
        # recognized in only 1 chunk description → rare
        TermRecord(
            key="rare_one_chunk",
            descriptions={"1": "desc"},
            occurrence={"1": 2, "2": 3},
            votes=1,
            total_api_calls=1,
        ),
        # already ignored → skip
        TermRecord(
            key="already_ignored",
            descriptions={"1": "desc"},
            occurrence={"1": 1},
            votes=1,
            total_api_calls=1,
            ignored=True,
        ),
    ]
    view.term_db.update_terms_bulk.return_value = 2
    view.table_model = MagicMock()
    view._update_stats = MagicMock()
    view.glossary_changed = MagicMock()

    with (
        patch(
            "context_aware_translation.ui.views.glossary_view.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ),
        patch("context_aware_translation.ui.views.glossary_view.QMessageBox.information") as info_mock,
    ):
        view._on_filter_rare()

    view.term_db.update_terms_bulk.assert_called_once_with(
        ["rare_once", "rare_one_chunk"], ignored=True, is_reviewed=True
    )
    view.table_model.refresh.assert_called_once()
    view._update_stats.assert_called_once()
    view.glossary_changed.emit.assert_called_once()
    assert info_mock.call_count == 1


def test_filter_rare_shows_no_match_message_when_nothing_is_rare():
    from context_aware_translation.storage.book_db import TermRecord

    view = _make_view()
    view.term_db = MagicMock()
    view.term_db.list_terms.return_value = [
        # multiple occurrences and multiple chunk descriptions → not rare
        TermRecord(
            key="keep",
            descriptions={"1": "desc", "2": "desc"},
            occurrence={"1": 2, "2": 1},
            votes=2,
            total_api_calls=1,
        ),
    ]
    view.table_model = MagicMock()
    view._update_stats = MagicMock()
    view.glossary_changed = MagicMock()

    with (
        patch(
            "context_aware_translation.ui.views.glossary_view.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ),
        patch("context_aware_translation.ui.views.glossary_view.QMessageBox.information") as info_mock,
    ):
        view._on_filter_rare()

    view.term_db.update_terms_bulk.assert_not_called()
    view.table_model.refresh.assert_not_called()
    view._update_stats.assert_not_called()
    view.glossary_changed.emit.assert_not_called()
    assert info_mock.call_count == 1
    assert "No" in info_mock.call_args.args[2]


def test_build_glossary_confirmation_clarifies_translation_step_is_separate():
    view = _make_view()
    view.document_repo = MagicMock()
    view.document_repo.list_documents.return_value = [{"document_id": 1, "document_type": "text"}]
    view.document_repo.list_documents_pending_glossary.return_value = [{"document_id": 1, "document_type": "text"}]
    view.document_repo.get_documents_with_status.return_value = [
        {"document_id": 1, "document_type": "text", "ocr_pending": 0},
    ]
    view.doc_combo = QComboBox()
    view.doc_combo.addItem("All Documents", None)
    view.doc_combo.addItem("Document 1", 1)

    captured: dict[str, str] = {}

    def _question(_parent, _title, text, *_args, **_kwargs):  # noqa: ANN001
        captured["text"] = text
        return QMessageBox.StandardButton.No

    with patch("context_aware_translation.ui.views.glossary_view.QMessageBox.question", side_effect=_question):
        view._on_build_glossary()

    assert "will not translate glossary terms" in captured["text"]
    assert "Translate Untranslated" in captured["text"]


def test_selected_document_ids_all_returns_pending_document_ids():
    view = _make_view()
    view.doc_combo = QComboBox()
    view.doc_combo.addItem("All Documents", None)
    view.doc_combo.addItem("Document 2", 2)
    view.doc_combo.addItem("Document 4", 4)

    assert view._get_selected_document_ids() == [2, 4]


def test_selected_document_ids_cutoff_returns_pending_up_to_selected():
    view = _make_view()
    view.doc_combo = QComboBox()
    view.doc_combo.addItem("All Documents", None)
    view.doc_combo.addItem("Document 2", 2)
    view.doc_combo.addItem("Document 4", 4)
    view.doc_combo.addItem("Document 6", 6)
    view.doc_combo.setCurrentIndex(2)  # doc_id=4

    assert view._get_selected_document_ids() == [2, 4]


def test_build_glossary_all_selection_processes_all_pending_documents_only():
    view = _make_view()
    view.book_manager = MagicMock()
    view.book_id = "book"
    view.progress_widget = MagicMock()
    view._set_controls_enabled = MagicMock()
    view.doc_combo = QComboBox()
    view.doc_combo.addItem("All Documents", None)
    view.doc_combo.addItem("Document 2", 2)
    view.doc_combo.addItem("Document 4", 4)
    view.document_repo = MagicMock()
    view.document_repo.list_documents.return_value = [
        {"document_id": 2, "document_type": "text"},
        {"document_id": 4, "document_type": "text"},
    ]
    view.document_repo.list_documents_pending_glossary.return_value = [
        {"document_id": 2, "document_type": "text"},
        {"document_id": 4, "document_type": "text"},
    ]
    view.document_repo.get_documents_with_status.return_value = [
        {"document_id": 2, "document_type": "text", "ocr_pending": 0},
        {"document_id": 4, "document_type": "text", "ocr_pending": 0},
    ]

    with patch(
        "context_aware_translation.ui.views.glossary_view.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        view._on_build_glossary()

    view._task_engine.submit_and_start.assert_called_once()
    call_args = view._task_engine.submit_and_start.call_args
    assert call_args.args[0] == "glossary_extraction"
    assert call_args.args[1] == "book"
    assert call_args.kwargs["document_ids"] == [2, 4]


def test_build_glossary_blocks_when_earlier_ocr_required_document_is_pending():
    view = _make_view()
    view.doc_combo = QComboBox()
    view.doc_combo.addItem("All Documents", None)
    view.doc_combo.addItem("Document 3", 3)
    view.doc_combo.setCurrentIndex(1)
    view.document_repo = MagicMock()
    view.document_repo.list_documents.return_value = [
        {"document_id": 1, "document_type": "pdf"},
        {"document_id": 3, "document_type": "manga"},
    ]
    view.document_repo.list_documents_pending_glossary.return_value = [
        {"document_id": 3, "document_type": "manga"},
    ]
    view.document_repo.get_documents_with_status.return_value = [
        {"document_id": 1, "document_type": "pdf", "ocr_pending": 1},
        {"document_id": 3, "document_type": "manga", "ocr_pending": 0},
    ]

    with (
        patch("context_aware_translation.ui.views.glossary_view.QMessageBox.warning") as warning_mock,
        patch("context_aware_translation.ui.views.glossary_view.QMessageBox.question") as question_mock,
    ):
        view._on_build_glossary()

    question_mock.assert_not_called()
    view._task_engine.submit_and_start.assert_not_called()
    assert warning_mock.call_count == 1
    assert "earlier OCR-required" in warning_mock.call_args.args[2]


def test_build_button_disabled_when_selected_stack_has_blocking_ocr_document():
    view = _make_view()
    view.doc_combo = QComboBox()
    view.doc_combo.addItem("All Documents", None)
    view.doc_combo.addItem("Document 3", 3)
    view.doc_combo.setCurrentIndex(1)
    view.document_repo = MagicMock()
    view.document_repo.list_documents.return_value = [
        {"document_id": 1, "document_type": "pdf"},
        {"document_id": 3, "document_type": "manga"},
    ]
    view.document_repo.get_documents_with_status.return_value = [
        {"document_id": 1, "document_type": "pdf", "ocr_pending": 1},
        {"document_id": 3, "document_type": "manga", "ocr_pending": 0},
    ]

    view._update_build_button_state()

    assert not view.build_button.isEnabled()
    assert view.doc_combo.isEnabled()
    assert "Blocked:" in view.build_button.toolTip()


def test_build_button_enabled_for_epub_selection_even_if_earlier_pdf_has_pending_ocr():
    view = _make_view()
    view.doc_combo = QComboBox()
    view.doc_combo.addItem("All Documents", None)
    view.doc_combo.addItem("Document 2", 2)
    view.doc_combo.setCurrentIndex(1)
    view.document_repo = MagicMock()
    view.document_repo.list_documents.return_value = [
        {"document_id": 1, "document_type": "pdf"},
        {"document_id": 2, "document_type": "epub"},
    ]
    view.document_repo.get_documents_with_status.return_value = [
        {"document_id": 1, "document_type": "pdf", "ocr_pending": 1},
        {"document_id": 2, "document_type": "epub", "ocr_pending": 0},
    ]

    view._update_build_button_state()

    assert view.build_button.isEnabled()


def test_build_button_disabled_for_text_selection_when_earlier_pdf_has_pending_ocr():
    view = _make_view()
    view.doc_combo = QComboBox()
    view.doc_combo.addItem("All Documents", None)
    view.doc_combo.addItem("Document 2", 2)
    view.doc_combo.setCurrentIndex(1)
    view.document_repo = MagicMock()
    view.document_repo.list_documents.return_value = [
        {"document_id": 1, "document_type": "pdf"},
        {"document_id": 2, "document_type": "text"},
    ]
    view.document_repo.get_documents_with_status.return_value = [
        {"document_id": 1, "document_type": "pdf", "ocr_pending": 1},
        {"document_id": 2, "document_type": "text", "ocr_pending": 0},
    ]

    view._update_build_button_state()

    assert not view.build_button.isEnabled()


def test_export_glossary_warns_that_export_triggers_summarization():
    view = _make_view()
    view._export_worker = None
    view.book_manager = MagicMock()
    view.book_id = "book"
    view.progress_widget = MagicMock()
    captured: dict[str, str] = {}

    class _FakeMessageBox:
        Icon = QMessageBox.Icon
        StandardButton = QMessageBox.StandardButton

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def setWindowTitle(self, _title: str) -> None:
            pass

        def setText(self, text: str) -> None:
            captured["text"] = text

        def setIcon(self, _icon) -> None:  # noqa: ANN001
            pass

        def setStandardButtons(self, _buttons) -> None:  # noqa: ANN001
            pass

        def setCheckBox(self, _checkbox) -> None:  # noqa: ANN001
            pass

        def exec(self) -> QMessageBox.StandardButton:
            return QMessageBox.StandardButton.No

    with (
        patch(
            "context_aware_translation.ui.views.glossary_view.QFileDialog.getSaveFileName",
            return_value=("/tmp/glossary.json", ""),
        ),
        patch("context_aware_translation.ui.views.glossary_view.QMessageBox", _FakeMessageBox),
        patch("context_aware_translation.ui.views.glossary_view.QCheckBox") as checkbox_cls,
        patch("context_aware_translation.ui.views.glossary_view.ExportGlossaryWorker") as worker_cls,
    ):
        checkbox = MagicMock()
        checkbox.isChecked.return_value = True
        checkbox_cls.return_value = checkbox
        view._on_export_glossary()

    worker_cls.assert_not_called()
    assert checkbox_cls.call_count == 1
    assert "Skip context" in checkbox_cls.call_args.args[0]
    assert "summarize glossary descriptions" in captured["text"]


def test_export_glossary_forwards_skip_context_to_worker():
    view = _make_view()
    view._export_worker = None
    view.book_manager = MagicMock()
    view.book_id = "book"
    view.progress_widget = MagicMock()
    view._set_controls_enabled = MagicMock()

    worker_instance = MagicMock()

    with (
        patch(
            "context_aware_translation.ui.views.glossary_view.QFileDialog.getSaveFileName",
            return_value=("/tmp/glossary.json", ""),
        ),
        patch.object(view, "_confirm_export_glossary", return_value=True),
        patch(
            "context_aware_translation.ui.views.glossary_view.ExportGlossaryWorker",
            return_value=worker_instance,
        ) as worker_cls,
    ):
        view._on_export_glossary()

    assert worker_cls.call_count == 1
    assert worker_cls.call_args.kwargs.get("skip_context") is True
    worker_instance.start.assert_called_once()
    view.progress_widget.reset.assert_called_once()
    view.progress_widget.set_cancellable.assert_called_once_with(True)
    view.progress_widget.show.assert_called_once()
    view._set_controls_enabled.assert_called_once_with(False)


def test_review_button_disabled_when_engine_preflight_denied():
    from context_aware_translation.workflow.tasks.models import Decision

    view = _make_view()
    view._task_engine.preflight.return_value = Decision(
        allowed=False, code="no_review_config", reason="Review config not set."
    )

    view._update_review_button_state()

    assert not view.review_button.isEnabled()
    assert "no_review_config" in view.review_button.toolTip() or "Review config" in view.review_button.toolTip()


def test_review_button_enabled_when_engine_preflight_allowed():
    from context_aware_translation.workflow.tasks.models import Decision

    view = _make_view()
    view._task_engine.preflight.return_value = Decision(allowed=True)

    view._update_review_button_state()

    assert view.review_button.isEnabled()


def test_on_review_terms_shows_warning_when_preflight_denied():
    from context_aware_translation.workflow.tasks.models import Decision

    view = _make_view()
    view._task_engine.preflight.return_value = Decision(
        allowed=False, code="no_pending_terms", reason="No terms pending review."
    )

    with patch("context_aware_translation.ui.views.glossary_view.QMessageBox.warning") as warning_mock:
        view._on_review_terms()

    warning_mock.assert_called_once()
    view._task_engine.submit_and_start.assert_not_called()


def test_on_review_terms_submits_task_when_preflight_allowed():
    from context_aware_translation.workflow.tasks.models import Decision

    view = _make_view()
    view._task_engine.preflight.return_value = Decision(allowed=True)
    view._update_review_button_state = MagicMock()

    with patch(
        "context_aware_translation.ui.views.glossary_view.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        view._on_review_terms()

    view._task_engine.submit_and_start.assert_called_once_with("glossary_review", "test-book")
    view._update_review_button_state.assert_called_once()


def test_on_review_terms_does_not_submit_when_user_cancels():
    from context_aware_translation.workflow.tasks.models import Decision

    view = _make_view()
    view._task_engine.preflight.return_value = Decision(allowed=True)

    with patch(
        "context_aware_translation.ui.views.glossary_view.QMessageBox.question",
        return_value=QMessageBox.StandardButton.No,
    ):
        view._on_review_terms()

    view._task_engine.submit_and_start.assert_not_called()


def test_on_review_terms_shows_error_when_submit_raises():
    from context_aware_translation.workflow.tasks.models import Decision

    view = _make_view()
    view._task_engine.preflight.return_value = Decision(allowed=True)
    view._task_engine.submit_and_start.side_effect = RuntimeError("engine error")

    with (
        patch(
            "context_aware_translation.ui.views.glossary_view.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ),
        patch("context_aware_translation.ui.views.glossary_view.QMessageBox.critical") as critical_mock,
    ):
        view._on_review_terms()

    critical_mock.assert_called_once()


def test_glossary_view_cleanup_calls_task_console_cleanup():
    from context_aware_translation.ui.views.glossary_view import GlossaryView

    with patch.object(GlossaryView, "__init__", _noop_init):
        view = GlossaryView(None, "")

    view.task_console = MagicMock()
    view._export_worker = None
    view.term_db = MagicMock()

    view.cleanup()

    view.task_console.cleanup.assert_called_once()
    view.term_db.close.assert_called_once()
