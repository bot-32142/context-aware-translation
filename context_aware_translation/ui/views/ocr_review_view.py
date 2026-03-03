"""OCR Review View for reviewing and editing OCR results."""

import contextlib
import json
import logging

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.documents.content.ocr_content import SinglePageOCRContent
from context_aware_translation.documents.content.ocr_items import ImageItem
from context_aware_translation.storage.book_db import SQLiteBookDB
from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.document_repository import DocumentRepository
from context_aware_translation.ui.i18n import qarg, translate_progress_message, translate_task_block_reason
from context_aware_translation.ui.utils import create_tip_label, translate_document_type
from context_aware_translation.ui.widgets import ImageViewer, OCRElementList, ProgressWidget
from context_aware_translation.ui.widgets.task_status_card import TaskStatusCard
from context_aware_translation.workflow.tasks.models import TERMINAL_TASK_STATUSES, TaskAction

logger = logging.getLogger(__name__)


class OCRReviewView(QWidget):
    """View for reviewing and editing OCR results from document images."""

    open_activity_requested = Signal()
    _TASKS_CHANGED_COALESCE_MS = 200

    def __init__(
        self,
        book_manager: BookManager,
        book_id: str,
        *,
        task_engine,
        parent: QWidget | None = None,
    ):
        """Initialize OCR review view.

        Args:
            book_manager: BookManager instance
            book_id: Current book ID
            task_engine: TaskEngine instance
            parent: Parent widget
        """
        super().__init__(parent)
        self.book_manager = book_manager
        self.book_id = book_id
        self._task_engine = task_engine

        # Get database connection
        book = book_manager.get_book(book_id)
        if not book:
            raise ValueError(f"Book not found: {book_id}")

        db_path = book_manager.get_book_db_path(book_id)
        self.term_db = SQLiteBookDB(db_path)
        self.document_repo = DocumentRepository(self.term_db)

        # Data state
        self.sources: list[dict] = []
        self.current_index: int = -1
        self.document_id: int | None = None
        self._active_task_id: str | None = None
        self._rerun_backup: dict[str, object] | None = None
        self._ocr_run_document_id: int | None = None
        self._ocr_run_page_index: int = -1

        # Current page OCR state for editing
        self._current_ocr_content: SinglePageOCRContent | None = None
        self._current_original_texts: list[str] = []  # Original text lines
        self._is_structured_mode: bool = False  # True when showing element cards
        self._is_epub_image_mode: bool = False  # True when showing EPUB {"embedded_text":...}
        self._element_to_bbox: dict[int, int] = {}  # element_index -> bbox_index
        self._bbox_to_element: dict[int, int] = {}  # bbox_index -> element_index
        self._tasks_dirty: bool = False
        self._task_refresh_scheduled: bool = False
        self._task_refresh_timer = QTimer(self)
        self._task_refresh_timer.setSingleShot(True)
        self._task_refresh_timer.setInterval(self._TASKS_CHANGED_COALESCE_MS)
        self._task_refresh_timer.timeout.connect(self._flush_scheduled_task_refresh)

        # Create UI
        self._setup_ui()
        self._load_data()

        # Connect task engine signal
        self._task_engine.tasks_changed.connect(self._on_tasks_changed)

    def _setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)

        # Document selector row
        doc_selector_layout = QHBoxLayout()
        self.doc_selector_label = QLabel(self.tr("Document:"))
        doc_selector_layout.addWidget(self.doc_selector_label)
        self.doc_combo = QComboBox()
        self.doc_combo.setMinimumWidth(0)
        self.doc_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.doc_combo.setMinimumContentsLength(1)
        self.doc_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.doc_combo.currentIndexChanged.connect(self._on_document_changed)
        doc_selector_layout.addWidget(self.doc_combo, stretch=1)
        doc_selector_layout.addStretch()
        layout.addLayout(doc_selector_layout)

        self.tip_label = create_tip_label(self._tip_text())
        layout.addWidget(self.tip_label)

        # Main splitter: image on left, text on right
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel: Image viewer
        self.image_viewer = ImageViewer()
        self.image_viewer.bbox_clicked.connect(self._on_bbox_clicked)
        splitter.addWidget(self.image_viewer)

        # Right panel: stacked text editor (manga) / element list (structured)
        self._right_stack = QStackedWidget()

        # Index 0: flat text editor (manga / fallback)
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText(self.tr("OCR text will appear here..."))
        self._right_stack.addWidget(self.text_edit)

        # Index 1: structured element list (scanned books, PDFs)
        self.element_list = OCRElementList()
        self.element_list.element_selected.connect(self._on_element_selected)
        self._right_stack.addWidget(self.element_list)

        splitter.addWidget(self._right_stack)

        # Set initial splitter sizes (50/50)
        splitter.setSizes([500, 500])
        layout.addWidget(splitter, stretch=1)

        # Navigation toolbar
        nav_layout = QHBoxLayout()

        # Navigation buttons
        self.first_button = QPushButton("|<")
        self.first_button.setToolTip(self.tr("First page"))
        self.first_button.clicked.connect(self._go_first)
        nav_layout.addWidget(self.first_button)

        self.prev_button = QPushButton("<")
        self.prev_button.setToolTip(self.tr("Previous page"))
        self.prev_button.clicked.connect(self._go_prev)
        nav_layout.addWidget(self.prev_button)

        self.page_label = QLabel(self.tr("Page 0 of 0"))
        nav_layout.addWidget(self.page_label)

        self.ocr_status_label = QLabel()
        nav_layout.addWidget(self.ocr_status_label)

        self.next_button = QPushButton(">")
        self.next_button.setToolTip(self.tr("Next page"))
        self.next_button.clicked.connect(self._go_next)
        nav_layout.addWidget(self.next_button)

        self.last_button = QPushButton(">|")
        self.last_button.setToolTip(self.tr("Last page"))
        self.last_button.clicked.connect(self._go_last)
        nav_layout.addWidget(self.last_button)

        # Page jump input
        nav_layout.addSpacing(8)
        self.go_to_label = QLabel(self.tr("Go to:"))
        nav_layout.addWidget(self.go_to_label)
        self.page_spinbox = QSpinBox()
        self.page_spinbox.setMinimum(1)
        self.page_spinbox.setMaximum(1)
        self.page_spinbox.setFixedWidth(60)
        self.page_spinbox.setToolTip(self.tr("Enter page number"))
        nav_layout.addWidget(self.page_spinbox)

        self.go_button = QPushButton(self.tr("Go"))
        self.go_button.setToolTip(self.tr("Jump to page"))
        self.go_button.clicked.connect(self._go_to_entered_page)
        nav_layout.addWidget(self.go_button)

        nav_layout.addStretch()
        layout.addLayout(nav_layout)

        # OCR action toolbar
        action_layout = QHBoxLayout()

        self.run_ocr_button = QPushButton(self.tr("(Re)run OCR (Current Page)"))
        self.run_ocr_button.setToolTip(self.tr("Run or re-run OCR on the current page"))
        self.run_ocr_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.run_ocr_button.clicked.connect(self._run_ocr_current)
        action_layout.addWidget(self.run_ocr_button)

        self.run_all_ocr_button = QPushButton(self.tr("Run OCR for Pending Pages"))
        self.run_all_ocr_button.setToolTip(self.tr("Run OCR on all pending pages in this document"))
        self.run_all_ocr_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.run_all_ocr_button.clicked.connect(self._run_ocr_all)
        action_layout.addWidget(self.run_all_ocr_button)

        # Save button
        self.save_button = QPushButton(self.tr("Save"))
        self.save_button.setToolTip(self.tr("Save edited OCR text"))
        self.save_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.save_button.clicked.connect(self._save_current)
        action_layout.addWidget(self.save_button)

        action_layout.addStretch()
        layout.addLayout(action_layout)

        # Task status card (shown when OCR tasks exist for this book)
        self.task_status_card = TaskStatusCard(
            self._task_engine,
            self.book_id,
            task_types=["ocr"],
            display_label=self.tr("OCR"),
        )
        self.task_status_card.open_activity_requested.connect(self.open_activity_requested)
        layout.addWidget(self.task_status_card)

        # Progress widget (initially hidden)
        self.progress_widget = ProgressWidget()
        self.progress_widget.setVisible(False)
        self.progress_widget.cancelled.connect(self._cancel_ocr)
        layout.addWidget(self.progress_widget)

        # Empty state label (shown when no images)
        self.empty_label = QLabel(self.tr("No image sources found in this document."))
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: gray; font-size: 14pt;")
        self.empty_label.setVisible(False)
        layout.addWidget(self.empty_label)

    def _load_data(self) -> None:
        """Load documents and populate selector."""
        # Block signals while populating combo
        self.doc_combo.blockSignals(True)
        self.doc_combo.clear()

        # Get documents that have image sources (need OCR review)
        documents = self.document_repo.list_documents_with_image_sources()

        if not documents:
            self.doc_combo.blockSignals(False)
            self._show_empty_state()
            return

        # Populate document combo
        for doc in documents:
            doc_id = doc["document_id"]
            doc_type = translate_document_type(doc.get("document_type", "unknown"))
            self.doc_combo.addItem(qarg(self.tr("Document %1 (%2)"), doc_id, doc_type), doc_id)

        self.doc_combo.blockSignals(False)

        # Load first document
        self._load_document_sources(documents[0]["document_id"])

    def refresh(self) -> None:
        """Refresh the view with current data.

        Called when switching to this tab to ensure document list is up-to-date.
        """
        self.term_db.refresh()
        # Save current selection
        current_doc_id = self.doc_combo.currentData()
        current_page = self.current_index

        # Reload data
        self._load_data()

        # Try to restore selection
        if current_doc_id is not None:
            for i in range(self.doc_combo.count()):
                if self.doc_combo.itemData(i) == current_doc_id:
                    self.doc_combo.setCurrentIndex(i)
                    # Restore page position if valid
                    if self.sources and 0 <= current_page < len(self.sources):
                        self._go_to_page(current_page)
                    break

    def _on_document_changed(self, index: int) -> None:
        """Handle document selection change."""
        if index < 0:
            return
        doc_id = self.doc_combo.itemData(index)
        if doc_id is not None:
            self._load_document_sources(doc_id)

    def _load_document_sources(self, document_id: int) -> None:
        """Load sources for a specific document.

        Uses a lightweight metadata query (no binary_content/text_content) to
        avoid loading large blobs for every source upfront.  Binary content is
        fetched on-demand in _go_to_page() for the current page only.
        """
        self.document_id = document_id

        # Load metadata only — fully covered by idx_document_sources_metadata,
        # so SQLite never touches the main table (no overflow-page traversal).
        all_sources = self.document_repo.get_document_sources_metadata(document_id)

        # Filter to displayable image sources only (exclude fonts, archives, etc.)
        self.sources = [
            s
            for s in all_sources
            if s["source_type"] == "image"
            and (
                not (s.get("mime_type") or "").strip()
                or (s.get("mime_type") or "").strip().lower().startswith("image/")
            )
        ]

        if not self.sources:
            self._show_empty_state()
            return

        # Update page spinbox range
        self.page_spinbox.setMaximum(len(self.sources))
        self.page_spinbox.setValue(1)

        # Re-enable controls if they were disabled
        self._enable_controls()

        # Show first page
        self._go_to_page(0)

    def _enable_controls(self) -> None:
        """Re-enable controls after loading data."""
        self.empty_label.setVisible(False)
        self.image_viewer.setEnabled(True)
        self.text_edit.setEnabled(True)
        self.element_list.setEnabled(True)
        self.go_to_label.setEnabled(True)
        self.page_spinbox.setEnabled(True)
        self.go_button.setEnabled(True)
        self.run_ocr_button.setEnabled(True)
        self.run_all_ocr_button.setEnabled(True)
        self.save_button.setEnabled(True)

    def _show_empty_state(self) -> None:
        """Show empty state when no images available."""
        self.sources = []
        self.current_index = -1
        self.document_id = None
        self._current_ocr_content = None
        self._current_original_texts = []
        self._is_structured_mode = False
        self._is_epub_image_mode = False
        self._element_to_bbox = {}
        self._bbox_to_element = {}
        self.image_viewer.clear_image()
        self.text_edit.clear()
        self.element_list.clear()
        self.page_label.setText(self.tr("Page 0 of 0"))
        self.ocr_status_label.setText("")
        self.page_spinbox.setValue(1)
        self.page_spinbox.setMaximum(1)
        self.empty_label.setVisible(True)
        self.image_viewer.setEnabled(False)
        self.text_edit.setEnabled(False)
        self.element_list.setEnabled(False)
        self.first_button.setEnabled(False)
        self.prev_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.last_button.setEnabled(False)
        self.go_to_label.setEnabled(False)
        self.page_spinbox.setEnabled(False)
        self.go_button.setEnabled(False)
        self.run_ocr_button.setEnabled(False)
        self.run_all_ocr_button.setEnabled(False)
        self.save_button.setEnabled(False)

    def _go_to_page(self, index: int) -> None:
        """Navigate to a specific page.

        Args:
            index: Page index (0-based)
        """
        if not self.sources or index < 0 or index >= len(self.sources):
            return

        self.current_index = index
        source = self.sources[index]

        # Reset current page state
        self._current_ocr_content = None
        self._current_original_texts = []

        # Load image on-demand (binary_content is not pre-loaded in metadata query)
        binary_content = self.document_repo.get_source_binary_content(source["source_id"])
        if binary_content:
            self.image_viewer.set_image(binary_content)
        else:
            self.image_viewer.clear_image()

        # Reset structured mode state
        self._is_structured_mode = False
        self._is_epub_image_mode = False
        self._element_to_bbox.clear()
        self._bbox_to_element.clear()
        self.image_viewer.clear_bboxes()

        # Load OCR text on demand (by primary-key lookup — instant, no overflow pages)
        ocr_json = self.document_repo.get_source_ocr_json(source["source_id"])
        if ocr_json:
            try:
                ocr_data = json.loads(ocr_json)
                if isinstance(ocr_data, list):
                    # Structured OCR format (scanned books, PDFs)
                    self._current_ocr_content = SinglePageOCRContent.from_ocr_json(ocr_data)
                    self._current_original_texts = self._current_ocr_content.get_texts()
                    self._is_structured_mode = True

                    # Show element list
                    self._right_stack.setCurrentIndex(1)
                    page_image_bytes = binary_content
                    page_type = self._current_ocr_content.page_type
                    items = self._current_ocr_content.items

                    self.element_list.set_items(items, page_image_bytes, page_type)

                    # Build sparse element-to-bbox and bbox-to-element mappings
                    # Only ImageItem instances have bboxes
                    bboxes = []
                    bbox_idx = 0
                    for elem_idx, item in enumerate(items):
                        if isinstance(item, ImageItem) and item.bbox:
                            self._element_to_bbox[elem_idx] = bbox_idx
                            self._bbox_to_element[bbox_idx] = elem_idx
                            bboxes.append(item.bbox)
                            bbox_idx += 1

                    # Set bboxes on image viewer
                    if bboxes:
                        self.image_viewer.set_bboxes(bboxes)

                elif isinstance(ocr_data, dict) and "text" in ocr_data:
                    # Manga OCR format: {"text": "..."}
                    self._current_ocr_content = None
                    text = ocr_data["text"]
                    self._current_original_texts = [text] if text else []
                    self._right_stack.setCurrentIndex(0)
                    self.text_edit.setPlainText(text)
                elif isinstance(ocr_data, dict) and "embedded_text" in ocr_data:
                    # EPUB image OCR format: {"embedded_text": "..."}
                    self._current_ocr_content = None
                    self._is_epub_image_mode = True
                    text = ocr_data["embedded_text"]
                    self._current_original_texts = [text] if text else []
                    self._right_stack.setCurrentIndex(0)
                    self.text_edit.setPlainText(text)
                else:
                    self._right_stack.setCurrentIndex(0)
                    self.text_edit.setPlainText("")
            except (json.JSONDecodeError, TypeError):
                logger.warning("Failed to parse OCR JSON for source", exc_info=True)
                self._right_stack.setCurrentIndex(0)
                self.text_edit.setPlainText(self.tr("[Invalid OCR data - unable to parse]"))
        else:
            self._right_stack.setCurrentIndex(0)
            self.text_edit.setPlainText("")

        # Update navigation
        self._update_navigation()

        self._update_ocr_action_button_states()

    def _update_navigation(self) -> None:
        """Update navigation button states, page label, and OCR status."""
        if not self.sources:
            return

        total = len(self.sources)
        current = self.current_index + 1

        self.page_label.setText(qarg(self.tr("Page %1 of %2"), current, total))

        # Update page spinbox without triggering signals
        self.page_spinbox.blockSignals(True)
        self.page_spinbox.setValue(current)
        self.page_spinbox.blockSignals(False)

        # Update OCR status indicator
        source = self.sources[self.current_index]
        is_ocr_completed = source.get("is_ocr_completed", 0)
        if is_ocr_completed:
            self.ocr_status_label.setText(self.tr("OCR Done"))
            self.ocr_status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.ocr_status_label.setText(self.tr("Pending OCR"))
            self.ocr_status_label.setStyleSheet("color: orange; font-weight: bold;")

        self.first_button.setEnabled(self.current_index > 0)
        self.prev_button.setEnabled(self.current_index > 0)
        self.next_button.setEnabled(self.current_index < total - 1)
        self.last_button.setEnabled(self.current_index < total - 1)

    def _go_first(self) -> None:
        """Go to first page."""
        self._go_to_page(0)

    def _go_prev(self) -> None:
        """Go to previous page."""
        if self.current_index > 0:
            self._go_to_page(self.current_index - 1)

    def _go_next(self) -> None:
        """Go to next page."""
        if self.current_index < len(self.sources) - 1:
            self._go_to_page(self.current_index + 1)

    def _go_last(self) -> None:
        """Go to last page."""
        if self.sources:
            self._go_to_page(len(self.sources) - 1)

    def _go_to_entered_page(self) -> None:
        """Go to the page number entered in the spinbox."""
        page_num = self.page_spinbox.value()
        if self.sources and 1 <= page_num <= len(self.sources):
            self._go_to_page(page_num - 1)  # Convert to 0-based index

    def _on_element_selected(self, element_index: int) -> None:
        """Handle element card selection — highlight corresponding bbox if any."""
        bbox_index = self._element_to_bbox.get(element_index, -1)
        self.image_viewer.highlight_bbox(bbox_index)

    def _on_bbox_clicked(self, bbox_index: int) -> None:
        """Handle bbox click on image — select corresponding element card."""
        element_index = self._bbox_to_element.get(bbox_index, -1)
        if element_index >= 0:
            self.element_list.select_element(element_index)
        self.image_viewer.highlight_bbox(bbox_index)

    def _save_current(self) -> None:
        """Save edited OCR text for current page."""
        if self.current_index < 0 or self.current_index >= len(self.sources):
            return

        if self._is_current_document_ocr_running():
            QMessageBox.warning(
                self,
                self.tr("Cannot Save"),
                self.tr("Cannot save OCR text while an OCR task is running for this document."),
            )
            return

        source = self.sources[self.current_index]
        source_id = source["source_id"]

        if self._is_structured_mode and self._current_ocr_content is not None:
            # Structured OCR format — collect texts from element cards
            if self.element_list.is_placeholder_mode():
                QMessageBox.information(self, self.tr("Info"), self.tr("No editable content on this page."))
                return

            edited_lines = self.element_list.get_all_texts()
            original_line_count = len(self._current_original_texts)

            if len(edited_lines) != original_line_count:
                QMessageBox.warning(
                    self,
                    self.tr("Line Count Mismatch"),
                    qarg(
                        self.tr(
                            "Edited text has %1 lines but original has %2 lines.\n\n"
                            "Please ensure the line count matches. You can edit the text within each line, "
                            "but cannot add or remove lines."
                        ),
                        len(edited_lines),
                        original_line_count,
                    ),
                )
                return

            self._save_structured_ocr(source, source_id, edited_lines)
            return

        edited_text = self.text_edit.toPlainText()

        if self._current_ocr_content is not None:
            # Structured OCR viewed in text mode (shouldn't normally happen but safe fallback)
            edited_lines = edited_text.split("\n")
            original_line_count = len(self._current_original_texts)

            if len(edited_lines) != original_line_count:
                QMessageBox.warning(
                    self,
                    self.tr("Line Count Mismatch"),
                    qarg(
                        self.tr(
                            "Edited text has %1 lines but original has %2 lines.\n\n"
                            "Please ensure the line count matches. You can edit the text within each line, "
                            "but cannot add or remove lines."
                        ),
                        len(edited_lines),
                        original_line_count,
                    ),
                )
                return

            self._save_structured_ocr(source, source_id, edited_lines)
        elif self._current_original_texts or edited_text.strip():
            # Free-form editing: EPUB {"embedded_text":...} or manga {"text":...}
            try:
                key = "embedded_text" if self._is_epub_image_mode else "text"
                ocr_json = json.dumps({key: edited_text}, ensure_ascii=False)
                self.document_repo.update_source_ocr(source_id, ocr_json)
                source["ocr_json"] = ocr_json
                self._current_original_texts = [edited_text] if edited_text else []
                QMessageBox.information(self, self.tr("Success"), self.tr("OCR text saved successfully."))
            except Exception as e:
                QMessageBox.critical(self, self.tr("Error"), qarg(self.tr("Failed to save OCR text: %1"), e))
        else:
            QMessageBox.warning(self, self.tr("Cannot Save"), self.tr("No OCR data available. Please run OCR first."))

    def _save_structured_ocr(self, source: dict, source_id: int, edited_lines: list[str]) -> None:
        """Save structured OCR data to database.

        Args:
            source: Source dictionary to update
            source_id: Source ID in database
            edited_lines: List of edited text lines
        """
        if self._current_ocr_content is None:
            return

        try:
            self._current_ocr_content.set_texts(edited_lines)
            ocr_json = json.dumps(self._current_ocr_content.to_json(), ensure_ascii=False)
            self.document_repo.update_source_ocr(source_id, ocr_json)
            source["ocr_json"] = ocr_json
            self._current_original_texts = edited_lines
            QMessageBox.information(self, self.tr("Success"), self.tr("OCR text saved successfully."))
        except Exception as e:
            QMessageBox.critical(self, self.tr("Error"), qarg(self.tr("Failed to save OCR text: %1"), e))

    def _run_ocr_current(self) -> None:
        """Run OCR on current page only."""
        if self.current_index < 0 or self.current_index >= len(self.sources):
            return

        if self.document_id is None:
            return

        if self._active_task_id is not None:
            QMessageBox.warning(self, self.tr("Warning"), self.tr("OCR is already running."))
            return

        source = self.sources[self.current_index]
        source_id = source["source_id"]

        # Check if this page already has OCR - if so, warn about data loss
        if source.get("is_ocr_completed"):
            reply = QMessageBox.warning(
                self,
                self.tr("Re-run OCR"),
                self.tr(
                    "Re-running OCR will overwrite the current OCR results for this page.\n\nDo you want to continue?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # Keep previous OCR so cancellation/error does not drop existing content.
        self._save_rerun_backup(source)
        self._capture_ocr_run_context()

        # Reset OCR flags before preflight so rerun of an already-completed page
        # is admitted as pending work.
        try:
            self.document_repo.reset_source_ocr(source_id)
            # Update local copy
            source["is_ocr_completed"] = 0
            source["ocr_json"] = None
            self.text_edit.clear()
            self.element_list.clear()

            # Preflight check after reset
            decision = self._task_engine.preflight(
                "ocr",
                self.book_id,
                {"document_ids": [self.document_id], "source_ids": [source_id]},
                TaskAction.RUN,
            )
            if not decision.allowed:
                self._clear_ocr_run_context()
                self._restore_rerun_backup()
                QMessageBox.warning(
                    self,
                    self.tr("Cannot Run OCR"),
                    translate_task_block_reason(decision.reason, decision.code),
                )
                return

            record = self._task_engine.submit_and_start(
                "ocr",
                self.book_id,
                document_ids=[self.document_id],
                source_ids=[source_id],
            )
            self._active_task_id = record.task_id

            # Show progress
            self.progress_widget.reset()
            self.progress_widget.setVisible(True)
            self.progress_widget.set_cancellable(True)

            # Disable buttons during OCR
            self._set_buttons_enabled(False)

        except Exception as e:
            self._clear_ocr_run_context()
            self._restore_rerun_backup()
            self._active_task_id = None
            QMessageBox.critical(self, self.tr("Error"), qarg(self.tr("Failed to run OCR: %1"), e))

    def _run_ocr_all(self) -> None:
        """Run OCR on all pages in the current document that need it."""
        if self._active_task_id is not None:
            QMessageBox.warning(self, self.tr("Warning"), self.tr("OCR is already running."))
            return

        if not self.sources:
            QMessageBox.warning(self, self.tr("Warning"), self.tr("No image sources to process."))
            return

        if self.document_id is None:
            return

        # Preflight check
        decision = self._task_engine.preflight(
            "ocr",
            self.book_id,
            {"document_ids": [self.document_id], "source_ids": None},
            TaskAction.RUN,
        )
        if not decision.allowed:
            QMessageBox.warning(
                self,
                self.tr("Cannot Run OCR"),
                translate_task_block_reason(decision.reason, decision.code),
            )
            return

        self._capture_ocr_run_context()

        try:
            record = self._task_engine.submit_and_start(
                "ocr",
                self.book_id,
                document_ids=[self.document_id],
                source_ids=None,
            )
            self._active_task_id = record.task_id

            # Show progress
            self.progress_widget.reset()
            self.progress_widget.setVisible(True)
            self.progress_widget.set_cancellable(True)

            # Disable buttons during OCR
            self._set_buttons_enabled(False)

        except Exception as e:
            self._clear_ocr_run_context()
            self._active_task_id = None
            QMessageBox.critical(self, self.tr("Error"), qarg(self.tr("Failed to run OCR: %1"), e))

    def _capture_ocr_run_context(self) -> None:
        """Capture active document/page so completion can restore deterministic state."""
        self._ocr_run_document_id = self.document_id
        self._ocr_run_page_index = self.current_index

    def _clear_ocr_run_context(self) -> None:
        """Clear captured run context after OCR lifecycle ends."""
        self._ocr_run_document_id = None
        self._ocr_run_page_index = -1

    def _save_rerun_backup(self, source: dict) -> None:
        """Store previous OCR state for current-page rerun recovery."""
        self._rerun_backup = None
        if not source.get("is_ocr_completed"):
            return

        source_id = source.get("source_id")
        if source_id is None:
            return

        self._rerun_backup = {
            "source_id": int(source_id),
            "ocr_json": self.document_repo.get_source_ocr_json(int(source_id)),
            "is_ocr_completed": bool(source.get("is_ocr_completed")),
        }

    def _restore_rerun_backup(self) -> None:
        """Restore previous OCR state if rerun failed or was cancelled."""
        backup = self._rerun_backup
        self._rerun_backup = None
        if not backup:
            return

        source_id = int(backup["source_id"])
        ocr_json = backup.get("ocr_json")
        was_completed = bool(backup.get("is_ocr_completed"))

        try:
            if isinstance(ocr_json, str):
                self.document_repo.update_source_ocr(source_id, ocr_json)
            if was_completed:
                self.document_repo.update_source_ocr_completed(source_id)

            for source in self.sources:
                if source.get("source_id") == source_id:
                    source["ocr_json"] = ocr_json
                    source["is_ocr_completed"] = 1 if was_completed else 0
                    break

            if 0 <= self.current_index < len(self.sources):
                current_source = self.sources[self.current_index]
                if current_source.get("source_id") == source_id:
                    self._go_to_page(self.current_index)
        except Exception:
            logger.exception("Failed to restore OCR backup for source %s", source_id)

    def _cancel_ocr(self) -> None:
        """Cancel running OCR operation."""
        if self._active_task_id:
            self._task_engine.cancel(self._active_task_id)

    def _on_tasks_changed(self, book_id: str) -> None:
        """React to engine task-changed events for this book."""
        if book_id != self.book_id:
            return
        if self._should_defer_task_refresh():
            self._tasks_dirty = True
            return
        self._schedule_task_refresh()

    def _flush_scheduled_task_refresh(self) -> None:
        if not self._task_refresh_scheduled:
            return
        self._task_refresh_scheduled = False
        if self._should_defer_task_refresh():
            self._tasks_dirty = True
            return

        self._on_tasks_changed_now()

    def _schedule_task_refresh(self) -> None:
        if self._task_refresh_scheduled:
            return
        self._task_refresh_scheduled = True
        self._task_refresh_timer.start()

    def _on_tasks_changed_now(self) -> None:
        """Handle task-change refresh after coalescing."""
        # Keep controls in sync even when OCR tasks are started externally
        # (e.g. from TaskStatusCard/Activity panel).
        if not self._active_task_id:
            self._update_ocr_action_button_states()
            return

        record = self._task_engine.get_task(self._active_task_id)
        if record is None:
            return

        # Update progress widget
        completed = record.completed_items or 0
        total = record.total_items or 0
        phase = record.phase or ""
        translated_message = translate_progress_message(phase)
        self.progress_widget.set_progress(completed, total, translated_message)

        # Check for terminal states
        if record.status not in TERMINAL_TASK_STATUSES:
            return

        # Task is done — capture run context before clearing
        status = record.status
        saved_document_id = self._ocr_run_document_id if self._ocr_run_document_id is not None else self.document_id
        saved_page_index = self._ocr_run_page_index if self._ocr_run_page_index >= 0 else self.current_index
        self._active_task_id = None
        self.progress_widget.setVisible(False)
        self._clear_ocr_run_context()

        if status == "completed" or status == "completed_with_errors":
            self._rerun_backup = None
            count = record.completed_items or 0

            QMessageBox.information(
                self,
                self.tr("OCR Complete"),
                qarg(self.tr("OCR completed successfully. %1 pages processed."), count),
            )

            if saved_document_id is not None:
                self._load_document_sources(saved_document_id)
                if self.sources and saved_page_index >= 0:
                    restored_index = min(saved_page_index, len(self.sources) - 1)
                    self._go_to_page(restored_index)

        elif status == "failed":
            self._restore_rerun_backup()
            error_msg = translate_task_block_reason(record.last_error) or self.tr("Unknown error")
            QMessageBox.critical(self, self.tr("OCR Error"), qarg(self.tr("OCR failed: %1"), error_msg))

        elif status == "cancelled":
            self._restore_rerun_backup()
            QMessageBox.information(self, self.tr("Cancelled"), self.tr("OCR cancelled."))

        self._set_buttons_enabled(True)
        self._update_ocr_action_button_states()

    def _update_ocr_action_button_states(self) -> None:
        """Sync OCR button enabled states after task completion."""
        if self.document_id is None:
            return

        if self._is_current_document_ocr_running():
            running_tip = self.tr("Disabled while OCR is running for this document.")
            self.run_ocr_button.setEnabled(False)
            self.run_ocr_button.setToolTip(running_tip)
            self.run_all_ocr_button.setEnabled(False)
            self.run_all_ocr_button.setToolTip(running_tip)
            self.save_button.setEnabled(False)
            self.save_button.setToolTip(running_tip)
            return

        chunk_count = self.document_repo.get_chunk_count(self.document_id)
        if chunk_count > 0:
            glossary_tip = self.tr(
                "Disabled after text has been added to the translation stack "
                "(glossary build or translation start). Reset from the Import tab to make changes."
            )
            self.run_ocr_button.setEnabled(False)
            self.run_ocr_button.setToolTip(glossary_tip)
            self.run_all_ocr_button.setEnabled(False)
            self.run_all_ocr_button.setToolTip(glossary_tip)
            self.save_button.setEnabled(False)
            self.save_button.setToolTip(glossary_tip)
            return

        # Default (eligible) tooltips when no run-time locks apply.
        has_sources = bool(self.sources)
        self.run_ocr_button.setEnabled(has_sources)
        self.run_all_ocr_button.setEnabled(has_sources)
        self.save_button.setEnabled(has_sources)
        self.save_button.setToolTip(self.tr("Save edited OCR text"))
        self.run_ocr_button.setToolTip(self.tr("Run or re-run OCR on the current page"))
        self.run_all_ocr_button.setToolTip(self.tr("Run OCR on all pending pages in this document"))

    def _is_current_document_ocr_running(self) -> bool:
        """Return True if there is any non-terminal OCR task for current document."""
        if self.document_id is None:
            return False

        for record in self._task_engine.get_tasks(self.book_id, task_type="ocr"):
            if record.status in TERMINAL_TASK_STATUSES:
                continue
            if not record.document_ids_json:
                continue
            try:
                ids = json.loads(record.document_ids_json)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(ids, list) and len(ids) == 1 and int(ids[0]) == int(self.document_id):
                return True
        return False

    def _set_buttons_enabled(self, enabled: bool) -> None:
        """Enable or disable all buttons.

        Args:
            enabled: Whether buttons should be enabled
        """
        has_sources = bool(self.sources)
        controls_enabled = enabled and has_sources

        self.image_viewer.setEnabled(controls_enabled)
        self.text_edit.setEnabled(controls_enabled)
        self.element_list.setEnabled(controls_enabled)
        self.doc_combo.setEnabled(enabled and self.doc_combo.count() > 0)
        self.go_to_label.setEnabled(controls_enabled)
        self.page_spinbox.setEnabled(controls_enabled)
        self.go_button.setEnabled(controls_enabled)
        self.first_button.setEnabled(controls_enabled)
        self.prev_button.setEnabled(controls_enabled)
        self.next_button.setEnabled(controls_enabled)
        self.last_button.setEnabled(controls_enabled)
        self.run_ocr_button.setEnabled(controls_enabled)
        self.run_all_ocr_button.setEnabled(controls_enabled)
        self.save_button.setEnabled(controls_enabled)

        # Update navigation state if enabled
        if controls_enabled:
            self._update_navigation()

    def cleanup(self) -> None:
        """Clean up background worker and database resources."""
        if hasattr(self, "_task_refresh_timer"):
            self._task_refresh_timer.stop()
        if hasattr(self, "_task_engine"):
            with contextlib.suppress(TypeError, RuntimeError):
                self._task_engine.tasks_changed.disconnect(self._on_tasks_changed)
        if hasattr(self, "task_status_card"):
            self.task_status_card.cleanup()
        if hasattr(self, "term_db"):
            self.term_db.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle widget close event."""
        self.cleanup()
        super().closeEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if getattr(self, "_tasks_dirty", False):
            self._tasks_dirty = False
            self._on_tasks_changed_now()

    def _should_defer_task_refresh(self) -> bool:
        """Return True when task-driven refresh should wait until widget is visible."""
        with contextlib.suppress(RuntimeError):
            if self.isVisible():
                return False
            return self.parentWidget() is not None
        return False

    def retranslateUi(self) -> None:
        self.tip_label.setText(self._tip_text())
        self.doc_selector_label.setText(self.tr("Document:"))
        self.text_edit.setPlaceholderText(self.tr("OCR text will appear here..."))
        self.first_button.setToolTip(self.tr("First page"))
        self.prev_button.setToolTip(self.tr("Previous page"))
        self.next_button.setToolTip(self.tr("Next page"))
        self.last_button.setToolTip(self.tr("Last page"))
        self.go_to_label.setText(self.tr("Go to:"))
        self.page_spinbox.setToolTip(self.tr("Enter page number"))
        self.go_button.setText(self.tr("Go"))
        self.go_button.setToolTip(self.tr("Jump to page"))
        self.run_ocr_button.setText(self.tr("(Re)run OCR (Current Page)"))
        self.run_all_ocr_button.setText(self.tr("Run OCR for Pending Pages"))
        self.save_button.setText(self.tr("Save"))
        self.task_status_card.set_display_label(self.tr("OCR"))
        self.empty_label.setText(self.tr("No image sources found in this document."))
        self._update_navigation()

    def _tip_text(self) -> str:
        return self.tr(
            "Run OCR and save edits before text is added to translation chunks. "
            "After glossary build or translation start, OCR editing is locked."
        )
