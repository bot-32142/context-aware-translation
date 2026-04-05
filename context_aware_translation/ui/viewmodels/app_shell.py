from __future__ import annotations

from PySide6.QtCore import Property, QCoreApplication, Signal

from context_aware_translation.ui.viewmodels.router import ModalRoute, PrimaryRoute, RouteStateViewModel


class AppShellViewModel(RouteStateViewModel):
    """QML-facing route and chrome state for the app shell."""

    current_project_name_changed = Signal()
    labels_changed = Signal()

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._current_project_name = ""

    @Property(bool, notify=current_project_name_changed)
    def has_current_project(self) -> bool:
        return bool(self._current_project_name)

    @Property(str, notify=current_project_name_changed)
    def current_project_name(self) -> str:
        return self._current_project_name

    @Property(str, notify=current_project_name_changed)
    def surface_title(self) -> str:
        return self._current_project_name or self.projects_label

    @Property(str, notify=labels_changed)
    def app_name(self) -> str:
        return QCoreApplication.translate("MainWindow", "Context-Aware Translation")

    @Property(str, notify=labels_changed)
    def projects_label(self) -> str:
        return QCoreApplication.translate("MainWindow", "Projects")

    @Property(str, notify=labels_changed)
    def queue_label(self) -> str:
        return QCoreApplication.translate("MainWindow", "Queue")

    @Property(str, notify=labels_changed)
    def app_settings_label(self) -> str:
        return QCoreApplication.translate("MainWindow", "App Settings")

    @Property(str, notify=labels_changed)
    def setup_wizard_label(self) -> str:
        return QCoreApplication.translate("SetupWizardDialog", "Setup Wizard")

    @Property(str, notify=labels_changed)
    def back_to_projects_label(self) -> str:
        return QCoreApplication.translate("ProjectShellView", "Back to Projects")

    def set_active_project(
        self,
        project_id: str,
        project_name: str,
        *,
        primary: PrimaryRoute = PrimaryRoute.WORK,
    ) -> None:
        normalized_name = project_name.strip()
        if normalized_name != self._current_project_name:
            self._current_project_name = normalized_name
            self.current_project_name_changed.emit()
            self.mark_changed()
        self.open_project(project_id, primary=primary)

    def show_projects_home(self) -> None:
        if self._current_project_name:
            self._current_project_name = ""
            self.current_project_name_changed.emit()
            self.mark_changed()
        self.open_projects()

    def present_app_settings(self) -> None:
        self.open_modal(ModalRoute.APP_SETTINGS)

    def present_queue(self, *, project_id: str | None = None) -> None:
        self.open_modal(ModalRoute.QUEUE, project_id=project_id)

    def dismiss_modal(self) -> None:
        self.close_modal()

    def retranslate(self) -> None:
        self.labels_changed.emit()
        self.current_project_name_changed.emit()
        self.mark_changed()
