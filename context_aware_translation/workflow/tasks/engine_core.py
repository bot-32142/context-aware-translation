from __future__ import annotations

import json
import logging
import threading
import time
from typing import TYPE_CHECKING

from context_aware_translation.workflow.tasks.claims import ClaimArbiter, ResourceClaim
from context_aware_translation.workflow.tasks.exceptions import CancelDispatchRaceError, RunValidationError
from context_aware_translation.workflow.tasks.handlers.base import TaskTypeHandler
from context_aware_translation.workflow.tasks.models import TERMINAL_TASK_STATUSES, ActionSnapshot, Decision, TaskAction

if TYPE_CHECKING:
    from context_aware_translation.storage.repositories.task_store import TaskRecord, TaskStore
    from context_aware_translation.workflow.tasks.worker_deps import WorkerDeps

# TTL in seconds for the config snapshot viability probe cache (per book)
_PROBE_CACHE_TTL = 2.0

logger = logging.getLogger(__name__)


class EngineCore:
    """Pure-Python task scheduling/admission engine (no Qt dependency)."""

    def __init__(self, *, store: TaskStore, deps: WorkerDeps) -> None:
        self._handlers: dict[str, TaskTypeHandler] = {}
        self._store: TaskStore = store
        self._deps: WorkerDeps = deps
        self._active_workers: dict[str, object] = {}  # task_id -> worker
        self._active_claims: dict[str, frozenset[ResourceClaim]] = {}
        self._retry_after_by_book: dict[str, float] = {}
        self._book_locks: dict[str, threading.RLock] = {}
        self._book_locks_guard = threading.Lock()
        self._arbiter = ClaimArbiter()
        # Cache: book_id -> (expires_monotonic, success: bool)
        self._probe_cache: dict[str, tuple[float, bool]] = {}

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
        with self._book_locks_guard:
            lock = self._book_locks.get(book_id)
            if lock is None:
                lock = threading.RLock()
                self._book_locks[book_id] = lock
            return lock

    # ------------------------------------------------------------------
    # Config snapshot helpers
    # ------------------------------------------------------------------

    def _capture_config_snapshot(self, book_id: str) -> str | None:
        """Capture and serialize current config for book_id. Returns None on failure."""
        try:
            return self._deps.book_manager.get_config_snapshot_json(book_id)
        except Exception:
            logger.warning("Failed to capture config snapshot for %s", book_id, exc_info=True)
            return None

    def _probe_config_snapshot(self, book_id: str) -> bool:
        """Check if config snapshot can be captured, with short-TTL cache.

        Note: ``_probe_cache`` is accessed without a lock.  This is intentional —
        a stale or torn read can only cause an extra (cheap) snapshot attempt,
        and the TTL is short enough that any inconsistency expires within
        seconds.  Adding a lock here would serialize all preflight calls across
        books for negligible correctness gain.
        """
        now = time.monotonic()
        cached = self._probe_cache.get(book_id)
        if cached is not None:
            expires, success = cached
            if now < expires:
                return success
        result = self._capture_config_snapshot(book_id)
        success = result is not None
        self._probe_cache[book_id] = (now + _PROBE_CACHE_TTL, success)
        return success

    # ------------------------------------------------------------------
    # Action snapshot helpers
    # ------------------------------------------------------------------

    def _build_snapshot(self) -> ActionSnapshot:
        """Unlocked snapshot for tick scanning."""
        return ActionSnapshot(
            running_task_ids=frozenset(self._active_workers.keys()),
            active_claims=frozenset(claim for claims in self._active_claims.values() for claim in claims),
            now_monotonic=time.monotonic(),
            retry_after_by_book=dict(self._retry_after_by_book),
        )

    def _build_snapshot_locked(self, book_id: str) -> ActionSnapshot:
        """Locked snapshot for preflight/start (called under book lock)."""
        return self._build_snapshot()

    # ------------------------------------------------------------------
    # Query APIs
    # ------------------------------------------------------------------

    def get_tasks(self, book_id: str, task_type: str | None = None, limit: int | None = None) -> list[TaskRecord]:
        """Return full task records, including payload/config snapshot fields."""
        return self._store.list_tasks(
            book_id=book_id,
            task_type=task_type,
            limit=limit,
        )

    def get_tasks_lightweight(
        self, book_id: str, task_type: str | None = None, limit: int | None = None
    ) -> list[TaskRecord]:
        """Return lightweight task rows for UI listing.

        payload/config snapshot blobs are omitted to avoid repeated large-row reads.
        """
        return self._store.list_tasks(
            book_id=book_id,
            task_type=task_type,
            limit=limit,
            include_payload=False,
            include_config_snapshot=False,
        )

    def get_task(self, task_id: str) -> TaskRecord | None:
        return self._store.get(task_id)

    def has_active_worker(self, task_id: str) -> bool:
        return task_id in self._active_workers

    def has_running_work(self) -> bool:
        return bool(self._active_workers)

    def has_active_claims(self, book_id: str, wanted: frozenset[ResourceClaim]) -> bool:
        all_active: frozenset[ResourceClaim] = frozenset(
            claim for claims in self._active_claims.values() for claim in claims
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
    ) -> TaskRecord:
        from context_aware_translation.storage.repositories.task_store import TaskRecord

        now = time.time()
        return TaskRecord(
            task_id="__draft__",
            book_id=book_id,
            task_type=task_type,
            status="queued",
            phase=None,
            document_ids_json=document_ids_json,
            payload_json=payload_json,
            config_snapshot_json=None,
            cancel_requested=False,
            total_items=0,
            completed_items=0,
            failed_items=0,
            last_error=None,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _payload_json_for_task_rerun(task_type: str, payload_json: str | None) -> str | None:
        """Return payload_json override for rerun semantics, preserving existing keys when possible."""
        if task_type != "image_reembedding":
            return payload_json

        if not payload_json:
            raise ValueError(
                "Cannot rerun image_reembedding task: payload is missing. "
                "Task payload must be valid JSON object containing task parameters."
            )
        try:
            decoded = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            raise ValueError("Cannot rerun image_reembedding task: payload is malformed JSON.") from exc
        if not isinstance(decoded, dict):
            raise ValueError("Cannot rerun image_reembedding task: payload must be a JSON object.")
        payload: dict[str, object] = dict(decoded)

        payload["force"] = True
        return json.dumps(payload, ensure_ascii=False)

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
            # Config snapshot viability probe (matches strict submit behavior)
            if not self._probe_config_snapshot(book_id):
                return Decision(
                    allowed=False,
                    code="config_snapshot_unavailable",
                    reason="Cannot load config for this book. Check that a profile or custom config is assigned.",
                )
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
                claim for claims_set in self._active_claims.values() for claim in claims_set
            )
            if self._arbiter.conflicts(wanted, all_active):
                return Decision(allowed=False, code="blocked_claim_conflict", reason="Blocked by active task claims")
            return Decision(allowed=True)

    def preflight_task(self, task_id: str, action: TaskAction) -> Decision:
        """Advisory check for an existing task."""
        record = self._store.get(task_id)
        if record is None:
            return Decision(allowed=False, code="task_not_found", reason=f"Task not found: {task_id}")
        with self._book_lock(record.book_id):
            handler = self._handler_or_raise(record.task_type)
            payload = handler.decode_payload(record)
            snapshot = self._build_snapshot_locked(record.book_id)
            decision = handler.can(action, record, payload, snapshot)
            if not decision.allowed:
                return decision
            # RUN-specific domain validation
            if action == TaskAction.RUN:
                run_decision = handler.validate_run(record, payload, self._deps)
                if not run_decision.allowed:
                    return run_decision
            # Check claim conflicts for RUN action
            if action == TaskAction.RUN:
                wanted = handler.claims(record, payload)
                all_active = frozenset(claim for claims_set in self._active_claims.values() for claim in claims_set)
                if self._arbiter.conflicts(wanted, all_active):
                    return Decision(
                        allowed=False, code="blocked_claim_conflict", reason="Blocked by active task claims"
                    )
            return Decision(allowed=True)

    # ------------------------------------------------------------------
    # Mutation APIs
    # ------------------------------------------------------------------

    def authorize_start(self, task_id: str, action: TaskAction) -> tuple[TaskRecord, object, frozenset[ResourceClaim]]:
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
                if action == TaskAction.CANCEL:
                    raise CancelDispatchRaceError(f"Cancel not allowed for task {task_id}: {decision.reason}")
                raise RuntimeError(f"Action {action} not allowed for task {task_id}: {decision.reason}")

            # RUN-specific domain validation
            if action == TaskAction.RUN:
                run_decision = handler.validate_run(record, payload, self._deps)
                if not run_decision.allowed:
                    raise RunValidationError(
                        f"Run validation failed for task {task_id}: "
                        f"code={run_decision.code}, reason={run_decision.reason}"
                    )

            # For CANCEL, skip claim conflict check
            if action == TaskAction.CANCEL:
                worker = handler.build_worker(action, record, payload, self._deps)
                return record, worker, frozenset()

            claims = handler.claims(record, payload)
            all_active: frozenset[ResourceClaim] = frozenset(
                claim for claims_set in self._active_claims.values() for claim in claims_set
            )
            if self._arbiter.conflicts(claims, all_active):
                raise RuntimeError(f"Resource conflict for task {task_id}")

            worker = handler.build_worker(action, record, payload, self._deps)

        return record, worker, claims

    def register_active_worker(self, task_id: str, worker: object, claims: frozenset[ResourceClaim]) -> None:
        """Register a worker as active after it has been started."""
        self._active_workers[task_id] = worker
        self._active_claims[task_id] = claims

    def submit(self, task_type: str, book_id: str, **params: object) -> TaskRecord:
        """Create a new task row (does not start worker — caller handles that)."""
        handler = self._handler_or_raise(task_type)
        submit_decision = handler.validate_submit(book_id, params, self._deps)
        if not submit_decision.allowed:
            raise ValueError(f"Submit rejected: {submit_decision.reason}")
        config_snapshot_json = self._capture_config_snapshot(book_id)
        if config_snapshot_json is None:
            raise ValueError(
                f"Cannot submit task: failed to capture config snapshot for book {book_id!r}. "
                "Ensure the book has a valid profile or custom config assigned."
            )
        document_ids_json, payload_json = self._encode_creation_params(params)
        with self._book_lock(book_id):
            record = self._store.create(
                book_id=book_id,
                task_type=task_type,
                status="queued",
                document_ids_json=document_ids_json,
                payload_json=payload_json,
                config_snapshot_json=config_snapshot_json,
            )
        return record

    def ensure_runnable(self, task_id: str) -> TaskRecord:
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
                config_snapshot_json = self._capture_config_snapshot(record.book_id)
                if config_snapshot_json is None:
                    raise ValueError(
                        f"Cannot rerun task {task_id}: failed to capture config snapshot for book {record.book_id!r}. "
                        "Ensure the book has a valid profile or custom config assigned."
                    )
                payload_json = self._payload_json_for_task_rerun(record.task_type, record.payload_json)
                update_fields: dict[str, object] = {
                    "status": "queued",
                    "cancel_requested": False,
                    "config_snapshot_json": config_snapshot_json,
                }
                if payload_json != record.payload_json:
                    update_fields["payload_json"] = payload_json
                record = self._store.update(task_id, **update_fields)
        return record

    def rerun(self, task_id: str) -> TaskRecord:
        """Reset a terminal task to queued, re-capturing config snapshot."""
        record = self._store.get(task_id)
        if record is None:
            raise KeyError(f"Task not found: {task_id}")
        with self._book_lock(record.book_id):
            record = self._store.get(task_id)
            if record is None:
                raise KeyError(f"Task not found after lock: {task_id}")
            if record.status not in TERMINAL_TASK_STATUSES:
                raise ValueError(f"Cannot rerun task {task_id} with non-terminal status: {record.status}")
            handler = self._handler_or_raise(record.task_type)
            payload = handler.decode_payload(record)
            snapshot = self._build_snapshot_locked(record.book_id)
            decision = handler.can(TaskAction.RUN, record, payload, snapshot)
            if not decision.allowed:
                raise ValueError(f"Cannot rerun task {task_id}: {decision.reason}")
            config_snapshot_json = self._capture_config_snapshot(record.book_id)
            if config_snapshot_json is None:
                raise ValueError(
                    f"Cannot rerun task {task_id}: failed to capture config snapshot for book {record.book_id!r}. "
                    "Ensure the book has a valid profile or custom config assigned."
                )
            payload_json = self._payload_json_for_task_rerun(record.task_type, record.payload_json)
            update_fields: dict[str, object] = {
                "status": "queued",
                "cancel_requested": False,
                "config_snapshot_json": config_snapshot_json,
            }
            if payload_json != record.payload_json:
                update_fields["payload_json"] = payload_json
            return self._store.update(task_id, **update_fields)

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

    def handle_cancel_dispatch_failure(self, task_id: str, *, reason: str) -> None:
        record = self._store.get(task_id)
        if record is None:
            return
        with self._book_lock(record.book_id):
            record = self._store.get(task_id)
            if record is None:
                return
            if task_id in self._active_workers:
                return
            handler = self._handler_or_raise(record.task_type)
            payload = handler.decode_payload(record)
            from context_aware_translation.workflow.tasks.handlers.base import CancelDispatchPolicy

            policy = handler.cancel_dispatch_policy(record, payload)
            if policy == CancelDispatchPolicy.LOCAL_TERMINALIZE:
                if record.status in {"cancel_requested", "cancelling", "queued", "paused"}:
                    self._store.update(task_id, status="cancelled", cancel_requested=False, last_error=reason)
            elif policy == CancelDispatchPolicy.REQUIRE_REMOTE_CONFIRMATION:
                self._store.update(task_id, status="cancelling", cancel_requested=True, last_error=reason)
            else:
                raise RuntimeError(f"Unknown cancel dispatch policy: {policy!r}")

    def cancel_running_tasks(self, book_id: str) -> list[object]:
        """Interrupt active workers for the given book using handler policy.
        Returns list of workers to interrupt.
        """
        workers_to_interrupt: list[object] = []
        for task_id, _worker in list(self._active_workers.items()):
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
            tid for tid, w in list(self._active_workers.items()) if hasattr(w, "isRunning") and not w.isRunning()
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
