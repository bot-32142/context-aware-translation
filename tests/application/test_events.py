from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

from context_aware_translation.adapters.qt.application_event_bridge import QtApplicationEventBridge
from context_aware_translation.application.composition import build_application_context
from context_aware_translation.application.contracts.app_setup import (
    ConnectionDraft,
    SaveWorkflowProfileRequest,
    SetupWizardRequest,
)
from context_aware_translation.application.contracts.common import ProviderKind
from context_aware_translation.application.contracts.projects import CreateProjectRequest
from context_aware_translation.application.events import (
    ApplicationEventKind,
    InMemoryApplicationEventBus,
    ProjectsInvalidatedEvent,
    QueueChangedEvent,
)


def _ensure_qt_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    assert isinstance(app, QApplication)
    return app


def _build_configured_context(tmp_path: Path):
    context = build_application_context(library_root=tmp_path)
    context.services.app_setup.run_setup_wizard(
        SetupWizardRequest(
            providers=[ProviderKind.OPENAI],
            connections=[
                ConnectionDraft(
                    display_name="OpenAI",
                    provider=ProviderKind.OPENAI,
                    api_key="test-key",
                )
            ],
        )
    )
    return context


def test_event_bus_filters_and_unsubscribes() -> None:
    bus = InMemoryApplicationEventBus()
    seen_all: list[ApplicationEventKind] = []
    seen_queue: list[ApplicationEventKind] = []

    sub_all = bus.subscribe(lambda event: seen_all.append(event.kind))
    sub_queue = bus.subscribe(
        lambda event: seen_queue.append(event.kind),
        kinds={ApplicationEventKind.QUEUE_CHANGED},
    )

    bus.publish(QueueChangedEvent(project_id="proj-1"))
    bus.publish(ProjectsInvalidatedEvent())
    sub_queue.close()
    bus.publish(QueueChangedEvent(project_id="proj-2"))
    sub_all.close()

    assert seen_all == [
        ApplicationEventKind.QUEUE_CHANGED,
        ApplicationEventKind.PROJECTS_INVALIDATED,
        ApplicationEventKind.QUEUE_CHANGED,
    ]
    assert seen_queue == [ApplicationEventKind.QUEUE_CHANGED]


def test_event_bus_isolates_subscriber_failures() -> None:
    bus = InMemoryApplicationEventBus()
    seen: list[ApplicationEventKind] = []

    bus.subscribe(lambda _event: (_ for _ in ()).throw(RuntimeError("boom")))
    bus.subscribe(lambda event: seen.append(event.kind))

    bus.publish(QueueChangedEvent(project_id="proj-1"))

    assert seen == [ApplicationEventKind.QUEUE_CHANGED]


def test_services_publish_invalidation_events(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    seen: list[ApplicationEventKind] = []
    subscription = context.events.subscribe(lambda event: seen.append(event.kind))
    try:
        created = context.services.projects.create_project(
            CreateProjectRequest(name="One Piece", target_language="English")
        )
        assert created.project.name == "One Piece"
        assert ApplicationEventKind.PROJECTS_INVALIDATED in seen
        assert ApplicationEventKind.SETUP_INVALIDATED in seen
        assert ApplicationEventKind.WORKBOARD_INVALIDATED in seen

        seen.clear()
        state = context.services.app_setup.get_state()
        profile = state.shared_profiles[0]
        context.services.app_setup.save_workflow_profile(SaveWorkflowProfileRequest(profile=profile))
        assert ApplicationEventKind.SETUP_INVALIDATED in seen
    finally:
        subscription.close()
        context.close()


def test_task_engine_signal_is_forwarded_to_application_events(tmp_path: Path) -> None:
    _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    seen: list[ApplicationEventKind] = []
    subscription = context.events.subscribe(lambda event: seen.append(event.kind))
    try:
        created = context.services.projects.create_project(
            CreateProjectRequest(name="Signal Test", target_language="English")
        )
        seen.clear()
        context.runtime.task_engine.tasks_changed.emit(created.project.project_id)

        assert ApplicationEventKind.QUEUE_CHANGED in seen
        assert ApplicationEventKind.WORKBOARD_INVALIDATED in seen
        assert ApplicationEventKind.DOCUMENT_INVALIDATED in seen
        assert ApplicationEventKind.TERMS_INVALIDATED in seen
        assert ApplicationEventKind.PROJECTS_INVALIDATED in seen
    finally:
        subscription.close()
        context.close()


def test_worker_task_change_uses_single_coalesced_application_event_flush(tmp_path: Path) -> None:
    app = _ensure_qt_app()
    context = _build_configured_context(tmp_path)
    seen: list[ApplicationEventKind] = []
    subscription = context.events.subscribe(lambda event: seen.append(event.kind))
    try:
        context.runtime.worker_deps.notify_task_changed("proj-1")
        app.processEvents()
        assert seen == []

        context.runtime.task_engine._flush_task_changed()

        assert seen == [
            ApplicationEventKind.QUEUE_CHANGED,
            ApplicationEventKind.WORKBOARD_INVALIDATED,
            ApplicationEventKind.DOCUMENT_INVALIDATED,
            ApplicationEventKind.TERMS_INVALIDATED,
            ApplicationEventKind.PROJECTS_INVALIDATED,
        ]
    finally:
        subscription.close()
        context.close()


def test_qt_application_event_bridge_emits_typed_signals() -> None:
    app = _ensure_qt_app()
    bus = InMemoryApplicationEventBus()
    bridge = QtApplicationEventBridge(bus)
    seen: list[tuple[str, str | None]] = []

    bridge.event_received.connect(lambda event: seen.append(("event", event.kind.value)))
    bridge.queue_changed.connect(lambda event: seen.append(("queue", event.project_id)))

    bus.publish(QueueChangedEvent(project_id="proj-1"))
    app.processEvents()
    bridge.close()

    assert seen == [("event", "queue_changed"), ("queue", "proj-1")]
