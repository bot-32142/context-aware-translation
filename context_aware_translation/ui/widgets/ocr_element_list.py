"""OCR element list panel for structured OCR review."""

from __future__ import annotations

from PySide6.QtCore import QT_TR_NOOP, QCoreApplication, Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .ocr_element_card import OCRElementCard

# Page-type placeholder messages
_PLACEHOLDER_MESSAGES = {
    "cover": QT_TR_NOOP("Cover Page \u2014 No editable text content"),
    "toc": QT_TR_NOOP("Table of Contents \u2014 No editable text content"),
    "blank": QT_TR_NOOP("Blank Page \u2014 No editable text content"),
    "content": QT_TR_NOOP("No OCR elements found on this page"),
}


class OCRElementList(QScrollArea):
    """Scrollable list of OCR element cards with page-type placeholder support."""

    element_selected = Signal(int)  # Emits element index when a card is clicked

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: list[OCRElementCard] = []
        self._selected_index: int = -1
        self._placeholder_mode: bool = False

        # Container widget
        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(6)

        self.setWidget(self._container)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def set_items(self, items: list, page_image_bytes: bytes | None, page_type: str = "content") -> None:
        """Set the OCR items to display.

        Args:
            items: List of OCRItem instances
            page_image_bytes: Full page image bytes for cropping ImageItem thumbnails
            page_type: Page type string ("content", "cover", "toc", "blank")
        """
        self.clear()

        if not items:
            # Show placeholder
            self._placeholder_mode = True
            message = _PLACEHOLDER_MESSAGES.get(page_type, _PLACEHOLDER_MESSAGES["content"])
            placeholder = QLabel(QCoreApplication.translate("OCRElementList", message))
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: #9e9e9e; font-size: 14px; padding: 40px;")
            placeholder.setWordWrap(True)
            self._layout.addWidget(placeholder)
            self._layout.addStretch()
            return

        # Build cards
        self._placeholder_mode = False
        for index, item in enumerate(items):
            card = OCRElementCard(item, index, page_image_bytes)
            card.clicked.connect(self._on_card_clicked)
            self._cards.append(card)
            self._layout.addWidget(card)

        self._layout.addStretch()

    def get_all_texts(self) -> list[str]:
        """Collect texts from all cards in order for saving.

        Returns empty list in placeholder mode.
        """
        if self._placeholder_mode:
            return []

        result: list[str] = []
        for card in self._cards:
            result.extend(card.get_texts())
        return result

    def select_element(self, index: int) -> None:
        """Select a card and scroll it into view."""
        # Deselect previous
        if 0 <= self._selected_index < len(self._cards):
            self._cards[self._selected_index].set_selected(False)

        self._selected_index = index

        # Select new
        if 0 <= index < len(self._cards):
            self._cards[index].set_selected(True)
            # Scroll into view
            self.ensureWidgetVisible(self._cards[index])

    def clear(self) -> None:
        """Remove all cards and placeholders."""
        self._cards.clear()
        self._selected_index = -1
        self._placeholder_mode = False

        # Remove all widgets from layout
        while self._layout.count():
            child = self._layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def is_placeholder_mode(self) -> bool:
        """Return True if showing a page-type placeholder."""
        return self._placeholder_mode

    def _on_card_clicked(self, index: int) -> None:
        """Handle card click."""
        self.select_element(index)
        self.element_selected.emit(index)

    def keyPressEvent(self, event) -> None:
        """Handle keyboard navigation between cards."""
        if not self._cards:
            super().keyPressEvent(event)
            return

        if event.key() == Qt.Key.Key_Down:
            new_index = min(self._selected_index + 1, len(self._cards) - 1)
            if new_index != self._selected_index:
                self.select_element(new_index)
                self.element_selected.emit(new_index)
            event.accept()
        elif event.key() == Qt.Key.Key_Up:
            new_index = max(self._selected_index - 1, 0)
            if new_index != self._selected_index:
                self.select_element(new_index)
                self.element_selected.emit(new_index)
            event.accept()
        else:
            super().keyPressEvent(event)
