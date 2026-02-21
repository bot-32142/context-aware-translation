"""Qt models for profile management."""

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import QWidget

from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.config_profile import ConfigProfile

# Column indices
COL_NAME = 0
COL_TARGET_LANGUAGE = 1
COL_DESCRIPTION = 2
COL_DEFAULT = 3


class ConfigProfileModel(QAbstractTableModel):
    """Table model for config profiles."""

    def __init__(self, book_manager: BookManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.book_manager = book_manager
        self._profiles: list[ConfigProfile] = []
        self._id_to_row: dict[str, int] = {}
        self.refresh()

    def refresh(self) -> None:
        """Reload profiles from database."""
        self.beginResetModel()
        self._profiles = self.book_manager.list_profiles()
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
            elif section == COL_DESCRIPTION:
                return self.tr("Description")
            elif section == COL_DEFAULT:
                return self.tr("Default")
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Return data for display."""
        if not index.isValid() or not (0 <= index.row() < len(self._profiles)):
            return None

        profile = self._profiles[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_NAME:
                return profile.name
            elif col == COL_TARGET_LANGUAGE:
                return profile.config.get("translation_target_language", "")
            elif col == COL_DESCRIPTION:
                return profile.description or ""
            elif col == COL_DEFAULT:
                return self.tr("Yes") if profile.is_default else self.tr("No")

        elif role == Qt.ItemDataRole.TextAlignmentRole and col == COL_DEFAULT:
            # Center-align the "Default" column
            return Qt.AlignmentFlag.AlignCenter

        return None

    def retranslate(self) -> None:
        """Notify views that header data needs re-translation."""
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, self.columnCount() - 1)

    def get_profile(self, row: int) -> ConfigProfile | None:
        """Get profile at row index."""
        if 0 <= row < len(self._profiles):
            return self._profiles[row]
        return None

    def get_profile_by_id(self, profile_id: str) -> ConfigProfile | None:
        """Get profile by ID using indexed lookup."""
        row = self._id_to_row.get(profile_id)
        if row is not None and 0 <= row < len(self._profiles):
            return self._profiles[row]
        return None
