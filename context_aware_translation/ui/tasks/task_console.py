"""TaskConsole widget — reusable task-list panel with Run / Cancel / Delete actions."""

from __future__ import annotations

import time
from collections.abc import Sequence
from contextlib import suppress

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.ui.i18n import translate_task_block_reason, translate_task_phase, translate_task_status
from context_aware_translation.ui.tasks.task_view_model_mapper import map_tasks_to_row_vms
from context_aware_translation.ui.tasks.task_view_models import TaskRowVM
from context_aware_translation.workflow.tasks.models import TaskAction

_AUTO_REFRESH_INTERVAL_MS = 3000
_TASK_CONSOLE_LIST_LIMIT = 200


def _format_eta(seconds_left: float) -> str:
    """Format remaining seconds into a human-readable ETA string."""
    if seconds_left < 60:
        return f"ETA ~{int(seconds_left)}s"
    minutes_left = seconds_left / 60
    if minutes_left < 60:
        return f"ETA ~{int(minutes_left)}m"
    hours_left = minutes_left / 60
    return f"ETA ~{hours_left:.1f}h"


def _row_text(vm: TaskRowVM, start_times: dict[str, float]) -> str:
    """Format a single-line display string for a TaskRowVM."""
    status = translate_task_status(vm.status)
    phase = translate_task_phase(vm.phase) if vm.phase else ""
    text = f"#{vm.task_id[:8]} | {status} | {phase} | {vm.completed_items}/{vm.total_items}"
    if vm.status == "running" and vm.task_id in start_times:
        elapsed = time.monotonic() - start_times[vm.task_id]
        if elapsed > 0 and vm.completed_items > 0 and vm.total_items > 0:
            rate = vm.completed_items / elapsed
            remaining = vm.total_items - vm.completed_items
            if remaining > 0:
                text += f" | {_format_eta(remaining / rate)}"
    if vm.last_error:
        text += f" | {vm.last_error}"
    return text


