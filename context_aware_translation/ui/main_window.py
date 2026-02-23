"""Main application window with sidebar navigation."""

import contextlib
import logging
import time

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
from context_aware_translation.storage.book import BookStatus
from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.translation_batch_task_store import (
    STATUS_PAUSED,
    TERMINAL_TASK_STATUSES,
    TranslationBatchTaskStore,
)
from context_aware_translation.workflow.batch_translation_task_service import select_next_auto_run_task

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
from .workers.batch_task_overlap_guard import has_any_batch_task_overlap
from .workers.batch_translation_task_worker import BatchTranslationTaskWorker
from .workers.operation_tracker import DocumentOperationTracker

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window with sidebar navigation."""

    _GLOBAL_BATCH_AUTORUN_INTERVAL_MS = 3000
    _GLOBAL_BATCH_AUTORUN_RETRY_BACKOFF_SEC = 30

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

        # Navigation items (store for retranslation)
        self._library_nav_item: QListWidgetItem | None = None
        self._profiles_nav_item: QListWidgetItem | None = None
        self._global_batch_workers: dict[str, dict[str, BatchTranslationTaskWorker]] = {}
        self._global_batch_retry_after: dict[str, float] = {}
        self._global_batch_timer: QTimer | None = None
        self._global_batch_task_stores: dict[str, TranslationBatchTaskStore] = {}
        self._sleep_inhibitor = SleepInhibitor()

        # Initialize book manager
        self.book_manager = BookManager()
        self.book_manager.seed_system_defaults()

        # Initialize TokenTracker
        TokenTracker.initialize(self.book_manager.registry)

        # Initialize UI components (status bar first to avoid errors during nav init)
        self._init_status_bar()
        self._init_ui()
        self._init_menu_bar()

        # Restore window geometry
        self._restore_geometry()
        self._start_global_batch_autorun()

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

    def _start_global_batch_autorun(self) -> None:
        """Start background scheduler for async batch tasks across all books."""
        if self._global_batch_timer is not None:
            self._global_batch_timer.stop()
        self._global_batch_timer = QTimer(self)
        self._global_batch_timer.setInterval(self._GLOBAL_BATCH_AUTORUN_INTERVAL_MS)
        self._global_batch_timer.timeout.connect(self._on_global_batch_autorun_tick)
        self._global_batch_timer.start()
        self._on_global_batch_autorun_tick()

    def _shutdown_global_batch_autorun(self) -> None:
        """Stop global scheduler and interrupt active background batch workers."""
        timer = self._global_batch_timer
        if timer is not None:
            timer.stop()
            self._global_batch_timer = None
        for task_workers in list(self._global_batch_workers.values()):
            for worker in list(task_workers.values()):
                if worker.isRunning():
                    worker.requestInterruption()
                    if not worker.wait(1500):
                        logger.warning("Timed out while stopping global batch worker during shutdown")
        self._global_batch_workers.clear()
        self._global_batch_retry_after.clear()
        for store in self._global_batch_task_stores.values():
            with contextlib.suppress(Exception):
                store.close()
        self._global_batch_task_stores.clear()

    def _update_sleep_inhibitor(self) -> None:
        """Acquire or release sleep inhibition based on whether any work is active."""
        if any(task_workers for task_workers in self._global_batch_workers.values()):
            self._sleep_inhibitor.acquire()
            return

        # Detached run workers can outlive their originating translation view.
        # Keep sleep inhibition active until those workers have actually finished.
        from .views.translation_view import TranslationView

        for worker in list(TranslationView._DETACHED_BATCH_RUN_WORKERS):
            try:
                if worker.isRunning():
                    self._sleep_inhibitor.acquire()
                    return
            except RuntimeError:
                continue

        for view_name, widget in self._view_registry.items():
            if not view_name.startswith("book_"):
                continue

            if isinstance(widget, BookWorkspace):
                translation_view = widget.get_translation_view()
                if translation_view is not None:
                    batch_worker = getattr(translation_view, "batch_task_worker", None)
                    if batch_worker is not None and batch_worker.isRunning():
                        self._sleep_inhibitor.acquire()
                        return

            if hasattr(widget, "get_running_operations"):
                ops = widget.get_running_operations()
                if isinstance(ops, list) and ops:
                    self._sleep_inhibitor.acquire()
                    return
        self._sleep_inhibitor.release()

    def _on_global_batch_autorun_tick(self) -> None:
        """Auto-run queued/ongoing async batch tasks for all active books."""
        self._cleanup_finished_global_batch_workers()
        self._update_sleep_inhibitor()
        try:
            books = self.book_manager.list_books(status=BookStatus.ACTIVE)
        except Exception:
            logger.exception("Failed to list books for global batch auto-run")
            return
        now = time.monotonic()
        for book in books:
            book_id = book.book_id
            retry_after = self._global_batch_retry_after.get(book_id)
            if retry_after is not None:
                if now < retry_after:
                    continue
                self._global_batch_retry_after.pop(book_id, None)
            if self._is_workspace_translation_worker_running(book_id):
                continue
            candidate = self._next_auto_batch_candidate(book_id)
            if candidate is None:
                continue
            task_id, doc_ids = candidate
            if DocumentOperationTracker.has_document_overlap(book_id, doc_ids):
                continue
            if has_any_batch_task_overlap(
                self.book_manager,
                book_id,
                doc_ids,
                exclude_task_ids={task_id},
            ):
                continue
            self._start_global_batch_worker(book_id, task_id, doc_ids)

    def _cleanup_finished_global_batch_workers(self) -> None:
        for book_id in list(self._global_batch_workers.keys()):
            task_workers = self._global_batch_workers[book_id]
            finished_task_ids = [tid for tid, worker in task_workers.items() if not worker.isRunning()]
            for tid in finished_task_ids:
                task_workers.pop(tid, None)
            if not task_workers:
                self._global_batch_workers.pop(book_id, None)

    def _get_batch_task_store(self, book_id: str) -> TranslationBatchTaskStore:
        """Return a cached ``TranslationBatchTaskStore`` for *book_id*."""
        store = self._global_batch_task_stores.get(book_id)
        if store is None:
            store_path = self.book_manager.get_book_db_path(book_id).parent / "translation_batch_tasks.db"
            store = TranslationBatchTaskStore(store_path)
            self._global_batch_task_stores[book_id] = store
        return store

    def _next_auto_batch_candidate(self, book_id: str) -> tuple[str, list[int] | None] | None:
        """Return (task_id, document_ids) for the next auto-runnable task, or None."""
        store = self._get_batch_task_store(book_id)
        tasks = store.list_tasks(book_id)
        task = select_next_auto_run_task(tasks)
        if task is None:
            return None
        doc_ids = self._parse_task_doc_ids(task)
        return task.task_id, doc_ids

    @staticmethod
    def _parse_task_doc_ids(task: object) -> list[int] | None:
        """Parse document_ids_json from a task record."""
        import json

        raw = getattr(task, "document_ids_json", None)
        if raw is None or raw == "" or raw == "null":
            return None
        try:
            parsed = json.loads(raw)
            if parsed is None:
                return None
            return [int(doc_id) for doc_id in parsed]
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    def _is_workspace_translation_worker_running(self, book_id: str) -> bool:
        workspace = self._view_registry.get(f"book_{book_id}")
        if not isinstance(workspace, BookWorkspace):
            return False
        translation_view = workspace.get_translation_view()
        if translation_view is None:
            return False
        if translation_view.worker is not None and translation_view.worker.isRunning():
            return True
        if translation_view.retranslate_worker is not None and translation_view.retranslate_worker.isRunning():
            return True
        return translation_view.batch_task_worker is not None and translation_view.batch_task_worker.isRunning()

    def _start_global_batch_worker(self, book_id: str, task_id: str, doc_ids: list[int] | None = None) -> None:
        worker = BatchTranslationTaskWorker(
            self.book_manager,
            book_id,
            action="run",
            task_id=task_id,
            document_ids=doc_ids,
        )
        worker.finished_success.connect(
            lambda payload, bid=book_id, _tid=task_id: self._on_global_batch_worker_success(bid, payload)
        )
        worker.error.connect(
            lambda error_msg, bid=book_id, tid=task_id: self._on_global_batch_worker_error(bid, tid, error_msg)
        )
        worker.finished.connect(lambda bid=book_id, tid=task_id: self._on_global_batch_worker_finished(bid, tid))
        self._global_batch_workers.setdefault(book_id, {})[task_id] = worker
        worker.start()

    def _on_global_batch_worker_success(self, book_id: str, payload: object) -> None:
        task_status = ""
        last_error = ""
        if isinstance(payload, dict):
            task_payload = payload.get("task")
            if isinstance(task_payload, dict):
                status_value = task_payload.get("status")
                error_value = task_payload.get("last_error")
                if isinstance(status_value, str):
                    task_status = status_value
                if isinstance(error_value, str):
                    last_error = error_value

        if task_status == STATUS_PAUSED:
            normalized_error = last_error.lower()
            if any(token in normalized_error for token in ("429", "resource_exhausted", "quota", "rate limit")):
                self._global_batch_retry_after[book_id] = (
                    time.monotonic() + self._GLOBAL_BATCH_AUTORUN_RETRY_BACKOFF_SEC
                )
                return

        self._global_batch_retry_after.pop(book_id, None)

    def _on_global_batch_worker_error(self, book_id: str, task_id: str, error_msg: str) -> None:
        self._global_batch_retry_after[book_id] = time.monotonic() + self._GLOBAL_BATCH_AUTORUN_RETRY_BACKOFF_SEC
        logger.warning("Global batch worker failed for book %s task %s: %s", book_id, task_id, error_msg)
        self._pause_global_task_after_worker_error(book_id, task_id, error_msg)

    def _pause_global_task_after_worker_error(self, book_id: str, task_id: str, error_msg: str) -> None:
        if not isinstance(task_id, str) or not task_id:
            return
        try:
            store = self._get_batch_task_store(book_id)
            task = store.get(task_id)
            if task is None or task.status in TERMINAL_TASK_STATUSES:
                return
            store.update(
                task_id,
                status=STATUS_PAUSED,
                last_error=f"Global auto-run worker error: {error_msg}",
            )
        except Exception:
            logger.exception("Failed to pause task %s after global worker error", task_id)

    def _on_global_batch_worker_finished(self, book_id: str, task_id: str) -> None:
        task_workers = self._global_batch_workers.get(book_id)
        if task_workers is not None:
            worker = task_workers.get(task_id)
            if worker is not None and worker.isRunning():
                return
            task_workers.pop(task_id, None)
            if not task_workers:
                self._global_batch_workers.pop(book_id, None)
        self._refresh_translation_view_if_open(book_id)
        QTimer.singleShot(0, self._on_global_batch_autorun_tick)

    def _refresh_translation_view_if_open(self, book_id: str) -> None:
        workspace = self._view_registry.get(f"book_{book_id}")
        if not isinstance(workspace, BookWorkspace):
            return
        translation_view = workspace.get_translation_view()
        if translation_view is not None:
            translation_view.refresh()

    def _get_book_running_operations(self) -> list[str]:
        """Return running operations in the current book workspace."""
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
                    "Leaving the book will stop local processing.\n\n"
                    "Submitted async batch tasks will continue at the provider and can be resumed later.\n\n"
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
                    workspace.request_cancel_running_operations()

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
        workspace = BookWorkspace(self.book_manager, book_id, book_name)
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
        self._shutdown_global_batch_autorun()
        self._sleep_inhibitor.release()
        self.close_book()
        # Safety: interrupt and release any detached batch workers that outlived their views.
        from .views.translation_view import TranslationView

        for worker in list(TranslationView._DETACHED_BATCH_RUN_WORKERS):
            worker.requestInterruption()
            worker.wait(1000)
        TranslationView._DETACHED_BATCH_RUN_WORKERS.clear()
        self._save_geometry()
        event.accept()
