"""View for managing endpoint profiles."""

import sqlite3

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
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
from context_aware_translation.storage.endpoint_profile import EndpointProfile

from ..dialogs.endpoint_profile_dialog import EndpointProfileDialog
from ..i18n import qarg
from ..models.endpoint_profile_model import EndpointProfileModel


class EndpointProfileView(QWidget):
    """View for managing endpoint profiles."""

    _TOKEN_REFRESH_INTERVAL_MS = 5000

    def __init__(self, book_manager: BookManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.book_manager = book_manager
        self._setup_ui()

        # Periodic timer for live token-usage updates
        self._token_timer = QTimer(self)
        self._token_timer.setInterval(self._TOKEN_REFRESH_INTERVAL_MS)
        self._token_timer.timeout.connect(self._on_token_timer)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Toolbar
        toolbar = QHBoxLayout()

        self.add_btn = QPushButton(self.tr("Add"))
        self.add_btn.clicked.connect(self._on_add)
        toolbar.addWidget(self.add_btn)

        self.edit_btn = QPushButton(self.tr("Edit"))
        self.edit_btn.clicked.connect(self._on_edit)
        toolbar.addWidget(self.edit_btn)

        self.delete_btn = QPushButton(self.tr("Delete"))
        self.delete_btn.clicked.connect(self._on_delete)
        toolbar.addWidget(self.delete_btn)

        self.duplicate_btn = QPushButton(self.tr("Duplicate"))
        self.duplicate_btn.clicked.connect(self._on_duplicate)
        toolbar.addWidget(self.duplicate_btn)

        self.default_btn = QPushButton(self.tr("Set Default"))
        self.default_btn.clicked.connect(self._on_set_default)
        toolbar.addWidget(self.default_btn)

        self.reset_btn = QPushButton(self.tr("Reset Usage"))
        self.reset_btn.clicked.connect(self._on_reset_usage)
        toolbar.addWidget(self.reset_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Table
        self.model = EndpointProfileModel(self.book_manager)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.doubleClicked.connect(self._on_edit)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Name
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Base URL
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Model
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Default
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Token Usage
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Usage %

        layout.addWidget(self.table)

        # Update button states
        self.table.selectionModel().selectionChanged.connect(self._update_button_states)
        self._update_button_states()

    def _update_button_states(self) -> None:
        """Update button enabled states based on selection."""
        has_selection = len(self.table.selectionModel().selectedRows()) > 0
        self.edit_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)
        self.duplicate_btn.setEnabled(has_selection)
        self.default_btn.setEnabled(has_selection)
        self.reset_btn.setEnabled(has_selection)

    def _restore_selection(self, profile_id: str | None) -> None:
        """Restore row selection for a profile ID after model refresh."""
        if not profile_id:
            return
        for row in range(self.model.rowCount()):
            profile = self.model.get_profile(row)
            if profile is not None and profile.profile_id == profile_id:
                index = self.model.index(row, 0)
                self.table.setCurrentIndex(index)
                self.table.selectRow(row)
                return

    def refresh(self, selected_profile_id: str | None = None) -> None:
        if selected_profile_id is None:
            selected = self._get_selected_profile()
            selected_profile_id = selected.profile_id if selected else None
        self.model.refresh()
        self._restore_selection(selected_profile_id)
        self._update_button_states()

    def _get_selected_profile(self) -> EndpointProfile | None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            current_index = self.table.currentIndex()
            if current_index.isValid():
                return self.model.get_profile(current_index.row())
            return None
        return self.model.get_profile(indexes[0].row())

    def _on_add(self) -> None:
        dialog = EndpointProfileDialog(self.book_manager, parent=self)
        if dialog.exec():
            self.refresh()

    def _on_edit(self) -> None:
        profile = self._get_selected_profile()
        if profile is None:
            return
        dialog = EndpointProfileDialog(self.book_manager, profile=profile, parent=self)
        if dialog.exec():
            self.refresh()

    def _on_delete(self) -> None:
        profile = self._get_selected_profile()
        if profile is None:
            return
        reply = QMessageBox.question(
            self,
            self.tr("Confirm Delete"),
            qarg(self.tr("Delete endpoint profile '%1'?"), profile.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.book_manager.delete_endpoint_profile(profile.profile_id)
                self.refresh()
            except ValueError as e:
                QMessageBox.warning(self, self.tr("Error"), qarg(self.tr("Failed to delete profile: %1"), e))

    def _on_duplicate(self) -> None:
        profile = self._get_selected_profile()
        if profile is None:
            return
        existing_names = {p.name for p in self.book_manager.list_endpoint_profiles()}
        duplicate_name = qarg(self.tr("%1 (Copy)"), profile.name)
        if duplicate_name in existing_names:
            suffix = 2
            while f"{duplicate_name} {suffix}" in existing_names:
                suffix += 1
            duplicate_name = f"{duplicate_name} {suffix}"

        try:
            duplicated = self.book_manager.create_endpoint_profile(
                name=duplicate_name,
                description=profile.description,
                api_key=profile.api_key,
                base_url=profile.base_url,
                model=profile.model,
                temperature=profile.temperature,
                kwargs=profile.kwargs,
                timeout=profile.timeout,
                max_retries=profile.max_retries,
                concurrency=profile.concurrency,
                token_limit=profile.token_limit,
                input_token_limit=profile.input_token_limit,
                output_token_limit=profile.output_token_limit,
            )
            self.refresh(selected_profile_id=duplicated.profile_id)
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, self.tr("Error"), self.tr("A profile with this name already exists."))

    def _on_set_default(self) -> None:
        profile = self._get_selected_profile()
        if profile is None:
            return
        self.book_manager.set_default_endpoint_profile(profile.profile_id)
        self.refresh()

    def _on_reset_usage(self) -> None:
        profile = self._get_selected_profile()
        if profile is None:
            return
        reply = QMessageBox.question(
            self,
            self.tr("Confirm Reset"),
            qarg(self.tr("Reset token usage counter for '%1' to 0?"), profile.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.book_manager.reset_endpoint_tokens(profile.profile_id)
            # Clear tracker warning if active
            from context_aware_translation.llm.token_tracker import TokenTracker

            tracker = TokenTracker.get()
            if tracker is not None:
                tracker.clear_warning(profile.name)
            self.refresh()

    def _show_context_menu(self, pos: QPoint) -> None:
        index = self.table.indexAt(pos)
        row = index.row() if index.isValid() else self.table.rowAt(pos.y())
        if row < 0:
            # Be lenient when callers pass table-relative coordinates instead of viewport-relative ones.
            viewport_pos = self.table.viewport().mapFrom(self.table, pos)
            row = self.table.rowAt(viewport_pos.y())
        if row < 0:
            return

        model = self.table.model()
        if model is not None:
            current = model.index(row, 0)
            if current.isValid():
                self.table.setCurrentIndex(current)
        self.table.selectRow(row)
        menu = QMenu(self)
        menu.addAction(self.tr("Add"), self._on_add)
        menu.addAction(self.tr("Edit"), self._on_edit)
        menu.addAction(self.tr("Duplicate"), self._on_duplicate)
        menu.addSeparator()
        menu.addAction(self.tr("Set Default"), self._on_set_default)
        menu.addAction(self.tr("Reset Usage"), self._on_reset_usage)
        menu.addSeparator()
        menu.addAction(self.tr("Delete"), self._on_delete)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _on_token_timer(self) -> None:
        """Refresh token usage columns if the view is visible."""
        if self.isVisible():
            self.refresh()

    def showEvent(self, event: QEvent) -> None:
        super().showEvent(event)
        self.model.refresh()
        self._token_timer.start()

    def hideEvent(self, event: QEvent) -> None:
        self._token_timer.stop()
        super().hideEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.add_btn.setText(self.tr("Add"))
        self.edit_btn.setText(self.tr("Edit"))
        self.delete_btn.setText(self.tr("Delete"))
        self.duplicate_btn.setText(self.tr("Duplicate"))
        self.default_btn.setText(self.tr("Set Default"))
        self.reset_btn.setText(self.tr("Reset Usage"))
        self.model.retranslate()
