"""Main application window with sidebar navigation."""

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

from context_aware_translation.application.composition import build_application_context
from context_aware_translation.ui import i18n
from context_aware_translation.ui.adapters import QtApplicationEventBridge
from context_aware_translation.ui.constants import (
    APP_VERSION,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    SIDEBAR_WIDTH,
)
from context_aware_translation.ui.features import AppSetupView, ProjectSetupView, ProjectShellView, WorkView
from context_aware_translation.ui.i18n import qarg
from context_aware_translation.ui.sleep_inhibitor import SleepInhibitor
from context_aware_translation.ui.views import LibraryView


class MainWindow(QMainWindow):
    """Main application window with sidebar navigation."""

    def __init__(self) -> None:
        """Initialize the main window."""
        super().__init__()
        self.setWindowTitle(self.tr("Context-Aware Translation"))
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)

        # View registry: name -> widget reference
        self._view_registry: dict[str, QWidget] = {}

        # Current project state (legacy internal naming retained for compatibility)
        self._current_book_id: str | None = None
        self._current_book_name: str | None = None
        self._book_nav_item: QListWidgetItem | None = None
        self._is_closing = False

        # Navigation items (store for retranslation)
        self._library_nav_item: QListWidgetItem | None = None
        self._profiles_nav_item: QListWidgetItem | None = None
        self._sleep_inhibitor = SleepInhibitor()

        # Initialize the application composition root and bridge application events.
        self._app_context = build_application_context(task_parent=self)
        self._app_events = QtApplicationEventBridge(self._app_context.events, parent=self)
        self.book_manager = self._app_context.runtime.book_manager
        self._task_store = self._app_context.runtime.task_store
        self._task_engine = self._app_context.runtime.task_engine
        self._worker_deps = self._app_context.runtime.worker_deps
        self._task_engine.running_work_changed.connect(self._on_engine_running_work_changed)
        self._app_events.projects_invalidated.connect(self._refresh_projects_view)
        self._app_events.setup_invalidated.connect(self._refresh_app_setup_view)

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
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

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

        self._library_nav_item = QListWidgetItem(self.tr("Projects"))
        self._library_nav_item.setData(Qt.ItemDataRole.UserRole, "projects")
        self._nav_list.addItem(self._library_nav_item)

        self._profiles_nav_item = QListWidgetItem(self.tr("App Setup"))
        self._profiles_nav_item.setData(Qt.ItemDataRole.UserRole, "app_setup")
        self._nav_list.addItem(self._profiles_nav_item)

        self._stack = QStackedWidget()

        self.projects_view = LibraryView(self.book_manager)
        self.projects_view.book_opened.connect(self._on_book_opened)
        self.library_view = self.projects_view
        self.register_view("projects", self.projects_view)

        self.app_setup_view = AppSetupView(self._app_context.services.app_setup)
        self.profile_view = self.app_setup_view
        self.register_view("app_setup", self.app_setup_view)

        main_layout.addWidget(self._nav_list)
        main_layout.addWidget(self._stack, 1)

        self._nav_list.setCurrentRow(0)

    def _init_menu_bar(self) -> None:
        """Initialize the menu bar."""
        menubar = self.menuBar()
        menubar.setNativeMenuBar(False)

        self._file_menu = menubar.addMenu(self.tr("&File"))

        self._open_data_action = QAction(self.tr("Open &Data Folder"), self)
        self._open_data_action.triggered.connect(self._on_open_data_folder)
        self._file_menu.addAction(self._open_data_action)

        self._language_menu = menubar.addMenu(self.tr("&Language"))
        self._language_group = QActionGroup(self)
        self._language_group.setExclusive(True)

        for locale_code, display_name in i18n.SUPPORTED_LANGUAGES.items():
            action = QAction(display_name, self)
            action.setCheckable(True)
            action.setData(locale_code)
            if locale_code == i18n.get_current_language():
                action.setChecked(True)
            self._language_group.addAction(action)
            self._language_menu.addAction(action)

        self._language_group.triggered.connect(self._on_language_changed)

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
            if not view_name.startswith(("project_", "book_")):
                continue

            if hasattr(widget, "get_running_operations"):
                ops = widget.get_running_operations()
                if isinstance(ops, list) and ops:
                    self._sleep_inhibitor.acquire()
                    return
        self._sleep_inhibitor.release()

    def _current_project_view_name(self) -> str | None:
        if self._current_book_id is None:
            return None
        project_view_name = f"project_{self._current_book_id}"
        if project_view_name in self._view_registry:
            return project_view_name
        legacy_view_name = f"book_{self._current_book_id}"
        if legacy_view_name in self._view_registry:
            return legacy_view_name
        return None

    def _get_book_running_operations(self) -> list[str]:
        """Return running operations in the current project shell."""
        if getattr(self, "_is_closing", False):
            return []

        if self._current_book_id is None:
            return []
        view_name = self._current_project_view_name()
        if view_name is None:
            return []
        workspace = self._view_registry.get(view_name)
        if workspace is None:
            return []
        if hasattr(workspace, "get_running_operations"):
            running = workspace.get_running_operations()
            if isinstance(running, list):
                return running
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
                    "Leaving the project may stop local non-task processing.\n\n"
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

        current_project_view = self._current_project_view_name()
        is_navigating_away_from_project = self._current_book_id is not None and view_name != current_project_view
        running_operations = self._get_book_running_operations()
        if is_navigating_away_from_project and running_operations:
            if not self._warn_running_operations(running_operations):
                self._nav_list.blockSignals(True)
                self._nav_list.setCurrentItem(self._book_nav_item)
                self._nav_list.blockSignals(False)
                return
            if current_project_view is not None:
                workspace = self._view_registry.get(current_project_view)
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
        """Handle project opened signal from the Projects view."""
        self.open_project(book_id, book_name)

    def register_view(self, name: str, widget: QWidget) -> None:
        """Register a view widget with the stacked widget."""
        self._stack.addWidget(widget)
        self._view_registry[name] = widget

    def switch_view(self, view_name: str) -> None:
        """Switch to a registered view."""
        if view_name not in self._view_registry:
            self.show_status(qarg(self.tr("View '%1' not found"), view_name), 3000)
            return

        widget = self._view_registry[view_name]
        self._stack.setCurrentWidget(widget)

    def open_project(self, book_id: str, book_name: str) -> None:
        """Open a project shell and add it to navigation."""
        self.close_book()

        self._current_book_id = book_id
        self._current_book_name = book_name

        project_item = QListWidgetItem(qarg(self.tr("Project: %1"), book_name))
        project_item.setData(Qt.ItemDataRole.UserRole, f"project_{book_id}")
        self._nav_list.addItem(project_item)
        self._book_nav_item = project_item

        work_view = WorkView(
            book_id,
            self._app_context.services.work,
            self._app_context.services.document,
            self._app_context.services.terms,
            self._app_context.events,
        )
        setup_view = ProjectSetupView(
            book_id,
            self._app_context.services.project_setup,
            self._app_context.events,
        )
        project_shell = ProjectShellView(
            project_id=book_id,
            project_name=book_name,
            work_widget=work_view,
            setup_widget=setup_view,
        )
        project_shell.close_requested.connect(self.close_book)
        project_shell.queue_requested.connect(self._on_queue_requested)
        work_view.open_app_setup_requested.connect(self._open_app_setup)
        work_view.open_project_setup_requested.connect(project_shell.show_setup)
        setup_view.open_app_setup_requested.connect(self._open_app_setup)
        setup_view.save_completed.connect(lambda _project_id: self._on_project_setup_saved(project_shell))
        self.register_view(f"project_{book_id}", project_shell)

        self._nav_list.setCurrentItem(project_item)
        self.show_status(qarg(self.tr("Opened project: %1"), book_name))

    def open_book(self, book_id: str, book_name: str) -> None:
        """Compatibility wrapper during the shell migration."""
        self.open_project(book_id, book_name)

    def close_book(self) -> None:
        """Close the current project shell and remove it from navigation."""
        if self._current_book_id is None:
            return

        book_name = self._current_book_name
        view_name = self._current_project_view_name() or f"project_{self._current_book_id}"

        if self._book_nav_item is not None:
            row = self._nav_list.row(self._book_nav_item)
            self._nav_list.takeItem(row)
            self._book_nav_item = None

        if view_name in self._view_registry:
            widget = self._view_registry[view_name]
            if widget is not None:
                if hasattr(widget, "cleanup"):
                    widget.cleanup()
                self._stack.removeWidget(widget)
                widget.deleteLater()
            del self._view_registry[view_name]

        self._current_book_id = None
        self._current_book_name = None
        self._nav_list.setCurrentRow(0)

        if book_name:
            self.show_status(qarg(self.tr("Closed project: %1"), book_name))

    def _refresh_projects_view(self, _event: object) -> None:
        if hasattr(self.projects_view, "refresh"):
            self.projects_view.refresh()

    def _refresh_app_setup_view(self, _event: object) -> None:
        if hasattr(self.app_setup_view, "refresh"):
            self.app_setup_view.refresh()

    def _open_app_setup(self) -> None:
        if self._profiles_nav_item is not None:
            self._nav_list.setCurrentItem(self._profiles_nav_item)

    def _on_project_setup_saved(self, shell: ProjectShellView) -> None:
        shell.show_work()
        self.show_status(self.tr("Project setup saved."), 3000)

    def _on_queue_requested(self) -> None:
        self.show_status(self.tr("Queue drawer will attach to the new shell in a later migration task."), 3000)

    def show_status(self, message: str, timeout_ms: int = 5000) -> None:
        """Show a status message in the status bar."""
        self._status_bar.showMessage(message, timeout_ms)

    def changeEvent(self, event: QEvent) -> None:
        """Handle change events."""
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        """Retranslate all UI elements."""
        self.setWindowTitle(self.tr("Context-Aware Translation"))

        if self._library_nav_item is not None:
            self._library_nav_item.setText(self.tr("Projects"))
        if self._profiles_nav_item is not None:
            self._profiles_nav_item.setText(self.tr("App Setup"))
        if self._book_nav_item is not None and self._current_book_name is not None:
            self._book_nav_item.setText(qarg(self.tr("Project: %1"), self._current_book_name))

        self._file_menu.setTitle(self.tr("&File"))
        self._language_menu.setTitle(self.tr("&Language"))
        self._help_menu.setTitle(self.tr("&Help"))

        self._open_data_action.setText(self.tr("Open &Data Folder"))
        self._about_action.setText(self.tr("&About"))

        current_message = self._status_bar.currentMessage()
        if not current_message:
            self.show_status(self.tr("Ready"))

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close event."""
        self._is_closing = True
        self._sleep_check_timer.stop()
        self.close_book()
        self._app_events.close()
        self._task_engine.close()
        self._task_store.close()
        self.book_manager.close()
        self._sleep_inhibitor.release()
        self._save_geometry()
        super().closeEvent(event)
