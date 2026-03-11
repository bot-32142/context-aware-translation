from __future__ import annotations

import pytest

from context_aware_translation.application.contracts.common import (
    DocumentSection,
    NavigationTarget,
    NavigationTargetKind,
)
from context_aware_translation.application.events import (
    ApplicationEventKind,
    InMemoryApplicationEventBus,
    ProjectsInvalidatedEvent,
)
from context_aware_translation.ui.viewmodels.base import ViewModelBase
from context_aware_translation.ui.viewmodels.router import (
    ModalRoute,
    PrimaryRoute,
    RouteState,
    RouteStateViewModel,
    route_state_from_navigation_target,
)

try:
    from PySide6.QtWidgets import QApplication

    HAS_PYSIDE6 = True
except ImportError:  # pragma: no cover - environment dependent
    HAS_PYSIDE6 = False

pytestmark = pytest.mark.skipif(not HAS_PYSIDE6, reason="PySide6 not available")


@pytest.fixture(autouse=True, scope="module")
def _qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class _Subscription:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_viewmodel_base_tracks_busy_and_error_state():
    viewmodel = ViewModelBase()

    assert viewmodel.busy is False
    assert viewmodel.error_message == ""
    assert viewmodel.is_disposed is False

    viewmodel.set_busy(True)
    viewmodel.set_error_message("boom")

    assert viewmodel.busy is True
    assert viewmodel.error_message == "boom"

    viewmodel.clear_error_message()

    assert viewmodel.error_message == ""


def test_viewmodel_base_closes_tracked_subscriptions_on_dispose():
    subscription = _Subscription()
    viewmodel = ViewModelBase()

    viewmodel.add_subscription(subscription)
    viewmodel.dispose()

    assert subscription.closed is True
    assert viewmodel.is_disposed is True


def test_viewmodel_base_requests_refresh_for_matching_application_events():
    bus = InMemoryApplicationEventBus()
    viewmodel = ViewModelBase()
    refresh_calls: list[bool] = []
    viewmodel.refresh_requested.connect(lambda: refresh_calls.append(True))

    viewmodel.subscribe_to_events(bus, kinds={ApplicationEventKind.PROJECTS_INVALIDATED})

    bus.publish(ProjectsInvalidatedEvent())

    assert refresh_calls == [True]

    viewmodel.dispose()
    bus.publish(ProjectsInvalidatedEvent())

    assert refresh_calls == [True]


def test_viewmodel_base_bind_refresh_on_events_runs_hook_before_refresh():
    bus = InMemoryApplicationEventBus()
    viewmodel = ViewModelBase()
    observed: list[str] = []
    viewmodel.refresh_requested.connect(lambda: observed.append("refresh"))

    viewmodel.bind_refresh_on_events(
        bus,
        kinds={ApplicationEventKind.PROJECTS_INVALIDATED},
        before_refresh=lambda event: observed.append(event.kind.value),
    )

    bus.publish(ProjectsInvalidatedEvent())

    assert observed == ["projects_invalidated", "refresh"]


def test_route_state_scope_tracks_app_project_and_document_levels():
    assert RouteState().scope.value == "app"
    assert RouteState(primary=PrimaryRoute.WORK, project_id="proj-1").scope.value == "project"
    assert (
        RouteState(
            primary=PrimaryRoute.WORK,
            project_id="proj-1",
            document_id=3,
            document_section=DocumentSection.TRANSLATION,
        ).scope.value
        == "document"
    )


def test_route_state_viewmodel_can_open_project_document_and_modals():
    viewmodel = RouteStateViewModel()

    viewmodel.open_project("proj-1", primary=PrimaryRoute.TERMS)
    assert viewmodel.route_state() == RouteState(primary=PrimaryRoute.TERMS, project_id="proj-1")
    assert viewmodel.scope == "project"

    viewmodel.open_document("proj-1", 7, DocumentSection.OCR)
    assert viewmodel.route_state() == RouteState(
        primary=PrimaryRoute.WORK,
        project_id="proj-1",
        document_id=7,
        document_section=DocumentSection.OCR,
    )
    assert viewmodel.scope == "document"

    viewmodel.open_project_settings()
    assert viewmodel.route_state().modal is ModalRoute.PROJECT_SETTINGS

    viewmodel.close_modal()
    assert viewmodel.route_state().modal is None


def test_route_state_viewmodel_maps_navigation_targets_to_new_shell_state():
    viewmodel = RouteStateViewModel()

    viewmodel.apply_navigation_target(
        NavigationTarget(kind=NavigationTargetKind.DOCUMENT_IMAGES, project_id="proj-1", document_id=9)
    )
    assert viewmodel.route_state() == RouteState(
        primary=PrimaryRoute.WORK,
        project_id="proj-1",
        document_id=9,
        document_section=DocumentSection.IMAGES,
    )

    viewmodel.apply_navigation_target(NavigationTarget(kind=NavigationTargetKind.APP_SETUP))
    assert viewmodel.route_state().modal is ModalRoute.APP_SETTINGS

    viewmodel.apply_navigation_target(NavigationTarget(kind=NavigationTargetKind.QUEUE, project_id="proj-1"))
    assert viewmodel.route_state().modal is ModalRoute.QUEUE

    viewmodel.apply_navigation_target(NavigationTarget(kind=NavigationTargetKind.TERMS, project_id="proj-1"))
    assert viewmodel.route_state() == RouteState(primary=PrimaryRoute.TERMS, project_id="proj-1")


def test_route_state_helper_centralizes_navigation_target_mapping():
    assert route_state_from_navigation_target(NavigationTarget(kind=NavigationTargetKind.PROJECTS)) == RouteState()
    assert route_state_from_navigation_target(NavigationTarget(kind=NavigationTargetKind.APP_SETUP)) == RouteState(
        modal=ModalRoute.APP_SETTINGS
    )
    assert route_state_from_navigation_target(
        NavigationTarget(kind=NavigationTargetKind.PROJECT_SETUP, project_id="proj-1")
    ) == RouteState(
        primary=PrimaryRoute.WORK,
        project_id="proj-1",
        modal=ModalRoute.PROJECT_SETTINGS,
    )
    assert route_state_from_navigation_target(
        NavigationTarget(kind=NavigationTargetKind.QUEUE, project_id="proj-1")
    ) == RouteState(
        primary=PrimaryRoute.WORK,
        project_id="proj-1",
        modal=ModalRoute.QUEUE,
    )
