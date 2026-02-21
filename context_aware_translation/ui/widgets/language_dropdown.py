"""Language dropdown widget for selecting target language."""

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox

from ..constants import LANGUAGES

logger = logging.getLogger(__name__)


class LanguageDropdown(QComboBox):
    """A dropdown for selecting target language."""

    language_changed = Signal(str)

    def __init__(self, parent=None):
        """Initialize the language dropdown.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)

        # Populate with languages
        for display_name, code in LANGUAGES:
            self.addItem(display_name, code)

        # Connect signal
        self.currentIndexChanged.connect(self._on_selection_changed)

    def _on_selection_changed(self, index: int) -> None:
        """Handle selection change.

        Args:
            index: Selected index
        """
        code = self.itemData(index)
        if code:
            self.language_changed.emit(code)

    def get_value(self) -> str:
        """Get the current language code.

        Returns:
            Language code (e.g., "zh-CN", "en")
        """
        return self.currentData() or ""

    def set_value(self, code: str) -> None:
        """Set the current language by code.

        Args:
            code: Language code to select
        """
        # Find the index with matching code
        for i in range(self.count()):
            if self.itemData(i) == code:
                self.setCurrentIndex(i)
                return

        # If not found, log warning and default to first item
        logger.warning(f"Unknown language code '{code}', defaulting to first available language")
        if self.count() > 0:
            self.setCurrentIndex(0)
