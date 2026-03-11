from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot

from context_aware_translation.workflow.tasks.claims import ResourceClaim
from context_aware_translation.workflow.tasks.engine_core import EngineCore
from context_aware_translation.workflow.tasks.exceptions import CancelDispatchRaceError, RunValidationError
from context_aware_translation.workflow.tasks.models import TaskAction

if TYPE_CHECKING:
    from context_aware_translation.storage.task_store import TaskRecord, TaskStore
    from context_aware_translation.workflow.tasks.handlers.base import TaskTypeHandler
    from context_aware_translation.workflow.tasks.models import Decision
    from context_aware_translation.workflow.tasks.worker_deps import WorkerDeps

logger = logging.getLogger(__name__)


class TaskEngine(QObject):
    """QObject orchestrator that drives the task lifecycle."""

    tasks_changed = Signal(str)  # book_id
    error_occurred = Signal(str)  # message
    running_work_changed = Signal(bool)  # is_running
    enqueue_task_changed = Signal(str)  # internal — connected via QueuedConnection to _emit_task_changed

    def __init__(self, *, store: TaskStore, deps: WorkerDeps, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._core = EngineCore(store=store, deps=deps)
        self._store = store
        self._autorun_timer: QTimer | None = None
        self._was_running: bool = self._core.has_running_work()

        # Coalesce rapid-fire task-changed signals into at most one UI
        # refresh per 250 ms window.  Worker threads emit
        # ``enqueue_task_changed`` on every DB persist; without
        # coalescing, 8 connected widgets each re-query the DB on every
        # emission, starving the event loop.
        self._pending_book_ids: set[str] = set()
        self._coalesce_timer = QTimer(self)
        self._coalesce_timer.setSingleShot(True)
        self._coalesce_timer.setInterval(250)
        self._coalesce_timer.timeout.connect(self._flush_task_changed)

        self.enqueue_task_changed.connect(self._emit_task_changed, Qt.ConnectionType.QueuedConnection)

    @property
    def store(self) -> TaskStore:
        return self._store

    # ------------------------------------------------------------------
    # Delegate to core
    # ------------------------------------------------------------------

    def register_handler(self, handler: TaskTypeHandler) -> None:
        self._core.register_handler(handler)

    def get_tasks(
        self,
        book_id: str,
        task_type: str | None = None,
        limit: int | None = None,
        *,
        full: bool = False,
    ) -> list[TaskRecord]:
        if full:
            return self._core.get_tasks(book_id, task_type, limit)
        return self._core.get_tasks_lightweight(book_id, task_type, limit)

    def get_task(self, task_id: str) -> TaskRecord | None:
        return self._core.get_task(task_id)

    def has_active_worker(self, task_id: str) -> bool:
        return self._core.has_active_worker(task_id)

    def has_running_work(self) -> bool:
        return self._core.has_running_work()

    def has_active_claims(self, book_id: str, wanted: frozenset[ResourceClaim]) -> bool:
        return self._core.has_active_claims(book_id, wanted)

    def preflight(self, task_type: str, book_id: str, params: dict, action: TaskAction) -> Decision:
        return self._core.preflight(task_type, book_id, params, action)

    def preflight_task(self, task_id: str, action: TaskAction) -> Decision:
        return self._core.preflight_task(task_id, action)

    # ------------------------------------------------------------------
    # Mutation APIs
    # ------------------------------------------------------------------

    def enqueue_followup_task(self, task_type: str, book_id: str, **params: object) -> None:
        """Submit a follow-up task (queued only, no immediate start).

        Used by workers to chain tasks (e.g., translation -> reembedding).
        Failures are logged and re-raised so caller workers can surface
        partial-success state (e.g. completed_with_errors).
        """
        try:
            record = self._core.submit(task_type, book_id, **params)
            logger.info("Follow-up %s task %s enqueued for book %s", task_type, record.task_id, book_id)
            self.enqueue_task_changed.emit(book_id)
        except Exception:
            logger.warning("Failed to enqueue follow-up %s for book %s", task_type, book_id, exc_info=True)
            raise

    def submit(self, task_type: str, book_id: str, **params) -> TaskRecord:
        """Create a new task row then best-effort start it."""
        record = self._core.submit(task_type, book_id, **params)
        try:
            self._start_action(record.task_id, TaskAction.RUN)
        except Exception:
            logger.debug("Best-effort start failed for task %s; will retry on next tick", record.task_id)
        self._emit_running_work_changed_if_needed()
        return record

    def submit_and_start(self, task_type: str, book_id: str, **params) -> TaskRecord:
        """Create a new task row and immediately start it (strict mode).

        Unlike ``submit``, this method guarantees the task either starts
        successfully or is immediately marked failed.  It never leaves the
        task in ``queued`` state and never silently discards a created row.

        Raises ``ValueError`` if ``_core.submit`` itself rejects the task
        (e.g. validate_submit fails).
        """
        record = self._core.submit(task_type, book_id, **params)
        try:
            self._start_action(record.task_id, TaskAction.RUN)
        except Exception as exc:
            reason = f"strict-start failed: {type(exc).__name__}: {exc}"
            logger.warning("submit_and_start: marking task %s failed — %s", record.task_id, reason)
            try:
                self._store.update(record.task_id, status="failed", last_error=reason)
            except Exception:
                logger.exception("submit_and_start: could not mark task %s failed", record.task_id)
            self.enqueue_task_changed.emit(book_id)
            self._emit_running_work_changed_if_needed()
            # Re-fetch the record so the caller sees the failed status.
            updated = self._core.get_task(record.task_id)
            return updated if updated is not None else record
        self._emit_running_work_changed_if_needed()
        return record

    def run_task(self, task_id: str) -> TaskRecord:
        """Run a task: atomically resets to queued if terminal, then starts it (strict).

        Raises ``ValueError`` if the task cannot be requeued (e.g. config snapshot
        capture fails or the handler denies the RUN action).

        If the worker fails to start, the task is immediately marked failed so it
        is never left stranded in ``queued`` state.
        """
        record = self._core.ensure_runnable(task_id)  # may raise ValueError
        try:
            self._start_action(task_id, TaskAction.RUN)
        except Exception as exc:
            reason = f"strict-start failed: {type(exc).__name__}: {exc}"
            logger.warning("run_task: marking task %s failed — %s", task_id, reason)
            try:
                self._store.update(task_id, status="failed", last_error=reason)
            except Exception:
                logger.exception("run_task: could not mark task %s failed", task_id)
            self.enqueue_task_changed.emit(record.book_id)
            self._emit_running_work_changed_if_needed()
            updated = self._core.get_task(task_id)
            return updated if updated is not None else record
        self._emit_running_work_changed_if_needed()
        return record

    def rerun(self, task_id: str) -> TaskRecord:
        """Reset a terminal task to queued then start it (strict).

        Raises ``ValueError`` if the task cannot be rerun (e.g. config snapshot
        capture fails or the handler denies the RUN action).

        If the worker fails to start, the task is immediately marked failed so it
        is never left stranded in ``queued`` state.
        """
        record = self._core.rerun(task_id)  # may raise ValueError
        try:
            self._start_action(task_id, TaskAction.RUN)
        except Exception as exc:
            reason = f"strict-start failed: {type(exc).__name__}: {exc}"
            logger.warning("rerun: marking task %s failed — %s", task_id, reason)
            try:
                self._store.update(task_id, status="failed", last_error=reason)
            except Exception:
                logger.exception("rerun: could not mark task %s failed", task_id)
            self.enqueue_task_changed.emit(record.book_id)
            self._emit_running_work_changed_if_needed()
            updated = self._core.get_task(task_id)
            return updated if updated is not None else record
        self._emit_running_work_changed_if_needed()
        return record

    def cancel(self, task_id: str) -> None:
        """Request cancellation only if handler policy allows it."""
        try:
            worker = self._core.cancel(task_id)
            if worker is not None and hasattr(worker, "requestInterruption"):
                worker.requestInterruption()  # type: ignore[attr-defined]
            elif worker is None:
                # No active RUN worker — dispatch explicit cancel action worker
                # Only if core.cancel() actually accepted the request (cancel_requested=True).
                record_after = self._core.get_task(task_id)
                if record_after is not None and record_after.cancel_requested:
                    try:
                        self._start_action(task_id, TaskAction.CANCEL)
                    except (CancelDispatchRaceError, KeyError) as exc:
                        logger.debug("Cancel action worker not started for task %s", task_id)
                        self._core.handle_cancel_dispatch_failure(
                            task_id,
                            reason=f"cancel dispatch failed: {type(exc).__name__}: {exc}",
                        )
            record = self._core.get_task(task_id)
            if record is not None:
                self.enqueue_task_changed.emit(record.book_id)
        finally:
            self._emit_running_work_changed_if_needed()

    def delete(self, task_id: str) -> None:
        """Delete a task if handler policy allows it and worker is not active."""
        try:
            book_id = self._core.delete(task_id)
            if book_id is not None:
                self.enqueue_task_changed.emit(book_id)
        finally:
            self._emit_running_work_changed_if_needed()

    def cancel_running_tasks(self, book_id: str) -> None:
        """Interrupt active workers for the given book and mark them cancel_requested."""
        workers = self._core.cancel_running_tasks(book_id)
        for worker in workers:
            if hasattr(worker, "requestInterruption"):
                worker.requestInterruption()  # type: ignore[attr-defined]
        self._emit_running_work_changed_if_needed()

    # ------------------------------------------------------------------
    # Autorun timer
    # ------------------------------------------------------------------

    def start_autorun(self, interval_ms: int = 3000) -> None:
        if self._autorun_timer is None:
            self._autorun_timer = QTimer(self)
            self._autorun_timer.timeout.connect(self.tick)
        self._autorun_timer.start(interval_ms)
        self._emit_running_work_changed_if_needed()

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
            except RunValidationError as exc:
                # validate_run rejected — mark task failed so it does not loop.
                logger.warning("Run validation failed for task %s: %s", task_id, exc)
                try:
                    self._store.update(task_id, status="failed", last_error=str(exc))
                except Exception:
                    logger.exception("Could not mark task %s failed after RunValidationError", task_id)
                record = self._core.get_task(task_id)
                if record is not None:
                    self.enqueue_task_changed.emit(record.book_id)
                continue
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
            self._emit_running_work_changed_if_needed()
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
        self._pending_book_ids.add(book_id)
        if not self._coalesce_timer.isActive():
            self._coalesce_timer.start()

    @Slot()
    def _flush_task_changed(self) -> None:
        book_ids = list(self._pending_book_ids)
        self._pending_book_ids.clear()
        for book_id in book_ids:
            self.tasks_changed.emit(book_id)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def close(self) -> None:
        self.stop_autorun()
        # Flush any coalesced task-changed notifications before tearing down.
        if self._coalesce_timer.isActive():
            self._coalesce_timer.stop()
            self._flush_task_changed()
        # Request interruption for all active workers
        for _task_id, worker in self._core.active_worker_items():
            if hasattr(worker, "requestInterruption"):
                worker.requestInterruption()  # type: ignore[attr-defined]
        # Wait up to 5000ms for workers to finish
        deadline = time.monotonic() + 5.0
        for _task_id, worker in self._core.active_worker_items():
            if hasattr(worker, "wait"):
                remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
                worker.wait(remaining_ms)  # type: ignore[attr-defined]
        # Release claims for any workers that finished
        self._core.cleanup_finished_workers()
        self._emit_running_work_changed_if_needed()
        # Only close the store if no workers are still running
        if not self._core.has_running_work():
            self._core.close()
        else:
            logger.warning("Skipping store close: %d workers still active", len(self._core.active_worker_items()))
