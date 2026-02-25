from __future__ import annotations
import json
import logging
import threading
import time
from typing import TYPE_CHECKING

from context_aware_translation.workflow.tasks.models import ActionSnapshot, Decision, TaskAction, TERMINAL_TASK_STATUSES
from context_aware_translation.workflow.tasks.claims import ClaimArbiter, ResourceClaim
from context_aware_translation.workflow.tasks.handlers.base import TaskTypeHandler

if TYPE_CHECKING:
    from context_aware_translation.storage.task_store import TaskStore, TaskRecord
    from context_aware_translation.workflow.tasks.worker_deps import WorkerDeps

logger = logging.getLogger(__name__)


class EngineCore:
    """Pure-Python task scheduling/admission engine (no Qt dependency)."""

    def __init__(self, *, store: "TaskStore", deps: "WorkerDeps") -> None:
        self._handlers: dict[str, TaskTypeHandler] = {}
        self._store: "TaskStore" = store
        self._deps: "WorkerDeps" = deps
        self._active_workers: dict[str, object] = {}      # task_id -> worker
        self._active_claims: dict[str, frozenset[ResourceClaim]] = {}
        self._retry_after_by_book: dict[str, float] = {}
        self._book_locks: dict[str, threading.RLock] = {}
        self._arbiter = ClaimArbiter()

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def register_handler(self, handler: TaskTypeHandler) -> None:
        self._handlers[handler.task_type] = handler

    def _handler_or_raise(self, task_type: str) -> TaskTypeHandler:
        handler = self._handlers.get(task_type)
        if handler is None:
            raise RuntimeError(f"No handler registered for task_type={task_type!r}")
        return handler

    # ------------------------------------------------------------------
    # Locking helpers
    # ------------------------------------------------------------------

    def _book_lock(self, book_id: str) -> threading.RLock:
        lock = self._book_locks.get(book_id)
        if lock is None:
            lock = threading.RLock()
            self._book_locks[book_id] = lock
        return lock

    # ------------------------------------------------------------------
    # Snapshot helpers
    # ------------------------------------------------------------------

    def _build_snapshot(self) -> ActionSnapshot:
        """Unlocked snapshot for tick scanning."""
        return ActionSnapshot(
            running_task_ids=frozenset(self._active_workers.keys()),
            active_claims=frozenset(
                claim
                for claims in self._active_claims.values()
                for claim in claims
            ),
            now_monotonic=time.monotonic(),
            retry_after_by_book=dict(self._retry_after_by_book),
        )

    def _build_snapshot_locked(self, book_id: str) -> ActionSnapshot:
        """Locked snapshot for preflight/start (called under book lock)."""
        return self._build_snapshot()

    # ------------------------------------------------------------------
    # Query APIs
    # ------------------------------------------------------------------

    def get_tasks(self, book_id: str, task_type: str | None = None) -> list["TaskRecord"]:
        return self._store.list_tasks(book_id=book_id, task_type=task_type)

    def get_task(self, task_id: str) -> "TaskRecord | None":
        return self._store.get(task_id)

    def has_active_worker(self, task_id: str) -> bool:
        return task_id in self._active_workers

    def has_running_work(self) -> bool:
        return bool(self._active_workers)

    def has_active_claims(self, book_id: str, wanted: frozenset[ResourceClaim]) -> bool:
        all_active: frozenset[ResourceClaim] = frozenset(
            claim
            for claims in self._active_claims.values()
            for claim in claims
        )
        return self._arbiter.conflicts(wanted, all_active)

    # ------------------------------------------------------------------
    # Preflight checks
    # ------------------------------------------------------------------

    @staticmethod
    def _encode_creation_params(params: dict) -> tuple[str | None, str | None]:
        document_ids_json: str | None = None
        doc_ids = params.get("document_ids")
        if doc_ids is not None:
            if not isinstance(doc_ids, list):
                raise ValueError("document_ids must be a list[int] or None")
            document_ids_json = json.dumps([int(doc_id) for doc_id in doc_ids], ensure_ascii=False)
        payload_json = json.dumps(params, ensure_ascii=False) if params else None
        return document_ids_json, payload_json

    @staticmethod
    def _build_draft_record(
        *,
        book_id: str,
        task_type: str,
        document_ids_json: str | None,
        payload_json: str | None,
    ):
        from context_aware_translation.storage.task_store import TaskRecord

        now = time.time()
        return TaskRecord(
            task_id="__draft__",
            book_id=book_id,
            task_type=task_type,
            status="queued",
            phase=None,
            document_ids_json=document_ids_json,
            payload_json=payload_json,
            cancel_requested=False,
            total_items=0,
            completed_items=0,
            failed_items=0,
            last_error=None,
            created_at=now,
            updated_at=now,
        )

    def preflight(
        self,
        task_type: str,
        book_id: str,
        params: dict,
        action: TaskAction,
    ) -> Decision:
        """Advisory check under book lock."""
        with self._book_lock(book_id):
            handler = self._handler_or_raise(task_type)
            # Domain-specific submission validation (e.g. manga check)
            submit_decision = handler.validate_submit(book_id, params, self._deps)
            if not submit_decision.allowed:
                return submit_decision
            document_ids_json, payload_json = self._encode_creation_params(params)
            draft = self._build_draft_record(
                book_id=book_id,
                task_type=task_type,
                document_ids_json=document_ids_json,
                payload_json=payload_json,
            )
            payload = handler.decode_payload(draft)
            snapshot = self._build_snapshot_locked(book_id)
            decision = handler.can(action, draft, payload, snapshot)
            if not decision.allowed:
                return decision
            wanted = handler.claims(draft, payload)
            all_active: frozenset[ResourceClaim] = frozenset(
                claim
                for claims_set in self._active_claims.values()
                for claim in claims_set
            )
            if self._arbiter.conflicts(wanted, all_active):
                return Decision(allowed=False, reason="Blocked by active task claims")
            return Decision(allowed=True)

    def preflight_task(self, task_id: str, action: TaskAction) -> Decision:
        """Advisory check for an existing task."""
        record = self._store.get(task_id)
        if record is None:
            return Decision(allowed=False, reason=f"Task not found: {task_id}")
        with self._book_lock(record.book_id):
            handler = self._handler_or_raise(record.task_type)
            payload = handler.decode_payload(record)
            snapshot = self._build_snapshot_locked(record.book_id)
            decision = handler.can(action, record, payload, snapshot)
            if not decision.allowed:
                return decision
            # Check claim conflicts for RUN action
            if action == TaskAction.RUN:
                wanted = handler.claims(record, payload)
                all_active = frozenset(
                    claim
                    for claims_set in self._active_claims.values()
                    for claim in claims_set
                )
                if self._arbiter.conflicts(wanted, all_active):
                    return Decision(allowed=False, reason="Blocked by active task claims")
            return Decision(allowed=True)

    # ------------------------------------------------------------------
    # Mutation APIs
    # ------------------------------------------------------------------

    def authorize_start(self, task_id: str, action: TaskAction) -> tuple["TaskRecord", object, frozenset[ResourceClaim]]:
        """Authorize under per-book lock, build worker. Returns (record, worker, claims).

        Caller is responsible for connecting signals and calling worker.start().
        """
        record = self._store.get(task_id)
        if record is None:
            raise KeyError(f"Task not found: {task_id}")

        with self._book_lock(record.book_id):
            # Re-fetch under lock for freshness
            record = self._store.get(task_id)
            if record is None:
                raise KeyError(f"Task not found after lock: {task_id}")
            if task_id in self._active_workers:
                raise RuntimeError(f"Task {task_id} already has an active worker")

            handler = self._handler_or_raise(record.task_type)
            payload = handler.decode_payload(record)
            snapshot = self._build_snapshot_locked(record.book_id)
            decision = handler.can(action, record, payload, snapshot)
            if not decision.allowed:
                raise RuntimeError(f"Action {action} not allowed for task {task_id}: {decision.reason}")

            claims = handler.claims(record, payload)
            all_active: frozenset[ResourceClaim] = frozenset(
                claim
                for claims_set in self._active_claims.values()
                for claim in claims_set
            )
            if self._arbiter.conflicts(claims, all_active):
                raise RuntimeError(f"Resource conflict for task {task_id}")

            worker = handler.build_worker(action, record, payload, self._deps)

        return record, worker, claims

    def register_active_worker(self, task_id: str, worker: object, claims: frozenset[ResourceClaim]) -> None:
        """Register a worker as active after it has been started."""
        self._active_workers[task_id] = worker
        self._active_claims[task_id] = claims

    def submit(self, task_type: str, book_id: str, **params) -> "TaskRecord":
        """Create a new task row (does not start worker — caller handles that)."""
        handler = self._handler_or_raise(task_type)
        submit_decision = handler.validate_submit(book_id, params, self._deps)
        if not submit_decision.allowed:
            raise ValueError(f"Submit rejected: {submit_decision.reason}")
        document_ids_json, payload_json = self._encode_creation_params(params)
        with self._book_lock(book_id):
            record = self._store.create(
                book_id=book_id,
                task_type=task_type,
                status="queued",
                document_ids_json=document_ids_json,
                payload_json=payload_json,
            )
        return record

    def ensure_runnable(self, task_id: str) -> "TaskRecord":
        """Atomically reset a terminal task to queued if handler allows RUN; non-terminal tasks are returned as-is."""
        record = self._store.get(task_id)
        if record is None:
            raise KeyError(f"Task not found: {task_id}")
        with self._book_lock(record.book_id):
            record = self._store.get(task_id)
            if record is None:
                raise KeyError(f"Task not found after lock: {task_id}")
            if record.status in TERMINAL_TASK_STATUSES:
                handler = self._handler_or_raise(record.task_type)
                payload = handler.decode_payload(record)
                snapshot = self._build_snapshot_locked(record.book_id)
                decision = handler.can(TaskAction.RUN, record, payload, snapshot)
                if not decision.allowed:
                    raise ValueError(f"Cannot run task {task_id}: {decision.reason}")
                record = self._store.update(task_id, status="queued", cancel_requested=False)
        return record

    def rerun(self, task_id: str) -> "TaskRecord":
        """Reset a terminal task to queued."""
        record = self._store.get(task_id)
        if record is None:
            raise KeyError(f"Task not found: {task_id}")
        if record.status not in TERMINAL_TASK_STATUSES:
            raise ValueError(f"Cannot rerun task {task_id} with non-terminal status: {record.status}")
        return self._store.update(task_id, status="queued", cancel_requested=False)

    def cancel(self, task_id: str) -> object | None:
        """Request cancellation only if handler policy allows it.
        Returns the worker to interrupt (if any), or None.
        """
        record = self._store.get(task_id)
        if record is None:
            logger.warning("cancel() called for unknown task %s", task_id)
            return None
        worker = None
        with self._book_lock(record.book_id):
            record = self._store.get(task_id)
            if record is None:
                logger.warning("cancel() called for missing task %s after lock", task_id)
                return None
            handler = self._handler_or_raise(record.task_type)
            payload = handler.decode_payload(record)
            snapshot = self._build_snapshot_locked(record.book_id)
            decision = handler.can(TaskAction.CANCEL, record, payload, snapshot)
            if not decision.allowed:
                logger.debug("cancel() denied for task %s: %s", task_id, decision.reason)
                return None
            self._store.mark_cancel_requested(task_id)
            worker = self._active_workers.get(task_id)
        return worker

    def delete(self, task_id: str) -> str | None:
        """Delete a task if handler policy allows it and worker is not active.
        Returns book_id on success, None on task-not-found.
        """
        record = self._store.get(task_id)
        if record is None:
            return None
        with self._book_lock(record.book_id):
            record = self._store.get(task_id)
            if record is None:
                return None
            handler = self._handler_or_raise(record.task_type)
            payload = handler.decode_payload(record)
            snapshot = self._build_snapshot_locked(record.book_id)
            decision = handler.can(TaskAction.DELETE, record, payload, snapshot)
            if not decision.allowed:
                raise ValueError(f"Cannot delete task {task_id}: {decision.reason}")
            if task_id in self._active_workers:
                raise ValueError(f"Cannot delete task {task_id}: worker still active")
            warnings = handler.pre_delete(record, payload, self._deps)
            for w in warnings:
                logger.warning("pre_delete warning for task %s: %s", task_id, w)
            self._store.delete(task_id)
        return record.book_id

    def cancel_running_tasks(self, book_id: str) -> list[object]:
        """Interrupt active workers for the given book using handler policy.
        Returns list of workers to interrupt.
        """
        workers_to_interrupt: list[object] = []
        for task_id, worker in list(self._active_workers.items()):
            record = self._store.get(task_id)
            if record is None or record.book_id != book_id:
                continue
            cancelled_worker = self.cancel(task_id)
            if cancelled_worker is not None:
                workers_to_interrupt.append(cancelled_worker)
        return workers_to_interrupt

    # ------------------------------------------------------------------
    # Tick scanning
    # ------------------------------------------------------------------

    def scan_autorunnable(self) -> list[str]:
        """Return list of task_ids that should be started."""
        snapshot = self._build_snapshot()
        startable: list[str] = []
        for record in self._store.list_tasks(exclude_statuses=TERMINAL_TASK_STATUSES):
            if record.task_id in self._active_workers:
                continue
            try:
                handler = self._handler_or_raise(record.task_type)
            except RuntimeError:
                raise
            payload = handler.decode_payload(record)
            if self._is_in_backoff(record.book_id, snapshot.now_monotonic):
                continue
            decision = handler.can_autorun(record, payload, snapshot)
            if not decision.allowed:
                continue
            startable.append(record.task_id)
        return startable

    # ------------------------------------------------------------------
    # Worker tracking
    # ------------------------------------------------------------------

    def release_task_resources(self, task_id: str) -> None:
        self._active_workers.pop(task_id, None)
        self._active_claims.pop(task_id, None)

    def cleanup_finished_workers(self) -> list[str]:
        """Clean up finished workers. Returns list of cleaned-up task_ids."""
        finished = [
            tid for tid, w in list(self._active_workers.items())
            if hasattr(w, "isRunning") and not w.isRunning()  # type: ignore[attr-defined]
        ]
        for task_id in finished:
            self.release_task_resources(task_id)
        return finished

    # ------------------------------------------------------------------
    # Backoff helpers
    # ------------------------------------------------------------------

    def _set_backoff(self, book_id: str, now: float) -> None:
        self._retry_after_by_book[book_id] = now + 30

    def _is_in_backoff(self, book_id: str, now: float) -> bool:
        retry_after = self._retry_after_by_book.get(book_id)
        return retry_after is not None and now < retry_after

    # ------------------------------------------------------------------
    # Public worker access
    # ------------------------------------------------------------------

    def active_worker_items(self) -> list[tuple[str, object]]:
        """Return snapshot of (task_id, worker) pairs."""
        return list(self._active_workers.items())

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._store.close()
