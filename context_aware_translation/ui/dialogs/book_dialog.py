"""Dialog for creating/editing books."""

import sqlite3

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.storage.book import Book
from context_aware_translation.storage.book_manager import BookManager

from ..i18n import qarg
from ..widgets import ConfigEditorWidget

# Dialog size constants
DIALOG_WIDTH_NORMAL = 650
DIALOG_HEIGHT_NORMAL = 400
DIALOG_WIDTH_EXPANDED = 750
DIALOG_HEIGHT_EXPANDED = 700


class BookDialog(QDialog):
    """Dialog for creating or editing a book."""

    def __init__(
        self,
        book_manager: BookManager,
        book: Book | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.book_manager = book_manager
        self.book = book
        self.is_edit_mode = book is not None
        self._has_existing_custom_config = False
        self._form_layout: QFormLayout | None = None

        self.setWindowTitle(self.tr("Edit Book") if self.is_edit_mode else self.tr("New Book"))
        self.setMinimumWidth(DIALOG_WIDTH_NORMAL)
        self.setMinimumHeight(DIALOG_HEIGHT_NORMAL)

        self._setup_ui()
        if self.is_edit_mode and book:
            config = self.book_manager.get_book_config(book.book_id)
            self._has_existing_custom_config = book.profile_id is None
            self.set_book_data(book, config)

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Form layout
        self._form_layout = QFormLayout()

        # Name field
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(self.tr("Enter book name"))
        self._form_layout.addRow(self.tr("Name*:"), self.name_edit)

        # Description field
        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText(self.tr("Optional description"))
        self.description_edit.setMaximumHeight(80)
        self._form_layout.addRow(self.tr("Description:"), self.description_edit)

        # Profile selection
        self.profile_combo = QComboBox()
        self._populate_profiles()
        self._form_layout.addRow(self.tr("Profile*:"), self.profile_combo)

        # Custom config option
        self.custom_config_checkbox = QCheckBox(self.tr("Use custom configuration"))
        self.custom_config_checkbox.setToolTip(self.tr("Override profile settings with book-specific configuration"))
        self.custom_config_checkbox.stateChanged.connect(self._on_custom_config_toggled)
        self._form_layout.addRow("", self.custom_config_checkbox)

        layout.addLayout(self._form_layout)

        # Config editor widget (hidden by default)
        self.config_editor = ConfigEditorWidget(self.book_manager)
        self.config_editor.hide()
        layout.addWidget(self.config_editor)

        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self._on_save)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _populate_profiles(self) -> None:
        """Populate profile dropdown with available profiles."""
        profiles = self.book_manager.list_profiles()

        if not profiles:
            self.profile_combo.addItem(self.tr("No profiles available"), None)
            self.profile_combo.setEnabled(False)
            return

        for profile in profiles:
            display_text = profile.name
            if profile.is_default:
                display_text += " " + self.tr("(Default)")
            self.profile_combo.addItem(display_text, profile.profile_id)

        # Select default profile if exists and not in edit mode
        if not self.is_edit_mode:
            default_profile = self.book_manager.get_default_profile()
            if default_profile:
                for i in range(self.profile_combo.count()):
                    if self.profile_combo.itemData(i) == default_profile.profile_id:
                        self.profile_combo.setCurrentIndex(i)
                        break

    def _on_custom_config_toggled(self, state: int) -> None:
        """Handle custom config checkbox toggle."""
        is_checked = state == Qt.CheckState.Checked.value

        if is_checked:
            # Disable profile dropdown and show config editor
            self.profile_combo.setEnabled(False)
            self.config_editor.show()

            # Pre-populate from current profile if not editing existing custom config
            if not self._has_existing_custom_config:
                profile_id = self.profile_combo.currentData()
                if profile_id:
                    profile = self.book_manager.get_profile(profile_id)
                    if profile:
                        self.config_editor.set_config(profile.config)

            # Resize dialog to accommodate config editor
            self.resize(DIALOG_WIDTH_EXPANDED, DIALOG_HEIGHT_EXPANDED)
        else:
            # Enable profile dropdown and hide config editor
            self.profile_combo.setEnabled(True)
            self.config_editor.hide()

            # Resize dialog back to smaller size
            self.resize(DIALOG_WIDTH_NORMAL, DIALOG_HEIGHT_NORMAL)

    def _handle_integrity_error(self, _e: sqlite3.IntegrityError) -> None:
        """Handle IntegrityError by showing a duplicate book warning."""
        name = self.name_edit.text().strip()
        QMessageBox.warning(
            self,
            self.tr("Duplicate Book"),
            qarg(self.tr("A book with the name '%1' already exists."), name),
        )

    def _on_save(self) -> None:
        """Handle save button click."""
        try:
            # Validate name
            name = self.name_edit.text().strip()
            if not name:
                QMessageBox.warning(self, self.tr("Validation Error"), self.tr("Book name is required."))
                return

            description = self.description_edit.toPlainText().strip() or None

            if self.custom_config_checkbox.isChecked():
                # Custom config mode
                validation_error = self.config_editor.validate()
                if validation_error:
                    QMessageBox.warning(self, self.tr("Validation Error"), validation_error)
                    return

                config = self.config_editor.get_config()

                if self.is_edit_mode and self.book:
                    # Update book metadata
                    result = self.book_manager.update_book(
                        self.book.book_id,
                        name=name,
                        description=description,
                    )
                    if result is None:
                        QMessageBox.critical(self, self.tr("Error"), self.tr("Failed to update book. Book not found."))
                        return
                    # Set custom config (this also clears profile_id)
                    self.book_manager.set_book_custom_config(self.book.book_id, config)
                else:
                    # Create new book with custom config
                    try:
                        self.book_manager.create_book(
                            name=name,
                            description=description,
                            custom_config=config,
                        )
                    except sqlite3.IntegrityError as e:
                        self._handle_integrity_error(e)
                        return
            else:
                # Profile mode
                profile_id = self.profile_combo.currentData()
                if not profile_id:
                    QMessageBox.warning(
                        self,
                        self.tr("Validation Error"),
                        self.tr("Please select a profile or create one first."),
                    )
                    return

                if self.is_edit_mode and self.book:
                    result = self.book_manager.update_book(
                        self.book.book_id,
                        name=name,
                        description=description,
                        profile_id=profile_id,
                    )
                    if result is None:
                        QMessageBox.critical(self, self.tr("Error"), self.tr("Failed to update book. Book not found."))
                        return
                else:
                    try:
                        self.book_manager.create_book(
                            name=name,
                            description=description,
                            profile_id=profile_id,
                        )
                    except sqlite3.IntegrityError as e:
                        self._handle_integrity_error(e)
                        return

            self.accept()

        except Exception as e:
            QMessageBox.critical(self, self.tr("Error"), qarg(self.tr("Failed to save book: %1"), e))

    def set_book_data(self, book: Book, config: dict | None) -> None:
        """Populate form fields from book."""
        self.name_edit.setText(book.name)

        if book.description:
            self.description_edit.setPlainText(book.description)

        # Select the book's profile
        if book.profile_id:
            for i in range(self.profile_combo.count()):
                if self.profile_combo.itemData(i) == book.profile_id:
                    self.profile_combo.setCurrentIndex(i)
                    break
        else:
            # Book has custom config
            self.custom_config_checkbox.setChecked(True)
            if config:
                self.config_editor.set_config(config)

    def changeEvent(self, event: QEvent) -> None:
        """Handle change events."""
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        """Retranslate UI strings."""
        self.setWindowTitle(self.tr("Edit Book") if self.is_edit_mode else self.tr("New Book"))

        if self._form_layout:
            label = self._form_layout.labelForField(self.name_edit)
            if label:
                label.setText(self.tr("Name*:"))

            label = self._form_layout.labelForField(self.description_edit)
            if label:
                label.setText(self.tr("Description:"))

            label = self._form_layout.labelForField(self.profile_combo)
            if label:
                label.setText(self.tr("Profile*:"))

        self.name_edit.setPlaceholderText(self.tr("Enter book name"))
        self.description_edit.setPlaceholderText(self.tr("Optional description"))
        self.custom_config_checkbox.setText(self.tr("Use custom configuration"))
        self.custom_config_checkbox.setToolTip(self.tr("Override profile settings with book-specific configuration"))
