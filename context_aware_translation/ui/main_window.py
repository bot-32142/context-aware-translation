"""Main application window with QML app and project shell chrome."""

from PySide6.QtCore import QEvent, QSettings, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QWidget,
)

from context_aware_translation.adapters.qt.application_event_bridge import QtApplicationEventBridge
from context_aware_translation.application.composition import build_application_context
from context_aware_translation.application.contracts.common import (
    NavigationTarget,
    UserMessage,
    UserMessageSeverity,
)
from context_aware_translation.ui import i18n
from context_aware_translation.ui.constants import (
    APP_VERSION,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
)
from context_aware_translation.ui.features.app_settings_pane import AppSettingsPane
from context_aware_translation.ui.features.library_view import LibraryView
from context_aware_translation.ui.features.project_settings_pane import ProjectSettingsPane
from context_aware_translation.ui.features.queue_drawer_view import QueueDrawerView
from context_aware_translation.ui.features.terms_view import TermsView
from context_aware_translation.ui.features.work_view import WorkView
from context_aware_translation.ui.i18n import qarg
from context_aware_translation.ui.shell_hosts.app_settings_dialog_host import AppSettingsDialogHost
from context_aware_translation.ui.shell_hosts.app_shell_host import AppShellHost
from context_aware_translation.ui.shell_hosts.project_settings_dialog_host import ProjectSettingsDialogHost
from context_aware_translation.ui.shell_hosts.project_shell_host import ProjectShellHost
from context_aware_translation.ui.shell_hosts.queue_shell_host import QueueShellHost
from context_aware_translation.ui.sleep_inhibitor import SleepInhibitor
from context_aware_translation.ui.viewmodels.router import ModalRoute, PrimaryRoute, route_state_from_navigation_target
from context_aware_translation.ui.window_controllers import (
    ProjectSessionManager,
    QueueDockController,
    cleanup_widget,
    navigation_blockers_for,
    request_cancel_for,
    running_operations_for,
)


