"""TaskConsole widget — reusable task-list panel with Run / Cancel / Delete actions."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.workflow.tasks.models import TaskAction

from .task_view_model_mapper import map_tasks_to_row_vms
from .task_view_models import TaskRowVM

_AUTO_REFRESH_INTERVAL_MS = 3000


def _row_text(vm: TaskRowVM) -> str:
    """Format a single-line display string for a TaskRowVM."""
    text = f"#{vm.task_id[:8]} | {vm.status} | {vm.phase} | {vm.completed_items}/{vm.total_items}"
    if vm.last_error:
        text += f" | {vm.last_error}"
    return text


class TaskConsole(QWidget):
    """Reusable panel that lists tasks and exposes Run / Cancel / Delete actions.

    The widget owns its own refresh timer, connects to the engine's
    ``tasks_changed`` signal, and calls ``preflight_task`` to gate buttons.
    """

    console_refreshed = Signal()

    def __init__(
        self,
        task_engine,
        book_id: str,
        task_type: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._engine = task_engine
        self._book_id = book_id
        self._task_type = task_type
        self._vms: list[TaskRowVM] = []

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
        records = self._engine.get_tasks(self._book_id, task_type=self._task_type)
        self._vms = map_tasks_to_row_vms(records)
        self._repopulate_list()
        self.console_refreshed.emit()

    def cleanup(self) -> None:
        """Stop timer and disconnect engine signal."""
        self._auto_timer.stop()
        try:
            self._engine.tasks_changed.disconnect(self._on_tasks_changed)
        except (TypeError, RuntimeError):
            pass

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
            item = QListWidgetItem(_row_text(vm))
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
        self._run_btn.setToolTip(run_d.reason)
        self._cancel_btn.setEnabled(cancel_d.allowed)
        self._cancel_btn.setToolTip(cancel_d.reason)
        self._delete_btn.setEnabled(delete_d.allowed)
        self._delete_btn.setToolTip(delete_d.reason)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_tasks_changed(self, book_id: str) -> None:
        if book_id == self._book_id:
            self.refresh()

    def _on_row_changed(self, _row: int) -> None:
        self._update_action_buttons_for_selection()

    def _on_run_clicked(self) -> None:
        task_id = self.selected_task_id()
        if task_id:
            self._engine.run_task(task_id)

    def _on_cancel_clicked(self) -> None:
        task_id = self.selected_task_id()
        if task_id:
            self._engine.cancel(task_id)

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
            self._engine.delete(task_id)
