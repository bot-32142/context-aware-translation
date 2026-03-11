from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from context_aware_translation.ui.shell_hosts.hybrid import HybridShellHost
from context_aware_translation.ui.viewmodels.project_shell import PrimaryRoute, ProjectShellViewModel


class ProjectShellHost(HybridShellHost):
    """Project-level shell host with QML chrome and hosted QWidget content."""

    queue_requested = Signal()
    project_settings_requested = Signal()
    back_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        self.viewmodel = ProjectShellViewModel(parent)
        self._work_widget: QWidget | None = None
        self._terms_widget: QWidget | None = None
        self._project_settings_widget: QWidget | None = None
        super().__init__(
            "project/ProjectShellChrome.qml",
            context_objects={"projectShell": self.viewmodel},
            parent=parent,
        )
        self._connect_qml_signals()

    def set_work_widget(self, widget: QWidget) -> QWidget:
        self._work_widget = widget
        return self.register_content("work", widget)

    def set_terms_widget(self, widget: QWidget) -> QWidget:
        self._terms_widget = widget
        return self.register_content("terms", widget)

    def set_project_settings_widget(self, widget: QWidget) -> QWidget:
        self._project_settings_widget = widget
        return widget

    @property
    def work_widget(self) -> QWidget | None:
        return self._work_widget

    @property
    def terms_widget(self) -> QWidget | None:
        return self._terms_widget

    @property
    def project_settings_widget(self) -> QWidget | None:
        return self._project_settings_widget

    def set_project_context(
        self,
        project_id: str,
        project_name: str,
        *,
        primary: PrimaryRoute = PrimaryRoute.WORK,
    ) -> None:
        self.viewmodel.set_project_context(project_id, project_name, primary=primary)
        if primary is PrimaryRoute.TERMS:
            self.show_terms_view()
            return
        self.show_work_view()

    def show_work_view(self) -> None:
        self.viewmodel.show_work()
        if self.content_widget("work") is not None:
            self.show_content("work")

    def show_terms_view(self) -> None:
        self.viewmodel.show_terms()
        if self.content_widget("terms") is not None:
            self.show_content("terms")

    def present_project_settings(self) -> None:
        self.viewmodel.present_project_settings()

    def present_queue(self) -> None:
        self.viewmodel.present_queue()

    def dismiss_modal(self) -> None:
        self.viewmodel.dismiss_modal()

    def retranslate(self) -> None:
        self.viewmodel.retranslate()

    def get_running_operations(self) -> list[str]:
        if self._work_widget is None:
            return []
        get_running_operations = getattr(self._work_widget, "get_running_operations", None)
        if not callable(get_running_operations):
            return []
        running = get_running_operations()
        return running if isinstance(running, list) else []

    def request_cancel_running_operations(self, *, include_engine_tasks: bool = False) -> None:
        if self._work_widget is None:
            return
        request_cancel = getattr(self._work_widget, "request_cancel_running_operations", None)
        if callable(request_cancel):
            request_cancel(include_engine_tasks=include_engine_tasks)

    def cleanup(self) -> None:
        settings_widget = self._project_settings_widget
        self._project_settings_widget = None
        super().cleanup()
        if settings_widget is not None:
            cleanup = getattr(settings_widget, "cleanup", None)
            if callable(cleanup):
                cleanup()
            if settings_widget.parent() is None:
                settings_widget.deleteLater()

    def _connect_qml_signals(self) -> None:
        root = self.chrome_host.rootObject()
        if root is None:
            return
        root.workRequested.connect(self.show_work_view)
        root.termsRequested.connect(self.show_terms_view)
        root.queueRequested.connect(self._on_queue_requested)
        root.projectSettingsRequested.connect(self._on_project_settings_requested)
        root.backRequested.connect(self.back_requested.emit)

    def _on_queue_requested(self) -> None:
        self.present_queue()
        self.queue_requested.emit()

    def _on_project_settings_requested(self) -> None:
        self.present_project_settings()
        self.project_settings_requested.emit()
