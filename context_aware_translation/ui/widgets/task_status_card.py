"""TaskStatusCard and TaskStatusStrip — compact inline task status widgets."""

from __future__ import annotations

from contextlib import suppress

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.workflow.tasks.models import (
    TERMINAL_TASK_STATUSES,
    TaskAction,
)

from ..i18n import translate_task_block_reason, translate_task_phase, translate_task_status
from ..tasks.task_view_model_mapper import map_tasks_to_row_vms
from ..tasks.task_view_models import TaskRowVM

_AUTO_REFRESH_INTERVAL_MS = 3000

# Status → CSS background color for the chip label
_STATUS_COLORS: dict[str, str] = {
    "completed": "#2e7d32",  # green
    "completed_with_errors": "#388e3c",
    "running": "#1565c0",  # blue
    "queued": "#f57f17",  # yellow/amber
    "cancel_requested": "#e65100",
    "cancelling": "#e65100",
    "failed": "#b71c1c",  # red
    "cancelled": "#616161",  # gray
    "paused": "#616161",
}
_DEFAULT_CHIP_COLOR = "#616161"


def _chip_style(status: str) -> str:
    color = _STATUS_COLORS.get(status, _DEFAULT_CHIP_COLOR)
    return (
        f"background-color: {color}; color: white; border-radius: 4px;"
        " padding: 1px 6px; font-size: 11px; font-weight: bold;"
    )


def _progress_text(vm: TaskRowVM) -> str:
    if vm.total_items > 0:
        template = QCoreApplication.translate("TaskStatusCard", "{0}/{1} items")
        return template.format(vm.completed_items, vm.total_items)
    return ""


def _pick_primary_vm(vms: list[TaskRowVM]) -> TaskRowVM | None:
    """Return the most relevant task: first non-terminal, else most-recent."""
    if not vms:
        return None
    for vm in vms:
        if vm.status not in TERMINAL_TASK_STATUSES:
            return vm
    return vms[0]  # already sorted newest-first


# ---------------------------------------------------------------------------
# TaskStatusCard
# ---------------------------------------------------------------------------


