from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from context_aware_translation.ui.shell_hosts.hybrid import HybridShellHost
from context_aware_translation.ui.viewmodels.app_shell import AppShellViewModel


class AppShellHost(HybridShellHost):
    """App-level shell host with QML chrome and hosted QWidget pages."""

    projects_requested = Signal()
    app_settings_requested = Signal()
    queue_requested = Signal()
    close_project_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        self.viewmodel = AppShellViewModel(parent)
        super().__init__(
            "app/AppShellChrome.qml",
            context_objects={"appShell": self.viewmodel},
            parent=parent,
        )
        self._connect_qml_signals()

    def set_projects_widget(self, widget: QWidget) -> QWidget:
        return self.register_content("projects", widget)

    def set_project_widget(self, key: str, widget: QWidget) -> QWidget:
        return self.register_content(key, widget)

    def show_projects_view(self) -> None:
        self.viewmodel.show_projects_home()
        self.chrome_host.show()
        self.show_content("projects")

    def show_project_view(self, key: str, project_id: str, project_name: str) -> None:
        self.viewmodel.set_active_project(project_id, project_name)
        self.chrome_host.hide()
        self.show_content(key)

    def remove_project_widget(self, key: str) -> QWidget | None:
        return self.remove_content(key)

    def present_app_settings(self) -> None:
        self.viewmodel.present_app_settings()

    def present_queue(self, *, project_id: str | None = None) -> None:
        self.viewmodel.present_queue(project_id=project_id)

    def dismiss_modal(self) -> None:
        self.viewmodel.dismiss_modal()

    def retranslate(self) -> None:
        self.viewmodel.retranslate()

    def _connect_qml_signals(self) -> None:
        root = self.chrome_host.rootObject()
        if root is None:
            return
        projects_requested = getattr(root, "projectsRequested", None)
        if projects_requested is not None:
            projects_requested.connect(self.projects_requested.emit)
        app_settings_requested = getattr(root, "appSettingsRequested", None)
        if app_settings_requested is not None:
            app_settings_requested.connect(self.app_settings_requested.emit)
        queue_requested = getattr(root, "queueRequested", None)
        if queue_requested is not None:
            queue_requested.connect(self.queue_requested.emit)
        close_project_requested = getattr(root, "closeProjectRequested", None)
        if close_project_requested is not None:
            close_project_requested.connect(self.close_project_requested.emit)
