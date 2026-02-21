"""Qt model for glossary term management."""

from datetime import UTC, datetime
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import QWidget

from context_aware_translation.storage.book_db import SQLiteBookDB, TermRecord

# Column indices
COL_TERM = 0
COL_TRANSLATION = 1
COL_DESCRIPTION = 2
COL_CREATED = 3
COL_OCCURRENCES = 4
COL_VOTES = 5
COL_IGNORED = 6
COL_REVIEWED = 7


class TermTableModel(QAbstractTableModel):
    """Table model for glossary terms with filtering and sorting."""

    def __init__(self, term_db: SQLiteBookDB, parent: QWidget | None = None) -> None:
        """Initialize the term table model.

        Args:
            term_db: SQLite term database instance
            parent: Parent widget
        """
        super().__init__(parent)
        self.term_db = term_db
        self._terms: list[TermRecord] = []
        self._filter_params: dict = {}
        # Sort stack: newest sort first. Applied in reverse (oldest first)
        # to leverage Python stable sort.
        self._sort_stack: list[tuple[int, bool]] = []
        self._search_pattern = ""
        self.refresh()

    def set_filter(self, filter_type: str) -> None:
        """Set filter type for terms.

        Args:
            filter_type: Filter type (all, unreviewed, ignored, translated, untranslated)
        """
        self._filter_params = {}
        if filter_type == "unreviewed":
            self._filter_params["filter_reviewed"] = False
        elif filter_type == "ignored":
            self._filter_params["filter_ignored"] = True
        elif filter_type == "translated":
            self._filter_params["filter_translated"] = True
        elif filter_type == "untranslated":
            self._filter_params["filter_translated"] = False
        self.refresh()

    def set_search(self, pattern: str) -> None:
        """Set search pattern for term filtering.

        Args:
            pattern: Search pattern (case-insensitive substring match)
        """
        self._search_pattern = pattern
        self.refresh()

    def set_sort(self, column: int, descending: bool) -> None:
        """Set sort column and direction.

        Maintains a sort stack so that successive sorts are stable:
        sorting by column A then column B preserves A's order for
        equal B values.

        Args:
            column: Column index to sort by
            descending: Sort in descending order if True
        """
        sortable = {
            COL_TERM,
            COL_TRANSLATION,
            COL_DESCRIPTION,
            COL_CREATED,
            COL_OCCURRENCES,
            COL_VOTES,
            COL_IGNORED,
            COL_REVIEWED,
        }
        if column in sortable:
            # Remove previous entry for this column, then push to front
            self._sort_stack = [(c, d) for c, d in self._sort_stack if c != column]
            self._sort_stack.insert(0, (column, descending))
            self.refresh()

    @staticmethod
    def _sort_key_for_column(col: int, term: TermRecord) -> Any:
        """Return a sort key for the given term and column."""
        if col == COL_TERM:
            return term.key.lower()
        elif col == COL_TRANSLATION:
            return (term.translated_name or "").lower()
        elif col == COL_DESCRIPTION:
            return TermTableModel._max_chunk_id(term)
        elif col == COL_CREATED:
            return term.created_at or 0.0
        elif col == COL_OCCURRENCES:
            return len(term.occurrence)
        elif col == COL_VOTES:
            return TermTableModel._chunk_desc_count(term)
        elif col == COL_IGNORED:
            return term.ignored
        elif col == COL_REVIEWED:
            return term.is_reviewed
        return term.key.lower()

    def refresh(self) -> None:
        """Reload terms from database.

        Sorting is done in Python (stable sort) so that successive
        sorts preserve the relative order from previous sorts.
        The sort stack is applied oldest-first so the most recent
        sort becomes the primary key.
        """
        self.term_db.refresh()
        self.beginResetModel()
        if self._search_pattern:
            self._terms = self.term_db.search_terms(self._search_pattern)
        else:
            self._terms = self.term_db.list_terms(**self._filter_params)
        # Apply sorts oldest-first; stable sort ensures newest is primary
        for col, desc in reversed(self._sort_stack):
            self._terms.sort(
                key=lambda t, c=col: self._sort_key_for_column(c, t),
                reverse=desc,
            )
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        """Return the number of rows.

        Args:
            parent: Parent index (unused for table model)

        Returns:
            Number of rows
        """
        if parent is None:
            parent = QModelIndex()
        if parent.isValid():
            return 0
        return len(self._terms)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        """Return the number of columns.

        Args:
            parent: Parent index (unused for table model)

        Returns:
            Number of columns
        """
        if parent is None:
            parent = QModelIndex()
        if parent.isValid():
            return 0
        return 8

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Return header data for the given section.

        Args:
            section: Column or row index
            orientation: Horizontal or vertical
            role: Data role

        Returns:
            Header text or None
        """
        if role == Qt.ItemDataRole.ToolTipRole and orientation == Qt.Orientation.Horizontal:
            if section == COL_TERM:
                return self.tr(
                    "Source-language term key. During glossary translation, terms can be grouped "
                    "with similar keys using string-similarity matching."
                )
            elif section == COL_TRANSLATION:
                return self.tr(
                    "Target-language term. For untranslated terms, the translator receives up to "
                    "3 most similar already-translated terms as references, and similar "
                    "untranslated terms may be sent together in the same LLM call."
                )
            elif section == COL_DESCRIPTION:
                return self.tr(
                    "Primary description built from accumulated context. During chunk translation, "
                    "only context summaries ending at or before the current chunk are sent."
                )
            elif section == COL_CREATED:
                return self.tr("When this term was first created in the glossary.")
            elif section == COL_OCCURRENCES:
                return self.tr("Number of chunks where this term appears.")
            elif section == COL_VOTES:
                return self.tr("Number of chunks where the LLM recognized this as a term.")
            elif section == COL_IGNORED:
                return self.tr("Ignored terms are excluded from glossary and chunk translation term injection.")
            elif section == COL_REVIEWED:
                return self.tr("Whether this term has been processed by the Review Terms pass.")

        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if section == COL_TERM:
                return self.tr("Term")
            elif section == COL_TRANSLATION:
                return self.tr("Translation")
            elif section == COL_DESCRIPTION:
                return self.tr("Description")
            elif section == COL_CREATED:
                return self.tr("Created")
            elif section == COL_OCCURRENCES:
                return self.tr("Occurrences")
            elif section == COL_VOTES:
                return self.tr("Recognized")
            elif section == COL_IGNORED:
                return self.tr("Ignored")
            elif section == COL_REVIEWED:
                return self.tr("Reviewed")
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Return data for the given index and role.

        Args:
            index: Model index
            role: Data role

        Returns:
            Data for the index or None
        """
        if not index.isValid() or not (0 <= index.row() < len(self._terms)):
            return None

        term = self._terms[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_TERM:
                return term.key
            elif col == COL_TRANSLATION:
                return term.translated_name or ""
            elif col == COL_DESCRIPTION:
                if term.descriptions:
                    # Get the first description value (descriptions is a dict)
                    first_desc = next(iter(term.descriptions.values()), "")
                    # Truncate long descriptions for display
                    if len(first_desc) > 100:
                        return first_desc[:100] + "..."
                    return first_desc
                return ""
            elif col == COL_CREATED:
                if term.created_at:
                    dt = datetime.fromtimestamp(term.created_at, tz=UTC)
                    return dt.strftime("%Y-%m-%d %H:%M")
                return ""
            elif col == COL_OCCURRENCES:
                return str(len(term.occurrence))
            elif col == COL_VOTES:
                return str(self._chunk_desc_count(term))
            elif col in (COL_IGNORED, COL_REVIEWED):
                return None  # Use CheckStateRole instead

        elif role == Qt.ItemDataRole.CheckStateRole:
            if col == COL_IGNORED:
                return Qt.CheckState.Checked if term.ignored else Qt.CheckState.Unchecked
            elif col == COL_REVIEWED:
                return Qt.CheckState.Checked if term.is_reviewed else Qt.CheckState.Unchecked

        elif role == Qt.ItemDataRole.EditRole and col == COL_TRANSLATION:
            return term.translated_name or ""

        elif role == Qt.ItemDataRole.ToolTipRole and col == COL_DESCRIPTION:
            # Full description as tooltip
            if term.descriptions:
                return "\n".join(f"{k}: {v}" for k, v in term.descriptions.items())
            return None

        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        """Set data for the given index.

        Args:
            index: Model index
            value: New value
            role: Data role

        Returns:
            True if data was set successfully
        """
        if not index.isValid() or not (0 <= index.row() < len(self._terms)):
            return False

        term = self._terms[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.EditRole and col == COL_TRANSLATION:
            # Update translation - write to DB first, then update in-memory
            new_translation = value.strip() if value else None
            if new_translation == term.translated_name:
                return False

            # Write to database first
            self.term_db.update_terms_bulk([term.key], translated_name=new_translation)
            # Update in-memory only after DB write succeeds
            term.translated_name = new_translation
            self.dataChanged.emit(index, index, [role])
            return True

        elif role == Qt.ItemDataRole.CheckStateRole:
            if col == COL_IGNORED:
                # Handle both enum and integer values from PySide6
                check_value = value.value if hasattr(value, "value") else int(value)
                new_ignored = check_value == Qt.CheckState.Checked.value
                if new_ignored == term.ignored:
                    return False

                # Write to database first
                self.term_db.update_terms_bulk([term.key], ignored=new_ignored)
                # Update in-memory only after DB write succeeds
                term.ignored = new_ignored
                self.dataChanged.emit(index, index, [role])
                return True

            elif col == COL_REVIEWED:
                # Handle both enum and integer values from PySide6
                check_value = value.value if hasattr(value, "value") else int(value)
                new_reviewed = check_value == Qt.CheckState.Checked.value
                if new_reviewed == term.is_reviewed:
                    return False

                # Write to database first
                self.term_db.update_terms_bulk([term.key], is_reviewed=new_reviewed)
                # Update in-memory only after DB write succeeds
                term.is_reviewed = new_reviewed
                self.dataChanged.emit(index, index, [role])
                return True

        return False

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        """Return item flags for the given index.

        Args:
            index: Model index

        Returns:
            Item flags
        """
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        flags = super().flags(index)
        col = index.column()

        if col == COL_TRANSLATION:
            flags |= Qt.ItemFlag.ItemIsEditable
        elif col in (COL_IGNORED, COL_REVIEWED):
            flags |= Qt.ItemFlag.ItemIsUserCheckable

        return flags

    def retranslate(self) -> None:
        """Notify views that header data needs re-translation."""
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, self.columnCount() - 1)

    def get_term(self, row: int) -> TermRecord | None:
        """Get term record at the given row.

        Args:
            row: Row index

        Returns:
            TermRecord or None if row is invalid
        """
        if 0 <= row < len(self._terms):
            return self._terms[row]
        return None

    @staticmethod
    def _chunk_desc_count(term: TermRecord) -> int:
        """Count description keys that are chunk IDs (numeric strings)."""
        return sum(1 for k in (term.descriptions or {}) if str(k).lstrip("-").isdigit())

    @staticmethod
    def _max_chunk_id(term: TermRecord) -> int:
        """Return the maximum numeric chunk ID from description keys, or -1 if none."""
        chunk_ids = [int(k) for k in (term.descriptions or {}) if str(k).lstrip("-").isdigit()]
        return max(chunk_ids) if chunk_ids else -1

    def get_selected_keys(self, rows: list[int]) -> list[str]:
        """Get term keys for the selected rows.

        Args:
            rows: List of row indices

        Returns:
            List of term keys
        """
        return [self._terms[row].key for row in rows if 0 <= row < len(self._terms)]
