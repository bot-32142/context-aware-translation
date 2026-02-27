"""Main application window with sidebar navigation."""

import logging

from PySide6.QtCore import QEvent, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QWidget,
)

from context_aware_translation.llm.token_tracker import TokenTracker
from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.task_store import TaskStore
from context_aware_translation.ui.tasks.qt_task_engine import TaskEngine
from context_aware_translation.workflow.session import WorkflowSession
from context_aware_translation.workflow.tasks.handlers.batch_translation import BatchTranslationHandler
from context_aware_translation.workflow.tasks.handlers.chunk_retranslation import ChunkRetranslationHandler
from context_aware_translation.workflow.tasks.handlers.glossary_export import GlossaryExportHandler
from context_aware_translation.workflow.tasks.handlers.glossary_extraction import GlossaryExtractionHandler
from context_aware_translation.workflow.tasks.handlers.glossary_review import GlossaryReviewHandler
from context_aware_translation.workflow.tasks.handlers.glossary_translation import GlossaryTranslationHandler
from context_aware_translation.workflow.tasks.handlers.ocr import OCRHandler
from context_aware_translation.workflow.tasks.handlers.translation_manga import TranslationMangaHandler
from context_aware_translation.workflow.tasks.handlers.translation_text import TranslationTextHandler
from context_aware_translation.workflow.tasks.worker_deps import WorkerDeps

