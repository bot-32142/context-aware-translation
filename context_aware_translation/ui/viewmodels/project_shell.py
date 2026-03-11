from __future__ import annotations

from PySide6.QtCore import Property, QCoreApplication, Signal

from context_aware_translation.ui.viewmodels.router import PrimaryRoute, RouteStateViewModel


class ProjectShellViewModel(RouteStateViewModel):
    """QML-facing state for the project overview shell."""

    current_project_name_changed = Signal()
    labels_changed = Signal()
    selection_changed = Signal()

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._current_project_name = ""
        self.route_changed.connect(self.selection_changed.emit)

    @Property(bool, notify=current_project_name_changed)
    def has_current_project(self) -> bool:
        return bool(self._current_project_name)

    @Property(str, notify=current_project_name_changed)
    def current_project_name(self) -> str:
        return self._current_project_name

    @Property(str, notify=current_project_name_changed)
    def surface_title(self) -> str:
        return self._current_project_name

    @Property(str, notify=labels_changed)
    def work_label(self) -> str:
        return QCoreApplication.translate("ProjectShellView", "Work")

    @Property(str, notify=labels_changed)
    def terms_label(self) -> str:
        return QCoreApplication.translate("ProjectShellView", "Terms")

    @Property(str, notify=labels_changed)
    def queue_label(self) -> str:
        return QCoreApplication.translate("ProjectShellView", "Queue")

    @Property(str, notify=labels_changed)
    def project_settings_label(self) -> str:
        return QCoreApplication.translate("MainWindow", "Project Settings")

    @Property(str, notify=labels_changed)
    def back_to_projects_label(self) -> str:
        return QCoreApplication.translate("ProjectShellView", "Back to Projects")

    @Property(bool, notify=selection_changed)
    def work_selected(self) -> bool:
        return self.route_state().primary is PrimaryRoute.WORK

    @Property(bool, notify=selection_changed)
    def terms_selected(self) -> bool:
        return self.route_state().primary is PrimaryRoute.TERMS

    def set_project_context(
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

    def show_work(self) -> None:
        project_id = self.route_state().project_id
        if project_id is None:
            return
        self.open_project(project_id, primary=PrimaryRoute.WORK)

    def show_terms(self) -> None:
        project_id = self.route_state().project_id
        if project_id is None:
            return
        self.open_project(project_id, primary=PrimaryRoute.TERMS)

    def present_project_settings(self) -> None:
        self.open_project_settings(self.route_state().project_id)

    def present_queue(self) -> None:
        self.open_queue(project_id=self.route_state().project_id)

    def dismiss_modal(self) -> None:
        self.close_modal()

    def retranslate(self) -> None:
        self.labels_changed.emit()
        self.current_project_name_changed.emit()
        self.mark_changed()
