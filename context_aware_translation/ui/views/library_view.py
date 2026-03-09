"""Main projects view for managing books/projects."""

from PySide6.QtCore import QEvent, QPoint, Qt, Signal, Slot
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
from context_aware_translation.ui.dialogs.book_dialog import BookDialog
from context_aware_translation.ui.i18n import qarg
from context_aware_translation.ui.models.book_model import BookTableModel
from context_aware_translation.ui.utils import create_tip_label


class LibraryView(QWidget):
    """Main projects view for managing books/projects."""

    # Signal emitted when a book should be opened (book_id, book_name)
    book_opened = Signal(str, str)

    def __init__(self, book_manager: BookManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.book_manager = book_manager
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        """Set up the view UI."""
        layout = QVBoxLayout(self)

        self.tip_label = create_tip_label(self._tip_text())
        layout.addWidget(self.tip_label)

        # Toolbar
        toolbar = self._create_toolbar()
        layout.addLayout(toolbar)

        # Table view
        self.table_view = QTableView()
        self.model = BookTableModel(self.book_manager)
        self.table_view.setModel(self.model)

        # Configure table
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSortingEnabled(True)
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # Resize columns
        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Name
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Target Language
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Progress
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Modified

        layout.addWidget(self.table_view)

    def _create_toolbar(self) -> QHBoxLayout:
        """Create toolbar with action buttons and filters."""
        toolbar = QHBoxLayout()

        # Action buttons
        self.new_button = QPushButton(self.tr("New Project"))
        self.open_button = QPushButton(self.tr("Open"))
        self.edit_button = QPushButton(self.tr("Edit"))
        self.delete_button = QPushButton(self.tr("Delete"))

        toolbar.addWidget(self.new_button)
        toolbar.addWidget(self.open_button)
        toolbar.addWidget(self.edit_button)
        toolbar.addWidget(self.delete_button)

        toolbar.addStretch()

        return toolbar

    def _connect_signals(self) -> None:
        """Connect signals to slots."""
        self.new_button.clicked.connect(self._on_new_book)
        self.open_button.clicked.connect(self._on_open_book)
        self.edit_button.clicked.connect(self._on_edit_book)
        self.delete_button.clicked.connect(self._on_delete_book)
        self.table_view.doubleClicked.connect(self._on_row_double_clicked)
        self.table_view.customContextMenuRequested.connect(self._show_context_menu)

    @Slot()
    def _on_new_book(self) -> None:
        """Handle new book button click."""
        dialog = BookDialog(self.book_manager, parent=self)
        if dialog.exec():
            self.model.refresh()

    @Slot()
    def _on_open_book(self) -> None:
        """Handle open book button click."""
        selection = self.table_view.selectionModel()
        if not selection.hasSelection():
            QMessageBox.information(self, self.tr("No Selection"), self.tr("Please select a project to open."))
            return

        row = selection.selectedRows()[0].row()
        book = self.model.get_book(row)
        if book:
            self.book_opened.emit(book.book_id, book.name)

    @Slot()
    def _on_edit_book(self) -> None:
        """Handle edit book button click."""
        selection = self.table_view.selectionModel()
        if not selection.hasSelection():
            QMessageBox.information(self, self.tr("No Selection"), self.tr("Please select a project to edit."))
            return

        row = selection.selectedRows()[0].row()
        book = self.model.get_book(row)
        if book:
            dialog = BookDialog(self.book_manager, book=book, parent=self)
            if dialog.exec():
                self.model.refresh()

    @Slot()
    def _on_delete_book(self) -> None:
        """Handle delete book button click."""
        selection = self.table_view.selectionModel()
        if not selection.hasSelection():
            QMessageBox.information(self, self.tr("No Selection"), self.tr("Please select a project to delete."))
            return

        row = selection.selectedRows()[0].row()
        book = self.model.get_book(row)
        if not book:
            return

        # Confirm deletion
        reply = QMessageBox.question(
            self,
            self.tr("Confirm Deletion"),
            qarg(
                self.tr(
                    "Are you sure you want to delete project '%1'?\n\n"
                    "This will permanently remove all project data including documents, "
                    "translations, and glossary entries."
                ),
                book.name,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            success = self.book_manager.delete_book(book.book_id, permanent=True)
            if success:
                self.model.refresh()
                QMessageBox.information(
                    self,
                    self.tr("Success"),
                    qarg(self.tr("Project '%1' has been deleted."), book.name),
                )
            else:
                QMessageBox.critical(self, self.tr("Error"), self.tr("Failed to delete project."))

    @Slot()
    def _on_row_double_clicked(self) -> None:
        """Handle row double-click to open book."""
        self._on_open_book()

    @Slot()
    def _show_context_menu(self, position: QPoint) -> None:
        """Show context menu on right-click."""
        index = self.table_view.indexAt(position)
        if not index.isValid():
            return

        self.table_view.selectRow(index.row())
        row = index.row()
        book = self.model.get_book(row)
        if not book:
            return

        menu = QMenu(self)
        open_action = menu.addAction(self.tr("Open"))
        edit_action = menu.addAction(self.tr("Edit"))
        menu.addSeparator()
        delete_action = menu.addAction(self.tr("Delete"))

        # Execute menu
        action = menu.exec(self.table_view.viewport().mapToGlobal(position))

        if action == open_action:
            self._on_open_book()
        elif action == edit_action:
            self._on_edit_book()
        elif action == delete_action:
            self._on_delete_book()

    def refresh(self) -> None:
        """Refresh the book list."""
        self.model.refresh()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.tip_label.setText(self._tip_text())
        self.new_button.setText(self.tr("New Project"))
        self.open_button.setText(self.tr("Open"))
        self.edit_button.setText(self.tr("Edit"))
        self.delete_button.setText(self.tr("Delete"))
        self.model.retranslate()

    def _tip_text(self) -> str:
        return self.tr("Create a project, finish setup, then open it to work through the document pipeline.")
