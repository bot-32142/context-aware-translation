"""Dialog for creating/editing config profiles."""

import sqlite3
from typing import Any

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.config_profile import ConfigProfile
from context_aware_translation.ui.i18n import qarg
from context_aware_translation.ui.widgets import CollapsibleSection, ConfigEditorWidget


class ConfigProfileDialog(QDialog):
    """Dialog for creating or editing a config profile."""

    def __init__(
        self,
        book_manager: BookManager,
        profile: ConfigProfile | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.book_manager = book_manager
        self.profile = profile
        self.is_edit_mode = profile is not None
        self._general_layout: QFormLayout | None = None
        self._general_section: CollapsibleSection | None = None

        self.setWindowTitle(self.tr("Edit Profile") if self.is_edit_mode else self.tr("New Profile"))
        self.setMinimumSize(650, 600)
        self.resize(750, 750)

        self._setup_ui()
        if self.is_edit_mode and profile:
            self.set_profile_data(profile)

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        main_layout = QVBoxLayout(self)

        # === General Section (name/description) ===
        self._general_section = CollapsibleSection(self.tr("General"))
        self._general_layout = QFormLayout()
        self._general_layout.setContentsMargins(16, 8, 8, 8)
        self._general_layout.setVerticalSpacing(8)
        self._general_layout.setHorizontalSpacing(12)
        general_widget = QWidget()
        general_widget.setLayout(self._general_layout)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(self.tr("Enter profile name"))
        self._general_layout.addRow(self.tr("Name*:"), self.name_edit)

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText(self.tr("Optional description"))
        self.description_edit.setMaximumHeight(60)
        self._general_layout.addRow(self.tr("Description:"), self.description_edit)

        self._general_section.set_content(general_widget)
        self._general_section.set_expanded(True)
        main_layout.addWidget(self._general_section)

        # === Config Editor Widget ===
        self.config_editor = ConfigEditorWidget(self.book_manager)
        main_layout.addWidget(self.config_editor)

        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self._on_save)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)
        self._apply_tooltips()

    def _set_field_tooltip(self, widget: QWidget, text: str) -> None:
        """Apply tooltip to a field and its label in the General section."""
        if self._general_layout is None:
            return
        widget.setToolTip(text)
        label = self._general_layout.labelForField(widget)
        if label:
            label.setToolTip(text)

    def _apply_tooltips(self) -> None:
        """Apply hover explanations for profile-level options."""
        self._set_field_tooltip(self.name_edit, self.tr("Profile name shown when selecting config profiles."))
        self._set_field_tooltip(self.description_edit, self.tr("Optional notes describing this config profile."))

    def _on_save(self) -> None:
        """Handle save button click."""
        try:
            profile_data = self.get_profile_data()

            # Validate required fields
            if not profile_data["name"].strip():
                QMessageBox.warning(self, self.tr("Validation Error"), self.tr("Profile name is required."))
                return

            validation_error = self.config_editor.validate()
            if validation_error:
                QMessageBox.warning(self, self.tr("Validation Error"), validation_error)
                return

            # Save to database
            if self.is_edit_mode and self.profile:
                result = self.book_manager.update_profile(self.profile.profile_id, **profile_data)
                if result is None:
                    QMessageBox.critical(
                        self, self.tr("Error"), self.tr("Failed to update profile. Profile not found.")
                    )
                    return
            else:
                try:
                    self.book_manager.create_profile(**profile_data)
                except sqlite3.IntegrityError:
                    QMessageBox.warning(
                        self,
                        self.tr("Duplicate Profile"),
                        qarg(self.tr("A profile with the name '%1' already exists."), profile_data["name"]),
                    )
                    return

            self.accept()

        except Exception as e:
            QMessageBox.critical(self, self.tr("Error"), qarg(self.tr("Failed to save profile: %1"), e))

    def get_profile_data(self) -> dict[str, Any]:
        """Get profile data from form fields."""
        return {
            "name": self.name_edit.text().strip(),
            "config": self.config_editor.get_config(),
            "description": self.description_edit.toPlainText().strip() or None,
        }

    def set_profile_data(self, profile: ConfigProfile) -> None:
        """Populate form fields from profile."""
        self.name_edit.setText(profile.name)

        if profile.description:
            self.description_edit.setPlainText(profile.description)

        self.config_editor.set_config(profile.config)

    def changeEvent(self, event: QEvent) -> None:
        """Handle change events."""
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        """Retranslate UI strings."""
        self.setWindowTitle(self.tr("Edit Profile") if self.is_edit_mode else self.tr("New Profile"))

        if self._general_section:
            self._general_section.toggle_button.setText(self.tr("General"))

        if self._general_layout:
            label = self._general_layout.labelForField(self.name_edit)
            if label:
                label.setText(self.tr("Name*:"))

            label = self._general_layout.labelForField(self.description_edit)
            if label:
                label.setText(self.tr("Description:"))

        self.name_edit.setPlaceholderText(self.tr("Enter profile name"))
        self.description_edit.setPlaceholderText(self.tr("Optional description"))
        self._apply_tooltips()
