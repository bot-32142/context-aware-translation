from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget, QWidget


def running_operations_for(widget: object) -> list[str]:
    get_running_operations = getattr(widget, "get_running_operations", None)
    if not callable(get_running_operations):
        return []
    running = get_running_operations()
    return running if isinstance(running, list) else []


def request_cancel_for(widget: object, *, include_engine_tasks: bool = False) -> None:
    request_cancel = getattr(widget, "request_cancel_running_operations", None)
    if callable(request_cancel):
        request_cancel(include_engine_tasks=include_engine_tasks)


def cleanup_widget(widget: object) -> None:
    cleanup = getattr(widget, "cleanup", None)
    if callable(cleanup):
        cleanup()


class QueueDockController:
    """Own the queue drawer widget, shell host, and dock lifecycle."""

    def __init__(
        self,
        *,
        parent_window,
        app_shell,
        queue_service,
        events,
        drawer_factory,
        shell_factory,
        open_navigation_target_callback: Callable[[object], None],
        notification_callback: Callable[[object], None],
        title_text: Callable[[], str],
    ) -> None:
        self._app_shell = app_shell
        self._title_text = title_text

        self.queue_drawer = drawer_factory(queue_service, events, parent=parent_window)
        self.queue_drawer.open_related_item_requested.connect(open_navigation_target_callback)
        self.queue_drawer.notification_requested.connect(notification_callback)

        self.queue_shell = shell_factory(parent_window)
        self.queue_shell.set_queue_widget(self.queue_drawer)

        self.dock = QDockWidget(self._title_text(), parent_window)
        self.dock.setObjectName("queueDrawerDock")
        self.dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self.dock.setWidget(self.queue_shell)
        self.dock.hide()
        self.dock.visibilityChanged.connect(self.handle_visibility_changed)
        self.queue_shell.close_requested.connect(self.dock.close)
        parent_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)

    def open(self, *, project_id: str | None, project_name: str | None = None) -> None:
        self._app_shell.present_queue(project_id=project_id)
        self.queue_shell.set_scope(project_id, project_name=project_name)
        self.dock.setWindowTitle(self._title_text())
        self.dock.show()
        self.dock.raise_()

    def handle_visibility_changed(self, visible: bool) -> None:
        if visible:
            return
        self._app_shell.dismiss_modal()
        self.queue_shell.clear_scope()

    def clear_if_visible(self) -> None:
        if not self.dock.isVisible():
            return
        self._app_shell.dismiss_modal()
        self.queue_shell.clear_scope()

    def retranslate(self) -> None:
        self.dock.setWindowTitle(self._title_text())
        self.queue_shell.retranslate()

    def cleanup(self) -> None:
        self.queue_shell.cleanup()
        self.queue_drawer.cleanup()


