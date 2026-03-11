from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Property, QObject, Signal

from context_aware_translation.application.events import (
    ApplicationEventFilter,
    ApplicationEventHandler,
    ApplicationEventKind,
    ApplicationEventPayload,
    ApplicationEventSubscriber,
    EventSubscription,
)


class ViewModelBase(QObject):
    """Minimal QObject base for QML-facing viewmodels."""

    state_changed = Signal()
    busy_changed = Signal()
    error_message_changed = Signal()
    refresh_requested = Signal()
    disposed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._busy = False
        self._error_message = ""
        self._disposed = False
        self._subscriptions: list[EventSubscription] = []

    @Property(bool, notify=busy_changed)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=error_message_changed)
    def error_message(self) -> str:
        return self._error_message

    @Property(bool, notify=disposed)
    def is_disposed(self) -> bool:
        return self._disposed

    def set_busy(self, value: bool) -> None:
        if self._busy == value:
            return
        self._busy = value
        self.busy_changed.emit()
        self.state_changed.emit()

    def set_error_message(self, message: str | None) -> None:
        normalized = message or ""
        if self._error_message == normalized:
            return
        self._error_message = normalized
        self.error_message_changed.emit()
        self.state_changed.emit()

    def clear_error_message(self) -> None:
        self.set_error_message(None)

    def mark_changed(self) -> None:
        self.state_changed.emit()

    def request_refresh(self) -> None:
        self.refresh_requested.emit()

    def add_subscription(self, subscription: EventSubscription) -> EventSubscription:
        if self._disposed:
            subscription.close()
            return subscription
        self._subscriptions.append(subscription)
        return subscription

    def subscribe_to_events(
        self,
        events: ApplicationEventSubscriber,
        *,
        kinds: set[ApplicationEventKind] | None = None,
        predicate: ApplicationEventFilter | None = None,
        handler: ApplicationEventHandler | None = None,
    ) -> EventSubscription:
        callback = handler or self._handle_application_event
        subscription = events.subscribe(callback, kinds=kinds, predicate=predicate)
        return self.add_subscription(subscription)

    def bind_refresh_on_events(
        self,
        events: ApplicationEventSubscriber,
        *,
        kinds: set[ApplicationEventKind] | None = None,
        predicate: ApplicationEventFilter | None = None,
        before_refresh: Callable[[ApplicationEventPayload], None] | None = None,
    ) -> EventSubscription:
        def _handler(event: ApplicationEventPayload) -> None:
            if before_refresh is not None:
                before_refresh(event)
            self.request_refresh()

        return self.subscribe_to_events(events, kinds=kinds, predicate=predicate, handler=_handler)

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        subscriptions = list(self._subscriptions)
        self._subscriptions.clear()
        for subscription in subscriptions:
            subscription.close()
        self.disposed.emit()

    def _handle_application_event(self, _event: ApplicationEventPayload) -> None:
        self.request_refresh()
