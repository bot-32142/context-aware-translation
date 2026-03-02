"""Qt model for book/library management."""

from datetime import UTC, datetime
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import QWidget

from context_aware_translation.storage.book import Book
from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.ui.i18n import qarg

# Column indices
COL_NAME = 0
COL_TARGET_LANGUAGE = 1
COL_PROGRESS = 2
COL_MODIFIED = 3


class BookTableModel(QAbstractTableModel):
    """Table model for books."""

    def __init__(self, book_manager: BookManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.book_manager = book_manager
        self._books: list[Book] = []
        self._progress_cache: dict[str, dict] = {}
        self._config_cache: dict[str, dict] = {}
        self._id_to_row: dict[str, int] = {}
        self.refresh()

    def refresh(self) -> None:
        """Reload books from database."""
        self.beginResetModel()
        self._books = self.book_manager.list_books()
        self._progress_cache.clear()
        self._config_cache.clear()
        self._build_id_index()
        self.endResetModel()

    def _build_id_index(self) -> None:
        """Build ID to row index mapping for fast lookups."""
        self._id_to_row = {book.book_id: idx for idx, book in enumerate(self._books)}

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        if parent is None:
            parent = QModelIndex()
        if parent.isValid():
            return 0
        return len(self._books)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        if parent is None:
            parent = QModelIndex()
        if parent.isValid():
            return 0
        return 4

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        """Return header data for the model."""
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if section == COL_NAME:
                return self.tr("Name")
            elif section == COL_TARGET_LANGUAGE:
                return self.tr("Target Language")
            elif section == COL_PROGRESS:
                return self.tr("Progress")
            elif section == COL_MODIFIED:
                return self.tr("Modified")
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Return data for display."""
        if not index.isValid() or not (0 <= index.row() < len(self._books)):
            return None

        book = self._books[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_NAME:
                return book.name
            elif col == COL_TARGET_LANGUAGE:
                config = self._get_book_config(book.book_id)
                if config:
                    return config.get("translation_target_language", "")
                return ""
            elif col == COL_PROGRESS:
                progress = self._get_book_progress(book.book_id)
                if progress:
                    percent = progress.get("progress_percent", 0.0)
                    translated = progress.get("translated_chunks", 0)
                    total = progress.get("chunks", 0)
                    return qarg(self.tr("%1% (%2/%3)"), f"{percent:.1f}", translated, total)
                return qarg(self.tr("%1% (%2/%3)"), "0.0", 0, 0)
            elif col == COL_MODIFIED:
                return self._format_timestamp(book.updated_at)

        elif role == Qt.ItemDataRole.TextAlignmentRole and col == COL_PROGRESS:
            # Center-align the Progress column
            return Qt.AlignmentFlag.AlignCenter

        return None

    def _get_book_config(self, book_id: str) -> dict | None:
        """Get book configuration with caching."""
        if book_id not in self._config_cache:
            config = self.book_manager.get_book_config(book_id)
            if config is not None:
                self._config_cache[book_id] = config
        return self._config_cache.get(book_id)

    def _get_book_progress(self, book_id: str) -> dict | None:
        """Get book progress with caching."""
        if book_id not in self._progress_cache:
            progress = self.book_manager.get_book_progress(book_id)
            if progress is not None:
                self._progress_cache[book_id] = progress
        return self._progress_cache.get(book_id)

    def _format_timestamp(self, timestamp: float) -> str:
        """Format timestamp as human-readable numeric date."""
        dt = datetime.fromtimestamp(timestamp, tz=UTC)
        now = datetime.now(tz=UTC)

        # Same day: show time as HH:MM
        if dt.date() == now.date():
            return dt.strftime("%H:%M")

        # Same year: show MM-DD
        if dt.year == now.year:
            return dt.strftime("%m-%d")

        # Different year: show YYYY-MM-DD
        return dt.strftime("%Y-%m-%d")

    def retranslate(self) -> None:
        """Notify views that header data needs re-translation."""
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, self.columnCount() - 1)

    def get_book(self, row: int) -> Book | None:
        """Get book at row index."""
        if 0 <= row < len(self._books):
            return self._books[row]
        return None