from . import i18n
from .constants import (
    APP_VERSION,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    SIDEBAR_WIDTH,
)
from .i18n import qarg
from .sleep_inhibitor import SleepInhibitor
from .views import BookWorkspace, LibraryView, ProfileView

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window with sidebar navigation."""

    def __init__(self) -> None:
        """Initialize the main window."""
        super().__init__()
        self.setWindowTitle(self.tr("Context-Aware Translation"))
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)

        # View registry: name -> widget reference
        self._view_registry: dict[str, QWidget] = {}

        # Current book state
        self._current_book_id: str | None = None
        self._current_book_name: str | None = None
        self._book_nav_item: QListWidgetItem | None = None
        self._is_closing = False

        # Navigation items (store for retranslation)
        self._library_nav_item: QListWidgetItem | None = None
        self._profiles_nav_item: QListWidgetItem | None = None
        self._sleep_inhibitor = SleepInhibitor()

        # Initialize book manager
        self.book_manager = BookManager()
        self.book_manager.seed_system_defaults()

        # Initialize TokenTracker
        TokenTracker.initialize(self.book_manager.registry)

        # Initialize centralized TaskEngine
        self._task_store = TaskStore(self.book_manager.library_root / "task_store.db")
        self._worker_deps = WorkerDeps(
            book_manager=self.book_manager,
            task_store=self._task_store,
            create_workflow_session=lambda book_id: WorkflowSession.from_book(self.book_manager, book_id),
            notify_task_changed=self._enqueue_task_changed,
        )
        self._task_engine = TaskEngine(store=self._task_store, deps=self._worker_deps, parent=self)
        self._task_engine.register_handler(BatchTranslationHandler())
        self._task_engine.register_handler(GlossaryExtractionHandler())
        self._task_engine.register_handler(GlossaryReviewHandler())
        self._task_engine.register_handler(GlossaryTranslationHandler())
        self._task_engine.register_handler(ChunkRetranslationHandler())
        self._task_engine.register_handler(GlossaryExportHandler())
        self._task_engine.register_handler(TranslationTextHandler())
        self._task_engine.register_handler(TranslationMangaHandler())
        self._task_engine.register_handler(OCRHandler())
        self._task_engine.running_work_changed.connect(self._on_engine_running_work_changed)

        self._sleep_check_timer = QTimer(self)
        self._sleep_check_timer.timeout.connect(self._update_sleep_inhibitor)
        self._sleep_check_timer.start(5000)

        # Initialize UI components (status bar first to avoid errors during nav init)
        self._init_status_bar()
        self._init_ui()
        self._init_menu_bar()

        # Restore window geometry
        self._restore_geometry()
        self._task_engine.start_autorun()

    def _init_ui(self) -> None:
        """Initialize the main UI layout."""
        # Central widget with horizontal layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar navigation
        self._nav_list = QListWidget()
        self._nav_list.setFixedWidth(SIDEBAR_WIDTH)
        self._nav_list.setStyleSheet(
            """
            QListWidget {
                background-color: #f5f5f5;
                color: #333333;
                border: none;
                border-right: 1px solid #e0e0e0;
            }
            QListWidget::item {
                padding: 12px;
                border-bottom: 1px solid #e0e0e0;
                color: #333333;
            }
            QListWidget::item:hover {
                background-color: #e8e8e8;
                color: #333333;
            }
            QListWidget::item:selected {
                background-color: #3b82f6;
                color: white;
            }
        """
        )
        self._nav_list.currentItemChanged.connect(self._on_nav_changed)

        # Add default navigation items
        self._library_nav_item = QListWidgetItem(self.tr("Library"))
        self._library_nav_item.setData(Qt.ItemDataRole.UserRole, "library")
        self._nav_list.addItem(self._library_nav_item)

        self._profiles_nav_item = QListWidgetItem(self.tr("Profiles"))
        self._profiles_nav_item.setData(Qt.ItemDataRole.UserRole, "profiles")
        self._nav_list.addItem(self._profiles_nav_item)

        # Select Library by default
        self._nav_list.setCurrentRow(0)

        # Stacked widget for views
        self._stack = QStackedWidget()

        # Create and register views
        self.library_view = LibraryView(self.book_manager)
        self.library_view.book_opened.connect(self._on_book_opened)
        self.register_view("library", self.library_view)

        self.profile_view = ProfileView(self.book_manager)
        self.register_view("profiles", self.profile_view)

        # Add to main layout
        main_layout.addWidget(self._nav_list)
        main_layout.addWidget(self._stack, 1)

    def _init_menu_bar(self) -> None:
        """Initialize the menu bar."""
        menubar = self.menuBar()
        menubar.setNativeMenuBar(False)

        # File menu
        self._file_menu = menubar.addMenu(self.tr("&File"))

        self._open_data_action = QAction(self.tr("Open &Data Folder"), self)
        self._open_data_action.triggered.connect(self._on_open_data_folder)
        self._file_menu.addAction(self._open_data_action)

        # Language menu
        self._language_menu = menubar.addMenu(self.tr("&Language"))
        self._language_group = QActionGroup(self)
        self._language_group.setExclusive(True)

        for locale_code, display_name in i18n.SUPPORTED_LANGUAGES.items():
            action = QAction(display_name, self)  # Display names NOT translated (shown in native script)
            action.setCheckable(True)
            action.setData(locale_code)
            if locale_code == i18n.get_current_language():
                action.setChecked(True)
            self._language_group.addAction(action)
            self._language_menu.addAction(action)

        self._language_group.triggered.connect(self._on_language_changed)

        # Help menu
        self._help_menu = menubar.addMenu(self.tr("&Help"))

        self._about_action = QAction(self.tr("&About"), self)
        self._about_action.triggered.connect(self._on_about)
        self._help_menu.addAction(self._about_action)

    def _init_status_bar(self) -> None:
        """Initialize the status bar."""
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self.show_status(self.tr("Ready"))

    def _restore_geometry(self) -> None:
        """Restore window geometry from settings."""
        settings = QSettings("CAT", "Context-Aware Translation")
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)

    def _save_geometry(self) -> None:
        """Save window geometry to settings."""
        settings = QSettings("CAT", "Context-Aware Translation")
        settings.setValue("geometry", self.saveGeometry())

    def _enqueue_task_changed(self, book_id: str) -> None:
        """Thread-safe relay: emit engine signal from any thread."""
        self._task_engine.enqueue_task_changed.emit(book_id)

    def _on_engine_running_work_changed(self, is_running: bool) -> None:
        """React to TaskEngine running-work state changes."""
        self._update_sleep_inhibitor()

    def _update_sleep_inhibitor(self) -> None:
        """Acquire or release sleep inhibition based on whether any work is active."""
        if getattr(self, "_is_closing", False):
            self._sleep_inhibitor.release()
            return

        if self._task_engine.has_running_work():
            self._sleep_inhibitor.acquire()
            return

        for view_name, widget in self._view_registry.items():
            if not view_name.startswith("book_"):
                continue

            if hasattr(widget, "get_running_operations"):
                ops = widget.get_running_operations()
                if isinstance(ops, list) and ops:
                    self._sleep_inhibitor.acquire()
                    return
        self._sleep_inhibitor.release()

    def _get_book_running_operations(self) -> list[str]:
        """Return running operations in the current book workspace."""
        if getattr(self, "_is_closing", False):
            return []

        if self._current_book_id is None:
            return []
        view_name = f"book_{self._current_book_id}"
        workspace = self._view_registry.get(view_name)
        if workspace is None:
            return []
        if hasattr(workspace, "get_running_operations"):
            running = workspace.get_running_operations()
            if isinstance(running, list):
                return running
        # Backward compatibility with older workspace instances.
        if hasattr(workspace, "is_translation_running") and workspace.is_translation_running():
            return [self.tr("Translation")]
        return []

    def _warn_running_operations(self, operations: list[str] | None = None) -> bool:
        """Show a warning if operations are running. Returns True if user wants to proceed."""
        running_operations = operations if operations is not None else self._get_book_running_operations()
        if not running_operations:
            return True
        operations_text = ", ".join(running_operations)
        result = QMessageBox.warning(
            self,
            self.tr("Operation in Progress"),
            qarg(
                self.tr(
                    "The following operations are currently running: %1.\n\n"
                    "Leaving the book may stop local non-task processing.\n\n"
                    "Engine-managed tasks continue in background and can be resumed later.\n\n"
                    "All completed results are already saved and won't be lost."
                ),
                operations_text,
            ),
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return result == QMessageBox.StandardButton.Ok

    def _on_nav_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        """Handle navigation item change."""
        if getattr(self, "_is_closing", False):
            return

        if current is None:
            return

        view_name = current.data(Qt.ItemDataRole.UserRole)
        if not view_name or not isinstance(view_name, str):
            return

        # If navigating away from a book, warn about running operations
        is_navigating_away_from_book = (
            self._current_book_id is not None and view_name != f"book_{self._current_book_id}"
        )
        running_operations = self._get_book_running_operations()
        if is_navigating_away_from_book and running_operations:
            if not self._warn_running_operations(running_operations):
                # Revert sidebar selection back to book
                self._nav_list.blockSignals(True)
                self._nav_list.setCurrentItem(self._book_nav_item)
                self._nav_list.blockSignals(False)
                return
            # User confirmed — request cancellation in-place and navigate.
            # Avoid synchronous close/cleanup here because cleanup waits on
            # workers and can block the UI thread while cancellation propagates.
            if self._current_book_id is not None:
                view_name_current = f"book_{self._current_book_id}"
                workspace = self._view_registry.get(view_name_current)
                if workspace is not None and hasattr(workspace, "request_cancel_running_operations"):
                    workspace.request_cancel_running_operations(include_engine_tasks=False)

        self.switch_view(view_name)

    def _on_open_data_folder(self) -> None:
        """Open the data folder in the system file manager."""
        from PySide6.QtCore import QUrl

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.book_manager.library_root)))

    def _on_about(self) -> None:
        """Handle about action."""
        QMessageBox.about(
            self,
            self.tr("About Context-Aware Translation"),
            qarg(
                self.tr(
                    "<h3>Context-Aware Translation</h3>"
                    "<p>Version %1</p>"
                    "<p>A desktop application for context-aware document translation "
                    "with glossary management and OCR support.</p>"
                    "<p>Built with PySide6 (Qt for Python)</p>"
                ),
                APP_VERSION,
            ),
        )

    def _on_language_changed(self, action: QAction) -> None:
        """Handle language change."""
        locale_code = action.data()
        app = QApplication.instance()
        if app is not None and isinstance(app, QApplication):
            i18n.load_translation(app, locale_code)
            i18n.save_language(locale_code)

    def _on_book_opened(self, book_id: str, book_name: str) -> None:
        """Handle book opened signal from LibraryView."""
        self.open_book(book_id, book_name)

    def register_view(self, name: str, widget: QWidget) -> None:
        """
        Register a view widget with the stacked widget.

        Args:
            name: Unique identifier for the view
            widget: The widget to register
        """
        self._stack.addWidget(widget)
        self._view_registry[name] = widget

    def switch_view(self, view_name: str) -> None:
        """
        Switch to a registered view.

        Args:
            view_name: The name of the view to switch to
        """
        if view_name not in self._view_registry:
            self.show_status(qarg(self.tr("View '%1' not found"), view_name), 3000)
            return

        widget = self._view_registry[view_name]
        self._stack.setCurrentWidget(widget)

    def open_book(self, book_id: str, book_name: str) -> None:
        """
        Open a book workspace and add it to navigation.

        Args:
            book_id: Unique identifier for the book
            book_name: Display name of the book
        """
        # Close any existing book first
        self.close_book()

        # Store current book state
        self._current_book_id = book_id
        self._current_book_name = book_name

        # Create and add book navigation item
        book_item = QListWidgetItem(qarg(self.tr("Book: %1"), book_name))
        book_item.setData(Qt.ItemDataRole.UserRole, f"book_{book_id}")
        self._nav_list.addItem(book_item)
        self._book_nav_item = book_item

        # Create book workspace
        workspace = BookWorkspace(self.book_manager, book_id, book_name, task_engine=self._task_engine)
        workspace.close_requested.connect(self.close_book)
        self.register_view(f"book_{book_id}", workspace)

        # Switch to book view
        self._nav_list.setCurrentItem(book_item)
        self.show_status(qarg(self.tr("Opened book: %1"), book_name))

    def close_book(self) -> None:
        """Close the current book workspace and remove it from navigation."""
        if self._current_book_id is None:
            return

        # Remove book navigation item
        if self._book_nav_item is not None:
            row = self._nav_list.row(self._book_nav_item)
            self._nav_list.takeItem(row)
            self._book_nav_item = None

        # Remove book view from registry
        view_name = f"book_{self._current_book_id}"
        if view_name in self._view_registry:
            widget = self._view_registry[view_name]
            if widget is not None:
                if hasattr(widget, "cleanup"):
                    widget.cleanup()
                self._stack.removeWidget(widget)
                widget.deleteLater()
            del self._view_registry[view_name]

        # Switch back to library view
        self._nav_list.setCurrentRow(0)

        # Clear current book state
        book_name = self._current_book_name
        self._current_book_id = None
        self._current_book_name = None

        if book_name:
            self.show_status(qarg(self.tr("Closed book: %1"), book_name))

    def show_status(self, message: str, timeout_ms: int = 5000) -> None:
        """
        Show a status message in the status bar.

        Args:
            message: The message to display
            timeout_ms: How long to show the message in milliseconds (0 = permanent)
        """
        self._status_bar.showMessage(message, timeout_ms)

    def changeEvent(self, event: QEvent) -> None:
        """Handle change events."""
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        """Retranslate all UI elements."""
        # Window title
        self.setWindowTitle(self.tr("Context-Aware Translation"))

        # Navigation items
        if self._library_nav_item is not None:
            self._library_nav_item.setText(self.tr("Library"))
        if self._profiles_nav_item is not None:
            self._profiles_nav_item.setText(self.tr("Profiles"))
        if self._book_nav_item is not None and self._current_book_name is not None:
            self._book_nav_item.setText(qarg(self.tr("Book: %1"), self._current_book_name))

        # Menu titles
        self._file_menu.setTitle(self.tr("&File"))
        self._language_menu.setTitle(self.tr("&Language"))
        self._help_menu.setTitle(self.tr("&Help"))

        # Menu actions
        self._open_data_action.setText(self.tr("Open &Data Folder"))
        self._about_action.setText(self.tr("&About"))

        # Status bar (keep current message if any, or show "Ready")
        current_message = self._status_bar.currentMessage()
        if not current_message:
            self.show_status(self.tr("Ready"))

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close event."""
        self._is_closing = True
        self._sleep_check_timer.stop()
        self.close_book()
        self._task_engine.close()
        self._sleep_inhibitor.release()
        self._save_geometry()
        event.accept()