class TaskConsole(QWidget):
    """Reusable panel that lists tasks and exposes Run / Cancel / Delete actions.

    The widget owns its own refresh timer, connects to the engine's
    ``tasks_changed`` signal, and calls ``preflight_task`` to gate buttons.
    """

    def __init__(
        self,
        task_engine,
        book_id: str,
        task_type: str | Sequence[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._engine = task_engine
        self._book_id = book_id
        self._task_type = task_type
        self._vms: list[TaskRowVM] = []
        self._start_times: dict[str, float] = {}

        self._init_ui()
        self.retranslate_ui()
        self._engine.tasks_changed.connect(self._on_tasks_changed)

        # Auto-refresh timer
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(_AUTO_REFRESH_INTERVAL_MS)
        self._auto_timer.timeout.connect(self.refresh)
        self._auto_timer.start()

        # Initial data load — do not wait for first timer tick
        self.refresh()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def selected_task_id(self) -> str | None:
        """Return the task_id of the currently selected row, or ``None``."""
        item = self._task_list.currentItem()
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if isinstance(value, str) else None

    def task_vms(self) -> list[TaskRowVM]:
        """Return the current list of view-models (last refresh snapshot)."""
        return list(self._vms)

    def refresh(self) -> None:
        """Re-fetch tasks from the engine and repaint the list."""
        if isinstance(self._task_type, str):
            records = self._engine.get_tasks(self._book_id, task_type=self._task_type, limit=_TASK_CONSOLE_LIST_LIMIT)
        else:
            records = []
            for tt in self._task_type:
                records.extend(self._engine.get_tasks(self._book_id, task_type=tt, limit=_TASK_CONSOLE_LIST_LIMIT))
            records.sort(key=lambda r: r.updated_at, reverse=True)
        self._vms = map_tasks_to_row_vms(records)

        # Track when tasks first enter "running" and prune stale entries.
        now = time.monotonic()
        current_ids: set[str] = set()
        for vm in self._vms:
            current_ids.add(vm.task_id)
            if vm.status == "running":
                if vm.task_id not in self._start_times:
                    self._start_times[vm.task_id] = now
            else:
                # Task left running (paused, cancel_requested, cancelling, terminal)
                self._start_times.pop(vm.task_id, None)
        # Prune IDs no longer in the current snapshot
        for stale_id in list(self._start_times):
            if stale_id not in current_ids:
                del self._start_times[stale_id]

        self._repopulate_list()

    def cleanup(self) -> None:
        """Stop timer and disconnect engine signal."""
        self._auto_timer.stop()
        with suppress(TypeError, RuntimeError):
            self._engine.tasks_changed.disconnect(self._on_tasks_changed)

    # ------------------------------------------------------------------
    # i18n
    # ------------------------------------------------------------------

    def retranslate_ui(self) -> None:
        """Set translatable button labels."""
        self._run_btn.setText(self.tr("Run Selected Task"))
        self._cancel_btn.setText(self.tr("Cancel Selected Task"))
        self._delete_btn.setText(self.tr("Delete Selected Task"))
        self._update_action_buttons_for_selection()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._task_list = QListWidget()
        self._task_list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._task_list)

        btn_layout = QHBoxLayout()
        self._run_btn = QPushButton()
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run_clicked)
        btn_layout.addWidget(self._run_btn)

        self._cancel_btn = QPushButton()
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)
        btn_layout.addWidget(self._cancel_btn)

        self._delete_btn = QPushButton()
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        btn_layout.addWidget(self._delete_btn)

        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    # Internal: list population with stable selection
    # ------------------------------------------------------------------

    def _repopulate_list(self) -> None:
        current_id = self.selected_task_id()
        self._task_list.blockSignals(True)
        self._task_list.clear()
        target_row = -1
        for idx, vm in enumerate(self._vms):
            item = QListWidgetItem(_row_text(vm, self._start_times))
            item.setData(Qt.ItemDataRole.UserRole, vm.task_id)
            self._task_list.addItem(item)
            if current_id and vm.task_id == current_id:
                target_row = idx
        self._task_list.blockSignals(False)

        if target_row >= 0:
            self._task_list.setCurrentRow(target_row)
        elif self._task_list.count() > 0:
            self._task_list.setCurrentRow(0)

        # Always recompute — avoids stale button state when the selected row
        # index did not change and currentRowChanged was not emitted.
        self._update_action_buttons_for_selection()

    # ------------------------------------------------------------------
    # Button state
    # ------------------------------------------------------------------

    def _update_action_buttons_for_selection(self) -> None:
        """Set button enabled/tooltip from ``preflight_task`` for the current selection."""
        task_id = self.selected_task_id()
        if task_id is None:
            self._run_btn.setEnabled(False)
            self._run_btn.setToolTip("")
            self._cancel_btn.setEnabled(False)
            self._cancel_btn.setToolTip("")
            self._delete_btn.setEnabled(False)
            self._delete_btn.setToolTip("")
            return

        run_d = self._engine.preflight_task(task_id, TaskAction.RUN)
        cancel_d = self._engine.preflight_task(task_id, TaskAction.CANCEL)
        delete_d = self._engine.preflight_task(task_id, TaskAction.DELETE)

        self._run_btn.setEnabled(run_d.allowed)
        self._run_btn.setToolTip(translate_task_block_reason(run_d.reason, run_d.code))
        self._cancel_btn.setEnabled(cancel_d.allowed)
        self._cancel_btn.setToolTip(translate_task_block_reason(cancel_d.reason, cancel_d.code))
        self._delete_btn.setEnabled(delete_d.allowed)
        self._delete_btn.setToolTip(translate_task_block_reason(delete_d.reason, delete_d.code))

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_tasks_changed(self, book_id: str) -> None:
        if book_id != self._book_id:
            return
        if self._should_defer_hidden_refresh():
            self._dirty = True
            return
        self.refresh()

    def _should_defer_hidden_refresh(self) -> bool:
        """Return True when refresh should be deferred until the widget is shown.

        Embedded consoles in inactive tabs can defer expensive refresh work.
        Standalone/unparented consoles (common in tests) refresh immediately.
        """
        with suppress(RuntimeError):
            if self.isVisible():
                return False
            return self.parentWidget() is not None
        return False

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if getattr(self, "_dirty", False):
            self._dirty = False
            self.refresh()

    def _on_row_changed(self, _row: int) -> None:
        self._update_action_buttons_for_selection()

    def _on_run_clicked(self) -> None:
        task_id = self.selected_task_id()
        if not task_id:
            return
        try:
            self._engine.run_task(task_id)
        except ValueError as exc:
            self._engine.error_occurred.emit(str(exc))
            QMessageBox.warning(
                self,
                self.tr("Cannot Run Task"),
                self.tr("The task could not be started:\n\n{0}").format(str(exc)),
            )

    def _on_cancel_clicked(self) -> None:
        task_id = self.selected_task_id()
        if not task_id:
            return
        try:
            self._engine.cancel(task_id)
        except ValueError as exc:
            self._engine.error_occurred.emit(str(exc))
            QMessageBox.warning(
                self,
                self.tr("Cannot Cancel Task"),
                self.tr("The task could not be cancelled:\n\n{0}").format(str(exc)),
            )

    def _on_delete_clicked(self) -> None:
        task_id = self.selected_task_id()
        if not task_id:
            return
        reply = QMessageBox.question(
            self,
            self.tr("Delete Task"),
            self.tr("Delete the selected task from local history?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self._engine.delete(task_id)
            except ValueError as exc:
                self._engine.error_occurred.emit(str(exc))
                QMessageBox.warning(
                    self,
                    self.tr("Cannot Delete Task"),
                    self.tr("The task could not be deleted:\n\n{0}").format(str(exc)),
                )
