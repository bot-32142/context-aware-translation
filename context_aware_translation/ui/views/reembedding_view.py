"""Reembedding View for reviewing and managing image reembedding results."""

import contextlib
import json
import logging
from dataclasses import dataclass

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.storage.book_db import SQLiteBookDB
from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.document_repository import DocumentRepository
from context_aware_translation.workflow.tasks.models import TERMINAL_TASK_STATUSES, TaskAction

from ..i18n import qarg, translate_progress_message
from ..utils import create_tip_label, translate_document_type
from ..widgets import ImageViewer, ProgressWidget
from ..widgets.task_status_card import TaskStatusCard

logger = logging.getLogger(__name__)

_REEMBEDDABLE_TYPES = frozenset({"pdf", "scanned_book", "manga", "epub"})
_SOURCE_SCOPED_REEMBED_TYPES = frozenset({"manga", "epub"})


@dataclass
class _ReembedItem:
    """One reembeddable image item — the unit of navigation in the view."""

    source_id: int  # DB source row this image belongs to
    element_idx: int  # Key in reembedded_images_json
    translated_text: str = ""  # Translated text associated with this image
    original_image_bytes: bytes | None = None  # Cropped original from ImageItem.image_bytes
    reembedded_image_bytes: bytes | None = None  # From ImageItem.reembedded_image_bytes


