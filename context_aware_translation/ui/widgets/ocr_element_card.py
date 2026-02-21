"""OCR element card widget for structured OCR review."""

from __future__ import annotations

import logging

from PySide6.QtCore import QT_TR_NOOP, QCoreApplication, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.documents.content.ocr_items import (
    ChapterItem,
    ImageItem,
    ListItem,
    ParagraphItem,
    QuoteItem,
    SectionItem,
    SubsectionItem,
    TableItem,
)

logger = logging.getLogger(__name__)

# Text edit width for auto-resize calculation
TEXT_EDIT_WIDTH = 280

# Type config: (label, color_hex, background_hex)
_TYPE_CONFIG = {
    ChapterItem: (QT_TR_NOOP("Chapter"), "#1a237e", "#e8eaf6"),
    SectionItem: (QT_TR_NOOP("Section"), "#1565c0", "#e3f2fd"),
    SubsectionItem: (QT_TR_NOOP("Subsection"), "#42a5f5", "#e1f5fe"),
    ParagraphItem: (QT_TR_NOOP("Paragraph"), "#616161", "#f5f5f5"),
    ImageItem: (QT_TR_NOOP("Image"), "#2e7d32", "#e8f5e9"),
    TableItem: (QT_TR_NOOP("Table"), "#6a1b9a", "#f3e5f5"),
    ListItem: (QT_TR_NOOP("List"), "#e65100", "#fff3e0"),
    QuoteItem: (QT_TR_NOOP("Quote"), "#00695c", "#e0f2f1"),
}


