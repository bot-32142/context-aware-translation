"""Translation view with progress and review modes."""

import sqlite3

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.documents.base import is_ocr_required_for_type
from context_aware_translation.storage.book_db import SQLiteBookDB, TranslationChunkRecord
from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.document_repository import DocumentRepository
from context_aware_translation.storage.translation_batch_task_store import (
    STATUS_CANCEL_REQUESTED,
    STATUS_CANCELLED,
    STATUS_CANCELLING,
    STATUS_COMPLETED,
    STATUS_COMPLETED_WITH_ERRORS,
    STATUS_FAILED,
    STATUS_PAUSED,
    STATUS_RUNNING,
    TERMINAL_TASK_STATUSES,
    TranslationBatchTaskRecord,
    TranslationBatchTaskStore,
)

from ..i18n import qarg, translate_progress_message
from ..utils import create_tip_label, translate_document_type
from ..widgets import ProgressWidget
from ..workers.batch_translation_task_worker import BatchTranslationTaskWorker
from ..workers.translation_worker import RetranslateChunkWorker, TranslationWorker
from .manga_review_widget import MangaReviewWidget

PREVIEW_TRUNCATION_LENGTH = 50
_BATCH_AUTO_REFRESH_INTERVAL_MS = 3000
_NON_DELETABLE_BATCH_TASK_STATUSES = {
    STATUS_RUNNING,
    STATUS_CANCEL_REQUESTED,
    STATUS_CANCELLING,
}
_NON_RUNNABLE_BATCH_TASK_STATUSES = {
    STATUS_RUNNING,
    STATUS_CANCEL_REQUESTED,
    STATUS_CANCELLING,
    STATUS_COMPLETED,
}


def _is_closed_database_error(exc: Exception) -> bool:
    return isinstance(exc, sqlite3.ProgrammingError) and "closed" in str(exc).lower()


