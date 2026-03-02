"""View for managing config profiles."""

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.config_profile import ConfigProfile
from context_aware_translation.ui.dialogs.config_profile_dialog import ConfigProfileDialog
from context_aware_translation.ui.i18n import qarg
from context_aware_translation.ui.models.profile_model import ConfigProfileModel


class ConfigProfileView(QWidget):
    """View for managing config profiles."""

    def __init__(self, book_manager: BookManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.book_manager = book_manager
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the UI."""
        layout = QVBoxLayout(self)

        # Toolbar
        toolbar_layout = QHBoxLayout()

        self.add_button = QPushButton(self.tr("Add"))
        self.add_button.clicked.connect(self._on_add)
        toolbar_layout.addWidget(self.add_button)

        self.edit_button = QPushButton(self.tr("Edit"))
        self.edit_button.clicked.connect(self._on_edit)
        toolbar_layout.addWidget(self.edit_button)

        self.delete_button = QPushButton(self.tr("Delete"))
        self.delete_button.clicked.connect(self._on_delete)
        toolbar_layout.addWidget(self.delete_button)

        self.duplicate_button = QPushButton(self.tr("Duplicate"))
        self.duplicate_button.clicked.connect(self._on_duplicate)
        toolbar_layout.addWidget(self.duplicate_button)

        self.set_default_button = QPushButton(self.tr("Set Default"))
        self.set_default_button.clicked.connect(self._on_set_default)
        toolbar_layout.addWidget(self.set_default_button)

        toolbar_layout.addStretch()
        layout.addLayout(toolbar_layout)

        # Table view
        self.table_view = QTableView()
        self.model = ConfigProfileModel(self.book_manager, self)
        self.table_view.setModel(self.model)

        # Configure table
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self._show_context_menu)
        self.table_view.doubleClicked.connect(self._on_edit)

        # Resize columns
        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Name
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Language
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Description
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Default

        layout.addWidget(self.table_view)

        # Update button states
        self.table_view.selectionModel().selectionChanged.connect(self._update_button_states)
        self._update_button_states()

    def _update_button_states(self) -> None:
        """Update button enabled states based on selection."""
        has_selection = len(self.table_view.selectionModel().selectedRows()) > 0
        self.edit_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)
        self.duplicate_button.setEnabled(has_selection)
        self.set_default_button.setEnabled(has_selection)

    def _get_selected_profile(self) -> ConfigProfile | None:
        """Get the currently selected profile."""
        selected_rows = self.table_view.selectionModel().selectedRows()
        if not selected_rows:
            return None
        row = selected_rows[0].row()
        return self.model.get_profile(row)

    def _on_add(self) -> None:
        """Handle add button click."""
        dialog = ConfigProfileDialog(self.book_manager, parent=self)
        if dialog.exec():
            self.refresh()

    def _on_edit(self) -> None:
        """Handle edit button click or double-click."""
        profile = self._get_selected_profile()
        if profile is None:
            return

        dialog = ConfigProfileDialog(self.book_manager, profile=profile, parent=self)
        if dialog.exec():
            self.refresh()

    def _on_delete(self) -> None:
        """Handle delete button click."""
        profile = self._get_selected_profile()
        if profile is None:
            return

        reply = QMessageBox.question(
            self,
            self.tr("Confirm Delete"),
            qarg(self.tr("Are you sure you want to delete the profile '%1'?"), profile.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            success = self.book_manager.delete_profile(profile.profile_id)
            if success:
                self.refresh()
            else:
                QMessageBox.warning(
                    self, self.tr("Delete Failed"), self.tr("Failed to delete profile. Please try again.")
                )

    def _on_duplicate(self) -> None:
        """Handle duplicate button click."""
        profile = self._get_selected_profile()
        if profile is None:
            return

        # Create a new profile with copied data
        new_name = qarg(self.tr("%1 (Copy)"), profile.name)
        try:
            self.book_manager.create_profile(
                name=new_name,
                config=profile.config.copy(),
                description=profile.description,
                is_default=False,
            )
            self.refresh()
        except Exception as e:
            QMessageBox.critical(self, self.tr("Duplicate Failed"), qarg(self.tr("Failed to duplicate profile: %1"), e))

    def _on_set_default(self) -> None:
        """Handle set default button click."""
        profile = self._get_selected_profile()
        if profile is None:
            return

        try:
            self.book_manager.set_default_profile(profile.profile_id)
            self.refresh()
        except Exception as e:
            QMessageBox.critical(
                self, self.tr("Set Default Failed"), qarg(self.tr("Failed to set default profile: %1"), e)
            )

    def _show_context_menu(self, position: QPoint) -> None:
        """Show context menu at position."""
        index = self.table_view.indexAt(position)
        if not index.isValid():
            return

        self.table_view.selectRow(index.row())
        menu = QMenu(self)
        edit_action = menu.addAction(self.tr("Edit"))
        duplicate_action = menu.addAction(self.tr("Duplicate"))
        set_default_action = menu.addAction(self.tr("Set Default"))
        menu.addSeparator()
        delete_action = menu.addAction(self.tr("Delete"))

        action = menu.exec(self.table_view.viewport().mapToGlobal(position))

        if action == edit_action:
            self._on_edit()
        elif action == duplicate_action:
            self._on_duplicate()
        elif action == set_default_action:
            self._on_set_default()
        elif action == delete_action:
            self._on_delete()

    def refresh(self) -> None:
        """Refresh the view."""
        self.model.refresh()
        self._update_button_states()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.add_button.setText(self.tr("Add"))
        self.edit_button.setText(self.tr("Edit"))
        self.delete_button.setText(self.tr("Delete"))
        self.duplicate_button.setText(self.tr("Duplicate"))
        self.set_default_button.setText(self.tr("Set Default"))
        self.model.retranslate()
