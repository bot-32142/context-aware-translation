from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.adapters.qt.application_event_bridge import QtApplicationEventBridge
from context_aware_translation.application.contracts.common import (
    QueueActionKind,
    QueueStatus,
    UserMessage,
    UserMessageSeverity,
)
from context_aware_translation.application.contracts.queue import QueueActionRequest, QueueItem, QueueState
from context_aware_translation.application.errors import ApplicationError
from context_aware_translation.application.events import ApplicationEventSubscriber, QueueChangedEvent
from context_aware_translation.application.services.queue import QueueService
from context_aware_translation.ui.tips import create_tip_label
from context_aware_translation.ui.widgets.hybrid_controls import apply_hybrid_control_theme, set_button_tone

_STATUS_LABELS: dict[QueueStatus, str] = {
    QueueStatus.RUNNING: "Running",
    QueueStatus.QUEUED: "Queued",
    QueueStatus.BLOCKED: "Blocked",
    QueueStatus.FAILED: "Failed",
    QueueStatus.DONE: "Done",
    QueueStatus.CANCELLED: "Cancelled",
}


class _QueueItemCard(QFrame):
    action_requested = Signal(object, object)  # QueueItem, QueueActionKind

    def __init__(self, item: QueueItem, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._item = item
        self._buttons: dict[QueueActionKind, QPushButton] = {}
        self._init_ui()
        self.set_item(item)

    def _init_ui(self) -> None:
        self.setObjectName("queueItemCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        apply_hybrid_control_theme(
            self,
            extra_stylesheet="""
            QFrame#queueItemCard {
                background: #fcfaf6;
                border: 1px solid #d9d0c4;
                border-radius: 14px;
            }
            """,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-weight: 600;")
        top_row.addWidget(self.title_label, 1)
        self.status_label = QLabel()
        self.status_label.setStyleSheet("color: #675b4e; font-weight: 600;")
        top_row.addWidget(self.status_label)
        layout.addLayout(top_row)

        self.scope_label = QLabel()
        self.scope_label.setStyleSheet("color: #675b4e;")
        layout.addWidget(self.scope_label)

        self.detail_label = QLabel()
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet("color: #786b5e;")
        layout.addWidget(self.detail_label)

        self.blocker_label = create_tip_label("")
        self.blocker_label.setStyleSheet("QLabel { color: #b42318; }")
        self.blocker_label.hide()
        layout.addWidget(self.blocker_label)

        self.error_label = create_tip_label("")
        self.error_label.setStyleSheet("QLabel { color: #b42318; }")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        button_row = QHBoxLayout()
        for action in (
            QueueActionKind.OPEN_RELATED_ITEM,
            QueueActionKind.RUN,
            QueueActionKind.CANCEL,
            QueueActionKind.RETRY,
            QueueActionKind.DELETE,
        ):
            button = QPushButton()
            button.clicked.connect(lambda _checked=False, action=action: self.action_requested.emit(self._item, action))
            self._buttons[action] = button
            set_button_tone(
                button,
                "danger" if action is QueueActionKind.DELETE else None,
                size="compact",
            )
            button_row.addWidget(button)
        button_row.addStretch()
        layout.addLayout(button_row)

    def set_item(self, item: QueueItem) -> None:
        self._item = item
        self.title_label.setText(item.title)
        self.status_label.setText(_STATUS_LABELS[item.status])
        self.scope_label.setText(self._scope_text(item))
        self.scope_label.setVisible(bool(self.scope_label.text()))
        self.detail_label.setText(self._detail_text(item))
        self.detail_label.setVisible(bool(self.detail_label.text()))
        blocker_text = item.blocker.message if item.blocker is not None else ""
        self.blocker_label.setText(blocker_text)
        self.blocker_label.setVisible(bool(blocker_text))
        self.error_label.setText(item.error_message or "")
        self.error_label.setVisible(bool(item.error_message))

        labels = {
            QueueActionKind.OPEN_RELATED_ITEM: self.tr("Open"),
            QueueActionKind.RUN: self.tr("Run"),
            QueueActionKind.CANCEL: self.tr("Cancel"),
            QueueActionKind.RETRY: self.tr("Retry"),
            QueueActionKind.DELETE: self.tr("Delete"),
        }
        for action, button in self._buttons.items():
            button.setText(labels[action])
            enabled = action in item.available_actions and not (
                action is QueueActionKind.OPEN_RELATED_ITEM and item.related_target is None
            )
            button.setVisible(enabled)
            button.setEnabled(enabled)

    def retranslateUi(self) -> None:
        self.set_item(self._item)

    def _scope_text(self, item: QueueItem) -> str:
        parts: list[str] = []
        if item.project_id:
            parts.append(self.tr("Project: {0}").format(item.project_id))
        if item.document_id is not None:
            parts.append(self.tr("Document {0}").format(item.document_id))
        return " | ".join(parts)

    def _detail_text(self, item: QueueItem) -> str:
        parts: list[str] = []
        if item.stage:
            parts.append(self.tr("Stage: {0}").format(item.stage))
        if item.progress is not None and item.progress.total is not None and item.progress.current is not None:
            parts.append(self.tr("Progress: {0}/{1}").format(item.progress.current, item.progress.total))
        elif item.progress is not None and item.progress.label:
            parts.append(item.progress.label)
        return " | ".join(parts)


class QueueDrawerView(QWidget):
    """Application-backed queue drawer content."""

    open_related_item_requested = Signal(object)  # NavigationTarget
    notification_requested = Signal(object)  # UserMessage
    _refresh_requested = Signal()

    def __init__(
        self,
        service: QueueService,
        events: ApplicationEventSubscriber,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._scope_project_id: str | None = None
        self._scope_label: str | None = None
        self._rows: dict[str, _QueueItemCard] = {}
        self._last_status: dict[str, QueueStatus] = {}
        self._suppressed_transition_notifications: set[str] = set()
        self._loaded_once = False
        self._refresh_pending = False
        self._event_bridge = QtApplicationEventBridge(events, parent=self)
        self._event_bridge.queue_changed.connect(self._on_queue_changed)
        self._refresh_requested.connect(self._flush_queued_refresh, Qt.ConnectionType.QueuedConnection)
        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        apply_hybrid_control_theme(
            self,
            extra_stylesheet="""
            QFrame#queueEmptyCard {
                background: #f8f3ea;
                border: 1px dashed #d9d0c4;
                border-radius: 18px;
            }
            QLabel#queueEmptyTitle {
                color: #2f251d;
                font-size: 18px;
                font-weight: 600;
            }
            """,
        )

        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.title_label.hide()
        layout.addWidget(self.title_label)

        self.tip_label = create_tip_label("")
        self.tip_label.hide()
        layout.addWidget(self.tip_label)

        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet("color: #475467;")
        layout.addWidget(self.message_label)

        self.body_stack = QStackedWidget(self)
        self.body_stack.setMinimumHeight(240)

        self.empty_page = QWidget(self.body_stack)
        empty_layout = QVBoxLayout(self.empty_page)
        empty_layout.setContentsMargins(0, 0, 0, 0)
        empty_layout.addStretch(1)
        self.empty_card = QFrame(self.empty_page)
        self.empty_card.setObjectName("queueEmptyCard")
        self.empty_card.setMinimumHeight(180)
        empty_card_layout = QVBoxLayout(self.empty_card)
        empty_card_layout.setContentsMargins(22, 22, 22, 22)
        empty_card_layout.setSpacing(8)
        self.empty_title_label = QLabel(self.tr("Queue is clear"), self.empty_card)
        self.empty_title_label.setObjectName("queueEmptyTitle")
        self.empty_title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_card_layout.addWidget(self.empty_title_label)
        self.empty_label = create_tip_label(self.tr("No background actions right now."))
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_card_layout.addWidget(self.empty_label)
        empty_layout.addWidget(self.empty_card)
        empty_layout.addStretch(1)
        self.body_stack.addWidget(self.empty_page)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.rows_container = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(8)
        self.rows_layout.addStretch()
        self.scroll_area.setWidget(self.rows_container)
        self.body_stack.addWidget(self.scroll_area)
        layout.addWidget(self.body_stack, 1)

        self.refresh_button = QPushButton(self.tr("Refresh"))
        self.refresh_button.clicked.connect(self.refresh)
        set_button_tone(self.refresh_button, "ghost")
        layout.addWidget(self.refresh_button)

        self.retranslateUi()

    def set_scope(self, project_id: str | None, *, project_name: str | None = None) -> None:
        scope_changed = project_id != self._scope_project_id or project_name != self._scope_label
        self._scope_project_id = project_id
        self._scope_label = project_name
        self.retranslateUi()
        if scope_changed:
            self.refresh()

    def refresh(self) -> None:
        self._refresh_pending = False
        state = self._service.get_queue(project_id=self._scope_project_id)
        self._apply_state(state)

    def cleanup(self) -> None:
        self._event_bridge.close()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:
        self.title_label.setText(self.tr("Queue"))
        if self._scope_project_id is None:
            self.tip_label.setText(self.tr("Showing background actions across all projects."))
        elif self._scope_label:
            self.tip_label.setText(self.tr("Showing background actions for {0}.").format(self._scope_label))
        else:
            self.tip_label.setText(self.tr("Showing background actions for the current project."))
        self.empty_title_label.setText(self.tr("Queue is clear"))
        self.empty_label.setText(self.tr("No background actions right now."))
        self.refresh_button.setText(self.tr("Refresh"))
        for row in self._rows.values():
            row.retranslateUi()

    def _apply_state(self, state: QueueState) -> None:
        self.message_label.setText(self._summary_text(state))
        self.body_stack.setCurrentWidget(self.scroll_area if state.items else self.empty_page)

        self._clear_rows()
        previous_status = dict(self._last_status)
        self._last_status = {}
        for item in state.items:
            self._last_status[item.queue_item_id] = item.status
            row = _QueueItemCard(item, parent=self.rows_container)
            row.action_requested.connect(self._on_action_requested)
            self._rows[item.queue_item_id] = row
            self.rows_layout.insertWidget(self.rows_layout.count() - 1, row)
        self._suppressed_transition_notifications.intersection_update(self._last_status)

        if self._loaded_once:
            self._emit_transition_notifications(previous_status, state.items)
        self._loaded_once = True

    def _clear_rows(self) -> None:
        for row in self._rows.values():
            row.deleteLater()
        self._rows.clear()

    def _summary_text(self, state: QueueState) -> str:
        if not state.items:
            return self.tr("Nothing is running or queued.")
        running = sum(1 for item in state.items if item.status is QueueStatus.RUNNING)
        queued = sum(1 for item in state.items if item.status is QueueStatus.QUEUED)
        blocked = sum(1 for item in state.items if item.status is QueueStatus.BLOCKED)
        failed = sum(1 for item in state.items if item.status is QueueStatus.FAILED)
        return self.tr("Running {0} | Queued {1} | Blocked {2} | Failed {3}").format(
            running,
            queued,
            blocked,
            failed,
        )

    def _emit_transition_notifications(self, previous: dict[str, QueueStatus], items: list[QueueItem]) -> None:
        for item in items:
            if item.queue_item_id in self._suppressed_transition_notifications:
                self._suppressed_transition_notifications.discard(item.queue_item_id)
                continue
            old_status = previous.get(item.queue_item_id)
            if old_status is None or old_status is item.status:
                continue
            message: UserMessage | None = None
            if item.status is QueueStatus.DONE:
                message = UserMessage(
                    severity=UserMessageSeverity.SUCCESS, text=self.tr("{0} finished.").format(item.title)
                )
            elif item.status is QueueStatus.FAILED:
                text = item.error_message or self.tr("{0} failed.").format(item.title)
                message = UserMessage(severity=UserMessageSeverity.ERROR, text=text)
            elif item.status is QueueStatus.CANCELLED:
                message = UserMessage(
                    severity=UserMessageSeverity.WARNING,
                    text=self.tr("{0} was cancelled.").format(item.title),
                )
            if message is not None:
                self.notification_requested.emit(message)

    def _on_queue_changed(self, event: QueueChangedEvent) -> None:
        if self._scope_project_id is not None and event.project_id not in {None, self._scope_project_id}:
            return
        self.refresh()

    def _on_action_requested(self, item: QueueItem, action: QueueActionKind) -> None:
        if action is QueueActionKind.OPEN_RELATED_ITEM:
            if item.related_target is not None:
                self.open_related_item_requested.emit(item.related_target)
            return
        try:
            result = self._service.apply_action(QueueActionRequest(queue_item_id=item.queue_item_id, action=action))
        except ApplicationError as exc:
            self.notification_requested.emit(
                UserMessage(severity=UserMessageSeverity.ERROR, text=exc.payload.message, code=exc.payload.code.value)
            )
            self._queue_refresh()
            return
        self._suppressed_transition_notifications.add(item.queue_item_id)
        if result.message is not None:
            self.notification_requested.emit(result.message)
        else:
            self.notification_requested.emit(
                UserMessage(
                    severity=UserMessageSeverity.INFO,
                    text=self.tr("Queue action '{0}' applied.").format(result.command_name),
                )
            )
        self._queue_refresh()

    def _queue_refresh(self) -> None:
        if self._refresh_pending:
            return
        self._refresh_pending = True
        self._refresh_requested.emit()

    def _flush_queued_refresh(self) -> None:
        if not self._refresh_pending:
            return
        self.refresh()
