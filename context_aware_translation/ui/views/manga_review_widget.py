"""Manga page review widget with image viewer and translation editor."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.documents.manga_alignment import align_sources_to_chunks, count_nonempty_ocr_sources
from context_aware_translation.storage.book_db import SQLiteBookDB, TranslationChunkRecord
from context_aware_translation.storage.document_repository import DocumentRepository

from ..i18n import qarg
from ..widgets import ImageViewer

PREVIEW_TRUNCATION_LENGTH = 50


class MangaReviewWidget(QWidget):
    """Widget for reviewing manga page translations with image viewer."""

    def __init__(
        self,
        term_db: SQLiteBookDB,
        document_repo: DocumentRepository,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.term_db = term_db
        self.document_repo = document_repo

        # Manga review state
        self._manga_sources: list[dict] = []
        self._manga_current_index: int = -1
        self._manga_chunks: list[TranslationChunkRecord] = []
        self._source_to_chunk: dict[int, int] = {}

        self._init_ui()

    def _init_ui(self) -> None:
        """Initialize the manga review UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Splitter for page list and detail view
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel: page list
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.pages_label = QLabel(self.tr("Pages:"))
        left_layout.addWidget(self.pages_label)

        self.manga_page_list = QListWidget()
        self.manga_page_list.currentRowChanged.connect(self._on_manga_page_selected)
        left_layout.addWidget(self.manga_page_list)

        splitter.addWidget(left_widget)

        # Right panel: image viewer + translation editor
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Page label
        self.manga_page_label = QLabel(self.tr("No page selected"))
        self.manga_page_label.setStyleSheet("font-weight: bold;")
        right_layout.addWidget(self.manga_page_label)

        # Image viewer
        self.manga_image_viewer = ImageViewer()
        right_layout.addWidget(self.manga_image_viewer, stretch=2)

        # Translation editor
        self.manga_trans_label = QLabel(self.tr("Translation:"))
        self.manga_trans_label.setStyleSheet("font-weight: bold;")
        right_layout.addWidget(self.manga_trans_label)

        self.manga_translation_text = QTextEdit()
        self.manga_translation_text.setMaximumHeight(150)
        right_layout.addWidget(self.manga_translation_text)

        # Buttons row
        btn_layout = QHBoxLayout()
        self.manga_save_btn = QPushButton(self.tr("Save"))
        self.manga_save_btn.clicked.connect(self._save_manga_translation)
        btn_layout.addWidget(self.manga_save_btn)

        self.manga_prev_btn = QPushButton("\u2190 " + self.tr("Previous"))
        self.manga_prev_btn.clicked.connect(self._go_manga_previous)
        btn_layout.addWidget(self.manga_prev_btn)

        self.manga_next_btn = QPushButton(self.tr("Next") + " \u2192")
        self.manga_next_btn.clicked.connect(self._go_manga_next)
        btn_layout.addWidget(self.manga_next_btn)
        right_layout.addLayout(btn_layout)

        splitter.addWidget(right_widget)

        # Set splitter sizes (20% list, 80% detail)
        splitter.setSizes([200, 800])

        layout.addWidget(splitter)

        self._reset_manga_detail_state()

    def _reset_manga_detail_state(self) -> None:
        """Reset right-panel detail state when no valid page is selected."""
        self.manga_page_label.setText(self.tr("No page selected"))
        self.manga_image_viewer.clear_image()
        self.manga_translation_text.clear()
        self.manga_translation_text.setReadOnly(True)
        self.manga_prev_btn.setEnabled(False)
        self.manga_next_btn.setEnabled(False)
        self.manga_save_btn.setEnabled(False)

    def load_manga_pages(self, doc_id: int | None) -> None:
        """Load manga pages into the page list for review."""
        self.manga_page_list.clear()
        self._manga_sources = []
        self._manga_chunks = []
        self._manga_current_index = -1
        self._source_to_chunk = {}
        self._reset_manga_detail_state()

        if doc_id is None:
            return

        # Load sources (images) for this document
        sources = self.document_repo.get_document_sources(doc_id)
        self._manga_sources = sorted(sources, key=lambda s: s["sequence_number"])

        # Load chunks for this document to get translations
        chunks = self.term_db.list_chunks(document_id=doc_id)
        self._manga_chunks = sorted(chunks, key=lambda c: c.chunk_id)

        # Build source_index -> chunk_index mapping from shared alignment rules.
        self._source_to_chunk = align_sources_to_chunks(
            self._manga_sources,
            len(self._manga_chunks),
            strict=False,
        )
        nonempty_page_count = count_nonempty_ocr_sources(self._manga_sources)
        if nonempty_page_count != len(self._manga_chunks):
            QMessageBox.warning(
                self,
                self.tr("Manga Alignment Warning"),
                qarg(
                    self.tr(
                        "Detected OCR/chunk mismatch. Please rebuild glossary after OCR edits.\n"
                        "Non-empty OCR pages: %1, chunks: %2"
                    ),
                    nonempty_page_count,
                    len(self._manga_chunks),
                ),
            )

        for i, _source in enumerate(self._manga_sources):
            chunk_idx_for_page = self._source_to_chunk.get(i)
            if chunk_idx_for_page is not None:
                has_translation = self._manga_chunks[chunk_idx_for_page].is_translated
            else:
                has_translation = False
            status = "\u2713" if has_translation else ("\u2013" if i not in self._source_to_chunk else "\u25cb")
            item = QListWidgetItem(f"{status} {qarg(self.tr('Page %1'), i + 1)}")
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.manga_page_list.addItem(item)

        if self.manga_page_list.count() > 0:
            self.manga_page_list.setCurrentRow(0)

    def _on_manga_page_selected(self, row: int) -> None:
        """Handle manga page selection from list."""
        if row < 0 or row >= len(self._manga_sources):
            self._manga_current_index = -1
            self._reset_manga_detail_state()
            return

        self._manga_current_index = row
        source = self._manga_sources[row]

        # Update page label
        self.manga_page_label.setText(qarg(self.tr("Page %1 of %2"), row + 1, len(self._manga_sources)))

        # Load page image
        binary_content = source.get("binary_content")
        if binary_content:
            self.manga_image_viewer.set_image(binary_content)
        else:
            self.manga_image_viewer.clear_image()

        # Load translation from corresponding chunk via mapping
        chunk_idx = self._source_to_chunk.get(row)
        if chunk_idx is not None:
            chunk = self._manga_chunks[chunk_idx]
            self.manga_translation_text.setPlainText(chunk.translation or "")
            self.manga_translation_text.setReadOnly(False)
            self.manga_save_btn.setEnabled(True)
        else:
            self.manga_translation_text.setPlainText(self.tr("(No text detected on this page)"))
            self.manga_translation_text.setReadOnly(True)
            self.manga_save_btn.setEnabled(False)

        # Update navigation buttons
        self.manga_prev_btn.setEnabled(row > 0)
        self.manga_next_btn.setEnabled(row < len(self._manga_sources) - 1)

    def _save_manga_translation(self) -> None:
        """Save edited manga page translation to database."""
        idx = self._manga_current_index
        if idx < 0:
            return

        chunk_idx = self._source_to_chunk.get(idx)
        if chunk_idx is None:
            QMessageBox.information(
                self,
                self.tr("Info"),
                self.tr("No text chunk for this page (art-only page)."),
            )
            return

        chunk = self._manga_chunks[chunk_idx]
        new_translation = self.manga_translation_text.toPlainText()

        updated_chunk = _build_chunk_record(chunk, new_translation)

        self.term_db.upsert_chunks([updated_chunk])
        self._manga_chunks[chunk_idx] = updated_chunk

        # Update list item status
        item = self.manga_page_list.item(idx)
        if item:
            status = "\u2713" if updated_chunk.is_translated else "\u25cb"
            item.setText(f"{status} {qarg(self.tr('Page %1'), idx + 1)}")

        QMessageBox.information(self, self.tr("Saved"), self.tr("Translation saved successfully!"))

    def _go_manga_previous(self) -> None:
        """Navigate to previous manga page."""
        if self._manga_current_index > 0:
            self.manga_page_list.setCurrentRow(self._manga_current_index - 1)

    def _go_manga_next(self) -> None:
        """Navigate to next manga page."""
        if self._manga_current_index < len(self._manga_sources) - 1:
            self.manga_page_list.setCurrentRow(self._manga_current_index + 1)

    def retranslateUi(self) -> None:
        """Update translatable strings after language change."""
        self.pages_label.setText(self.tr("Pages:"))
        self.manga_trans_label.setText(self.tr("Translation:"))
        self.manga_save_btn.setText(self.tr("Save"))
        self.manga_prev_btn.setText("\u2190 " + self.tr("Previous"))
        self.manga_next_btn.setText(self.tr("Next") + " \u2192")


def _build_chunk_record(chunk: TranslationChunkRecord, translation_text: str) -> TranslationChunkRecord:
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