class TranslationView(QWidget):
    """View for translating chunks with progress and review modes."""

    # Class-level shared set: holds batch "run" workers detached during cleanup
    # so they stay alive until they finish naturally (preventing data loss).
    # Entries are auto-removed via the worker's ``finished`` signal.
    _DETACHED_BATCH_RUN_WORKERS: set[BatchTranslationTaskWorker] = set()

    translation_completed = Signal()

    def __init__(
        self,
        book_manager: BookManager,
        book_id: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.book_manager = book_manager
        self.book_id = book_id
        self.worker: TranslationWorker | None = None
        self.retranslate_worker: RetranslateChunkWorker | None = None
        self.batch_task_worker: BatchTranslationTaskWorker | None = None
        self._active_batch_task_id: str | None = None
        self._batch_tasks_cache: list[TranslationBatchTaskRecord] = []
        self._batch_auto_timer: QTimer | None = None
        self._is_cleaned_up = False

        # Initialize database
        db_path = book_manager.get_book_db_path(book_id)
        self.term_db = SQLiteBookDB(db_path)
        self.document_repo = DocumentRepository(self.term_db)
        self._batch_task_store = TranslationBatchTaskStore(
            book_manager.get_book_db_path(book_id).parent / "translation_batch_tasks.db"
        )

        self._current_chunk: TranslationChunkRecord | None = None
        self._original_line_count: int = 0
        self._find_pos: int = 0  # Track search position explicitly

        # Cache for document type lookups (L21)
        self._document_type_cache: dict[int, str] = {}

        self._init_ui()
        self._update_stats()

    @staticmethod
    def _db_call_or_default(default_value, fn, *args, **kwargs):  # noqa: ANN001
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            if _is_closed_database_error(exc):
                return default_value
            raise

    def _init_ui(self) -> None:
        """Initialize the user interface."""
        layout = QVBoxLayout(self)

        self.tip_label = create_tip_label(self._tip_text())
        layout.addWidget(self.tip_label)

        # Stacked widget for Progress/Review modes
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        # Progress Mode
        self.progress_page = self._create_progress_page()
        self.stack.addWidget(self.progress_page)

        # Review Mode
        self.review_page = self._create_review_page()
        self.stack.addWidget(self.review_page)

        # Start in progress mode
        self.stack.setCurrentWidget(self.progress_page)
        self._apply_button_tooltips()

    def _create_progress_page(self) -> QWidget:
        """Create the progress mode page."""
        page = QWidget()
        layout = QVBoxLayout(page)

        # Document selector row
        doc_selector_layout = QHBoxLayout()
        self.doc_selector_label = QLabel(self.tr("Document:"))
        doc_selector_layout.addWidget(self.doc_selector_label)
        self.doc_combo = QComboBox()
        self.doc_combo.addItem(self.tr("All Documents"), None)
        self._populate_documents()
        doc_selector_layout.addWidget(self.doc_combo, stretch=1)
        self.doc_combo.currentIndexChanged.connect(self._update_start_button_state)
        doc_selector_layout.addStretch(2)
        layout.addLayout(doc_selector_layout)

        # Stats display
        self.stats_label = QLabel()
        self.stats_label.setStyleSheet("font-size: 14pt; font-weight: bold;")
        layout.addWidget(self.stats_label)

        # Start translation button
        self.start_btn = QPushButton(self.tr("Start Translation"))
        self.start_btn.clicked.connect(self._start_translation)
        layout.addWidget(self.start_btn)

        # Optional prompt mode for large books: use only first glossary description.
        self.skip_context_cb = QCheckBox(self.tr("Skip context (use first description only)"))
        layout.addWidget(self.skip_context_cb)

        # Async batch-task section
        self.batch_section_label = QLabel(self.tr("Async Batch Tasks"))
        self.batch_section_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.batch_section_label)

        batch_action_layout = QHBoxLayout()
        self.submit_batch_btn = QPushButton(self.tr("Submit Batch Task"))
        self.submit_batch_btn.clicked.connect(self._submit_batch_task)
        batch_action_layout.addWidget(self.submit_batch_btn)
        layout.addLayout(batch_action_layout)

        self.batch_task_list = QListWidget()
        self.batch_task_list.currentRowChanged.connect(self._on_batch_task_selected)
        layout.addWidget(self.batch_task_list)

        batch_selected_layout = QHBoxLayout()
        self.run_batch_task_btn = QPushButton(self.tr("Run Selected Task"))
        self.run_batch_task_btn.clicked.connect(self._run_selected_batch_task)
        batch_selected_layout.addWidget(self.run_batch_task_btn)
        self.cancel_batch_task_btn = QPushButton(self.tr("Cancel Selected Task"))
        self.cancel_batch_task_btn.clicked.connect(self._cancel_selected_batch_task)
        batch_selected_layout.addWidget(self.cancel_batch_task_btn)
        self.delete_batch_task_btn = QPushButton(self.tr("Delete Selected Task"))
        self.delete_batch_task_btn.clicked.connect(self._delete_selected_batch_task)
        batch_selected_layout.addWidget(self.delete_batch_task_btn)
        layout.addLayout(batch_selected_layout)

        self.batch_status_label = QLabel()
        self.batch_status_label.setWordWrap(True)
        self.batch_status_label.hide()
        layout.addWidget(self.batch_status_label)

        # Update start button state based on pending documents
        self._update_start_button_state()
        self._refresh_batch_tasks()
        self._batch_auto_timer = QTimer(self)
        self._batch_auto_timer.setInterval(_BATCH_AUTO_REFRESH_INTERVAL_MS)
        self._batch_auto_timer.timeout.connect(self._on_batch_tasks_timer)
        self._batch_auto_timer.start()
        self._on_batch_tasks_timer()

        # Progress widget
        self.progress_widget = ProgressWidget()
        self.progress_widget.hide()
        self.progress_widget.cancelled.connect(self._cancel_translation)
        layout.addWidget(self.progress_widget)

        # Status message
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        layout.addWidget(self.status_label)

        # Switch to review button
        self.review_btn = QPushButton(self.tr("Review Translations"))
        self.review_btn.clicked.connect(self._switch_to_review)
        layout.addWidget(self.review_btn)

        layout.addStretch()

        return page

    def _create_review_page(self) -> QWidget:
        """Create the review mode page with text and manga sub-modes."""
        page = QWidget()
        layout = QVBoxLayout(page)

        # Top bar with back button and document selector
        top_layout = QHBoxLayout()
        self.back_btn = QPushButton(self.tr("Back to Progress"))
        self.back_btn.clicked.connect(self._switch_to_progress)
        top_layout.addWidget(self.back_btn)
        top_layout.addStretch()

        # Document filter for review
        self.review_doc_label = QLabel(self.tr("Document:"))
        top_layout.addWidget(self.review_doc_label)
        self.review_doc_combo = QComboBox()
        self.review_doc_combo.addItem(self.tr("All Documents"), None)
        self._populate_review_documents()
        self.review_doc_combo.currentIndexChanged.connect(self._on_review_document_changed)
        top_layout.addWidget(self.review_doc_combo)

        layout.addLayout(top_layout)

        # Stacked widget to switch between text review and manga review
        self.review_stack = QStackedWidget()

        # --- Text review sub-page (existing chunk-based UI) ---
        self._text_review_widget = self._create_text_review_widget()
        self.review_stack.addWidget(self._text_review_widget)

        # --- Manga review sub-page (delegated to MangaReviewWidget) ---
        self._manga_review_widget = MangaReviewWidget(self.term_db, self.document_repo)
        self.review_stack.addWidget(self._manga_review_widget)

        layout.addWidget(self.review_stack)

        return page

    def _create_text_review_widget(self) -> QWidget:
        """Create the text chunk review sub-widget."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # Splitter for chunks list and detail view
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel: chunks list
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.chunks_label = QLabel(self.tr("Chunks:"))
        left_layout.addWidget(self.chunks_label)

        self.chunk_list = QListWidget()
        self.chunk_list.currentRowChanged.connect(self._on_chunk_selected)
        left_layout.addWidget(self.chunk_list)

        splitter.addWidget(left_widget)

        # Right panel: chunk detail editor
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Original text
        self.orig_label = QLabel(self.tr("Original:"))
        self.orig_label.setStyleSheet("font-weight: bold;")
        right_layout.addWidget(self.orig_label)

        self.original_text = QTextEdit()
        self.original_text.setReadOnly(True)
        self.original_text.setMaximumHeight(150)
        right_layout.addWidget(self.original_text)

        # Translation text
        self.trans_label = QLabel(self.tr("Translation:"))
        self.trans_label.setStyleSheet("font-weight: bold;")
        right_layout.addWidget(self.trans_label)

        # Find/Replace bar
        find_replace_layout = QHBoxLayout()
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText(self.tr("Find..."))
        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText(self.tr("Replace with..."))
        self.find_next_btn = QPushButton(self.tr("Find Next"))
        self.replace_btn = QPushButton(self.tr("Replace"))
        self.replace_all_btn = QPushButton(self.tr("Replace All"))

        find_replace_layout.addWidget(self.find_input, stretch=1)
        find_replace_layout.addWidget(self.replace_input, stretch=1)
        find_replace_layout.addWidget(self.find_next_btn)
        find_replace_layout.addWidget(self.replace_btn)
        find_replace_layout.addWidget(self.replace_all_btn)

        self.find_next_btn.clicked.connect(self._find_next)
        self.replace_btn.clicked.connect(self._replace_current)
        self.replace_all_btn.clicked.connect(self._replace_all)
        self.find_input.returnPressed.connect(self._find_next)
        self.find_input.textChanged.connect(self._on_find_text_changed)

        right_layout.addLayout(find_replace_layout)

        self.translation_text = QTextEdit()
        right_layout.addWidget(self.translation_text)

        # Save and Retranslate buttons
        action_layout = QHBoxLayout()
        self.save_chunk_btn = QPushButton(self.tr("Save Changes"))
        self.save_chunk_btn.clicked.connect(self._save_chunk_translation)
        action_layout.addWidget(self.save_chunk_btn)

        self.retranslate_chunk_btn = QPushButton(self.tr("Retranslate"))
        self.retranslate_chunk_btn.clicked.connect(self._retranslate_current_chunk)
        action_layout.addWidget(self.retranslate_chunk_btn)

        right_layout.addLayout(action_layout)

        # Navigation buttons
        nav_layout = QHBoxLayout()
        self.prev_btn = QPushButton("\u2190 " + self.tr("Previous"))
        self.prev_btn.clicked.connect(self._go_previous)
        self.next_btn = QPushButton(self.tr("Next") + " \u2192")
        self.next_btn.clicked.connect(self._go_next)
        nav_layout.addWidget(self.prev_btn)
        nav_layout.addWidget(self.next_btn)
        right_layout.addLayout(nav_layout)

        splitter.addWidget(right_widget)

        # Set splitter sizes (30% list, 70% detail)
        splitter.setSizes([300, 700])

        layout.addWidget(splitter)

        return widget

    def _populate_documents(self) -> None:
        """Populate document selector with all translatable documents."""
        documents = self._db_call_or_default(
            [],
            lambda: sorted(self.document_repo.list_documents(), key=lambda d: int(d["document_id"])),
        )
        status_rows = self._db_call_or_default([], self.document_repo.get_documents_with_status)
        status_by_id = {int(doc["document_id"]): doc for doc in status_rows}
        for doc in documents:
            doc_id = doc["document_id"]
            doc_type = translate_document_type(doc.get("document_type", "unknown"))
            status = status_by_id.get(int(doc_id), {})
            total = int(status.get("total_chunks", 0) or 0)
            translated = int(status.get("chunks_translated", 0) or 0)
            ocr_pending = int(status.get("ocr_pending", 0) or 0)

            if is_ocr_required_for_type(doc.get("document_type", "")) and ocr_pending > 0:
                label = qarg(self.tr("Document %1 (%2) [OCR pending]"), doc_id, doc_type)
            elif translated == total and total > 0:
                label = qarg(self.tr("Document %1 (%2) [Translated]"), doc_id, doc_type)
            elif translated > 0:
                label = qarg(self.tr("Document %1 (%2) [%3/%4 translated]"), doc_id, doc_type, translated, total)
            else:
                label = qarg(self.tr("Document %1 (%2)"), doc_id, doc_type)

            self.doc_combo.addItem(label, doc_id)

    def _update_start_button_state(self) -> None:
        """Enable/disable start button and update label based on document state."""
        if self._is_cleaned_up:
            return
        if (self.worker and self.worker.isRunning()) or self._is_batch_task_worker_running():
            self.start_btn.setEnabled(False)
            self.doc_combo.setEnabled(False)
            self.skip_context_cb.setEnabled(False)
            return
        self.skip_context_cb.setEnabled(True)
        has_documents = self.doc_combo.count() > 1
        self.start_btn.setEnabled(has_documents)
        self.doc_combo.setEnabled(has_documents)

        if not has_documents:
            self.start_btn.setText(self.tr("Start Translation"))
            self.start_btn.setStyleSheet("")
            self.start_btn.setToolTip("")
            return

        pending_ocr_doc_ids = self._get_preflight_docs_with_pending_ocr()
        if pending_ocr_doc_ids:
            self.start_btn.setEnabled(False)
            self.start_btn.setText(self.tr("Start Translation"))
            self.start_btn.setStyleSheet("")
            self.start_btn.setToolTip(
                qarg(
                    self.tr("OCR is pending for document(s): %1. Complete OCR first."),
                    ", ".join(str(doc_id) for doc_id in pending_ocr_doc_ids),
                )
            )
            return

        is_retranslation = self._is_retranslation()
        if is_retranslation and self._has_uncancelled_batch_tasks():
            self.start_btn.setEnabled(False)
            self.start_btn.setText(self.tr("Retranslate"))
            self.start_btn.setStyleSheet("background-color: #e67e22; color: white; font-weight: bold;")
            self.start_btn.setToolTip(
                self.tr("Retranslate is unavailable while async batch tasks are active for this book.")
            )
            self._update_retranslate_chunk_button_state()
            return

        if is_retranslation:
            self.start_btn.setText(self.tr("Retranslate"))
            self.start_btn.setStyleSheet("background-color: #e67e22; color: white; font-weight: bold;")
        else:
            self.start_btn.setText(self.tr("Start Translation"))
            self.start_btn.setStyleSheet("")
        self.start_btn.setToolTip("")
        self._update_retranslate_chunk_button_state()

    def _has_uncancelled_batch_tasks(self) -> bool:
        """Return True when this book still has non-terminal async batch tasks."""
        tasks = self._batch_tasks_cache
        return any(task.status not in TERMINAL_TASK_STATUSES for task in tasks)

    def _update_retranslate_chunk_button_state(self) -> None:
        """Enable/disable chunk retranslate based on task state and selection."""
        if not hasattr(self, "retranslate_chunk_btn"):
            return
        retranslate_worker = getattr(self, "retranslate_worker", None)
        if retranslate_worker and retranslate_worker.isRunning():
            return

        has_selected_chunk = getattr(self, "_current_chunk", None) is not None
        blocked_by_batch_tasks = self._has_uncancelled_batch_tasks()
        self.retranslate_chunk_btn.setEnabled(has_selected_chunk and not blocked_by_batch_tasks)
        if blocked_by_batch_tasks:
            self.retranslate_chunk_btn.setToolTip(
                self.tr("Retranslate is unavailable while async batch tasks are active for this book.")
            )
        else:
            self.retranslate_chunk_btn.setToolTip(
                self.tr("Retranslate the selected chunk using the LLM (incurs API cost).")
            )

    def _is_retranslation(self) -> bool:
        """Check if the current document selection would be a retranslation."""
        refresh_ok = self._db_call_or_default(False, lambda: (self.term_db.refresh() or True))
        if not refresh_ok:
            return False
        selected_ids = self._get_selected_document_ids()
        if selected_ids is None:
            documents = self._db_call_or_default([], self.document_repo.list_documents)
            selected_ids = [int(doc["document_id"]) for doc in documents]
        if not selected_ids:
            return False

        has_chunks = False
        for doc_id in selected_ids:
            chunks = self.term_db.list_chunks(document_id=doc_id)
            if not chunks:
                return False
            has_chunks = True
            if not all(c.is_translated for c in chunks):
                return False
        return has_chunks

    def _get_preflight_document_ids(self) -> list[int] | None:
        """Get document IDs to preflight for current selection."""
        selected = self._get_selected_document_ids()
        all_docs = self._db_call_or_default(
            [],
            lambda: sorted(self.document_repo.list_documents(), key=lambda d: int(d["document_id"])),
        )
        if not all_docs:
            return None
        if selected is None:
            return [int(doc["document_id"]) for doc in all_docs]
        if not selected:
            return []

        selected_ids = {int(doc_id) for doc_id in selected}
        selected_docs = [doc for doc in all_docs if int(doc["document_id"]) in selected_ids]
        if selected_docs and all(
            not is_ocr_required_for_type(str(doc.get("document_type", ""))) for doc in selected_docs
        ):
            return [int(doc["document_id"]) for doc in selected_docs]

        cutoff = max(selected_ids)
        return [int(doc["document_id"]) for doc in all_docs if int(doc["document_id"]) <= cutoff]

    def _get_preflight_docs_with_pending_ocr(self) -> list[int]:
        """Return preflight document IDs that still need OCR."""
        preflight_ids = self._get_preflight_document_ids()
        if not preflight_ids:
            return []

        status_rows = self._db_call_or_default([], self.document_repo.get_documents_with_status)
        docs_by_id = {int(doc["document_id"]): doc for doc in status_rows}
        pending_ids: list[int] = []
        for doc_id in preflight_ids:
            doc = docs_by_id.get(doc_id)
            if doc is None:
                continue
            if not is_ocr_required_for_type(doc.get("document_type", "")):
                continue
            if int(doc.get("ocr_pending", 0) or 0) > 0:
                pending_ids.append(doc_id)
        return pending_ids

    def _refresh_document_selector(self) -> None:
        """Refresh the document selector with current pending documents."""
        if self._is_cleaned_up:
            return
        current_data = self.doc_combo.currentData()
        self.doc_combo.blockSignals(True)
        self.doc_combo.clear()
        self.doc_combo.addItem(self.tr("All Documents"), None)
        self._populate_documents()
        # Try to restore previous selection
        if current_data is not None:
            for i in range(self.doc_combo.count()):
                if self.doc_combo.itemData(i) == current_data:
                    self.doc_combo.setCurrentIndex(i)
                    break
        self.doc_combo.blockSignals(False)
        self._update_start_button_state()

    def refresh(self) -> None:
        """Refresh the view with current data.

        Called when switching to this tab to ensure document list is up-to-date.
        """
        if self._is_cleaned_up:
            return
        in_review_mode = self.stack.currentWidget() == self.review_page
        self._document_type_cache.clear()
        self._refresh_document_selector()
        self._refresh_review_document_selector()
        self._refresh_batch_tasks()
        self._update_stats()
        if in_review_mode:
            self._on_review_document_changed(self.review_doc_combo.currentIndex())

    def _get_selected_document_ids(self) -> list[int] | None:
        """Get selected document IDs from combo box."""
        doc_id = self.doc_combo.currentData()
        if doc_id is None:
            return None  # All documents
        return [doc_id]

    def _read_chunk_stats(self) -> dict:
        self.term_db.refresh()
        return self.term_db.get_chunk_stats()

    def _update_stats(self) -> None:
        """Update translation statistics display."""
        stats = self._db_call_or_default(None, self._read_chunk_stats)
        if stats is None:
            return
        total = stats.get("total", 0)
        translated = stats.get("translated", 0)
        progress = stats.get("progress_percent", 0.0)

        self.stats_label.setText(qarg(self.tr("Chunks: %1 translated / %2 total (%3%)"), translated, total, progress))

        # Enable/disable review button based on whether there are chunks
        self.review_btn.setEnabled(total > 0)

    def _has_manga_documents(self, document_ids: list[int] | None) -> bool:
        """Check if any of the selected documents are manga."""
        documents = self._db_call_or_default([], self.document_repo.list_documents)
        if document_ids is not None:
            id_set = set(document_ids)
            documents = [d for d in documents if d["document_id"] in id_set]
        return any(d.get("document_type") == "manga" for d in documents)

    def _resolve_trigger_conditions(
        self,
        *,
        for_batch_submit: bool,
    ) -> tuple[list[int] | None, bool] | None:
        """Resolve shared trigger conditions for sync and async translation flows."""
        pending_ocr_doc_ids = self._get_preflight_docs_with_pending_ocr()
        if pending_ocr_doc_ids:
            joined_ids = ", ".join(str(doc_id) for doc_id in pending_ocr_doc_ids)
            message = (
                self.tr(
                    "Cannot submit batch task yet. Documents with pending OCR in the selected stack: %1.\n\n"
                    "Please complete OCR from the OCR Review tab first."
                )
                if for_batch_submit
                else self.tr(
                    "Cannot translate yet. Documents with pending OCR in the selected stack: %1.\n\n"
                    "Please complete OCR from the OCR Review tab first."
                )
            )
            QMessageBox.warning(
                self,
                self.tr("OCR Not Complete"),
                qarg(message, joined_ids),
            )
            return None

        document_ids = self._get_selected_document_ids()
        has_manga = self._has_manga_documents(document_ids)
        config_dict = self.book_manager.get_book_config(self.book_id) or {}

        if for_batch_submit:
            if has_manga:
                QMessageBox.warning(
                    self,
                    self.tr("Not Supported"),
                    self.tr("Async batch tasks are not supported for manga documents."),
                )
                return None
            if not config_dict.get("translator_batch_config"):
                QMessageBox.warning(
                    self,
                    self.tr("Configuration Required"),
                    self.tr("translator_batch_config is required to submit async batch tasks."),
                )
                return None
        elif has_manga and not config_dict.get("manga_translator_config"):
            QMessageBox.warning(
                self,
                self.tr("Configuration Required"),
                self.tr(
                    "manga_translator_config is required to translate manga documents. "
                    "Please configure it in your book settings."
                ),
            )
            return None

        force = self._is_retranslation()
        if force and self._has_uncancelled_batch_tasks():
            QMessageBox.information(
                self,
                self.tr("Batch Task Running"),
                self.tr("Retranslate is unavailable while async batch tasks are active for this book."),
            )
            return None
        if force:
            reply = QMessageBox.question(
                self,
                self.tr("Retranslate Document"),
                self.tr(
                    "This will retranslate all chunks in the selected document(s). "
                    "Existing translations will be overwritten and LLM API costs will be incurred.\n\n"
                    "Are you sure you want to continue?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return None

        return document_ids, force

    def _start_translation(self) -> None:
        """Start translation in background."""
        # M40: Guard against double-start
        if self.worker and self.worker.isRunning():
            return
        if self._is_batch_task_worker_running():
            QMessageBox.information(
                self,
                self.tr("Batch Task Running"),
                self.tr("A batch task operation is running. Please wait for it to finish first."),
            )
            return

        resolved = self._resolve_trigger_conditions(for_batch_submit=False)
        if resolved is None:
            return
        document_ids, force = resolved

        # Disable start button (review stays enabled)
        self.start_btn.setEnabled(False)
        self.doc_combo.setEnabled(False)
        self.skip_context_cb.setEnabled(False)
        self.status_label.hide()

        # Show progress
        self.progress_widget.show()
        self.progress_widget.reset()
        self.progress_widget.set_cancellable(True)

        # Create and start worker
        self.worker = TranslationWorker(
            self.book_manager,
            self.book_id,
            document_ids,
            force=force,
            skip_context=self.skip_context_cb.isChecked(),
        )
        self.worker.progress.connect(self._on_translation_progress)
        self.worker.finished_success.connect(self._on_translation_success)
        self.worker.cancelled.connect(self._on_translation_cancelled)
        self.worker.error.connect(self._on_translation_error)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def _cancel_translation(self) -> None:
        """Cancel ongoing translation."""
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.progress_widget.message_label.setText(self.tr("Cancelling..."))
            self.progress_widget.set_cancellable(False)

    def _on_translation_progress(self, current: int, total: int, message: str) -> None:
        """Handle translation progress update."""
        translated_message = translate_progress_message(message)
        self.progress_widget.set_progress(current, total, translated_message)

    def _on_translation_success(self, _result: object) -> None:
        """Handle successful translation."""
        self.status_label.setText(self.tr("Translation completed successfully!"))
        self.status_label.setStyleSheet("color: green;")
        self.status_label.show()

        self._update_stats()
        self._refresh_document_selector()
        self.translation_completed.emit()

    def _on_translation_error(self, error_msg: str) -> None:
        """Handle translation error."""
        self.status_label.setText(qarg(self.tr("Translation failed: %1"), error_msg))
        self.status_label.setStyleSheet("color: red;")
        self.status_label.show()

        QMessageBox.critical(
            self,
            self.tr("Translation Error"),
            qarg(self.tr("Failed to translate chunks:\n%1"), error_msg),
        )

    def _on_translation_cancelled(self) -> None:
        """Handle user-cancelled translation."""
        self.status_label.setText(self.tr("Translation cancelled."))
        self.status_label.setStyleSheet("color: #b45309;")
        self.status_label.show()

    def _on_worker_finished(self) -> None:
        """Clean up after worker finishes."""
        self.progress_widget.hide()
        self.progress_widget.set_cancellable(True)
        self.worker = None
        self.skip_context_cb.setEnabled(True)
        self._refresh_document_selector()
        self._refresh_review_document_selector()

    # ------------------------------------------------------------------
    # Async batch task helpers
    # ------------------------------------------------------------------

    def _on_batch_tasks_timer(self) -> None:
        if self._is_cleaned_up:
            return
        if not hasattr(self, "batch_task_list"):
            return
        self._refresh_batch_tasks()

    def _refresh_batch_tasks(self) -> None:
        if self._is_cleaned_up:
            return
        if not hasattr(self, "batch_task_list"):
            return
        current_task_id = self._selected_batch_task_id()
        tasks = self._batch_task_store.list_tasks(self.book_id)
        self._batch_tasks_cache = tasks

        self.batch_task_list.blockSignals(True)
        self.batch_task_list.clear()
        target_row = -1
        for idx, task in enumerate(tasks):
            text = f"#{task.task_id[:8]} | {task.status} | {task.phase} | {task.completed_items}/{task.total_items}"
            if task.last_error:
                text += f" | {task.last_error}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, task.task_id)
            self.batch_task_list.addItem(item)
            if current_task_id and task.task_id == current_task_id:
                target_row = idx
        self.batch_task_list.blockSignals(False)

        if target_row >= 0:
            self.batch_task_list.setCurrentRow(target_row)
        elif self.batch_task_list.count() > 0:
            self.batch_task_list.setCurrentRow(0)
        else:
            self._on_batch_task_selected(-1)
        self._update_retranslate_chunk_button_state()

    def _selected_batch_task_id(self) -> str | None:
        if not hasattr(self, "batch_task_list"):
            return None
        item = self.batch_task_list.currentItem()
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if isinstance(value, str) else None

    def _on_batch_task_selected(self, _row: int) -> None:
        if (
            not hasattr(self, "run_batch_task_btn")
            or not hasattr(self, "cancel_batch_task_btn")
            or not hasattr(self, "delete_batch_task_btn")
        ):
            return
        task_id = self._selected_batch_task_id()
        if not task_id:
            self.run_batch_task_btn.setEnabled(False)
            self.cancel_batch_task_btn.setEnabled(False)
            self.delete_batch_task_btn.setEnabled(False)
            return

        task = self._batch_task_store.get(task_id)
        if task is None:
            self.run_batch_task_btn.setEnabled(False)
            self.cancel_batch_task_btn.setEnabled(False)
            self.delete_batch_task_btn.setEnabled(False)
            return

        if self._is_batch_task_worker_running():
            self.run_batch_task_btn.setEnabled(False)
            self.delete_batch_task_btn.setEnabled(False)
            self.cancel_batch_task_btn.setEnabled(task.task_id == getattr(self, "_active_batch_task_id", None))
            return

        is_terminal = task.status in TERMINAL_TASK_STATUSES
        is_non_deletable = task.status in _NON_DELETABLE_BATCH_TASK_STATUSES
        is_non_runnable = task.status in _NON_RUNNABLE_BATCH_TASK_STATUSES
        self.run_batch_task_btn.setEnabled(not is_non_runnable)
        self.cancel_batch_task_btn.setEnabled(not is_terminal)
        self.delete_batch_task_btn.setEnabled(not is_non_deletable)

    def _is_batch_task_worker_running(self) -> bool:
        return self.batch_task_worker is not None and self.batch_task_worker.isRunning()

    def _start_batch_task_worker(self, worker: BatchTranslationTaskWorker) -> None:
        if self._is_batch_task_worker_running():
            return
        if worker.action == "run" and BatchTranslationTaskWorker.is_run_active_for_book(self.book_id):
            if hasattr(self, "batch_status_label"):
                self.batch_status_label.setStyleSheet("color: #b45309;")
                self.batch_status_label.setText(self.tr("A batch run is already active for this book."))
                self.batch_status_label.show()
            return
        self.batch_task_worker = worker
        self._active_batch_task_id = worker.task_id if worker.action == "run" else None
        self.submit_batch_btn.setEnabled(False)
        self.run_batch_task_btn.setEnabled(False)
        self.cancel_batch_task_btn.setEnabled(bool(self._active_batch_task_id))
        self.delete_batch_task_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.batch_status_label.show()
        self.batch_status_label.setText(self.tr("Running batch task operation..."))

        worker.progress.connect(self._on_batch_task_progress)
        worker.finished_success.connect(self._on_batch_task_success)
        worker.error.connect(self._on_batch_task_error)
        worker.cancelled.connect(self._on_batch_task_cancelled)
        worker.finished.connect(self._on_batch_task_finished)
        worker.start()

    def _submit_batch_task(self) -> None:
        if (self.worker and self.worker.isRunning()) or self._is_batch_task_worker_running():
            return

        resolved = self._resolve_trigger_conditions(for_batch_submit=True)
        if resolved is None:
            return
        document_ids, force = resolved

        worker = BatchTranslationTaskWorker(
            self.book_manager,
            self.book_id,
            action="create",
            document_ids=document_ids,
            force=force,
            skip_context=self.skip_context_cb.isChecked(),
            auto_run_after_create=False,
        )
        self._start_batch_task_worker(worker)

    def _run_selected_batch_task(self) -> None:
        if (self.worker and self.worker.isRunning()) or self._is_batch_task_worker_running():
            return
        task_id = self._selected_batch_task_id()
        if not task_id:
            return
        worker = BatchTranslationTaskWorker(
            self.book_manager,
            self.book_id,
            action="run",
            task_id=task_id,
        )
        self._start_batch_task_worker(worker)

    def _cancel_selected_batch_task(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        task_id = self._selected_batch_task_id()
        if not task_id:
            return
        if self._is_batch_task_worker_running():
            if task_id != self._active_batch_task_id:
                return
            task = self._batch_task_store.get(task_id)
            if task is None or task.status in TERMINAL_TASK_STATUSES:
                self._refresh_batch_tasks()
                return
            self._batch_task_store.mark_cancel_requested(task_id)
            self.batch_status_label.setStyleSheet("")
            self.batch_status_label.setText(self.tr("Batch task cancellation requested."))
            self.batch_status_label.show()
            self._refresh_batch_tasks()
            return
        worker = BatchTranslationTaskWorker(
            self.book_manager,
            self.book_id,
            action="cancel",
            task_id=task_id,
        )
        self._start_batch_task_worker(worker)

    def _delete_selected_batch_task(self) -> None:
        if (self.worker and self.worker.isRunning()) or self._is_batch_task_worker_running():
            return
        task_id = self._selected_batch_task_id()
        if not task_id:
            return
        reply = QMessageBox.question(
            self,
            self.tr("Delete Batch Task"),
            self.tr("Delete the selected async batch task from local history?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        worker = BatchTranslationTaskWorker(
            self.book_manager,
            self.book_id,
            action="delete",
            task_id=task_id,
        )
        self._start_batch_task_worker(worker)

    def _on_batch_task_progress(self, current: int, total: int, message: str) -> None:
        if self._is_cleaned_up:
            return
        del current, total
        translated_message = translate_progress_message(message)
        self.batch_status_label.show()
        self.batch_status_label.setText(translated_message)

    def _on_batch_task_success(self, payload: object) -> None:
        if self._is_cleaned_up:
            return
        action = ""
        task_status = ""
        if isinstance(payload, dict):
            action = str(payload.get("action", ""))
            task_payload = payload.get("task")
            if isinstance(task_payload, dict):
                status_value = task_payload.get("status")
                if isinstance(status_value, str):
                    task_status = status_value
        self.batch_status_label.setStyleSheet("")
        if action == "cancel":
            if task_status == STATUS_CANCELLED:
                self.batch_status_label.setText(self.tr("Batch task cancelled."))
            elif task_status == STATUS_CANCELLING:
                self.batch_status_label.setText(self.tr("Batch task cancellation is in progress."))
            else:
                self.batch_status_label.setText(self.tr("Batch task cancellation requested."))
        elif action == "run":
            if task_status == STATUS_PAUSED:
                self.batch_status_label.setText(
                    self.tr("Batch task paused due to transient error. Re-run selected task.")
                )
                self.batch_status_label.setStyleSheet("color: #b45309;")
            elif task_status == STATUS_FAILED:
                self.batch_status_label.setText(self.tr("Batch task run failed."))
                self.batch_status_label.setStyleSheet("color: red;")
            elif task_status == STATUS_COMPLETED_WITH_ERRORS:
                self.batch_status_label.setText(self.tr("Batch task run completed with errors."))
                self.batch_status_label.setStyleSheet("color: #b45309;")
            else:
                self.batch_status_label.setText(self.tr("Batch task run completed."))
        elif action == "delete":
            cleanup_warnings: list[str] = []
            if isinstance(payload, dict):
                warnings_value = payload.get("cleanup_warnings")
                if isinstance(warnings_value, list):
                    cleanup_warnings = [str(item) for item in warnings_value if str(item)]
            if cleanup_warnings:
                self.batch_status_label.setText(
                    self.tr("Batch task deleted locally; remote cleanup completed with warnings.")
                )
                self.batch_status_label.setStyleSheet("color: #b45309;")
                self.batch_status_label.setToolTip("\n".join(cleanup_warnings))
            else:
                self.batch_status_label.setText(self.tr("Batch task deleted."))
                self.batch_status_label.setToolTip("")
        else:
            self.batch_status_label.setText(self.tr("Batch task submitted."))
        self.batch_status_label.show()
        self._refresh_batch_tasks()
        self._update_stats()
        self._refresh_document_selector()
        self._refresh_review_document_selector()

    def _on_batch_task_error(self, error_msg: str) -> None:
        if self._is_cleaned_up:
            return
        self.batch_status_label.setText(qarg(self.tr("Batch task failed: %1"), error_msg))
        self.batch_status_label.setStyleSheet("color: red;")
        self.batch_status_label.show()
        QMessageBox.critical(
            self,
            self.tr("Batch Task Error"),
            qarg(self.tr("Failed to process batch task:\n%1"), error_msg),
        )
        self._refresh_batch_tasks()

    def _on_batch_task_cancelled(self) -> None:
        if self._is_cleaned_up:
            return
        self.batch_status_label.setText(self.tr("Batch task operation paused."))
        self.batch_status_label.setStyleSheet("color: #b45309;")
        self.batch_status_label.show()
        self._refresh_batch_tasks()

    def _on_batch_task_finished(self) -> None:
        if self._is_cleaned_up:
            self.batch_task_worker = None
            self._active_batch_task_id = None
            return
        self.batch_task_worker = None
        self._active_batch_task_id = None
        self.submit_batch_btn.setEnabled(True)
        self._refresh_batch_tasks()
        self._on_batch_task_selected(self.batch_task_list.currentRow())
        self._update_start_button_state()

    def _populate_review_documents(self) -> None:
        """Populate review document selector."""
        documents = self._db_call_or_default([], self.document_repo.list_documents)
        for doc in documents:
            doc_id = doc["document_id"]
            doc_type = translate_document_type(doc.get("document_type", "unknown"))
            self.review_doc_combo.addItem(qarg(self.tr("Document %1 (%2)"), doc_id, doc_type), doc_id)

    def _refresh_review_document_selector(self) -> None:
        """Refresh review document selector with current documents."""
        if self._is_cleaned_up:
            return
        current_data = self.review_doc_combo.currentData()
        self.review_doc_combo.blockSignals(True)
        self.review_doc_combo.clear()
        self.review_doc_combo.addItem(self.tr("All Documents"), None)
        self._populate_review_documents()
        if current_data is not None:
            for i in range(self.review_doc_combo.count()):
                if self.review_doc_combo.itemData(i) == current_data:
                    self.review_doc_combo.setCurrentIndex(i)
                    break
        self.review_doc_combo.blockSignals(False)

    def _is_manga_document(self, doc_id: int | None) -> bool:
        """Check if the given document ID is a manga document."""
        if doc_id is None:
            return False
        # L21: Use cache to avoid querying all documents each time
        if doc_id in self._document_type_cache:
            return self._document_type_cache[doc_id] == "manga"
        doc = self.document_repo.get_document_by_id(doc_id)
        doc_type = doc.get("document_type", "unknown") if doc else "unknown"
        self._document_type_cache[doc_id] = doc_type
        return doc_type == "manga"

    def _on_review_document_changed(self, _index: int) -> None:
        """Handle document filter change in review mode."""
        doc_id = self._get_review_document_id()
        if self._is_manga_document(doc_id):
            self._manga_review_widget.load_manga_pages(doc_id)
            self.review_stack.setCurrentWidget(self._manga_review_widget)
        else:
            self._load_chunks_list()
            self.review_stack.setCurrentWidget(self._text_review_widget)

    def _switch_to_review(self) -> None:
        """Switch to review mode."""
        doc_id = self._get_review_document_id()
        if self._is_manga_document(doc_id):
            self._manga_review_widget.load_manga_pages(doc_id)
            self.review_stack.setCurrentWidget(self._manga_review_widget)
        else:
            self._load_chunks_list()
            self.review_stack.setCurrentWidget(self._text_review_widget)
        self.stack.setCurrentWidget(self.review_page)

    def _switch_to_progress(self) -> None:
        """Switch to progress mode."""
        self._update_stats()
        self.stack.setCurrentWidget(self.progress_page)

    def _get_review_document_id(self) -> int | None:
        """Get selected document ID from review combo box."""
        return self.review_doc_combo.currentData()

    def _load_chunks_list(self) -> None:
        """Load chunks into the list widget, filtered by selected document."""
        self.chunk_list.clear()
        doc_id = self._get_review_document_id()
        chunks = self.term_db.list_chunks(document_id=doc_id)

        for chunk in chunks:
            text = chunk.text or ""
            preview = text[:PREVIEW_TRUNCATION_LENGTH] + "..." if len(text) > PREVIEW_TRUNCATION_LENGTH else text
            status = "\u2713" if chunk.is_translated else "\u25cb"

            item = QListWidgetItem(f"{status} #{chunk.chunk_id}: {preview}")
            item.setData(Qt.ItemDataRole.UserRole, chunk)
            self.chunk_list.addItem(item)

        # Select first item if available
        if self.chunk_list.count() > 0:
            self.chunk_list.setCurrentRow(0)
        else:
            self._on_chunk_selected(-1)

    def _on_chunk_selected(self, row: int) -> None:
        """Handle chunk selection from list."""
        self._find_pos = 0
        if row < 0:
            self._current_chunk = None
            self.original_text.clear()
            self.translation_text.clear()
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            self._update_retranslate_chunk_button_state()
            return

        item = self.chunk_list.item(row)
        if not item:
            return

        chunk = item.data(Qt.ItemDataRole.UserRole)
        if not chunk:
            return

        self._current_chunk = chunk
        self.original_text.setPlainText(chunk.text or "")
        self.translation_text.setPlainText(chunk.translation or "")

        # Track original line count for validation
        translation_text = chunk.translation or chunk.text or ""
        self._original_line_count = len(translation_text.splitlines()) if translation_text.strip() else 0

        # Update navigation buttons
        self.prev_btn.setEnabled(row > 0)
        self.next_btn.setEnabled(row < self.chunk_list.count() - 1)
        self._update_retranslate_chunk_button_state()

    def _save_chunk_translation(self) -> None:
        """Save edited translation to database."""
        if not self._current_chunk:
            return

        new_translation = self.translation_text.toPlainText()

        # Validate line count matches original
        new_line_count = len(new_translation.splitlines()) if new_translation.strip() else 0
        if self._original_line_count > 0 and new_line_count != self._original_line_count:
            QMessageBox.warning(
                self,
                self.tr("Line Count Mismatch"),
                qarg(
                    self.tr(
                        "Cannot save: translation has %1 lines but original has %2 lines.\n\n"
                        "The number of lines must remain the same."
                    ),
                    new_line_count,
                    self._original_line_count,
                ),
            )
            return

        # Update chunk record
        updated_chunk = self._build_chunk_record(self._current_chunk, new_translation)

        # Save to database
        self.term_db.upsert_chunks([updated_chunk])

        # Update current chunk reference
        self._current_chunk = updated_chunk

        # Refresh list item
        current_row = self.chunk_list.currentRow()
        if current_row >= 0:
            item = self.chunk_list.item(current_row)
            if item:
                text = updated_chunk.text or ""
                preview = text[:PREVIEW_TRUNCATION_LENGTH] + "..." if len(text) > PREVIEW_TRUNCATION_LENGTH else text
                status = "\u2713" if updated_chunk.is_translated else "\u25cb"
                item.setText(f"{status} #{updated_chunk.chunk_id}: {preview}")
                item.setData(Qt.ItemDataRole.UserRole, updated_chunk)

        # Show confirmation
        QMessageBox.information(self, self.tr("Saved"), self.tr("Translation saved successfully!"))

    def _retranslate_current_chunk(self) -> None:
        """Retranslate the currently selected chunk using the LLM."""
        if self._has_uncancelled_batch_tasks():
            QMessageBox.information(
                self,
                self.tr("Batch Task Running"),
                self.tr("Retranslate is unavailable while async batch tasks are active for this book."),
            )
            return
        if not self._current_chunk:
            return

        if self.retranslate_worker and self.retranslate_worker.isRunning():
            return

        chunk = self._current_chunk
        if chunk.document_id is None:
            QMessageBox.warning(self, self.tr("Error"), self.tr("Chunk has no associated document."))
            return

        reply = QMessageBox.question(
            self,
            self.tr("Retranslate Chunk"),
            qarg(
                self.tr("This will retranslate chunk #%1 using the LLM.\nLLM API costs will be incurred.\n\nContinue?"),
                chunk.chunk_id,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.retranslate_chunk_btn.setEnabled(False)
        self.retranslate_chunk_btn.setText(self.tr("Retranslating..."))

        self.retranslate_worker = RetranslateChunkWorker(
            self.book_manager,
            self.book_id,
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            skip_context=self.skip_context_cb.isChecked(),
        )
        self.retranslate_worker.finished_success.connect(self._on_retranslate_success)
        self.retranslate_worker.error.connect(self._on_retranslate_error)
        self.retranslate_worker.cancelled.connect(self._on_retranslate_finished)
        self.retranslate_worker.finished.connect(self._on_retranslate_finished)
        self.retranslate_worker.start()

    def _on_retranslate_success(self, new_translation: object) -> None:
        """Handle successful chunk retranslation."""
        if isinstance(new_translation, str):
            self.translation_text.setPlainText(new_translation)

            # Update the current chunk reference
            if self._current_chunk:
                self._current_chunk = self._build_chunk_record(self._current_chunk, new_translation)
                # Refresh list item
                current_row = self.chunk_list.currentRow()
                if current_row >= 0:
                    item = self.chunk_list.item(current_row)
                    if item:
                        text = self._current_chunk.text or ""
                        preview = (
                            text[:PREVIEW_TRUNCATION_LENGTH] + "..." if len(text) > PREVIEW_TRUNCATION_LENGTH else text
                        )
                        status = "\u2713" if self._current_chunk.is_translated else "\u25cb"
                        item.setText(f"{status} #{self._current_chunk.chunk_id}: {preview}")
                        item.setData(Qt.ItemDataRole.UserRole, self._current_chunk)

                # Update original line count for validation
                self._original_line_count = len(new_translation.splitlines()) if new_translation.strip() else 0

    def _on_retranslate_error(self, error_msg: str) -> None:
        """Handle retranslation error."""
        QMessageBox.critical(
            self,
            self.tr("Retranslation Error"),
            qarg(self.tr("Failed to retranslate chunk:\n%1"), error_msg),
        )

    def _on_retranslate_finished(self) -> None:
        """Clean up after retranslation worker finishes."""
        self.retranslate_chunk_btn.setText(self.tr("Retranslate"))
        self.retranslate_worker = None
        self._update_retranslate_chunk_button_state()

    def _build_chunk_record(self, chunk: TranslationChunkRecord, translation_text: str) -> TranslationChunkRecord:
        """Build a TranslationChunkRecord with updated translation.

        Args:
            chunk: Original chunk record
            translation_text: New translation text

        Returns:
            Updated TranslationChunkRecord
        """
        return TranslationChunkRecord(
            chunk_id=chunk.chunk_id,
            hash=chunk.hash,
            text=chunk.text,
            document_id=chunk.document_id,
            created_at=chunk.created_at,
            is_extracted=chunk.is_extracted,
            is_summarized=chunk.is_summarized,
            is_occurrence_mapped=chunk.is_occurrence_mapped,
            is_translated=bool(translation_text.strip()),
            translation=translation_text if translation_text.strip() else None,
        )

    def _go_previous(self) -> None:
        """Navigate to previous chunk."""
        current_row = self.chunk_list.currentRow()
        if current_row > 0:
            self.chunk_list.setCurrentRow(current_row - 1)

    def _go_next(self) -> None:
        """Navigate to next chunk."""
        current_row = self.chunk_list.currentRow()
        if current_row < self.chunk_list.count() - 1:
            self.chunk_list.setCurrentRow(current_row + 1)

    def _on_find_text_changed(self, _text: str) -> None:
        """Reset search position when the find input text changes."""
        self._find_pos = 0
        self._clear_find_highlight()

    def _find_in_current_chunk(self, search_text: str, from_start: bool = False) -> bool:
        """Search for text in the current chunk's translation editor.

        Args:
            search_text: Text to search for.
            from_start: If True, search from the beginning of the document.

        Returns True if a match was found.
        """
        text = self.translation_text.toPlainText()
        start = 0 if from_start else self._find_pos

        pos = text.find(search_text, start)
        if pos >= 0:
            self._find_pos = pos + len(search_text)
            cursor = self.translation_text.textCursor()
            cursor.setPosition(pos)
            cursor.setPosition(pos + len(search_text), QTextCursor.MoveMode.KeepAnchor)
            self.translation_text.setTextCursor(cursor)
            self._highlight_current_match()
            return True
        return False

    def _auto_save_if_modified(self) -> None:
        """Save the current chunk if the translation text was modified."""
        if not self._current_chunk:
            return
        current_text = self.translation_text.toPlainText()
        if current_text != (self._current_chunk.translation or ""):
            self._save_chunk_translation()

    def _find_next(self) -> None:
        """Find the next occurrence, advancing across chunks if needed."""
        search_text = self.find_input.text()
        if not search_text:
            return

        self._clear_find_highlight()

        # 1. Try finding forward in the current chunk
        if self._find_in_current_chunk(search_text):
            return

        # 2. Search subsequent chunks by checking data directly (no UI switch)
        start_row = self.chunk_list.currentRow()
        total = self.chunk_list.count()

        if total > 1:
            self._auto_save_if_modified()
            for offset in range(1, total):
                row = (start_row + offset) % total
                item = self.chunk_list.item(row)
                if not item:
                    continue
                chunk = item.data(Qt.ItemDataRole.UserRole)
                if chunk and chunk.translation and search_text in chunk.translation:
                    self.chunk_list.setCurrentRow(row)
                    if self._find_in_current_chunk(search_text, from_start=True):
                        return

        # 3. All other chunks exhausted — wrap within original chunk from start
        if total > 1:
            self.chunk_list.setCurrentRow(start_row)
        if self._find_in_current_chunk(search_text, from_start=True):
            return

    def _replace_current(self) -> None:
        """Replace the current selection (if it matches) and find the next occurrence."""
        search_text = self.find_input.text()
        replace_text = self.replace_input.text()
        if not search_text:
            return

        cursor = self.translation_text.textCursor()
        if cursor.hasSelection() and cursor.selectedText() == search_text:
            pos = cursor.selectionStart()
            cursor.insertText(replace_text)
            # Adjust find position to right after the replacement
            self._find_pos = pos + len(replace_text)

        self._find_next()

    def _replace_all(self) -> None:
        """Replace all occurrences across all chunks."""
        search_text = self.find_input.text()
        replace_text = self.replace_input.text()
        if not search_text:
            return

        total = self.chunk_list.count()
        if total == 0:
            return

        self._auto_save_if_modified()
        total_count = 0

        for row in range(total):
            item = self.chunk_list.item(row)
            if not item:
                continue
            chunk = item.data(Qt.ItemDataRole.UserRole)
            if not chunk or not chunk.translation or search_text not in chunk.translation:
                continue

            # Only switch to this chunk if it has matches
            self.chunk_list.setCurrentRow(row)
            text = self.translation_text.toPlainText()
            count = text.count(search_text)
            new_text = text.replace(search_text, replace_text)
            self.translation_text.setPlainText(new_text)
            self._auto_save_if_modified()
            total_count += count

        if total_count > 0:
            self.translation_text.moveCursor(QTextCursor.MoveOperation.Start)

    def _highlight_current_match(self) -> None:
        """Highlight the currently selected match."""
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(255, 255, 0))  # Yellow highlight

        cursor = self.translation_text.textCursor()
        extra = QTextEdit.ExtraSelection()
        extra.cursor = cursor
        extra.format = fmt
        self.translation_text.setExtraSelections([extra])

    def _clear_find_highlight(self) -> None:
        """Clear all find highlights."""
        self.translation_text.setExtraSelections([])

    def cleanup(self) -> None:
        """Clean up resources."""
        if self._is_cleaned_up:
            return
        self._is_cleaned_up = True
        if self._batch_auto_timer is not None:
            self._batch_auto_timer.stop()

        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait()
        batch_task_worker = self.batch_task_worker
        if batch_task_worker is not None:
            self._disconnect_batch_task_worker_signals(batch_task_worker)
            if getattr(batch_task_worker, "action", "") == "run":
                self._detach_batch_run_worker(batch_task_worker)
            else:
                batch_task_worker.requestInterruption()
                if batch_task_worker.isRunning():
                    batch_task_worker.wait()
            self.batch_task_worker = None
            self._active_batch_task_id = None
        if self.retranslate_worker and self.retranslate_worker.isRunning():
            self.retranslate_worker.requestInterruption()
            self.retranslate_worker.wait()
        self._batch_task_store.close()
        if self.term_db:
            self.term_db.close()

    def _disconnect_batch_task_worker_signals(self, worker: BatchTranslationTaskWorker) -> None:
        signal_slot_pairs = (
            ("progress", self._on_batch_task_progress),
            ("finished_success", self._on_batch_task_success),
            ("error", self._on_batch_task_error),
            ("cancelled", self._on_batch_task_cancelled),
            ("finished", self._on_batch_task_finished),
        )
        for signal_name, slot in signal_slot_pairs:
            signal = getattr(worker, signal_name, None)
            if signal is None:
                continue
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                continue

    @classmethod
    def _detach_batch_run_worker(cls, worker: BatchTranslationTaskWorker) -> None:
        cls._DETACHED_BATCH_RUN_WORKERS.add(worker)

        def _release_worker() -> None:
            cls._DETACHED_BATCH_RUN_WORKERS.discard(worker)
            worker.deleteLater()

        finished_signal = getattr(worker, "finished", None)
        if finished_signal is None:
            cls._DETACHED_BATCH_RUN_WORKERS.discard(worker)
            return
        try:
            finished_signal.connect(_release_worker)
        except (TypeError, RuntimeError):
            cls._DETACHED_BATCH_RUN_WORKERS.discard(worker)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle widget close event."""
        self.cleanup()
        super().closeEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def _apply_button_tooltips(self) -> None:
        """Apply hover explanations for translation action buttons."""
        self.start_btn.setToolTip(
            self.tr("Start translation for selected documents. If already translated, this will retranslate.")
        )
        self.skip_context_cb.setToolTip(
            self.tr(
                "Use only the earliest glossary description for each term instead of chunk-positioned context summaries."
            )
        )
        if hasattr(self, "submit_batch_btn"):
            self.submit_batch_btn.setToolTip(self.tr("Create and run an async batch translation task."))
        if hasattr(self, "run_batch_task_btn"):
            self.run_batch_task_btn.setToolTip(self.tr("Resume processing for the selected async task."))
        if hasattr(self, "cancel_batch_task_btn"):
            self.cancel_batch_task_btn.setToolTip(
                self.tr("Request cancellation for the selected async task and provider batch job.")
            )
        if hasattr(self, "delete_batch_task_btn"):
            self.delete_batch_task_btn.setToolTip(self.tr("Delete the selected async task from local history."))
        self.review_btn.setToolTip(self.tr("Open review mode to inspect and edit translated chunks."))
        self.back_btn.setToolTip(self.tr("Return to progress mode and translation controls."))
        self.save_chunk_btn.setToolTip(self.tr("Save edits for the currently selected chunk translation."))
        self.retranslate_chunk_btn.setToolTip(
            self.tr("Retranslate the selected chunk using the LLM (incurs API cost).")
        )
        self.prev_btn.setToolTip(self.tr("Go to the previous chunk in the review list."))
        self.next_btn.setToolTip(self.tr("Go to the next chunk in the review list."))

    def retranslateUi(self) -> None:
        self.tip_label.setText(self._tip_text())
        # Progress page
        self.doc_selector_label.setText(self.tr("Document:"))
        self.review_btn.setText(self.tr("Review Translations"))
        self.skip_context_cb.setText(self.tr("Skip context (use first description only)"))
        self.batch_section_label.setText(self.tr("Async Batch Tasks"))
        self.submit_batch_btn.setText(self.tr("Submit Batch Task"))
        self.run_batch_task_btn.setText(self.tr("Run Selected Task"))
        self.cancel_batch_task_btn.setText(self.tr("Cancel Selected Task"))
        self.delete_batch_task_btn.setText(self.tr("Delete Selected Task"))
        self._update_stats()
        self._update_start_button_state()

        # Review page
        self.back_btn.setText(self.tr("Back to Progress"))
        self.review_doc_label.setText(self.tr("Document:"))

        # Text review
        self.chunks_label.setText(self.tr("Chunks:"))
        self.orig_label.setText(self.tr("Original:"))
        self.trans_label.setText(self.tr("Translation:"))
        self.find_input.setPlaceholderText(self.tr("Find..."))
        self.replace_input.setPlaceholderText(self.tr("Replace with..."))
        self.find_next_btn.setText(self.tr("Find Next"))
        self.replace_btn.setText(self.tr("Replace"))
        self.replace_all_btn.setText(self.tr("Replace All"))
        self.save_chunk_btn.setText(self.tr("Save Changes"))
        self.retranslate_chunk_btn.setText(self.tr("Retranslate"))
        self.prev_btn.setText("\u2190 " + self.tr("Previous"))
        self.next_btn.setText(self.tr("Next") + " \u2192")
        self._apply_button_tooltips()

        # Manga review (delegated)
        self._manga_review_widget.retranslateUi()

    def _tip_text(self) -> str:
        return self.tr(
            "Translate selected documents directly (glossary extraction is optional, but glossary terms are always used).\n"
            "For OCR-required document types, complete OCR first. Keep original line count when editing text chunks."
        )
