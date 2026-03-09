from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Iterable
from enum import StrEnum
from typing import Protocol

from pydantic import Field

from context_aware_translation.application.contracts.common import ContractModel, DocumentSection


class ApplicationEventKind(StrEnum):
    PROJECTS_INVALIDATED = "projects_invalidated"
    QUEUE_CHANGED = "queue_changed"
    WORKBOARD_INVALIDATED = "workboard_invalidated"
    DOCUMENT_INVALIDATED = "document_invalidated"
    TERMS_INVALIDATED = "terms_invalidated"
    SETUP_INVALIDATED = "setup_invalidated"


class ApplicationEvent(ContractModel):
    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    kind: ApplicationEventKind


class ProjectsInvalidatedEvent(ApplicationEvent):
    kind: ApplicationEventKind = ApplicationEventKind.PROJECTS_INVALIDATED


class QueueChangedEvent(ApplicationEvent):
    kind: ApplicationEventKind = ApplicationEventKind.QUEUE_CHANGED
    project_id: str | None = None


class WorkboardInvalidatedEvent(ApplicationEvent):
    kind: ApplicationEventKind = ApplicationEventKind.WORKBOARD_INVALIDATED
    project_id: str | None = None


class DocumentInvalidatedEvent(ApplicationEvent):
    kind: ApplicationEventKind = ApplicationEventKind.DOCUMENT_INVALIDATED
    project_id: str | None = None
    document_id: int | None = None
    sections: list[DocumentSection] = Field(default_factory=list)


class TermsInvalidatedEvent(ApplicationEvent):
    kind: ApplicationEventKind = ApplicationEventKind.TERMS_INVALIDATED
    project_id: str | None = None
    document_id: int | None = None


class SetupInvalidatedEvent(ApplicationEvent):
    kind: ApplicationEventKind = ApplicationEventKind.SETUP_INVALIDATED
    project_id: str | None = None


ApplicationEventPayload = (
    ProjectsInvalidatedEvent
    | QueueChangedEvent
    | WorkboardInvalidatedEvent
    | DocumentInvalidatedEvent
    | TermsInvalidatedEvent
    | SetupInvalidatedEvent
)
ApplicationEventHandler = Callable[[ApplicationEventPayload], None]
ApplicationEventFilter = Callable[[ApplicationEventPayload], bool]


class EventSubscription(Protocol):
    def close(self) -> None: ...


class ApplicationEventPublisher(Protocol):
    def publish(self, event: ApplicationEventPayload) -> None: ...

    def publish_many(self, events: Iterable[ApplicationEventPayload]) -> None: ...


class ApplicationEventSubscriber(Protocol):
    def subscribe(
        self,
        handler: ApplicationEventHandler,
        *,
        kinds: set[ApplicationEventKind] | None = None,
        predicate: ApplicationEventFilter | None = None,
    ) -> EventSubscription: ...


class _Subscription:
    def __init__(self, bus: InMemoryApplicationEventBus, subscription_id: str) -> None:
        self._bus = bus
        self._subscription_id = subscription_id
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._bus._unsubscribe(self._subscription_id)


class InMemoryApplicationEventBus(ApplicationEventPublisher, ApplicationEventSubscriber):
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscriptions: dict[str, tuple[ApplicationEventHandler, set[ApplicationEventKind] | None, ApplicationEventFilter | None]] = {}

    def publish(self, event: ApplicationEventPayload) -> None:
        with self._lock:
            subscriptions = list(self._subscriptions.values())
        for handler, kinds, predicate in subscriptions:
            if kinds is not None and event.kind not in kinds:
                continue
            if predicate is not None and not predicate(event):
                continue
            handler(event)

    def publish_many(self, events: Iterable[ApplicationEventPayload]) -> None:
        for event in events:
            self.publish(event)

    def subscribe(
        self,
        handler: ApplicationEventHandler,
        *,
        kinds: set[ApplicationEventKind] | None = None,
        predicate: ApplicationEventFilter | None = None,
    ) -> EventSubscription:
        subscription_id = uuid.uuid4().hex
        with self._lock:
            self._subscriptions[subscription_id] = (handler, set(kinds) if kinds is not None else None, predicate)
        return _Subscription(self, subscription_id)

    def _unsubscribe(self, subscription_id: str) -> None:
        with self._lock:
            self._subscriptions.pop(subscription_id, None)