class MainWindow(QMainWindow):
    """Main application window with QML app shell chrome."""

    def __init__(self) -> None:
        """Initialize the main window."""
        super().__init__()
        self.setWindowTitle(self.tr("Context-Aware Translation"))
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)

        # View registry: name -> widget reference
        self._view_registry: dict[str, QWidget] = {}

        # Current project state
        self._current_book_id: str | None = None
        self._current_book_name: str | None = None
        self._project_settings_dialog = None
        self._is_closing = False

        self._sleep_inhibitor = SleepInhibitor()
        self._sleep_inhibitor_acquired = False

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
        self._app_shell = AppShellHost(self)
        self._app_shell.projects_requested.connect(self._show_projects_surface)
        self._app_shell.close_project_requested.connect(self._show_projects_surface)
        self._app_shell.app_settings_requested.connect(self._open_app_setup)
        self._app_shell.queue_requested.connect(self._on_queue_requested)
        self.setCentralWidget(self._app_shell)

        self._project_sessions = ProjectSessionManager(
            parent_window=self,
            app_shell=self._app_shell,
            services=self._app_context.services,
            events=self._app_context.events,
            work_view_factory=WorkView,
            terms_view_factory=TermsView,
            project_settings_pane_factory=ProjectSettingsPane,
            project_shell_factory=ProjectShellHost,
            project_shell_type=ProjectShellHost,
            project_settings_dialog_factory=ProjectSettingsDialogHost,
            show_projects_surface_callback=self._show_projects_surface,
            queue_requested_callback=self._on_queue_requested,
            open_app_setup_callback=self._open_app_setup,
            project_setup_saved_callback=self._on_project_setup_saved,
        )
        self._sync_project_session_state()

        self.projects_view = LibraryView(self._app_context.services.projects)
        self.projects_view.book_opened.connect(self._on_book_opened)
        self.register_view("projects", self.projects_view)

        self.app_setup_view = AppSettingsPane(self._app_context.services.app_setup)
        self._app_settings_dialog = AppSettingsDialogHost(self)
        self._app_settings_dialog.set_app_settings_widget(self.app_setup_view)
        self._app_settings_dialog.finished.connect(lambda _result: self._app_shell.dismiss_modal())

        self._queue_controller = QueueDockController(
            parent_window=self,
            app_shell=self._app_shell,
            queue_service=self._app_context.services.queue,
            events=self._app_context.events,
            drawer_factory=QueueDrawerView,
            shell_factory=QueueShellHost,
            open_navigation_target_callback=self._open_navigation_target,
            notification_callback=self._on_queue_notification,
            title_text=lambda: self.tr("Queue"),
            dismiss_project_modal_callback=self._dismiss_current_project_modal,
        )
        self._queue_drawer = self._queue_controller.queue_drawer
        self._queue_shell = self._queue_controller.queue_shell
        self._queue_dock = self._queue_controller.dock

        self._app_shell.show_projects_view()

    def _init_menu_bar(self) -> None:
        """Initialize the menu bar."""
        menubar = self.menuBar()
        menubar.setNativeMenuBar(False)

        self._file_menu = menubar.addMenu(self.tr("&File"))

        self._open_data_action = QAction(self.tr("Open &Data Folder"), self)
        self._open_data_action.triggered.connect(self._on_open_data_folder)
        self._file_menu.addAction(self._open_data_action)

        self._app_settings_action = QAction(self.tr("App &Settings"), self)
        self._app_settings_action.triggered.connect(self._open_app_setup)
        self._file_menu.addAction(self._app_settings_action)

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
            MainWindow._set_sleep_inhibitor_active(self, False)
            return

        if self._task_engine.has_running_work():
            MainWindow._set_sleep_inhibitor_active(self, True)
            return

        for view_name, widget in self._view_registry.items():
            if view_name.startswith("project_") and MainWindow._running_operations_for(widget):
                MainWindow._set_sleep_inhibitor_active(self, True)
                return
        MainWindow._set_sleep_inhibitor_active(self, False)

    def _set_sleep_inhibitor_active(self, active: bool) -> None:
        if active == getattr(self, "_sleep_inhibitor_acquired", False):
            return
        self._sleep_inhibitor_acquired = active
        if active:
            self._sleep_inhibitor.acquire()
            return
        self._sleep_inhibitor.release()

    def _current_project_view_name(self) -> str | None:
        return self._project_sessions.current_project_view_name()

    def _current_project_widget(self) -> QWidget | None:
        return self._project_sessions.current_project_widget()

    def _current_project_shell(self) -> ProjectShellHost | None:
        shell = self._project_sessions.current_project_shell()
        return shell if isinstance(shell, ProjectShellHost) else None

    @staticmethod
    def _running_operations_for(widget: object) -> list[str]:
        return running_operations_for(widget)

    @staticmethod
    def _request_cancel_for(widget: object) -> None:
        request_cancel_for(widget)

    @staticmethod
    def _cleanup_widget(widget: object) -> None:
        cleanup_widget(widget)

    def _get_book_running_operations(self) -> list[str]:
        """Return navigation-blocking operations in the current project shell."""
        if getattr(self, "_is_closing", False):
            return []
        return navigation_blockers_for(self._current_project_widget())

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

    def _on_open_data_folder(self) -> None:
        """Open the data folder in the system file manager."""
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
        """Register a view widget with the app shell host."""
        self._project_sessions.register_view(name, widget)
        self._sync_project_session_state()

    def switch_view(self, view_name: str) -> None:
        """Switch to a registered view through the app shell host."""
        if not self._project_sessions.switch_view(view_name):
            self.show_status(qarg(self.tr("View '%1' not found"), view_name), 3000)

    def open_project(self, book_id: str, book_name: str) -> None:
        """Open a project shell through the app shell host."""
        if not self._prepare_to_leave_current_project():
            return
        self.close_book()
        self._project_sessions.open_project(book_id, book_name)
        self._sync_project_session_state()
        self.show_status(qarg(self.tr("Opened project: %1"), book_name))

    def close_book(self) -> None:
        """Close the current project shell and return to projects."""
        if self._project_sessions.current_project_id is None:
            self._app_shell.show_projects_view()
            return

        book_name = self._project_sessions.close_current_project()
        self._sync_project_session_state()
        self._queue_controller.clear_if_visible()

        if book_name:
            self.show_status(qarg(self.tr("Closed project: %1"), book_name))

    def _refresh_projects_view(self, _event: object) -> None:
        self.projects_view.refresh()

    def _refresh_app_setup_view(self, _event: object) -> None:
        self.app_setup_view.refresh()

    def _open_app_setup(self) -> None:
        self._app_shell.present_app_settings()
        self.app_setup_view.refresh()
        self._app_settings_dialog.retranslate()
        self._app_settings_dialog.present()

    def _destroy_project_settings_dialog(self) -> None:
        self._project_sessions.destroy_project_settings_dialog()
        self._sync_project_session_state()

    def _open_project_settings(self, shell: ProjectShellHost) -> None:
        self._project_sessions.open_project_settings(shell)
        self._sync_project_session_state()

    def _on_project_setup_saved(self, shell: ProjectShellHost) -> None:
        self._project_sessions.on_project_setup_saved(shell)
        self._sync_project_session_state()
        self.show_status(self.tr("Project setup saved."), 3000)

    def _on_queue_requested(self) -> None:
        self._open_queue_drawer(project_id=self._current_book_id, project_name=self._current_book_name)

    def _open_queue_drawer(self, *, project_id: str | None, project_name: str | None = None) -> None:
        self._queue_controller.open(project_id=project_id, project_name=project_name)

    def _on_queue_visibility_changed(self, visible: bool) -> None:
        self._queue_controller.handle_visibility_changed(visible)

    def _dismiss_current_project_modal(self) -> None:
        shell = self._current_project_shell()
        if shell is None:
            return
        modal_route = getattr(getattr(shell, "viewmodel", None), "modal_route", "")
        if modal_route and modal_route != ModalRoute.QUEUE.value:
            return
        if getattr(shell, "current_surface", "") not in {"", "queue"} and not modal_route:
            return
        shell.dismiss_modal()

    def _on_queue_notification(self, message: UserMessage) -> None:
        timeout_ms = 7000 if message.severity is UserMessageSeverity.ERROR else 3000
        self.show_status(message.text, timeout_ms)

    def _show_projects_surface(self) -> None:
        if not self._prepare_to_leave_current_project():
            return
        self.close_book()

    def _prepare_to_leave_current_project(self) -> bool:
        current_project_view = self._current_project_view_name()
        if current_project_view is None:
            return True
        running_operations = self._get_book_running_operations()
        if not running_operations:
            return True
        if not self._warn_running_operations(running_operations):
            return False
        MainWindow._request_cancel_for(self._view_registry.get(current_project_view))
        return True

    def _open_navigation_target(self, target: NavigationTarget) -> None:
        route = route_state_from_navigation_target(target)
        if route is None:
            return

        if route.primary is PrimaryRoute.PROJECTS and route.project_id is None and route.modal is None:
            self._show_projects_surface()
            return
        if route.modal is ModalRoute.APP_SETTINGS:
            self._open_app_setup()
            return
        if route.modal is ModalRoute.QUEUE:
            project_name = self._current_book_name if route.project_id == self._current_book_id else None
            if route.project_id is not None and project_name is None:
                book = self.book_manager.get_book(route.project_id)
                if book is not None:
                    project_name = book.name
            self._open_queue_drawer(project_id=route.project_id, project_name=project_name)
            return

        if route.project_id is not None and route.project_id != self._current_book_id:
            book = self.book_manager.get_book(route.project_id)
            if book is not None:
                self.open_project(book.book_id, book.name)
            if route.project_id != self._current_book_id:
                return

        shell = self._project_sessions.current_project_shell()
        if shell is None or not isinstance(shell, ProjectShellHost):
            return

        if route.modal is ModalRoute.PROJECT_SETTINGS:
            self._open_project_settings(shell)
        elif route.primary is PrimaryRoute.TERMS and route.document_id is None:
            shell.show_terms_view()
        elif route.primary is PrimaryRoute.WORK:
            shell.show_work_view()
            work_widget = shell.work_widget
            if work_widget is not None and route.document_id is not None and route.document_section is not None:
                work_widget.open_navigation_target(target)
        else:
            shell.show_work_view()

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
        self._app_shell.retranslate()
        self._app_settings_dialog.retranslate()
        self._queue_controller.retranslate()
        self._project_sessions.retranslate()
        self._sync_project_session_state()

        self._file_menu.setTitle(self.tr("&File"))
        self._language_menu.setTitle(self.tr("&Language"))
        self._help_menu.setTitle(self.tr("&Help"))

        self._open_data_action.setText(self.tr("Open &Data Folder"))
        self._app_settings_action.setText(self.tr("App &Settings"))
        self._about_action.setText(self.tr("&About"))

        current_message = self._status_bar.currentMessage()
        if not current_message:
            self.show_status(self.tr("Ready"))

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close event."""
        self._is_closing = True
        self._sleep_check_timer.stop()
        self.close_book()
        self._app_settings_dialog.close()
        self._queue_controller.cleanup()
        self._app_events.close()
        self._task_engine.close()
        if not self._task_engine.has_running_work():
            self._task_store.close()
            self.book_manager.close()
        self._set_sleep_inhibitor_active(False)
        self._save_geometry()
        super().closeEvent(event)

    def _sync_project_session_state(self) -> None:
        self._view_registry = self._project_sessions.view_registry
        self._current_book_id = self._project_sessions.current_project_id
        self._current_book_name = self._project_sessions.current_project_name
        self._project_settings_dialog = self._project_sessions.project_settings_dialog
