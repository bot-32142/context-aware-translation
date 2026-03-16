from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

from context_aware_translation.application.events import (
    ApplicationEventKind,
    ApplicationEventPayload,
    ApplicationEventSubscriber,
    DocumentInvalidatedEvent,
    ProjectsInvalidatedEvent,
    QueueChangedEvent,
    SetupInvalidatedEvent,
    TermsInvalidatedEvent,
    WorkboardInvalidatedEvent,
)


class QtApplicationEventBridge(QObject):
    """Adapt application events into Qt signals.

    The application event bus is the system of record. This bridge only turns
    those framework-agnostic events into Qt-friendly notifications.
    """

    event_received = Signal(object)
    projects_invalidated = Signal(object)
    queue_changed = Signal(object)
    workboard_invalidated = Signal(object)
    document_invalidated = Signal(object)
    terms_invalidated = Signal(object)
    setup_invalidated = Signal(object)

    _enqueue_event = Signal(object)

    def __init__(self, events: ApplicationEventSubscriber, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._subscription = events.subscribe(self._on_event_from_any_thread)
        self._enqueue_event.connect(self._dispatch_event, Qt.ConnectionType.QueuedConnection)

    def close(self) -> None:
        self._subscription.close()

    def __del__(self) -> None:
        self.close()

    def _on_event_from_any_thread(self, event: ApplicationEventPayload) -> None:
        if QThread.currentThread() is self.thread():
            self._dispatch_event(event)
            return
        self._enqueue_event.emit(event)

    @Slot(object)
    def _dispatch_event(self, event: ApplicationEventPayload) -> None:
        self.event_received.emit(event)
        if event.kind is ApplicationEventKind.PROJECTS_INVALIDATED:
            self.projects_invalidated.emit(event)
        elif event.kind is ApplicationEventKind.QUEUE_CHANGED:
            self.queue_changed.emit(event)
        elif event.kind is ApplicationEventKind.WORKBOARD_INVALIDATED:
            self.workboard_invalidated.emit(event)
        elif event.kind is ApplicationEventKind.DOCUMENT_INVALIDATED:
            self.document_invalidated.emit(event)
        elif event.kind is ApplicationEventKind.TERMS_INVALIDATED:
            self.terms_invalidated.emit(event)
        elif event.kind is ApplicationEventKind.SETUP_INVALIDATED:
            self.setup_invalidated.emit(event)


__all__ = [
    "QtApplicationEventBridge",
    "ApplicationEventPayload",
    "ProjectsInvalidatedEvent",
    "QueueChangedEvent",
    "WorkboardInvalidatedEvent",
    "DocumentInvalidatedEvent",
    "TermsInvalidatedEvent",
    "SetupInvalidatedEvent",
]
