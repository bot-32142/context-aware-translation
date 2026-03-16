from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from PySide6.QtCore import Property, Signal

from context_aware_translation.application.contracts.common import (
    DocumentSection,
    NavigationTarget,
    NavigationTargetKind,
)
from context_aware_translation.ui.viewmodels.base import ViewModelBase


class PrimaryRoute(StrEnum):
    PROJECTS = "projects"
    WORK = "work"
    TERMS = "terms"


class ModalRoute(StrEnum):
    APP_SETTINGS = "app_settings"
    PROJECT_SETTINGS = "project_settings"
    QUEUE = "queue"


class RouteScope(StrEnum):
    APP = "app"
    PROJECT = "project"
    DOCUMENT = "document"


@dataclass(frozen=True, slots=True)
class RouteState:
    primary: PrimaryRoute = PrimaryRoute.PROJECTS
    project_id: str | None = None
    document_id: int | None = None
    document_section: DocumentSection | None = None
    modal: ModalRoute | None = None

    @property
    def scope(self) -> RouteScope:
        if self.document_id is not None and self.document_section is not None:
            return RouteScope.DOCUMENT
        if self.project_id is not None:
            return RouteScope.PROJECT
        return RouteScope.APP


class RouteStateViewModel(ViewModelBase):
    """Shared route state for future app, project, and document shells."""

    route_changed = Signal()

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._state = RouteState()
        self._modal_return_state: RouteState | None = None

    @Property(str, notify=route_changed)
    def primary_route(self) -> str:
        return self._state.primary.value

    @Property(str, notify=route_changed)
    def project_id(self) -> str:
        return self._state.project_id or ""

    @Property(int, notify=route_changed)
    def document_id(self) -> int:
        return self._state.document_id if self._state.document_id is not None else -1

    @Property(str, notify=route_changed)
    def document_section(self) -> str:
        return self._state.document_section.value if self._state.document_section is not None else ""

    @Property(str, notify=route_changed)
    def modal_route(self) -> str:
        return self._state.modal.value if self._state.modal is not None else ""

    @Property(str, notify=route_changed)
    def scope(self) -> str:
        return self._state.scope.value

    def route_state(self) -> RouteState:
        return self._state

    def set_route(self, state: RouteState) -> None:
        if state == self._state:
            return
        self._state = state
        self.route_changed.emit()
        self.mark_changed()

    def open_projects(self) -> None:
        self._modal_return_state = None
        self.set_route(RouteState())

    def open_project(self, project_id: str, *, primary: PrimaryRoute = PrimaryRoute.WORK) -> None:
        self._modal_return_state = None
        self.set_route(RouteState(primary=primary, project_id=project_id))

    def open_document(self, project_id: str, document_id: int, section: DocumentSection) -> None:
        self._modal_return_state = None
        self.set_route(
            RouteState(
                primary=PrimaryRoute.WORK,
                project_id=project_id,
                document_id=document_id,
                document_section=section,
                modal=None,
            )
        )

    def open_modal(self, modal: ModalRoute, *, project_id: str | None = None) -> None:
        state = self._state
        if project_id is not None and project_id != state.project_id:
            state = RouteState(primary=PrimaryRoute.WORK, project_id=project_id)
        if state.modal is not None and state.modal is not modal:
            self._modal_return_state = replace(state)
        elif state.modal is None or state.modal is modal:
            self._modal_return_state = None
        self.set_route(replace(state, modal=modal))

    def close_modal(self) -> None:
        if self._state.modal is None:
            return
        if self._modal_return_state is not None:
            restored_state = self._modal_return_state
            self._modal_return_state = None
            self._state = restored_state
            self.route_changed.emit()
            self.mark_changed()
            return
        self.set_route(replace(self._state, modal=None))

    def open_app_settings(self) -> None:
        self.open_modal(ModalRoute.APP_SETTINGS)

    def open_project_settings(self, project_id: str | None = None) -> None:
        resolved_project_id = project_id or self._state.project_id
        if resolved_project_id is None:
            return
        self.open_modal(ModalRoute.PROJECT_SETTINGS, project_id=resolved_project_id)

    def open_queue(self, project_id: str | None = None) -> None:
        self.open_modal(ModalRoute.QUEUE, project_id=project_id)

    def apply_navigation_target(self, target: NavigationTarget) -> None:
        route = route_state_from_navigation_target(target)
        if route is None:
            return
        self._modal_return_state = None
        self.set_route(route)


def route_state_from_navigation_target(target: NavigationTarget) -> RouteState | None:
    if target.kind is NavigationTargetKind.PROJECTS:
        return RouteState()
    if target.kind is NavigationTargetKind.APP_SETUP:
        return RouteState(modal=ModalRoute.APP_SETTINGS)
    if target.kind is NavigationTargetKind.PROJECT_SETUP:
        if target.project_id is None:
            return None
        return RouteState(
            primary=PrimaryRoute.WORK,
            project_id=target.project_id,
            modal=ModalRoute.PROJECT_SETTINGS,
        )
    if target.kind is NavigationTargetKind.TERMS:
        if target.project_id is None:
            return None
        return RouteState(primary=PrimaryRoute.TERMS, project_id=target.project_id)
    if target.kind is NavigationTargetKind.QUEUE:
        return RouteState(
            primary=PrimaryRoute.WORK if target.project_id is not None else PrimaryRoute.PROJECTS,
            project_id=target.project_id,
            modal=ModalRoute.QUEUE,
        )
    if target.kind is NavigationTargetKind.WORK:
        if target.project_id is None:
            return None
        return RouteState(primary=PrimaryRoute.WORK, project_id=target.project_id)

    document_section = _DOCUMENT_SECTIONS_BY_TARGET.get(target.kind)
    if document_section is None or target.project_id is None or target.document_id is None:
        return None
    return RouteState(
        primary=PrimaryRoute.WORK,
        project_id=target.project_id,
        document_id=target.document_id,
        document_section=document_section,
    )


_DOCUMENT_SECTIONS_BY_TARGET = {
    NavigationTargetKind.DOCUMENT_OCR: DocumentSection.OCR,
    NavigationTargetKind.DOCUMENT_TERMS: DocumentSection.TERMS,
    NavigationTargetKind.DOCUMENT_TRANSLATION: DocumentSection.TRANSLATION,
    NavigationTargetKind.DOCUMENT_IMAGES: DocumentSection.IMAGES,
    NavigationTargetKind.DOCUMENT_EXPORT: DocumentSection.EXPORT,
}
