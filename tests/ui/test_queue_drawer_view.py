from __future__ import annotations

import threading

import pytest

from context_aware_translation.application.contracts.common import (
    AcceptedCommand,
    NavigationTarget,
    NavigationTargetKind,
    ProgressInfo,
    QueueActionKind,
    QueueStatus,
    UserMessage,
    UserMessageSeverity,
)
from context_aware_translation.application.contracts.queue import QueueItem, QueueState
from context_aware_translation.application.errors import ApplicationError, ApplicationErrorCode, ApplicationErrorPayload
from context_aware_translation.application.events import InMemoryApplicationEventBus, QueueChangedEvent
from tests.application.fakes import FakeQueueService

try:
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton, QWidget

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


@pytest.fixture(autouse=True)
def _close_queue_top_levels():
    yield
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, QWidget):
            widget.close()
            widget.deleteLater()
    QApplication.processEvents()


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


def _wait_until(predicate, *, timeout_ms: int = 1000) -> None:  # noqa: ANN001
    elapsed = 0
    while elapsed < timeout_ms:
        QApplication.processEvents()
        if predicate():
            return
        QTest.qWait(10)
        elapsed += 10
    assert predicate()


def test_queue_drawer_view_renders_backend_state():
    from context_aware_translation.ui.features.queue_drawer_view import QueueDrawerView

    service = FakeQueueService(state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = QueueDrawerView(service, bus)
    try:
        view.set_scope("proj-1", project_name="One Piece")

        assert "Running 1" in view.message_label.text()
        assert len(view._rows) == 1
        row = view._rows["task-1"]
        assert row.title_label.text() == "Read text from images"
        assert row.status_label.text() == "Running"
        assert "Document 4" in row.scope_label.text()
        assert not any(button.text() == "Refresh" for button in view.findChildren(QPushButton))
    finally:
        view.cleanup()


def test_queue_drawer_view_shows_translated_stage_and_progress_counts():
    from context_aware_translation.ui.features.queue_drawer_view import QueueDrawerView

    service = FakeQueueService(
        state=QueueState(
            items=[
                QueueItem(
                    queue_item_id="task-1",
                    title="Translate text",
                    project_id="proj-1",
                    document_id=4,
                    status=QueueStatus.RUNNING,
                    stage="term_memory",
                    progress=ProgressInfo(current=2, total=5, label="term_memory"),
                    related_target=NavigationTarget(
                        kind=NavigationTargetKind.DOCUMENT_TRANSLATION,
                        project_id="proj-1",
                        document_id=4,
                    ),
                    available_actions=[QueueActionKind.OPEN_RELATED_ITEM, QueueActionKind.CANCEL],
                )
            ]
        )
    )
    bus = InMemoryApplicationEventBus()
    view = QueueDrawerView(service, bus)
    try:
        row = view._rows["task-1"]
        assert row.detail_label.text() == "Stage: Summarizing term memory | Progress: 2/5"
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
        QApplication.processEvents()

        assert service.calls == [("get_queue", None), ("get_queue", "proj-1"), ("get_queue", "proj-1")]
        assert view._rows["task-1"].status_label.text() == "Done"
    finally:
        view.cleanup()


def test_queue_drawer_view_coalesces_repeated_queue_events_into_one_refresh():
    from context_aware_translation.ui.features.queue_drawer_view import QueueDrawerView

    service = FakeQueueService(state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = QueueDrawerView(service, bus)
    try:
        view.set_scope("proj-1", project_name="One Piece")
        service.calls.clear()
        service.state = _make_state(status=QueueStatus.DONE)

        bus.publish(QueueChangedEvent(project_id="proj-1"))
        bus.publish(QueueChangedEvent(project_id="proj-1"))
        QApplication.processEvents()

        assert service.calls == [("get_queue", "proj-1")]
    finally:
        view.cleanup()


def test_queue_drawer_view_reuses_existing_row_widgets_on_refresh():
    from context_aware_translation.ui.features.queue_drawer_view import QueueDrawerView

    service = FakeQueueService(state=_make_state())
    bus = InMemoryApplicationEventBus()
    view = QueueDrawerView(service, bus)
    try:
        original_row = view._rows["task-1"]
        service.state = _make_state(status=QueueStatus.DONE)

        bus.publish(QueueChangedEvent(project_id=None))
        QApplication.processEvents()

        assert view._rows["task-1"] is original_row
        assert original_row.status_label.text() == "Done"
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
        QApplication.processEvents()

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


def test_queue_drawer_view_marks_row_deleting_while_delete_runs_in_background():
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
    started = threading.Event()
    release = threading.Event()

    def _apply_action(request):  # noqa: ANN001
        service.calls.append(("apply_action", request))
        started.set()
        release.wait(timeout=1.0)
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

        assert started.wait(timeout=1.0)
        assert set(view._rows) == {"task-1", "task-2"}
        assert first_row.status_label.text() == "Deleting..."
        assert all(not button.isEnabled() for button in first_row._buttons.values() if button.isVisible())

        release.set()
        _wait_until(lambda: set(view._rows) == {"task-2"})

        second_row = view._rows["task-2"]
        started.clear()
        release.clear()
        second_row._buttons[QueueActionKind.DELETE].click()
        assert started.wait(timeout=1.0)
        assert second_row.status_label.text() == "Deleting..."
        release.set()
        _wait_until(lambda: view._rows == {})
        assert not view.empty_label.isHidden()
    finally:
        release.set()
        view.cleanup()


def test_queue_drawer_view_restores_row_after_failed_delete():
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
                )
            ]
        )
    )

    def _apply_action(request):  # noqa: ANN001
        service.calls.append(("apply_action", request))
        raise ApplicationError(
            ApplicationErrorPayload(
                code=ApplicationErrorCode.CONFLICT,
                message="Still cleaning up remote artifacts.",
            )
        )

    service.apply_action = _apply_action  # type: ignore[method-assign]
    bus = InMemoryApplicationEventBus()
    view = QueueDrawerView(service, bus)
    notices: list[UserMessage] = []
    view.notification_requested.connect(notices.append)
    try:
        row = view._rows["task-1"]
        row._buttons[QueueActionKind.DELETE].click()

        assert row.status_label.text() == "Deleting..."
        _wait_until(lambda: view._rows["task-1"].status_label.text() == "Done")

        restored_row = view._rows["task-1"]
        assert restored_row.status_label.text() == "Done"
        assert restored_row._buttons[QueueActionKind.DELETE].isEnabled()
        assert notices[-1].text == "Still cleaning up remote artifacts."
    finally:
        view.cleanup()
