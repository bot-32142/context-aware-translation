from __future__ import annotations
import logging
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal, Slot, Qt

from context_aware_translation.workflow.tasks.engine_core import EngineCore
from context_aware_translation.workflow.tasks.models import TaskAction, TERMINAL_TASK_STATUSES
from context_aware_translation.workflow.tasks.claims import ResourceClaim

if TYPE_CHECKING:
    from context_aware_translation.storage.task_store import TaskStore, TaskRecord
    from context_aware_translation.workflow.tasks.worker_deps import WorkerDeps
    from context_aware_translation.workflow.tasks.handlers.base import TaskTypeHandler
    from context_aware_translation.workflow.tasks.models import Decision

logger = logging.getLogger(__name__)


class TaskEngine(QObject):
    """QObject orchestrator that drives the task lifecycle."""

    tasks_changed = Signal(str)           # book_id
    status_message = Signal(str, str)     # style, message
    error_occurred = Signal(str)          # message
    running_work_changed = Signal(bool)   # is_running
    enqueue_task_changed = Signal(str)    # internal — connected via QueuedConnection to _emit_task_changed

    def __init__(self, *, store: "TaskStore", deps: "WorkerDeps", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._core = EngineCore(store=store, deps=deps)
        self._store = store
        self._autorun_timer: QTimer | None = None
        self._was_running: bool = False
        self.enqueue_task_changed.connect(self._emit_task_changed, Qt.ConnectionType.QueuedConnection)

    @property
    def store(self) -> "TaskStore":
        return self._store

    # ------------------------------------------------------------------
    # Delegate to core
    # ------------------------------------------------------------------

    def register_handler(self, handler: "TaskTypeHandler") -> None:
        self._core.register_handler(handler)

    def get_tasks(self, book_id: str, task_type: str | None = None) -> list["TaskRecord"]:
        return self._core.get_tasks(book_id, task_type)

    def get_task(self, task_id: str) -> "TaskRecord | None":
        return self._core.get_task(task_id)

    def has_active_worker(self, task_id: str) -> bool:
        return self._core.has_active_worker(task_id)

    def has_running_work(self) -> bool:
        return self._core.has_running_work()

    def has_active_claims(self, book_id: str, wanted: frozenset[ResourceClaim]) -> bool:
        return self._core.has_active_claims(book_id, wanted)

    def preflight(self, task_type: str, book_id: str, params: dict, action: TaskAction) -> "Decision":
        return self._core.preflight(task_type, book_id, params, action)

    def preflight_task(self, task_id: str, action: TaskAction) -> "Decision":
        return self._core.preflight_task(task_id, action)

    # ------------------------------------------------------------------
    # Mutation APIs
    # ------------------------------------------------------------------

    def submit(self, task_type: str, book_id: str, **params) -> "TaskRecord":
        """Create a new task row then best-effort start it."""
        record = self._core.submit(task_type, book_id, **params)
        try:
            self._start_action(record.task_id, TaskAction.RUN)
        except Exception:
            logger.debug("Best-effort start failed for task %s; will retry on next tick", record.task_id)
        return record

    def run_task(self, task_id: str) -> "TaskRecord":
        """Run a task: atomically resets to queued if terminal, then starts it."""
        record = self._core.ensure_runnable(task_id)
        try:
            self._start_action(task_id, TaskAction.RUN)
        except Exception:
            logger.debug("Best-effort run start failed for task %s", task_id)
        return record

    def rerun(self, task_id: str) -> "TaskRecord":
        """Reset a terminal task to queued then start it."""
        record = self._core.rerun(task_id)
        try:
            self._start_action(task_id, TaskAction.RUN)
        except Exception:
            logger.debug("Best-effort rerun start failed for task %s", task_id)
        return record

    def cancel(self, task_id: str) -> None:
        """Request cancellation only if handler policy allows it."""
        worker = self._core.cancel(task_id)
        if worker is not None and hasattr(worker, "requestInterruption"):
            worker.requestInterruption()  # type: ignore[attr-defined]
        record = self._core.get_task(task_id)
        if record is not None:
            self.enqueue_task_changed.emit(record.book_id)

    def delete(self, task_id: str) -> None:
        """Delete a task if handler policy allows it and worker is not active."""
        book_id = self._core.delete(task_id)
        if book_id is not None:
            self.enqueue_task_changed.emit(book_id)

    def cancel_running_tasks(self, book_id: str) -> None:
        """Interrupt active workers for the given book and mark them cancel_requested."""
        workers = self._core.cancel_running_tasks(book_id)
        for worker in workers:
            if hasattr(worker, "requestInterruption"):
                worker.requestInterruption()  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Autorun timer
    # ------------------------------------------------------------------

    def start_autorun(self, interval_ms: int = 3000) -> None:
        if self._autorun_timer is None:
            self._autorun_timer = QTimer(self)
            self._autorun_timer.timeout.connect(self.tick)
        self._autorun_timer.start(interval_ms)

    def stop_autorun(self) -> None:
        if self._autorun_timer is not None:
            self._autorun_timer.stop()

    # ------------------------------------------------------------------
    # Tick / scan
    # ------------------------------------------------------------------

    @Slot()
    def tick(self) -> None:
        self._core.cleanup_finished_workers()
        self._emit_running_work_changed_if_needed()
        try:
            startable = self._core.scan_autorunnable()
        except RuntimeError as exc:
            self.stop_autorun()
            self.error_occurred.emit(f"Fatal TaskEngine error: {exc}")
            raise
        for task_id in startable:
            try:
                self._start_action(task_id, TaskAction.RUN)
            except RuntimeError as exc:
                # Denied action or conflicts should not crash scheduler loop.
                logger.debug("Skipped task %s in tick: %s", task_id, exc)
                continue
            except Exception as exc:  # noqa: BLE001
                logger.exception("Unexpected autorun error for task %s: %s", task_id, exc)
                record = self._core.get_task(task_id)
                if record is not None:
                    self._core._set_backoff(record.book_id, time.monotonic())

    # ------------------------------------------------------------------
    # Internal: start a worker
    # ------------------------------------------------------------------

    def _start_action(self, task_id: str, action: TaskAction) -> None:
        """Authorize, build worker, connect signals, start."""
        record, worker, claims = self._core.authorize_start(task_id, action)
        self._core.register_active_worker(task_id, worker, claims)

        try:
            # Connect finished signal
            if hasattr(worker, "finished"):
                worker.finished.connect(
                    lambda tid=task_id: self._on_worker_finished(tid),
                    Qt.ConnectionType.QueuedConnection,
                )

            worker.start()  # type: ignore[attr-defined]
        except Exception:
            self._core.release_task_resources(task_id)
            raise

        self._emit_running_work_changed_if_needed()
        self.enqueue_task_changed.emit(record.book_id)

    # ------------------------------------------------------------------
    # Worker lifecycle callbacks
    # ------------------------------------------------------------------

    def _on_worker_finished(self, task_id: str) -> None:
        self._core.release_task_resources(task_id)
        self._emit_running_work_changed_if_needed()
        record = self._core.get_task(task_id)
        if record is not None:
            self.enqueue_task_changed.emit(record.book_id)

    def _emit_running_work_changed_if_needed(self) -> None:
        is_running = self._core.has_running_work()
        if is_running != self._was_running:
            self._was_running = is_running
            self.running_work_changed.emit(is_running)

    # ------------------------------------------------------------------
    # Signal relay
    # ------------------------------------------------------------------

    @Slot(str)
    def _emit_task_changed(self, book_id: str) -> None:
        self.tasks_changed.emit(book_id)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def close(self) -> None:
        self.stop_autorun()
        # Request interruption for all active workers
        for task_id, worker in self._core.active_worker_items():
            if hasattr(worker, "requestInterruption"):
                worker.requestInterruption()  # type: ignore[attr-defined]
        # Wait up to 5000ms for workers to finish
        deadline = time.monotonic() + 5.0
        for task_id, worker in self._core.active_worker_items():
            if hasattr(worker, "wait"):
                remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
                worker.wait(remaining_ms)  # type: ignore[attr-defined]
        # Release claims for any workers that finished
        self._core.cleanup_finished_workers()
        # Only close the store if no workers are still running
        if not self._core.has_running_work():
            self._core.close()
        else:
            logger.warning("Skipping store close: %d workers still active", len(self._core.active_worker_items()))