class ProjectSessionManager:
    """Manage project-shell creation, registration, and teardown."""

    def __init__(
        self,
        *,
        parent_window,
        app_shell,
        services,
        events,
        work_view_factory,
        terms_view_factory,
        project_settings_pane_factory,
        project_shell_factory,
        project_shell_type,
        project_settings_dialog_factory,
        show_projects_surface_callback: Callable[[], None],
        queue_requested_callback: Callable[[], None],
        open_app_setup_callback: Callable[[], None],
        project_setup_saved_callback: Callable[[object], None],
    ) -> None:
        self._parent_window = parent_window
        self._app_shell = app_shell
        self._services = services
        self._events = events
        self._work_view_factory = work_view_factory
        self._terms_view_factory = terms_view_factory
        self._project_settings_pane_factory = project_settings_pane_factory
        self._project_shell_factory = project_shell_factory
        self._project_shell_type = project_shell_type
        self._project_settings_dialog_factory = project_settings_dialog_factory
        self._show_projects_surface_callback = show_projects_surface_callback
        self._queue_requested_callback = queue_requested_callback
        self._open_app_setup_callback = open_app_setup_callback
        self._project_setup_saved_callback = project_setup_saved_callback

        self.view_registry: dict[str, QWidget] = {}
        self.current_project_id: str | None = None
        self.current_project_name: str | None = None
        self.project_settings_dialog = None

    def register_view(self, name: str, widget: QWidget) -> None:
        self.view_registry[name] = widget
        if name == "projects":
            self._app_shell.set_projects_widget(widget)
        elif name.startswith("project_") and self.current_project_id is not None and self.current_project_name is not None:
            self._app_shell.set_project_widget(name, widget)

    def switch_view(self, view_name: str) -> bool:
        if view_name not in self.view_registry:
            return False
        if view_name == "projects":
            self._app_shell.show_projects_view()
            return True
        if self.current_project_id is not None and self.current_project_name is not None:
            self._app_shell.show_project_view(view_name, self.current_project_id, self.current_project_name)
        return True

    def current_project_view_name(self) -> str | None:
        if self.current_project_id is None:
            return None
        project_view_name = f"project_{self.current_project_id}"
        return project_view_name if project_view_name in self.view_registry else None

    def current_project_widget(self) -> QWidget | None:
        view_name = self.current_project_view_name()
        return self.view_registry.get(view_name) if view_name is not None else None

    def current_project_shell(self):
        widget = self.current_project_widget()
        return widget if isinstance(widget, self._project_shell_type) else None

    def open_project(self, book_id: str, book_name: str) -> None:
        self.current_project_id = book_id
        self.current_project_name = book_name
        project_shell = self._build_project_shell(book_id, book_name)
        view_name = self._view_name_for(book_id)
        self.register_view(view_name, project_shell)
        self._app_shell.show_project_view(view_name, book_id, book_name)

    def close_current_project(self) -> str | None:
        if self.current_project_id is None:
            self._app_shell.show_projects_view()
            return None

        self.destroy_project_settings_dialog()
        book_name = self.current_project_name
        view_name = self.current_project_view_name() or self._view_name_for(self.current_project_id)
        widget = self.view_registry.pop(view_name, None)
        if widget is not None:
            self._app_shell.remove_project_widget(view_name)
            cleanup_widget(widget)
            widget.deleteLater()

        self.current_project_id = None
        self.current_project_name = None
        self._app_shell.show_projects_view()
        return book_name

    def open_project_settings(self, shell) -> None:
        settings_widget = shell.project_settings_widget
        if settings_widget is None:
            return
        shell.present_project_settings()
        refresh = getattr(settings_widget, "refresh", None)
        if callable(refresh):
            refresh()
        if self.project_settings_dialog is None:
            return
        self.project_settings_dialog.retranslate()
        self.project_settings_dialog.present()

    def on_project_setup_saved(self, shell) -> None:
        shell.dismiss_modal()
        shell.show_work_view()
        if self.project_settings_dialog is not None:
            self.project_settings_dialog.dismiss()

    def destroy_project_settings_dialog(self) -> None:
        if self.project_settings_dialog is None:
            return
        self.project_settings_dialog.close()
        self.project_settings_dialog.deleteLater()
        self.project_settings_dialog = None

    def retranslate(self) -> None:
        if self.project_settings_dialog is not None:
            self.project_settings_dialog.retranslate()

    def _build_project_shell(self, book_id: str, book_name: str):
        work_view = self._work_view_factory(
            book_id,
            self._services.work,
            self._services.document,
            self._services.terms,
            self._events,
        )
        terms_view = self._terms_view_factory(
            book_id,
            self._services.terms,
            self._events,
        )
        project_settings_pane = self._project_settings_pane_factory(
            book_id,
            self._services.project_setup,
            self._events,
        )
        project_shell = self._project_shell_factory(self._parent_window)
        project_settings_dialog = self._build_project_settings_dialog(project_shell, project_settings_pane)
        project_shell.set_work_widget(work_view)
        project_shell.set_terms_widget(terms_view)
        project_shell.set_project_settings_widget(project_settings_pane)
        project_shell.set_project_context(book_id, book_name)
        project_shell.back_requested.connect(self._show_projects_surface_callback)
        project_shell.queue_requested.connect(self._queue_requested_callback)
        project_shell.project_settings_requested.connect(lambda: self.open_project_settings(project_shell))
        work_view.open_app_setup_requested.connect(self._open_app_setup_callback)
        work_view.open_project_setup_requested.connect(lambda: self.open_project_settings(project_shell))
        project_settings_pane.open_app_setup_requested.connect(self._open_app_setup_callback)
        project_settings_pane.save_completed.connect(lambda _project_id: self._project_setup_saved_callback(project_shell))
        self.project_settings_dialog = project_settings_dialog
        return project_shell

    def _build_project_settings_dialog(self, project_shell, project_settings_pane):
        dialog = self._project_settings_dialog_factory(self._parent_window)
        dialog.set_project_settings_widget(project_settings_pane)
        dialog.finished.connect(lambda _result: project_shell.dismiss_modal())
        return dialog

    @staticmethod
    def _view_name_for(project_id: str) -> str:
        return f"project_{project_id}"
