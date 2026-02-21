"""Qt model for endpoint profile management."""

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import QWidget

from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.endpoint_profile import EndpointProfile

# Column indices
COL_NAME = 0
COL_BASE_URL = 1
COL_MODEL = 2
COL_DEFAULT = 3
COL_TOKEN_USAGE = 4
COL_USAGE_PCT = 5


class EndpointProfileModel(QAbstractTableModel):
    """Table model for endpoint profiles."""

    def __init__(self, book_manager: BookManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.book_manager = book_manager
        self._profiles: list[EndpointProfile] = []
        self._id_to_row: dict[str, int] = {}
        self.refresh()

    def refresh(self) -> None:
        """Reload profiles from database."""
        self.beginResetModel()
        self._profiles = self.book_manager.list_endpoint_profiles()
        self._build_id_index()
        self.endResetModel()

    def _build_id_index(self) -> None:
        """Build ID to row index mapping for fast lookups."""
        self._id_to_row = {profile.profile_id: idx for idx, profile in enumerate(self._profiles)}

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        if parent is None:
            parent = QModelIndex()
        if parent.isValid():
            return 0
        return len(self._profiles)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        if parent is None:
            parent = QModelIndex()
        if parent.isValid():
            return 0
        return 6

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
            elif section == COL_BASE_URL:
                return self.tr("Base URL")
            elif section == COL_MODEL:
                return self.tr("Model")
            elif section == COL_DEFAULT:
                return self.tr("Default")
            elif section == COL_TOKEN_USAGE:
                return self.tr("Token Usage")
            elif section == COL_USAGE_PCT:
                return self.tr("Usage %")
        return None

    def _usage_tooltip(self, profile: EndpointProfile) -> str:
        """Build a detailed tooltip showing all usage and limits."""
        lines = []

        # Total
        if profile.token_limit is not None:
            lines.append(f"Total: {profile.tokens_used:,} / {profile.token_limit:,}")
        else:
            lines.append(f"Total: {profile.tokens_used:,} / \u221e")

        # Input (with cached/uncached breakdown)
        if profile.input_token_limit is not None:
            lines.append(f"Input: {profile.input_tokens_used:,} / {profile.input_token_limit:,}")
        else:
            lines.append(f"Input: {profile.input_tokens_used:,} / \u221e")
        lines.append(f"  Cached: {profile.cached_input_tokens_used:,}")
        lines.append(f"  Uncached: {profile.uncached_input_tokens_used:,}")

        # Output
        if profile.output_token_limit is not None:
            lines.append(f"Output: {profile.output_tokens_used:,} / {profile.output_token_limit:,}")
        else:
            lines.append(f"Output: {profile.output_tokens_used:,} / \u221e")

        return "\n".join(lines)

    def _most_restrictive_pct(self, profile: EndpointProfile) -> float | None:
        """Return the highest usage percentage across all configured limits."""
        pcts: list[float] = []
        if profile.token_limit is not None and profile.token_limit > 0:
            pcts.append(profile.tokens_used / profile.token_limit * 100)
        if profile.input_token_limit is not None and profile.input_token_limit > 0:
            pcts.append(profile.input_tokens_used / profile.input_token_limit * 100)
        if profile.output_token_limit is not None and profile.output_token_limit > 0:
            pcts.append(profile.output_tokens_used / profile.output_token_limit * 100)
        return max(pcts) if pcts else None

    def _pct_tooltip(self, profile: EndpointProfile) -> str:
        """Build tooltip showing percentage for each configured limit."""
        lines = []
        if profile.token_limit is not None and profile.token_limit > 0:
            pct = profile.tokens_used / profile.token_limit * 100
            lines.append(f"Total: {pct:.1f}%")
        if profile.input_token_limit is not None and profile.input_token_limit > 0:
            pct = profile.input_tokens_used / profile.input_token_limit * 100
            lines.append(f"Input: {pct:.1f}%")
        if profile.output_token_limit is not None and profile.output_token_limit > 0:
            pct = profile.output_tokens_used / profile.output_token_limit * 100
            lines.append(f"Output: {pct:.1f}%")
        return "\n".join(lines) if lines else ""

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Return data for display."""
        if not index.isValid() or not (0 <= index.row() < len(self._profiles)):
            return None

        profile = self._profiles[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_NAME:
                return profile.name
            elif col == COL_BASE_URL:
                return profile.base_url or ""
            elif col == COL_MODEL:
                return profile.model or ""
            elif col == COL_DEFAULT:
                return self.tr("Yes") if profile.is_default else self.tr("No")
            elif col == COL_TOKEN_USAGE:
                if profile.token_limit is not None:
                    return f"{profile.tokens_used:,} / {profile.token_limit:,}"
                return f"{profile.tokens_used:,} / \u221e"
            elif col == COL_USAGE_PCT:
                pct = self._most_restrictive_pct(profile)
                if pct is not None:
                    return f"{pct:.1f}%"
                return "N/A"

        elif role == Qt.ItemDataRole.ToolTipRole:
            if col == COL_TOKEN_USAGE:
                return self._usage_tooltip(profile)
            elif col == COL_USAGE_PCT:
                return self._pct_tooltip(profile)

        elif role == Qt.ItemDataRole.TextAlignmentRole and col in (COL_DEFAULT, COL_TOKEN_USAGE, COL_USAGE_PCT):
            # Center-align the "Default", "Token Usage", and "Usage %" columns
            return Qt.AlignmentFlag.AlignCenter

        return None

    def retranslate(self) -> None:
        """Notify views that header data needs re-translation."""
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, self.columnCount() - 1)

    def get_profile(self, row: int) -> EndpointProfile | None:
        """Get profile at row index."""
        if 0 <= row < len(self._profiles):
            return self._profiles[row]
        return None

    def get_profile_by_id(self, profile_id: str) -> EndpointProfile | None:
        """Get profile by ID using indexed lookup."""
        row = self._id_to_row.get(profile_id)
        if row is not None and 0 <= row < len(self._profiles):
            return self._profiles[row]
        return None