class OCRElementCard(QFrame):
    """A card widget representing a single OCR element with type-specific rendering."""

    clicked = Signal(int)  # Emits element index when card is clicked

    def __init__(self, item, index: int, page_image_bytes: bytes | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._index = index
        self._item = item
        self._selected = False

        # Text widgets storage
        self._text_widget = None  # Main text widget (QTextEdit or QLineEdit)
        self._caption_widget = None  # Caption widget for ImageItem/TableItem

        # Determine type config
        item_type = type(item)
        label_text, color, bg_color = _TYPE_CONFIG.get(item_type, (QT_TR_NOOP("Unknown"), "#757575", "#eeeeee"))

        self._color = color
        self._bg_color = bg_color
        self._setup_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # Header row
        header = QHBoxLayout()
        type_label = QLabel(QCoreApplication.translate("OCRElementCard", label_text))
        type_label.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 11px;")
        header.addWidget(type_label)

        # Bbox info for ImageItem
        if isinstance(item, ImageItem):
            bbox = item.bbox
            bbox_label = QLabel(f"({bbox.x:.2f}, {bbox.y:.2f}, {bbox.width:.2f}, {bbox.height:.2f})")
            bbox_label.setStyleSheet("color: #9e9e9e; font-size: 10px;")
            header.addWidget(bbox_label)

        header.addStretch()
        layout.addLayout(header)

        # Build type-specific content
        self._build_content(item, layout, page_image_bytes)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    @property
    def index(self) -> int:
        return self._index

    def _setup_style(self) -> None:
        """Set default (unselected) style."""
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            f"OCRElementCard {{ background-color: {self._bg_color}; border: 1px solid #e0e0e0; border-radius: 4px; }}"
        )

    def set_selected(self, selected: bool) -> None:
        """Toggle visual selection state."""
        self._selected = selected
        if selected:
            self.setStyleSheet(
                f"OCRElementCard {{ background-color: {self._bg_color}; "
                f"border: 2px solid {self._color}; border-radius: 4px; }}"
            )
        else:
            self._setup_style()

    def mousePressEvent(self, event):
        """Emit clicked signal when card is clicked."""
        self.clicked.emit(self._index)
        super().mousePressEvent(event)

    def _build_content(self, item, layout: QVBoxLayout, page_image_bytes: bytes | None) -> None:
        """Build type-specific content widgets."""

        if isinstance(item, ImageItem):
            self._build_image_content(item, layout, page_image_bytes)
        elif isinstance(item, TableItem):
            self._build_table_content(item, layout)
        elif isinstance(item, ListItem):
            self._build_list_content(item, layout)
        elif isinstance(item, (ChapterItem, SectionItem, SubsectionItem)):
            self._build_heading_content(item, layout)
        elif isinstance(item, QuoteItem):
            self._build_quote_content(item, layout)
        elif isinstance(item, ParagraphItem):
            self._build_paragraph_content(item, layout)
        else:
            # Fallback for unknown types
            self._text_widget = QTextEdit()
            texts = item.get_texts()
            self._text_widget.setPlainText("\n".join(texts))
            self._auto_resize_textedit(self._text_widget)
            layout.addWidget(self._text_widget)

    def _build_heading_content(self, item, layout: QVBoxLayout) -> None:
        """Build content for Chapter/Section/Subsection items."""
        self._text_widget = QLineEdit()
        self._text_widget.setText(item.text)

        font = self._text_widget.font()
        if isinstance(item, ChapterItem):
            font.setBold(True)
            font.setPointSize(font.pointSize() + 2)
        elif isinstance(item, SectionItem):
            font.setBold(True)
        self._text_widget.setFont(font)

        layout.addWidget(self._text_widget)

    def _build_paragraph_content(self, item: ParagraphItem, layout: QVBoxLayout) -> None:
        """Build content for Paragraph items."""
        self._text_widget = QTextEdit()
        self._text_widget.setPlainText(item.text)
        self._auto_resize_textedit(self._text_widget)
        layout.addWidget(self._text_widget)

    def _build_image_content(self, item: ImageItem, layout: QVBoxLayout, page_image_bytes: bytes | None) -> None:
        """Build content for Image items with cropped thumbnail."""
        # Show cropped image thumbnail
        if page_image_bytes and item.bbox:
            try:
                cropped_bytes = item.bbox.crop_from_image(page_image_bytes)
                pixmap = QPixmap()
                pixmap.loadFromData(cropped_bytes)
                if not pixmap.isNull():
                    # Scale to max 200px height
                    if pixmap.height() > 200:
                        pixmap = pixmap.scaledToHeight(200, Qt.TransformationMode.SmoothTransformation)
                    img_label = QLabel()
                    img_label.setPixmap(pixmap)
                    img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    layout.addWidget(img_label)
            except Exception:
                logger.warning("Failed to load image crop", exc_info=True)
                placeholder = QLabel(self.tr("Could not load image"))
                placeholder.setStyleSheet("color: #9e9e9e; font-style: italic;")
                placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(placeholder)
        else:
            placeholder = QLabel(self.tr("No image available"))
            placeholder.setStyleSheet("color: #9e9e9e; font-style: italic;")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(placeholder)

        # Embedded text field
        if item.embedded_text:
            et_label = QLabel(self.tr("Embedded text:"))
            et_label.setStyleSheet("color: #757575; font-size: 10px;")
            layout.addWidget(et_label)
            self._text_widget = QTextEdit()
            self._text_widget.setPlainText(item.embedded_text)
            self._auto_resize_textedit(self._text_widget)
            layout.addWidget(self._text_widget)

        # Caption field
        if item.caption:
            cap_label = QLabel(self.tr("Caption:"))
            cap_label.setStyleSheet("color: #757575; font-size: 10px;")
            layout.addWidget(cap_label)
            self._caption_widget = QLineEdit()
            self._caption_widget.setText(item.caption)
            layout.addWidget(self._caption_widget)

    def _build_table_content(self, item: TableItem, layout: QVBoxLayout) -> None:
        """Build content for Table items."""
        self._text_widget = QTextEdit()
        self._text_widget.setPlainText(item.text)
        self._auto_resize_textedit(self._text_widget)
        layout.addWidget(self._text_widget)

        # Caption field
        if item.caption:
            cap_label = QLabel(self.tr("Caption:"))
            cap_label.setStyleSheet("color: #757575; font-size: 10px;")
            layout.addWidget(cap_label)
            self._caption_widget = QLineEdit()
            self._caption_widget.setText(item.caption)
            layout.addWidget(self._caption_widget)

    def _build_list_content(self, item: ListItem, layout: QVBoxLayout) -> None:
        """Build content for List items."""
        self._text_widget = QTextEdit()
        # Join all list items with newline
        self._text_widget.setPlainText("\n".join(item.items))
        self._auto_resize_textedit(self._text_widget)
        layout.addWidget(self._text_widget)

    def _build_quote_content(self, item: QuoteItem, layout: QVBoxLayout) -> None:
        """Build content for Quote items."""
        self._text_widget = QTextEdit()
        self._text_widget.setPlainText(item.text)
        font = self._text_widget.font()
        font.setItalic(True)
        self._text_widget.setFont(font)
        self._auto_resize_textedit(self._text_widget)
        layout.addWidget(self._text_widget)

    def _auto_resize_textedit(self, text_edit: QTextEdit) -> None:
        """Configure a QTextEdit to auto-resize based on content."""
        text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        doc = text_edit.document()
        # Force document layout at a reasonable width to account for word wrap
        doc.setTextWidth(TEXT_EDIT_WIDTH)
        doc_height = doc.size().height()
        margins = text_edit.contentsMargins()
        height = int(doc_height) + margins.top() + margins.bottom() + 10
        height = max(height, 60)  # Minimum ~3 lines

        if height <= 300:
            text_edit.setFixedHeight(height)
            text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        else:
            text_edit.setFixedHeight(300)
            text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def get_texts(self) -> list[str]:
        """Extract edited texts in same order as OCRItem.get_texts().

        CRITICAL: The concatenation order MUST match the corresponding OCRItem.get_texts():
        - ImageItem: embedded_text lines FIRST, then caption lines
        - TableItem: text lines FIRST, then caption lines
        - ListItem: flat splitlines() list
        - Others: text.splitlines()
        """
        result: list[str] = []

        if isinstance(self._item, ImageItem):
            # CRITICAL ORDER: embedded_text first, caption second
            if self._text_widget is not None:
                result.extend(self._text_widget.toPlainText().splitlines())
            if self._caption_widget is not None:
                result.extend(self._caption_widget.text().splitlines())
        elif isinstance(self._item, TableItem):
            # CRITICAL ORDER: text first, caption second
            if self._text_widget is not None:
                result.extend(self._text_widget.toPlainText().splitlines())
            if self._caption_widget is not None:
                result.extend(self._caption_widget.text().splitlines())
        elif isinstance(self._item, (ChapterItem, SectionItem, SubsectionItem)):
            # QLineEdit — use .text()
            if self._text_widget is not None:
                result.extend(self._text_widget.text().splitlines())
        else:
            # ParagraphItem, ListItem, QuoteItem — QTextEdit
            if self._text_widget is not None:
                result.extend(self._text_widget.toPlainText().splitlines())

        return result
