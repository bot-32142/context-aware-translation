from __future__ import annotations

import pytest

from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    NavigationTarget,
    NavigationTargetKind,
    QueueActionKind,
    QueueStatus,
    UserMessage,
    UserMessageSeverity,
)
from context_aware_translation.application.contracts.queue import QueueItem, QueueState
from context_aware_translation.application.events import InMemoryApplicationEventBus, QueueChangedEvent
from tests.application.fakes import FakeQueueService

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


def _make_state(*, status: QueueStatus = QueueStatus.RUNNING) -> QueueState:
    return QueueState(
        items=[
            QueueItem(
                queue_item_id="task-1",
                title="Read text from images",
                project_id="proj-1",
                document_id=4,
                status=status,
                stage="ocr",
                related_target=NavigationTarget(
                    kind=NavigationTargetKind.DOCUMENT_OCR,
                    project_id="proj-1",
                    document_id=4,
                ),
                available_actions=[QueueActionKind.OPEN_RELATED_ITEM, QueueActionKind.CANCEL]
                if status is QueueStatus.RUNNING
                else [QueueActionKind.OPEN_RELATED_ITEM, QueueActionKind.RETRY, QueueActionKind.DELETE],
            )
        ]
    )


def test_queue_drawer_view_renders_backend_state():
    from context_aware_translation.ui.features.queue_drawer_view import QueueDrawerView

    service = FakeQueueService(state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = QueueDrawerView(service, bus)
    try:
        view.set_scope("proj-1", project_name="One Piece")

        assert view.title_label.text() == view.tr("Queue")
        assert "One Piece" in view.tip_label.text()
        assert "Running 1" in view.message_label.text()
        assert len(view._rows) == 1
        row = view._rows["task-1"]
        assert row.title_label.text() == "Read text from images"
        assert row.status_label.text() == "Running"
        assert "Document 4" in row.scope_label.text()
    finally:
        view.cleanup()


def test_queue_drawer_view_refreshes_on_matching_queue_event():
    from context_aware_translation.ui.features.queue_drawer_view import QueueDrawerView

    service = FakeQueueService(state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = QueueDrawerView(service, bus)
    try:
        view.set_scope("proj-1", project_name="One Piece")
        service.state = _make_state(status=QueueStatus.DONE)
        bus.publish(QueueChangedEvent(project_id="proj-1"))

        assert service.calls == [("get_queue", None), ("get_queue", "proj-1"), ("get_queue", "proj-1")]
        assert view._rows["task-1"].status_label.text() == "Done"
    finally:
        view.cleanup()


def test_queue_drawer_view_emits_open_related_target():
    from context_aware_translation.ui.features.queue_drawer_view import QueueDrawerView

    service = FakeQueueService(state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = QueueDrawerView(service, bus)
    opened: list[NavigationTarget] = []
    view.open_related_item_requested.connect(opened.append)
    try:
        row = view._rows["task-1"]
        row._buttons[QueueActionKind.OPEN_RELATED_ITEM].click()

        assert len(opened) == 1
        assert opened[0].kind is NavigationTargetKind.DOCUMENT_OCR
        assert service.calls == [("get_queue", None)]
    finally:
        view.cleanup()


def test_queue_drawer_view_applies_action_and_emits_notification():
    from context_aware_translation.ui.features.queue_drawer_view import QueueDrawerView

    service = FakeQueueService(state=_make_state(status=QueueStatus.FAILED))
    bus = InMemoryApplicationEventBus()
    view = QueueDrawerView(service, bus)
    notices: list[UserMessage] = []
    view.notification_requested.connect(notices.append)
    try:
        # Fake service falls back to AcceptedCommand(command_name="queue_action") when None.
        row = view._rows["task-1"]
        row._buttons[QueueActionKind.RETRY].click()

        assert service.calls[1][0] == "apply_action"
        request = service.calls[1][1]
        assert request.queue_item_id == "task-1"
        assert request.action is QueueActionKind.RETRY
        assert notices[-1].text == "Queue action 'queue_action' applied."
    finally:
        view.cleanup()


def test_queue_drawer_view_emits_completion_notification_after_refresh():
    from context_aware_translation.ui.features.queue_drawer_view import QueueDrawerView

    service = FakeQueueService(state=_make_state(status=QueueStatus.RUNNING))
    bus = InMemoryApplicationEventBus()
    view = QueueDrawerView(service, bus)
    notices: list[UserMessage] = []
    view.notification_requested.connect(notices.append)
    try:
        service.state = QueueState(
            items=[
                QueueItem(
                    queue_item_id="task-1",
                    title="Read text from images",
                    project_id="proj-1",
                    document_id=4,
                    status=QueueStatus.DONE,
                    related_target=NavigationTarget(
                        kind=NavigationTargetKind.DOCUMENT_OCR,
                        project_id="proj-1",
                        document_id=4,
                    ),
                    available_actions=[QueueActionKind.OPEN_RELATED_ITEM],
                )
            ]
        )
        bus.publish(QueueChangedEvent(project_id="proj-1"))

        assert notices[-1].severity is UserMessageSeverity.SUCCESS
        assert notices[-1].text == "Read text from images finished."
    finally:
        view.cleanup()


def test_queue_drawer_view_deduplicates_local_action_and_transition_notifications():
    from context_aware_translation.ui.features.queue_drawer_view import QueueDrawerView

    service = FakeQueueService(state=_make_state(status=QueueStatus.FAILED))

    def _apply_action(request):  # noqa: ANN001
        service.calls.append(("apply_action", request))
        service.state = QueueState(
            items=[
                QueueItem(
                    queue_item_id="task-1",
                    title="Read text from images",
                    project_id="proj-1",
                    document_id=4,
                    status=QueueStatus.DONE,
                    related_target=NavigationTarget(
                        kind=NavigationTargetKind.DOCUMENT_OCR,
                        project_id="proj-1",
                        document_id=4,
                    ),
                    available_actions=[QueueActionKind.OPEN_RELATED_ITEM],
                )
            ]
        )
        return AcceptedCommand(
            command_name="retry",
            message=UserMessage(severity=UserMessageSeverity.INFO, text="Retry queued."),
        )

    service.apply_action = _apply_action  # type: ignore[method-assign]
    bus = InMemoryApplicationEventBus()
    view = QueueDrawerView(service, bus)
    notices: list[UserMessage] = []
    view.notification_requested.connect(notices.append)
    try:
        row = view._rows["task-1"]
        row._buttons[QueueActionKind.RETRY].click()

        assert len(notices) == 1
        assert notices[0].text == "Retry queued."
    finally:
        view.cleanup()


def test_queue_drawer_view_deletes_rows_on_next_event_turn():
    from context_aware_translation.ui.features.queue_drawer_view import QueueDrawerView

    service = FakeQueueService(
        state=QueueState(
            items=[
                QueueItem(
                    queue_item_id="task-1",
                    title="Read text from images",
                    project_id="proj-1",
                    document_id=4,
                    status=QueueStatus.DONE,
                    related_target=NavigationTarget(
                        kind=NavigationTargetKind.DOCUMENT_OCR,
                        project_id="proj-1",
                        document_id=4,
                    ),
                    available_actions=[QueueActionKind.OPEN_RELATED_ITEM, QueueActionKind.DELETE],
                ),
                QueueItem(
                    queue_item_id="task-2",
                    title="Export terms",
                    project_id="proj-1",
                    document_id=4,
                    status=QueueStatus.DONE,
                    related_target=NavigationTarget(
                        kind=NavigationTargetKind.DOCUMENT_TERMS,
                        project_id="proj-1",
                        document_id=4,
                    ),
                    available_actions=[QueueActionKind.OPEN_RELATED_ITEM, QueueActionKind.DELETE],
                ),
            ]
        )
    )

    def _apply_action(request):  # noqa: ANN001
        service.calls.append(("apply_action", request))
        service.state = QueueState(
            items=[item for item in service.state.items if item.queue_item_id != request.queue_item_id]
        )
        return AcceptedCommand(command_name="delete")

    service.apply_action = _apply_action  # type: ignore[method-assign]
    bus = InMemoryApplicationEventBus()
    view = QueueDrawerView(service, bus)
    try:
        first_row = view._rows["task-1"]
        first_row._buttons[QueueActionKind.DELETE].click()

        assert set(view._rows) == {"task-1", "task-2"}

        QApplication.processEvents()

        assert set(view._rows) == {"task-2"}

        second_row = view._rows["task-2"]
        second_row._buttons[QueueActionKind.DELETE].click()

        assert set(view._rows) == {"task-2"}

        QApplication.processEvents()

        assert view._rows == {}
        assert not view.empty_label.isHidden()
    finally:
        view.cleanup()
