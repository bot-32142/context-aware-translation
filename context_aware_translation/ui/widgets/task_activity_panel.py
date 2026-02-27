"""TaskActivityPanel widget — sliding panel showing all tasks for a book."""

from __future__ import annotations

from contextlib import suppress

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from context_aware_translation.workflow.tasks.models import TaskAction

from ..tasks.task_view_model_mapper import map_tasks_to_row_vms
from ..tasks.task_view_models import TaskRowVM


class _TaskRow(QWidget):
    """A single row inside TaskActivityPanel representing one task."""

    run_clicked = Signal(str)  # task_id
    cancel_clicked = Signal(str)  # task_id
    delete_clicked = Signal(str)  # task_id

    def __init__(self, vm: TaskRowVM, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._task_id = vm.task_id
        self._init_ui(vm)

    def _init_ui(self, vm: TaskRowVM) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Top row: title + status chip
        top = QHBoxLayout()
        self._title_label = QLabel(vm.title)
        self._title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        top.addWidget(self._title_label)

        self._status_label = QLabel(vm.status)
        self._status_label.setObjectName("statusChip")
        top.addWidget(self._status_label)
        layout.addLayout(top)

        # Middle row: phase + progress
        mid = QHBoxLayout()
        self._phase_label = QLabel(vm.phase or "")
        mid.addWidget(self._phase_label)
        mid.addStretch()

        self._progress_label = QLabel(f"{vm.completed_items}/{vm.total_items}")
        mid.addWidget(self._progress_label)
        layout.addLayout(mid)

        # Error row (only shown when non-empty)
        self._error_label = QLabel(vm.last_error or "")
        self._error_label.setObjectName("errorLabel")
        self._error_label.setVisible(bool(vm.last_error))
        self._error_label.setWordWrap(True)
        layout.addWidget(self._error_label)

        # Button row
        btn_row = QHBoxLayout()
        self._run_btn = QPushButton()
        self._run_btn.clicked.connect(lambda: self.run_clicked.emit(self._task_id))
        btn_row.addWidget(self._run_btn)

        self._cancel_btn = QPushButton()
        self._cancel_btn.clicked.connect(lambda: self.cancel_clicked.emit(self._task_id))
        btn_row.addWidget(self._cancel_btn)

        self._delete_btn = QPushButton()
        self._delete_btn.clicked.connect(lambda: self.delete_clicked.emit(self._task_id))
        btn_row.addWidget(self._delete_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

    def update_from_vm(self, vm: TaskRowVM) -> None:
        """Refresh display labels from an updated view-model."""
        self._title_label.setText(vm.title)
        self._status_label.setText(vm.status)
        self._phase_label.setText(vm.phase or "")
        self._progress_label.setText(f"{vm.completed_items}/{vm.total_items}")
        self._error_label.setText(vm.last_error or "")
        self._error_label.setVisible(bool(vm.last_error))

    def apply_preflight(self, run_d, cancel_d, delete_d) -> None:
        """Apply preflight decisions to buttons (enabled state + tooltip)."""
        self._run_btn.setEnabled(run_d.allowed)
        self._run_btn.setToolTip(run_d.reason)
        self._cancel_btn.setEnabled(cancel_d.allowed)
        self._cancel_btn.setToolTip(cancel_d.reason)
        self._delete_btn.setEnabled(delete_d.allowed)
        self._delete_btn.setToolTip(delete_d.reason)

    def retranslate(self) -> None:
        self._run_btn.setText(self.tr("Run"))
        self._cancel_btn.setText(self.tr("Cancel"))
        self._delete_btn.setText(self.tr("Delete"))


class TaskActivityPanel(QWidget):
    """Panel showing all tasks for a book with per-row Run/Cancel/Delete actions.

    Signals
    -------
    close_requested
        Emitted when the user clicks the Close button in the header.
    panel_refreshed
        Emitted after each refresh cycle (useful for testing).
    """

    close_requested = Signal()
    panel_refreshed = Signal()

    def __init__(self, task_engine, book_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._engine = task_engine
        self._book_id = book_id
        self._vms: list[TaskRowVM] = []
        self._rows: dict[str, _TaskRow] = {}  # task_id -> _TaskRow widget

        self._init_ui()
        self.retranslate_ui()
        self._engine.tasks_changed.connect(self._on_tasks_changed)

        # Initial data load
        self.refresh()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-fetch all tasks and rebuild the scroll area rows."""
        records = self._engine.get_tasks(self._book_id)
        self._vms = map_tasks_to_row_vms(records)
        self._repopulate_rows()
        self._apply_preflight_to_all_rows()
        self.panel_refreshed.emit()

    def cleanup(self) -> None:
        """Disconnect engine signal."""
        with suppress(TypeError, RuntimeError):
            self._engine.tasks_changed.disconnect(self._on_tasks_changed)

    # ------------------------------------------------------------------
    # i18n
    # ------------------------------------------------------------------

    def retranslate_ui(self) -> None:
        """Set translatable labels."""
        self._title_label.setText(self.tr("Activity"))
        self._close_btn.setText(self.tr("Close"))
        for row in self._rows.values():
            row.retranslate()
        self._apply_preflight_to_all_rows()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header bar
        header = QHBoxLayout()
        header.setContentsMargins(8, 4, 8, 4)
        self._title_label = QLabel()
        self._title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header.addWidget(self._title_label)

        self._close_btn = QPushButton()
        self._close_btn.clicked.connect(self.close_requested)
        header.addWidget(self._close_btn)
        root.addLayout(header)

        # Scroll area containing task rows
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(4, 4, 4, 4)
        self._rows_layout.setSpacing(4)
        self._rows_layout.addStretch()

        self._scroll_area.setWidget(self._rows_container)
        root.addWidget(self._scroll_area)

    # ------------------------------------------------------------------
    # Row management
    # ------------------------------------------------------------------

    def _repopulate_rows(self) -> None:
        """Sync the rows container to the current _vms list.

        Reuses existing _TaskRow widgets for tasks that are still present,
        creates new ones for new tasks, and removes rows for deleted tasks.
        """
        current_ids = {vm.task_id for vm in self._vms}

        # Remove rows that are no longer in the vm list
        for task_id in list(self._rows):
            if task_id not in current_ids:
                row = self._rows.pop(task_id)
                self._rows_layout.removeWidget(row)
                row.deleteLater()

        # Insert / update rows in vm order
        for idx, vm in enumerate(self._vms):
            if vm.task_id in self._rows:
                row = self._rows[vm.task_id]
                row.update_from_vm(vm)
                row.retranslate()
            else:
                row = _TaskRow(vm, self._rows_container)
                row.retranslate()
                row.run_clicked.connect(self._on_run_clicked)
                row.cancel_clicked.connect(self._on_cancel_clicked)
                row.delete_clicked.connect(self._on_delete_clicked)
                self._rows[vm.task_id] = row
                # Insert before the trailing stretch (last item)
                stretch_idx = self._rows_layout.count() - 1
                self._rows_layout.insertWidget(idx if idx <= stretch_idx else stretch_idx, row)

    def _apply_preflight_to_all_rows(self) -> None:
        """Call preflight_task for every visible row and update button state."""
        for vm in self._vms:
            row = self._rows.get(vm.task_id)
            if row is None:
                continue
            run_d = self._engine.preflight_task(vm.task_id, TaskAction.RUN)
            cancel_d = self._engine.preflight_task(vm.task_id, TaskAction.CANCEL)
            delete_d = self._engine.preflight_task(vm.task_id, TaskAction.DELETE)
            row.apply_preflight(run_d, cancel_d, delete_d)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_tasks_changed(self, book_id: str) -> None:
        if book_id == self._book_id:
            self.refresh()

    def _on_run_clicked(self, task_id: str) -> None:
        try:
            self._engine.run_task(task_id)
        except ValueError as exc:
            self._engine.error_occurred.emit(str(exc))
            QMessageBox.warning(
                self,
                self.tr("Cannot Run Task"),
                self.tr("The task could not be started:\n\n{0}").format(str(exc)),
            )

    def _on_cancel_clicked(self, task_id: str) -> None:
        try:
            self._engine.cancel(task_id)
        except ValueError as exc:
            self._engine.error_occurred.emit(str(exc))
            QMessageBox.warning(
                self,
                self.tr("Cannot Cancel Task"),
                self.tr("The task could not be cancelled:\n\n{0}").format(str(exc)),
            )

    def _on_delete_clicked(self, task_id: str) -> None:
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