class TaskStatusCard(QWidget):
    """Compact inline card showing the most relevant task for given task_types.

    Layout::

        +-----------------------------------------------+
        | [Status Chip] display_label                    |
        | Phase: extraction | 45/120 items               |
        | Last error: (if any)                           |
        | [Cancel] [Run/Retry] [Open Activity]           |
        +-----------------------------------------------+

    Signals:
        open_activity_requested(): emitted when the user clicks "Open Activity".
    """

    open_activity_requested = Signal()

    def __init__(
        self,
        task_engine,
        book_id: str,
        task_types: list[str],
        display_label: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._engine = task_engine
        self._book_id = book_id
        self._task_types = list(task_types)
        self._display_label = display_label
        self._current_vm: TaskRowVM | None = None

        self._init_ui()
        self.retranslateUi()

        self._engine.tasks_changed.connect(self._on_tasks_changed)

        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(_AUTO_REFRESH_INTERVAL_MS)
        self._auto_timer.timeout.connect(self._on_auto_refresh)
        self._auto_timer.start()

        self.refresh()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-fetch tasks and update the card display."""
        records = []
        for tt in self._task_types:
            records.extend(self._engine.get_tasks(self._book_id, task_type=tt))
        records.sort(key=lambda r: r.updated_at, reverse=True)
        vms = map_tasks_to_row_vms(records)
        self._current_vm = _pick_primary_vm(vms)

        if self._current_vm is None:
            self.setVisible(False)
            return

        self.setVisible(True)
        self._update_display(self._current_vm)
        self._update_buttons(self._current_vm)

    def cleanup(self) -> None:
        """Stop timer and disconnect engine signal."""
        self._auto_timer.stop()
        with suppress(TypeError, RuntimeError):
            self._engine.tasks_changed.disconnect(self._on_tasks_changed)

    # ------------------------------------------------------------------
    # i18n
    # ------------------------------------------------------------------

    def retranslateUi(self) -> None:  # noqa: N802
        self._open_activity_btn.setText(self.tr("Open Activity"))
        self._cancel_btn.setText(self.tr("Cancel"))
        self._run_btn.setText(self.tr("Run"))
        if self._current_vm is not None:
            self._update_buttons(self._current_vm)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(2)

        # Row 1: chip + display_label
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        self._chip = QLabel()
        self._chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        row1.addWidget(self._chip)
        self._title_label = QLabel(self._display_label)
        row1.addWidget(self._title_label)
        row1.addStretch()
        outer.addLayout(row1)

        # Row 2: phase + progress
        self._detail_label = QLabel()
        self._detail_label.setVisible(False)
        outer.addWidget(self._detail_label)

        # Row 3: last error
        self._error_label = QLabel()
        self._error_label.setVisible(False)
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet("color: #b71c1c;")
        outer.addWidget(self._error_label)

        # Row 4: action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self._cancel_btn = QPushButton()
        self._cancel_btn.setVisible(False)
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)
        btn_row.addWidget(self._cancel_btn)

        self._run_btn = QPushButton()
        self._run_btn.setVisible(False)
        self._run_btn.clicked.connect(self._on_run_clicked)
        btn_row.addWidget(self._run_btn)

        self._open_activity_btn = QPushButton()
        self._open_activity_btn.clicked.connect(self.open_activity_requested)
        btn_row.addWidget(self._open_activity_btn)
        btn_row.addStretch()
        outer.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_display(self, vm: TaskRowVM) -> None:
        self._chip.setText(translate_task_status(vm.status))
        self._chip.setStyleSheet(_chip_style(vm.status))

        parts = []
        if vm.phase:
            parts.append(self.tr("Phase: {0}").format(translate_task_phase(vm.phase)))
        prog = _progress_text(vm)
        if prog:
            parts.append(prog)
        detail = " | ".join(parts)
        if detail:
            self._detail_label.setText(detail)
            self._detail_label.setVisible(True)
        else:
            self._detail_label.setVisible(False)

        if vm.last_error:
            self._error_label.setText(self.tr("Last error: {0}").format(vm.last_error))
            self._error_label.setVisible(True)
        else:
            self._error_label.setVisible(False)

    def _update_buttons(self, vm: TaskRowVM) -> None:
        cancel_d = self._engine.preflight_task(vm.task_id, TaskAction.CANCEL)
        self._cancel_btn.setVisible(cancel_d.allowed)
        self._cancel_btn.setToolTip(translate_task_block_reason(cancel_d.reason, cancel_d.code))

        run_d = self._engine.preflight_task(vm.task_id, TaskAction.RUN)
        self._run_btn.setVisible(run_d.allowed)
        self._run_btn.setToolTip(translate_task_block_reason(run_d.reason, run_d.code))
        # Label: "Retry" if task is terminal, else "Run"
        if vm.status in TERMINAL_TASK_STATUSES:
            self._run_btn.setText(self.tr("Retry"))
        else:
            self._run_btn.setText(self.tr("Run"))

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_auto_refresh(self) -> None:
        if self._should_defer_hidden_refresh():
            return
        self.refresh()

    def _on_tasks_changed(self, book_id: str) -> None:
        if book_id != self._book_id:
            return
        if self._should_defer_hidden_refresh():
            self._dirty = True
            return
        self.refresh()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if getattr(self, "_dirty", False):
            self._dirty = False
            self.refresh()

    def _should_defer_hidden_refresh(self) -> bool:
        """Defer when the parent container (tab) is hidden.

        Unlike simple widgets we cannot check ``self.isVisible()`` because
        this widget calls ``setVisible(False)`` on itself when there are no
        tasks to show.  Checking the *parent* distinguishes "hidden by parent
        tab" from "self-hidden because no tasks".
        """
        with suppress(RuntimeError):
            parent = self.parentWidget()
            if parent is not None and not parent.isVisible():
                return True
        return False

    def _on_cancel_clicked(self) -> None:
        if self._current_vm is None:
            return
        try:
            self._engine.cancel(self._current_vm.task_id)
        except ValueError as exc:
            self._engine.error_occurred.emit(str(exc))

    def _on_run_clicked(self) -> None:
        if self._current_vm is None:
            return
        try:
            self._engine.run_task(self._current_vm.task_id)
        except ValueError as exc:
            self._engine.error_occurred.emit(str(exc))


# ---------------------------------------------------------------------------
# _MiniCard — internal helper used by TaskStatusStrip
# ---------------------------------------------------------------------------


class _MiniCard(QFrame):
    """Single-row mini card: [chip] title | progress | [Cancel] [Open Activity]."""

    open_activity_requested = Signal()

    def __init__(self, vm: TaskRowVM, engine, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._vm = vm
        self._init_ui()
        self._update(vm)

    def update_vm(self, vm: TaskRowVM) -> None:
        self._vm = vm
        self._update(vm)

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        self._chip = QLabel()
        self._chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._chip)

        self._title_label = QLabel()
        layout.addWidget(self._title_label)

        self._progress_label = QLabel()
        self._progress_label.setVisible(False)
        layout.addWidget(self._progress_label)

        layout.addStretch()

        self._cancel_btn = QPushButton()
        self._cancel_btn.setVisible(False)
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)
        layout.addWidget(self._cancel_btn)

        self._open_btn = QPushButton()
        self._open_btn.clicked.connect(self.open_activity_requested)
        layout.addWidget(self._open_btn)
        self.retranslate_ui()

    def _update(self, vm: TaskRowVM) -> None:
        self._chip.setText(translate_task_status(vm.status))
        self._chip.setStyleSheet(_chip_style(vm.status))
        self._title_label.setText(vm.title)

        prog = _progress_text(vm)
        if prog:
            self._progress_label.setText(prog)
            self._progress_label.setVisible(True)
        else:
            self._progress_label.setVisible(False)

        cancel_d = self._engine.preflight_task(vm.task_id, TaskAction.CANCEL)
        self._cancel_btn.setVisible(cancel_d.allowed)
        self._cancel_btn.setToolTip(translate_task_block_reason(cancel_d.reason, cancel_d.code))

    def _on_cancel_clicked(self) -> None:
        try:
            self._engine.cancel(self._vm.task_id)
        except ValueError as exc:
            self._engine.error_occurred.emit(str(exc))

    def retranslate_ui(self) -> None:
        self._cancel_btn.setText(self.tr("Cancel"))
        self._open_btn.setText(self.tr("Open Activity"))


# ---------------------------------------------------------------------------
# TaskStatusStrip
# ---------------------------------------------------------------------------


class TaskStatusStrip(QWidget):
    """Vertical strip of mini-cards, one per active/recent task.

    Shows ALL tasks matching task_types (not just the most recent).
    Intended for the Translation tab where multiple task types may be active.

    Signals:
        open_activity_requested(): emitted when any mini-card's Open Activity is clicked.
    """

    open_activity_requested = Signal()

    def __init__(
        self,
        task_engine,
        book_id: str,
        task_types: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._engine = task_engine
        self._book_id = book_id
        self._task_types = list(task_types)
        self._cards: dict[str, _MiniCard] = {}  # task_id -> card

        self._init_ui()

        self._engine.tasks_changed.connect(self._on_tasks_changed)

        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(_AUTO_REFRESH_INTERVAL_MS)
        self._auto_timer.timeout.connect(self._on_auto_refresh)
        self._auto_timer.start()

        self.refresh()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-fetch tasks and rebuild the strip."""
        records = []
        for tt in self._task_types:
            records.extend(self._engine.get_tasks(self._book_id, task_type=tt))
        records.sort(key=lambda r: r.updated_at, reverse=True)
        vms = map_tasks_to_row_vms(records)

        if not vms:
            self.setVisible(False)
            return

        self.setVisible(True)
        current_ids = {vm.task_id for vm in vms}

        # Remove cards that are no longer in the list
        for stale_id in list(self._cards):
            if stale_id not in current_ids:
                card = self._cards.pop(stale_id)
                self._strip_layout.removeWidget(card)
                card.deleteLater()

        # Add or update cards in order
        for idx, vm in enumerate(vms):
            if vm.task_id in self._cards:
                self._cards[vm.task_id].update_vm(vm)
                # Ensure correct position
                self._strip_layout.insertWidget(idx, self._cards[vm.task_id])
            else:
                card = _MiniCard(vm, self._engine, self)
                card.open_activity_requested.connect(self.open_activity_requested)
                self._strip_layout.insertWidget(idx, card)
                self._cards[vm.task_id] = card

    def cleanup(self) -> None:
        """Stop timer and disconnect engine signal."""
        self._auto_timer.stop()
        with suppress(TypeError, RuntimeError):
            self._engine.tasks_changed.disconnect(self._on_tasks_changed)

    # ------------------------------------------------------------------
    # i18n
    # ------------------------------------------------------------------

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self) -> None:  # noqa: N802
        for card in self._cards.values():
            card.retranslate_ui()
        self.refresh()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        self._strip_layout = QVBoxLayout(self)
        self._strip_layout.setContentsMargins(0, 0, 0, 0)
        self._strip_layout.setSpacing(2)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_auto_refresh(self) -> None:
        if self._should_defer_hidden_refresh():
            return
        self.refresh()

    def _on_tasks_changed(self, book_id: str) -> None:
        if book_id != self._book_id:
            return
        if self._should_defer_hidden_refresh():
            self._dirty = True
            return
        self.refresh()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if getattr(self, "_dirty", False):
            self._dirty = False
            self.refresh()

    def _should_defer_hidden_refresh(self) -> bool:
        with suppress(RuntimeError):
            parent = self.parentWidget()
            if parent is not None and not parent.isVisible():
                return True
        return False