class ReembeddingView(QWidget):
    """View for reviewing reembedded images from translated documents.

    Navigates per reembeddable image item (not per page).  For manga/epub each
    source IS one image.  For pdf/scanned_book each ImageItem with embedded text
    is one item, cropped from its source page via bounding box.
    """

    open_activity_requested = Signal()

    def __init__(
        self,
        book_manager: BookManager,
        book_id: str,
        *,
        task_engine,
        parent: QWidget | None = None,
    ):
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
        self._items: list[_ReembedItem] = []
        self.current_index: int = -1
        self.document_id: int | None = None
        self._active_task_id: str | None = None
        self._reembedded_images: dict[int, tuple[bytes, str]] = {}
        self._current_doc_type: str = ""

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
        self.doc_combo.currentIndexChanged.connect(self._on_document_changed)
        doc_selector_layout.addWidget(self.doc_combo, stretch=1)
        doc_selector_layout.addStretch()
        layout.addLayout(doc_selector_layout)

        self.tip_label = create_tip_label(self._tip_text())
        layout.addWidget(self.tip_label)

        # Main splitter: original image on left, reembedded / text on right
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel: Original image viewer
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.left_label = QLabel(self.tr("Original"))
        self.left_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.left_label.setStyleSheet("font-weight: bold;")
        left_layout.addWidget(self.left_label)
        self.image_viewer = ImageViewer()
        left_layout.addWidget(self.image_viewer, stretch=1)
        splitter.addWidget(left_container)

        # Right panel: stacked text (index 0) / reembedded image (index 1)
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Header + toggle button
        right_header = QHBoxLayout()
        self.right_label = QLabel(self.tr("Reembedded"))
        self.right_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.right_label.setStyleSheet("font-weight: bold;")
        right_header.addWidget(self.right_label, stretch=1)
        self.toggle_button = QPushButton(self.tr("Show Text"))
        self.toggle_button.setToolTip(self.tr("Toggle between reembedded image and translated text"))
        self.toggle_button.clicked.connect(self._toggle_right_panel)
        self.toggle_button.setFixedWidth(100)
        right_header.addWidget(self.toggle_button)
        right_layout.addLayout(right_header)

        # Stacked widget for image / text
        self._right_stack = QStackedWidget()

        # Index 0: Reembedded image viewer (default)
        self.reembedded_viewer = ImageViewer()
        self._right_stack.addWidget(self.reembedded_viewer)

        # Index 1: Translated text (read-only)
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setPlaceholderText(self.tr("Translated text will appear here..."))
        self._right_stack.addWidget(self.text_edit)

        right_layout.addWidget(self._right_stack, stretch=1)
        splitter.addWidget(right_container)

        # Set initial splitter sizes (50/50)
        splitter.setSizes([500, 500])
        layout.addWidget(splitter, stretch=1)

        # Navigation toolbar
        nav_layout = QHBoxLayout()

        self.first_button = QPushButton("|<")
        self.first_button.setToolTip(self.tr("First image"))
        self.first_button.clicked.connect(self._go_first)
        nav_layout.addWidget(self.first_button)

        self.prev_button = QPushButton("<")
        self.prev_button.setToolTip(self.tr("Previous image"))
        self.prev_button.clicked.connect(self._go_prev)
        nav_layout.addWidget(self.prev_button)

        self.page_label = QLabel(self.tr("Image 0 of 0"))
        nav_layout.addWidget(self.page_label)

        self.status_label = QLabel()
        nav_layout.addWidget(self.status_label)

        self.next_button = QPushButton(">")
        self.next_button.setToolTip(self.tr("Next image"))
        self.next_button.clicked.connect(self._go_next)
        nav_layout.addWidget(self.next_button)

        self.last_button = QPushButton(">|")
        self.last_button.setToolTip(self.tr("Last image"))
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
        self.page_spinbox.setToolTip(self.tr("Enter image number"))
        nav_layout.addWidget(self.page_spinbox)

        self.go_button = QPushButton(self.tr("Go"))
        self.go_button.setToolTip(self.tr("Jump to image"))
        self.go_button.clicked.connect(self._go_to_entered_page)
        nav_layout.addWidget(self.go_button)

        nav_layout.addStretch()

        layout.addLayout(nav_layout)

        # Action buttons toolbar
        action_layout = QHBoxLayout()

        self.reembed_current_button = QPushButton(self.tr("Reembed This Image"))
        self.reembed_current_button.setToolTip(self.tr("Reembed the current image"))
        self.reembed_current_button.clicked.connect(self._reembed_current)
        action_layout.addWidget(self.reembed_current_button)

        self.reembed_pending_button = QPushButton(self.tr("Reembed Pending"))
        self.reembed_pending_button.setToolTip(self.tr("Reembed all pending images in this document"))
        self.reembed_pending_button.clicked.connect(self._reembed_pending)
        action_layout.addWidget(self.reembed_pending_button)

        self.reembed_all_button = QPushButton(self.tr("Force Reembed All"))
        self.reembed_all_button.setToolTip(self.tr("Force reembed all images in this document"))
        self.reembed_all_button.clicked.connect(self._reembed_all)
        action_layout.addWidget(self.reembed_all_button)

        action_layout.addStretch()
        layout.addLayout(action_layout)

        # Task status card
        self.task_status_card = TaskStatusCard(
            self._task_engine,
            self.book_id,
            task_types=["image_reembedding"],
            display_label=self.tr("Reembedding"),
        )
        self.task_status_card.open_activity_requested.connect(self.open_activity_requested)
        layout.addWidget(self.task_status_card)

        # Progress widget (initially hidden)
        self.progress_widget = ProgressWidget()
        self.progress_widget.setVisible(False)
        self.progress_widget.cancelled.connect(self._cancel_reembed)
        layout.addWidget(self.progress_widget)

        # Empty state label
        self.empty_label = QLabel(self.tr("No reembeddable images found."))
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: gray; font-size: 14pt;")
        self.empty_label.setVisible(False)
        layout.addWidget(self.empty_label)

    # =========================================================================
    # Data Loading
    # =========================================================================

    def _load_data(self) -> None:
        """Load documents and populate selector."""
        self.doc_combo.blockSignals(True)
        self.doc_combo.clear()

        documents = self.document_repo.list_documents_with_image_sources()

        # Filter to reembeddable document types
        documents = [d for d in documents if d.get("document_type", "") in _REEMBEDDABLE_TYPES]

        if not documents:
            self.doc_combo.blockSignals(False)
            self._show_empty_state()
            return

        for doc in documents:
            doc_id = doc["document_id"]
            doc_type = translate_document_type(doc.get("document_type", "unknown"))
            self.doc_combo.addItem(qarg(self.tr("Document %1 (%2)"), doc_id, doc_type), doc_id)

        self.doc_combo.blockSignals(False)

        # Load first document
        first_doc = documents[0]
        self._current_doc_type = first_doc.get("document_type", "")
        self._load_document_data(first_doc["document_id"])

    def refresh(self) -> None:
        """Refresh the view with current data."""
        self.term_db.refresh()
        current_doc_id = self.doc_combo.currentData()
        current_page = self.current_index

        self._load_data()

        if current_doc_id is not None:
            for i in range(self.doc_combo.count()):
                if self.doc_combo.itemData(i) == current_doc_id:
                    self.doc_combo.setCurrentIndex(i)
                    if self._items and 0 <= current_page < len(self._items):
                        self._go_to_page(current_page)
                    break

    def _on_document_changed(self, index: int) -> None:
        """Handle document selection change."""
        if index < 0:
            return
        doc_id = self.doc_combo.itemData(index)
        if doc_id is not None:
            self._load_document_data(doc_id)

    def _load_document_data(self, document_id: int) -> None:
        """Load reembeddable items for a specific document."""
        self.document_id = document_id

        # Determine document type
        documents = self.document_repo.list_documents_with_image_sources()
        for doc in documents:
            if doc["document_id"] == document_id:
                self._current_doc_type = doc.get("document_type", "")
                break

        # Load reembedded images for this document
        self._reembedded_images = self.document_repo.load_reembedded_images(document_id)

        # Build items by loading the Document object and calling set_text,
        # which is the same code path used by the actual reembedding worker.
        self._items = self._build_items_via_document(document_id)

        if not self._items:
            self._show_empty_state()
            return

        # Update spinbox range
        self.page_spinbox.setMaximum(len(self._items))
        self.page_spinbox.setValue(1)

        # Re-enable controls and show first item
        self._enable_controls()
        self._go_to_page(0)

    def _get_translated_lines_with_fallback(self, document_id: int) -> list[str]:
        """Get translated lines for a document.

        For text-based documents, if nothing is translated yet, return an empty
        set of lines so the view does not present source text as translated.
        """
        chunks = self.term_db.list_chunks(document_id=document_id)
        if not chunks:
            return []
        sorted_chunks = sorted(chunks, key=lambda c: c.chunk_id)

        if self._current_doc_type == "manga":
            # Keep manga behavior aligned with workflow fallback semantics:
            # untranslated chunks become empty so reembedding skips those pages.
            return [c.translation if c.is_translated and c.translation is not None else "" for c in sorted_chunks]

        # Avoid showing source text as "Translated Text" for fully untranslated docs.
        if not any(c.is_translated and c.translation is not None for c in sorted_chunks):
            return []

        # Text-based types (epub, pdf, scanned_book): concatenate and split by newline
        translated_text = "".join(
            c.translation if c.is_translated and c.translation is not None else c.text for c in sorted_chunks
        )
        return translated_text.splitlines()

    def _build_items_via_document(self, document_id: int) -> list[_ReembedItem]:
        """Build reembeddable items by loading a Document and calling set_text.

        This uses the exact same code path as the reembedding worker, ensuring
        the translated text mapping is always correct regardless of document type.
        """
        import asyncio

        from context_aware_translation.documents.base import Document

        doc = Document.load_by_id(self.document_repo, document_id)
        if doc is None:
            return []

        lines = self._get_translated_lines_with_fallback(document_id)
        if not lines:
            return []

        try:
            asyncio.run(doc.set_text(lines))
        except Exception:
            logger.warning("Failed to set_text for document %d", document_id, exc_info=True)
            return []

        if self._current_doc_type == "manga":
            return self._collect_manga_items(doc)
        if self._current_doc_type == "epub":
            return self._collect_epub_items(doc)
        # pdf / scanned_book
        return self._collect_structured_items(doc)

    def _collect_manga_items(self, doc: object) -> list[_ReembedItem]:
        """Collect reembeddable items from a MangaDocument after set_text."""
        from context_aware_translation.documents.manga import MangaDocument

        assert isinstance(doc, MangaDocument)
        sources = self.document_repo.get_document_sources(doc.document_id)
        sources_sorted = sorted(sources, key=lambda s: s["sequence_number"])

        items: list[_ReembedItem] = []
        for idx, source in enumerate(sources_sorted):
            source_id = source["source_id"]
            translated = doc._page_translations.get(source_id, "")
            reembedded = self._reembedded_images.get(idx)
            items.append(
                _ReembedItem(
                    source_id=source_id,
                    element_idx=idx,  # manga uses positional index
                    translated_text=translated,
                    original_image_bytes=source.get("binary_content"),
                    reembedded_image_bytes=reembedded[0] if reembedded else None,
                )
            )
        return items

    def _collect_epub_items(self, doc: object) -> list[_ReembedItem]:
        """Collect reembeddable items from an EPUBDocument after set_text."""
        from context_aware_translation.documents.epub import EPUBDocument

        assert isinstance(doc, EPUBDocument)
        sources = self.document_repo.get_document_sources(doc.document_id)
        sources_sorted = sorted(sources, key=lambda s: s["sequence_number"])

        items: list[_ReembedItem] = []
        for source in sources_sorted:
            if source["source_type"] != "image" or not source.get("binary_content"):
                continue
            source_id = source["source_id"]
            translated = doc._translated_image_texts.get(source_id, "")
            if not translated.strip():
                continue
            reembedded = self._reembedded_images.get(source_id)
            items.append(
                _ReembedItem(
                    source_id=source_id,
                    element_idx=source_id,  # epub uses source_id as key
                    translated_text=translated,
                    original_image_bytes=source.get("binary_content"),
                    reembedded_image_bytes=reembedded[0] if reembedded else None,
                )
            )
        return items

    def _collect_structured_items(self, doc: object) -> list[_ReembedItem]:
        """Collect reembeddable items from a PDF/ScannedBook after set_text.

        Uses ImageItem.image_bytes (cropped original) and
        ImageItem.reembedded_image_bytes (loaded by set_text from DB) directly,
        so display is always consistent with what reembed() actually processes.
        """
        from context_aware_translation.documents.content.ocr_items import ImageItem
        from context_aware_translation.documents.pdf import PDFDocument
        from context_aware_translation.documents.scanned_book import ScannedBookDocument

        if isinstance(doc, (PDFDocument, ScannedBookDocument)):
            merged = doc._merged_content
        else:
            return []

        if merged is None:
            return []

        items: list[_ReembedItem] = []
        for idx, elem in enumerate(merged.elements):
            if not isinstance(elem, ImageItem) or not elem.needs_reembedding():
                continue
            translated = elem.get_embedded_translation() or ""
            items.append(
                _ReembedItem(
                    source_id=0,  # not used for display
                    element_idx=idx,
                    translated_text=translated,
                    original_image_bytes=elem.image_bytes,
                    reembedded_image_bytes=elem.reembedded_image_bytes,
                )
            )
        return items

    # =========================================================================
    # Navigation
    # =========================================================================

    def _go_to_page(self, index: int) -> None:
        """Navigate to a specific image item.

        Args:
            index: Item index (0-based)
        """
        if not self._items or index < 0 or index >= len(self._items):
            return

        self.current_index = index
        item = self._items[index]

        # Show original image (already cropped by ImageItem.prepare())
        if item.original_image_bytes:
            self.image_viewer.set_image(item.original_image_bytes)
        else:
            self.image_viewer.clear_image()

        # Load translated text
        self.text_edit.setPlainText(item.translated_text)

        # Check for reembedded image (stored on the item from set_text)
        if item.reembedded_image_bytes is not None:
            self.reembedded_viewer.set_image(item.reembedded_image_bytes)
            self._right_stack.setCurrentIndex(0)
            self.right_label.setText(self.tr("Reembedded"))
            self.toggle_button.setText(self.tr("Show Text"))
            self.toggle_button.setEnabled(True)
        else:
            self.reembedded_viewer.clear_image()
            # Show translated text when no reembedded image
            self._right_stack.setCurrentIndex(1)
            self.right_label.setText(self.tr("Translated Text"))
            self.toggle_button.setText(self.tr("Show Image"))
            self.toggle_button.setEnabled(False)

        # Update navigation
        self._update_navigation()
        self._update_action_button_states()

    def _toggle_right_panel(self) -> None:
        """Toggle between reembedded image and translated text."""
        if self._right_stack.currentIndex() == 0:
            # Switch to translated text
            self._right_stack.setCurrentIndex(1)
            self.right_label.setText(self.tr("Translated Text"))
            self.toggle_button.setText(self.tr("Show Image"))
        else:
            # Switch to reembedded image
            self._right_stack.setCurrentIndex(0)
            self.right_label.setText(self.tr("Reembedded"))
            self.toggle_button.setText(self.tr("Show Text"))

    def _update_navigation(self) -> None:
        """Update navigation button states, label, and status."""
        if not self._items:
            return

        total = len(self._items)
        current = self.current_index + 1

        self.page_label.setText(qarg(self.tr("Image %1 of %2"), current, total))

        # Update spinbox without triggering signals
        self.page_spinbox.blockSignals(True)
        self.page_spinbox.setValue(current)
        self.page_spinbox.blockSignals(False)

        # Update reembedding status indicator
        item = self._items[self.current_index]
        if item.reembedded_image_bytes is not None:
            self.status_label.setText(self.tr("Reembedded"))
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.status_label.setText(self.tr("Pending"))
            self.status_label.setStyleSheet("color: orange; font-weight: bold;")

        self.first_button.setEnabled(self.current_index > 0)
        self.prev_button.setEnabled(self.current_index > 0)
        self.next_button.setEnabled(self.current_index < total - 1)
        self.last_button.setEnabled(self.current_index < total - 1)

    def _go_first(self) -> None:
        """Go to first image."""
        self._go_to_page(0)

    def _go_prev(self) -> None:
        """Go to previous image."""
        if self.current_index > 0:
            self._go_to_page(self.current_index - 1)

    def _go_next(self) -> None:
        """Go to next image."""
        if self.current_index < len(self._items) - 1:
            self._go_to_page(self.current_index + 1)

    def _go_last(self) -> None:
        """Go to last image."""
        if self._items:
            self._go_to_page(len(self._items) - 1)

    def _go_to_entered_page(self) -> None:
        """Go to the image number entered in the spinbox."""
        page_num = self.page_spinbox.value()
        if self._items and 1 <= page_num <= len(self._items):
            self._go_to_page(page_num - 1)

    # =========================================================================
    # Actions
    # =========================================================================

    def _reembed_current(self) -> None:
        """Reembed current image for source-addressable document types."""
        if self.current_index < 0 or self.current_index >= len(self._items):
            return

        if self.document_id is None:
            return

        if self._active_task_id is not None:
            QMessageBox.warning(self, self.tr("Warning"), self.tr("Reembedding is already running."))
            return

        if self._current_doc_type not in _SOURCE_SCOPED_REEMBED_TYPES:
            QMessageBox.information(
                self,
                self.tr("Not Supported"),
                self.tr("Current-image reembedding is only available for manga and EPUB documents."),
            )
            return

        item = self._items[self.current_index]
        if item.source_id <= 0:
            QMessageBox.warning(self, self.tr("Cannot Reembed"), self.tr("Current item has no source id."))
            return
        use_source_ids = [item.source_id]

        # Preflight check
        decision = self._task_engine.preflight(
            "image_reembedding",
            self.book_id,
            {"document_ids": [self.document_id], "source_ids": use_source_ids},
            TaskAction.RUN,
        )
        if not decision.allowed:
            QMessageBox.warning(self, self.tr("Cannot Reembed"), decision.reason)
            return

        try:
            record = self._task_engine.submit_and_start(
                "image_reembedding",
                self.book_id,
                document_ids=[self.document_id],
                source_ids=use_source_ids,
            )
            self._active_task_id = record.task_id

            self.progress_widget.reset()
            self.progress_widget.setVisible(True)
            self.progress_widget.set_cancellable(True)

            self._set_buttons_enabled(False)

        except Exception as e:
            self._active_task_id = None
            QMessageBox.critical(self, self.tr("Error"), qarg(self.tr("Failed to start reembedding: %1"), e))

    def _reembed_pending(self) -> None:
        """Reembed all pending images in the current document."""
        if self._active_task_id is not None:
            QMessageBox.warning(self, self.tr("Warning"), self.tr("Reembedding is already running."))
            return

        if not self._items:
            QMessageBox.warning(self, self.tr("Warning"), self.tr("No images to process."))
            return

        if self.document_id is None:
            return

        # Preflight check
        decision = self._task_engine.preflight(
            "image_reembedding",
            self.book_id,
            {"document_ids": [self.document_id], "source_ids": None},
            TaskAction.RUN,
        )
        if not decision.allowed:
            QMessageBox.warning(self, self.tr("Cannot Reembed"), decision.reason)
            return

        try:
            record = self._task_engine.submit_and_start(
                "image_reembedding",
                self.book_id,
                document_ids=[self.document_id],
            )
            self._active_task_id = record.task_id

            self.progress_widget.reset()
            self.progress_widget.setVisible(True)
            self.progress_widget.set_cancellable(True)

            self._set_buttons_enabled(False)

        except Exception as e:
            self._active_task_id = None
            QMessageBox.critical(self, self.tr("Error"), qarg(self.tr("Failed to start reembedding: %1"), e))

    def _reembed_all(self) -> None:
        """Force reembed all images in the current document."""
        if self._active_task_id is not None:
            QMessageBox.warning(self, self.tr("Warning"), self.tr("Reembedding is already running."))
            return

        if not self._items:
            QMessageBox.warning(self, self.tr("Warning"), self.tr("No images to process."))
            return

        if self.document_id is None:
            return

        reply = QMessageBox.warning(
            self,
            self.tr("Force Reembed All"),
            self.tr(
                "This will reembed all images in this document, including those already reembedded.\n\n"
                "Do you want to continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Preflight check
        decision = self._task_engine.preflight(
            "image_reembedding",
            self.book_id,
            {"document_ids": [self.document_id], "source_ids": None},
            TaskAction.RUN,
        )
        if not decision.allowed:
            QMessageBox.warning(self, self.tr("Cannot Reembed"), decision.reason)
            return

        try:
            record = self._task_engine.submit_and_start(
                "image_reembedding",
                self.book_id,
                document_ids=[self.document_id],
                force=True,
            )
            self._active_task_id = record.task_id

            self.progress_widget.reset()
            self.progress_widget.setVisible(True)
            self.progress_widget.set_cancellable(True)

            self._set_buttons_enabled(False)

        except Exception as e:
            self._active_task_id = None
            QMessageBox.critical(self, self.tr("Error"), qarg(self.tr("Failed to start reembedding: %1"), e))

    def _cancel_reembed(self) -> None:
        """Cancel running reembedding operation."""
        if self._active_task_id:
            self._task_engine.cancel(self._active_task_id)

    # =========================================================================
    # Task Engine Integration
    # =========================================================================

    def _on_tasks_changed(self, book_id: str) -> None:
        """React to engine task-changed events for this book."""
        if book_id != self.book_id:
            return

        self._update_action_button_states()
        if not self._active_task_id:
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

        status = record.status
        saved_document_id = self.document_id
        saved_index = self.current_index
        self._active_task_id = None
        self.progress_widget.setVisible(False)

        if status == "completed" or status == "completed_with_errors":
            count = record.completed_items or 0

            QMessageBox.information(
                self,
                self.tr("Reembedding Complete"),
                qarg(self.tr("Reembedding completed successfully. %1 items processed."), count),
            )

            if saved_document_id is not None:
                self._load_document_data(saved_document_id)
                if self._items and saved_index >= 0:
                    restored_index = min(saved_index, len(self._items) - 1)
                    self._go_to_page(restored_index)

        elif status == "failed":
            error_msg = record.last_error or self.tr("Unknown error")
            QMessageBox.critical(
                self, self.tr("Reembedding Error"), qarg(self.tr("Reembedding failed: %1"), error_msg)
            )

        elif status == "cancelled":
            QMessageBox.information(self, self.tr("Cancelled"), self.tr("Reembedding cancelled."))

        self._set_buttons_enabled(True)
        self._update_action_button_states()

    def _update_action_button_states(self) -> None:
        """Sync action button enabled states."""
        if self.document_id is None:
            return

        if self._is_current_document_reembedding_running():
            running_tip = self.tr("Disabled while reembedding is running for this document.")
            self.reembed_current_button.setEnabled(False)
            self.reembed_current_button.setToolTip(running_tip)
            self.reembed_pending_button.setEnabled(False)
            self.reembed_pending_button.setToolTip(running_tip)
            self.reembed_all_button.setEnabled(False)
            self.reembed_all_button.setToolTip(running_tip)
            return

        has_items = bool(self._items)
        supports_reembed_current = self._current_doc_type in _SOURCE_SCOPED_REEMBED_TYPES
        if supports_reembed_current:
            self.reembed_current_button.setEnabled(has_items)
            self.reembed_current_button.setToolTip(self.tr("Reembed the current image"))
        else:
            self.reembed_current_button.setEnabled(False)
            self.reembed_current_button.setToolTip(
                self.tr("Current-image reembedding is only available for manga and EPUB documents.")
            )
        self.reembed_pending_button.setEnabled(has_items)
        self.reembed_pending_button.setToolTip(self.tr("Reembed all pending images in this document"))
        self.reembed_all_button.setEnabled(has_items)
        self.reembed_all_button.setToolTip(self.tr("Force reembed all images in this document"))

    def _is_current_document_reembedding_running(self) -> bool:
        """Return True if there is any non-terminal reembedding task covering current document."""
        if self.document_id is None:
            return False

        for record in self._task_engine.get_tasks(self.book_id, task_type="image_reembedding"):
            if record.status in TERMINAL_TASK_STATUSES:
                continue
            if not record.document_ids_json:
                # No document_ids_json means "all documents"
                return True
            try:
                ids = json.loads(record.document_ids_json)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(ids, list) and int(self.document_id) in {int(i) for i in ids}:
                return True
        return False

    # =========================================================================
    # UI State
    # =========================================================================

    def _enable_controls(self) -> None:
        """Re-enable controls after loading data."""
        self.empty_label.setVisible(False)
        self.image_viewer.setEnabled(True)
        self.text_edit.setEnabled(True)
        self.reembedded_viewer.setEnabled(True)
        self.toggle_button.setEnabled(True)
        self.go_to_label.setEnabled(True)
        self.page_spinbox.setEnabled(True)
        self.go_button.setEnabled(True)
        self.reembed_current_button.setEnabled(True)
        self.reembed_pending_button.setEnabled(True)
        self.reembed_all_button.setEnabled(True)

    def _show_empty_state(self) -> None:
        """Show empty state when no reembeddable images available."""
        self._items = []
        self.current_index = -1
        self.document_id = None
        self._reembedded_images = {}
        self._current_doc_type = ""
        self.image_viewer.clear_image()
        self.text_edit.clear()
        self.reembedded_viewer.clear_image()
        self.page_label.setText(self.tr("Image 0 of 0"))
        self.status_label.setText("")
        self.page_spinbox.setValue(1)
        self.page_spinbox.setMaximum(1)
        self.empty_label.setVisible(True)
        self.image_viewer.setEnabled(False)
        self.text_edit.setEnabled(False)
        self.reembedded_viewer.setEnabled(False)
        self.toggle_button.setEnabled(False)
        self.first_button.setEnabled(False)
        self.prev_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.last_button.setEnabled(False)
        self.go_to_label.setEnabled(False)
        self.page_spinbox.setEnabled(False)
        self.go_button.setEnabled(False)
        self.reembed_current_button.setEnabled(False)
        self.reembed_pending_button.setEnabled(False)
        self.reembed_all_button.setEnabled(False)

    def _set_buttons_enabled(self, enabled: bool) -> None:
        """Enable or disable all interactive controls.

        Args:
            enabled: Whether controls should be enabled
        """
        has_items = bool(self._items)
        controls_enabled = enabled and has_items

        self.image_viewer.setEnabled(controls_enabled)
        self.text_edit.setEnabled(controls_enabled)
        self.reembedded_viewer.setEnabled(controls_enabled)
        self.toggle_button.setEnabled(controls_enabled)
        self.doc_combo.setEnabled(enabled and self.doc_combo.count() > 0)
        self.go_to_label.setEnabled(controls_enabled)
        self.page_spinbox.setEnabled(controls_enabled)
        self.go_button.setEnabled(controls_enabled)
        self.first_button.setEnabled(controls_enabled)
        self.prev_button.setEnabled(controls_enabled)
        self.next_button.setEnabled(controls_enabled)
        self.last_button.setEnabled(controls_enabled)
        self.reembed_current_button.setEnabled(controls_enabled)
        self.reembed_pending_button.setEnabled(controls_enabled)
        self.reembed_all_button.setEnabled(controls_enabled)

        if controls_enabled:
            self._update_navigation()

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def cleanup(self) -> None:
        """Clean up background worker and database resources."""
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

    def retranslateUi(self) -> None:
        self.tip_label.setText(self._tip_text())
        self.doc_selector_label.setText(self.tr("Document:"))
        self.left_label.setText(self.tr("Original"))
        self.text_edit.setPlaceholderText(self.tr("Translated text will appear here..."))
        self.first_button.setToolTip(self.tr("First image"))
        self.prev_button.setToolTip(self.tr("Previous image"))
        self.next_button.setToolTip(self.tr("Next image"))
        self.last_button.setToolTip(self.tr("Last image"))
        self.go_to_label.setText(self.tr("Go to:"))
        self.page_spinbox.setToolTip(self.tr("Enter image number"))
        self.go_button.setText(self.tr("Go"))
        self.go_button.setToolTip(self.tr("Jump to image"))
        self.reembed_current_button.setText(self.tr("Reembed This Image"))
        self.reembed_pending_button.setText(self.tr("Reembed Pending"))
        self.reembed_all_button.setText(self.tr("Force Reembed All"))
        self.empty_label.setText(self.tr("No reembeddable images found."))
        # Update toggle button / right label based on current state
        if self._right_stack.currentIndex() == 0:
            self.right_label.setText(self.tr("Reembedded"))
            self.toggle_button.setText(self.tr("Show Text"))
        else:
            self.right_label.setText(self.tr("Translated Text"))
            self.toggle_button.setText(self.tr("Show Image"))
        self._update_navigation()

    def _tip_text(self) -> str:
        return self.tr(
            "Compare original images with their reembedded versions side by side."
        )
