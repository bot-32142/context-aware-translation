from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

import httpx

from context_aware_translation.config import TranslatorBatchConfig, TranslatorConfig
from context_aware_translation.core.cancellation import OperationCancelledError
from context_aware_translation.core.progress import ProgressCallback
from context_aware_translation.llm.batch_jobs import GeminiBatchJobGateway
from context_aware_translation.storage.llm_batch_store import LLMBatchStore
from context_aware_translation.storage.task_store import TaskRecord, TaskStore
from context_aware_translation.workflow.tasks.models import (
    PHASE_DONE,
    PHASE_TRANSLATION_SUBMIT,
)
from context_aware_translation.workflow.tasks.models import (
    STATUS_CANCEL_REQUESTED,
    STATUS_CANCELLED,
    STATUS_CANCELLING,
    STATUS_COMPLETED,
    STATUS_COMPLETED_WITH_ERRORS,
    STATUS_FAILED,
    STATUS_PAUSED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    TERMINAL_TASK_STATUSES,
)
from context_aware_translation.workflow.tasks.execution.batch_translation_ops import (
    apply_results,
    decode_task_payload,
    ensure_payload_prepared,
    is_item_translation_success,
    new_payload_stage,
    new_stage_state,
    run_polish_stage,
    run_translation_stage,
)
from context_aware_translation.workflow.service import WorkflowService

logger = logging.getLogger(__name__)

DEFAULT_TASK_POLL_INTERVAL_SEC = 10
_RERUNNABLE_TERMINAL_STATUSES = {
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_COMPLETED_WITH_ERRORS,
}
RERUNNABLE_TERMINAL_STATUSES = _RERUNNABLE_TERMINAL_STATUSES
AUTO_RUN_TASK_STATUSES = frozenset(
    {
        STATUS_QUEUED,
        STATUS_RUNNING,
        STATUS_PAUSED,
        STATUS_CANCEL_REQUESTED,
        STATUS_CANCELLING,
    }
)
_ACTIVE_PROVIDER_BATCH_STATES = {
    "",  # Treat unknown/empty state as active (fail-safe: assume still running)
    "QUEUED",
    "PENDING",
    "RUNNING",
    "UPDATING",
    "PAUSED",
    "CANCELLING",
}


class _PauseRequestedError(Exception):
    pass


def _is_transient_batch_error(exc: Exception) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (TimeoutError, httpx.TimeoutException, httpx.TransportError)):
            return True
        message = str(current).lower()
        if "timed out" in message or "timeout" in message:
            return True
        if any(
            token in message
            for token in (
                "429",
                "resource_exhausted",
                "quota",
                "rate limit",
                "temporarily unavailable",
                "connection reset",
                "connection aborted",
                "network is unreachable",
                "connection refused",
            )
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def prepare_payload_for_rerun(payload: dict[str, Any]) -> dict[str, Any]:
    """Reset a batch-task payload so unapplied items are retried."""
    payload = dict(payload)
    items = payload.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            if bool(item.get("applied")):
                continue
            for stage in ("translation", "polish"):
                existing = item.get(stage) if isinstance(item.get(stage), dict) else {}
                item[stage] = new_stage_state(messages=existing.get("messages") if existing else None)
    payload["translation"] = new_payload_stage()
    payload["polish"] = new_payload_stage()
    return payload


class BatchTranslationExecutor:
    """Persistent task orchestrator for async Gemini initial-call batch translation."""

    def __init__(
        self,
        *,
        workflow: WorkflowService,
        task_store: TaskStore,
        llm_batch_store: LLMBatchStore,
        poll_interval_sec: int = DEFAULT_TASK_POLL_INTERVAL_SEC,
        notify_task_changed: Callable[[str], None] | None = None,
    ) -> None:
        self.workflow = workflow
        self.task_store = task_store
        self.llm_batch_store = llm_batch_store
        self.gateway = GeminiBatchJobGateway()
        self.poll_interval_sec = max(1, int(poll_interval_sec))
        self._notify_task_changed = notify_task_changed
        self._book_id = workflow.book_id if workflow is not None else None

    @classmethod
    def from_workflow(
        cls,
        workflow: WorkflowService,
        *,
        task_store: TaskStore | None = None,
        notify_task_changed: Callable[[str], None] | None = None,
    ) -> BatchTranslationExecutor:
        if workflow.config.sqlite_path is None:
            raise ValueError("sqlite_path is required to create BatchTranslationExecutor.")
        runtime_root = workflow.config.sqlite_path.parent
        resolved_store = task_store if task_store is not None else TaskStore(runtime_root / "task_store.db")
        return cls(
            workflow=workflow,
            task_store=resolved_store,
            llm_batch_store=LLMBatchStore(runtime_root / "llm_batch_cache.db"),
            notify_task_changed=notify_task_changed,
        )

    def close(self) -> None:
        # Only close resources this executor owns (llm_batch_store).
        # task_store may be shared; caller is responsible for its lifecycle.
        self.llm_batch_store.close()

    # ------------------------------------------------------------------
    # Internal persistence helper
    # ------------------------------------------------------------------

    def _persist(self, task_id: str, **kwargs) -> TaskRecord:
        record = self.task_store.update(task_id, **kwargs)
        if self._notify_task_changed is not None:
            book_id = record.book_id if hasattr(record, "book_id") else self._book_id
            if book_id:
                self._notify_task_changed(book_id)
        return record

    # ------------------------------------------------------------------
    # Public APIs used by UI worker
    # ------------------------------------------------------------------

    def cleanup_remote_artifacts(self, task_id: str) -> dict[str, Any]:
        task = self.task_store.get(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")

        payload = self._decode_payload(task)
        cleanup_warnings: list[str] = []
        batch_names, file_names = self._collect_remote_cleanup_targets(payload)

        try:
            batch_config = self.batch_config()
        except ValueError as exc:
            if batch_names or file_names:
                cleanup_warnings.append(
                    f"Skipped remote cleanup because translator_batch_config is unavailable: {type(exc).__name__}: {exc}"
                )
        else:
            loop: asyncio.AbstractEventLoop | None
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is None:
                cleanup_warnings.extend(
                    asyncio.run(
                        self._cleanup_remote_artifacts(
                            batch_config=batch_config,
                            batch_names=batch_names,
                            file_names=file_names,
                        )
                    )
                )
            else:
                cleanup_warnings.append(
                    "Skipped remote cleanup because cleanup_remote_artifacts was called from a running event loop."
                )

        return {
            "task_id": task_id,
            "cleanup_warnings": cleanup_warnings,
        }

    async def request_cancel(self, task_id: str) -> TaskRecord:
        task = self.task_store.get(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        if task.status in TERMINAL_TASK_STATUSES:
            return task

        task = self.task_store.mark_cancel_requested(task_id)
        payload = self._decode_payload(task)
        collected_names, _ = self._collect_remote_cleanup_targets(payload)
        batch_names = list(collected_names)
        display_names = []
        for stage in ("translation", "polish"):
            stage_meta = payload.get(stage)
            if isinstance(stage_meta, dict):
                dn = stage_meta.get("batch_display_name")
                if isinstance(dn, str) and dn:
                    display_names.append(dn)
        try:
            batch_config = self.batch_config()
        except ValueError as exc:
            local_cancel_note = None
            if batch_names or display_names:
                local_cancel_note = (
                    "Skipped provider batch cancellation because translator_batch_config is unavailable: "
                    f"{type(exc).__name__}: {exc}"
                )
                logger.warning("Task %s marked cancelled locally without provider cancellation: %s", task_id, exc)
            return self._persist(
                task_id,
                status=STATUS_CANCELLED,
                phase=PHASE_DONE,
                last_error=local_cancel_note,
            )

        model = str(payload.get("model") or batch_config.model or "")
        for display_name in display_names:
            try:
                resolved_names = await self.gateway.find_batch_names(
                    batch_config=batch_config,
                    display_name=display_name,
                    model=model or None,
                )
            except Exception as exc:
                logger.warning("Failed to resolve batch names by display_name=%s: %s", display_name, exc)
                continue
            for resolved_name in resolved_names:
                if resolved_name not in batch_names:
                    batch_names.append(resolved_name)

        if not batch_names:
            return self._persist(
                task_id,
                status=STATUS_CANCELLED,
                phase=PHASE_DONE,
            )

        task = self._persist(task_id, status=STATUS_CANCELLING)
        has_active_batches = False
        last_error: str | None = None
        for batch_name in batch_names:
            try:
                await self.gateway.cancel_batch(
                    batch_config=batch_config,
                    batch_name=batch_name,
                )
            except Exception as exc:
                logger.warning("Failed to cancel Gemini batch %s for task %s: %s", batch_name, task_id, exc)
                if last_error is None:
                    last_error = f"{type(exc).__name__}: {exc}"
            try:
                state_name = await self.gateway.get_batch_state(
                    batch_config=batch_config,
                    batch_name=batch_name,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to inspect Gemini batch %s after cancel for task %s: %s", batch_name, task_id, exc
                )
                has_active_batches = True
                if last_error is None:
                    last_error = f"{type(exc).__name__}: {exc}"
                continue
            if state_name in _ACTIVE_PROVIDER_BATCH_STATES:
                has_active_batches = True

        if has_active_batches:
            return self._persist(
                task_id,
                status=STATUS_CANCELLING,
                last_error=last_error,
            )
        return self._persist(
            task_id,
            status=STATUS_CANCELLED,
            phase=PHASE_DONE,
            last_error=last_error,
        )

    async def run_task(
        self,
        task_id: str,
        *,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> TaskRecord:
        task = self.task_store.get(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        if task.status == STATUS_COMPLETED:
            return task
        if task.status in _RERUNNABLE_TERMINAL_STATUSES:
            payload = prepare_payload_for_rerun(self._decode_payload(task))
            task = self._persist(
                task_id,
                status=STATUS_PAUSED,
                cancel_requested=False,
                payload_json=json.dumps(payload, ensure_ascii=False),
                last_error=None,
            )
        elif task.status in TERMINAL_TASK_STATUSES:
            return task
        if task.cancel_requested:
            return await self.request_cancel(task_id)

        try:
            task = self._persist(task_id, status=STATUS_RUNNING)
            payload = self._decode_payload(task)
            # If re-queued from a terminal state, reset stale payload items.
            existing_items = payload.get("items")
            if isinstance(existing_items, list) and existing_items:
                payload = prepare_payload_for_rerun(payload)
            payload = await ensure_payload_prepared(self, task, payload, cancel_check=cancel_check)
            task = self.persist_payload(task_id, payload, phase=PHASE_TRANSLATION_SUBMIT, status=STATUS_RUNNING)

            if not payload.get("items"):
                return self._persist(
                    task_id,
                    status=STATUS_COMPLETED,
                    phase=PHASE_DONE,
                    total_items=0,
                    completed_items=0,
                    failed_items=0,
                )

            payload = await run_translation_stage(
                self,
                task_id,
                payload,
                force=self._get_force(task),
                cancel_check=cancel_check,
                progress_callback=progress_callback,
            )

            payload = await run_polish_stage(
                self,
                task_id,
                payload,
                force=self._get_force(task),
                cancel_check=cancel_check,
                progress_callback=progress_callback,
            )

            payload = apply_results(self, task_id, payload, progress_callback=progress_callback)

            failed_items = sum(1 for item in payload["items"] if not is_item_translation_success(item))
            completed_items = sum(1 for item in payload["items"] if bool(item.get("applied")))

            terminal_status = STATUS_COMPLETED
            last_error: str | None = None
            refreshed = self.task_store.get(task_id)
            if refreshed is not None and refreshed.cancel_requested:
                terminal_status = STATUS_CANCELLED
            elif failed_items > 0:
                terminal_status = STATUS_COMPLETED_WITH_ERRORS
                failed_messages = [
                    str(
                        item.get("translation", {}).get("error")
                        or item.get("polish", {}).get("error")
                        or "Unknown translation error"
                    )
                    for item in payload["items"]
                    if not is_item_translation_success(item)
                ]
                last_error = failed_messages[0] if failed_messages else "Some items failed."

            return self._persist(
                task_id,
                status=terminal_status,
                phase=PHASE_DONE,
                payload_json=json.dumps(payload, ensure_ascii=False),
                total_items=len(payload["items"]),
                completed_items=completed_items,
                failed_items=failed_items,
                last_error=last_error,
            )
        except _PauseRequestedError:
            refreshed = self.task_store.get(task_id)
            if refreshed is not None and refreshed.cancel_requested:
                return await self.request_cancel(task_id)
            return self._persist(task_id, status=STATUS_PAUSED)
        except OperationCancelledError:
            refreshed = self.task_store.get(task_id)
            if refreshed is not None and refreshed.cancel_requested:
                return await self.request_cancel(task_id)
            return self._persist(task_id, status=STATUS_PAUSED)
        except Exception as exc:
            if _is_transient_batch_error(exc):
                logger.warning("Batch translation task paused on transient error: %s (%s)", task_id, exc)
                return self._persist(
                    task_id,
                    status=STATUS_PAUSED,
                    last_error=f"{type(exc).__name__}: {exc}",
                )
            logger.exception("Batch translation task failed: %s", task_id)
            return self._persist(
                task_id,
                status=STATUS_FAILED,
                phase=PHASE_DONE,
                last_error=f"{type(exc).__name__}: {exc}",
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_force(self, task: TaskRecord) -> bool:
        """Extract the 'force' flag from task payload_json (set by engine at task creation)."""
        payload = self._decode_payload(task)
        return bool(payload.get("force", False))

    def _get_skip_context(self, task: TaskRecord) -> bool:
        """Extract the 'skip_context' flag from task payload_json."""
        payload = self._decode_payload(task)
        return bool(payload.get("skip_context", False))

    def _decode_payload(self, task: TaskRecord) -> dict[str, Any]:
        return decode_task_payload(task)

    @staticmethod
    def _collect_remote_cleanup_targets(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
        batch_names: set[str] = set()
        file_names: set[str] = set()

        for stage in ("translation", "polish"):
            stage_meta = payload.get(stage)
            if not isinstance(stage_meta, dict):
                continue
            value = stage_meta.get("batch_name")
            if isinstance(value, str) and value:
                batch_names.add(value)
            jobs = stage_meta.get("jobs")
            if not isinstance(jobs, list):
                continue
            for job in jobs:
                if not isinstance(job, dict):
                    continue
                batch_name = job.get("batch_name")
                if isinstance(batch_name, str) and batch_name:
                    batch_names.add(batch_name)
                source_file_name = job.get("source_file_name")
                if isinstance(source_file_name, str) and source_file_name:
                    file_names.add(source_file_name)
                output_file_name = job.get("output_file_name")
                if isinstance(output_file_name, str) and output_file_name:
                    file_names.add(output_file_name)

        return sorted(batch_names), sorted(file_names)

    async def _cleanup_remote_artifacts(
        self,
        *,
        batch_config: TranslatorBatchConfig,
        batch_names: list[str],
        file_names: list[str],
    ) -> list[str]:
        warnings: list[str] = []

        for batch_name in batch_names:
            try:
                await self.gateway.delete_batch(batch_config=batch_config, batch_name=batch_name)
            except Exception as exc:
                warnings.append(f"Failed to delete remote batch '{batch_name}': {type(exc).__name__}: {exc}")

        for file_name in file_names:
            try:
                await self.gateway.delete_file(batch_config=batch_config, file_name=file_name)
            except Exception as exc:
                warnings.append(f"Failed to delete remote file '{file_name}': {type(exc).__name__}: {exc}")

        return warnings

    def persist_payload(
        self,
        task_id: str,
        payload: dict[str, Any],
        *,
        phase: str,
        status: str,
    ) -> TaskRecord:
        items = payload.get("items", [])
        total_items = len(items) if isinstance(items, list) else 0
        completed_items = 0
        failed_items = 0
        if isinstance(items, list):
            completed_items = sum(1 for item in items if isinstance(item, dict) and bool(item.get("applied")))
            failed_items = sum(
                1
                for item in items
                if isinstance(item, dict)
                and isinstance(item.get("translation"), dict)
                and item["translation"].get("state") == "failed"
            )
        return self._persist(
            task_id,
            status=status,
            phase=phase,
            payload_json=json.dumps(payload, ensure_ascii=False),
            total_items=total_items,
            completed_items=completed_items,
            failed_items=failed_items,
        )

    def batch_config(self) -> TranslatorBatchConfig:
        batch_config = self.workflow.config.translator_batch_config
        if not isinstance(batch_config, TranslatorBatchConfig):
            raise ValueError("translator_batch_config is required.")
        return batch_config

    def translator_config(self) -> TranslatorConfig:
        translator_config = self.workflow.config.translator_config
        if translator_config is None:
            raise ValueError("translator_config is required.")
        return translator_config

    def document_ids_for_task(self, task: TaskRecord) -> list[int] | None:
        if task.document_ids_json is None or task.document_ids_json == "":
            return None
        raw = json.loads(task.document_ids_json)
        if not isinstance(raw, list):
            raise ValueError("Invalid task document_ids_json payload.")
        return [int(doc_id) for doc_id in raw]

    def raise_if_local_pause(self, task_id: str, cancel_check: Callable[[], bool] | None) -> None:
        # Check local thread interruption (UI-initiated pause).
        if cancel_check is not None and cancel_check():
            raise _PauseRequestedError()
        # Check DB for external cancel request (e.g. from cancel worker or UI).
        task = self.task_store.get(task_id)
        if task is not None and task.cancel_requested:
            raise _PauseRequestedError()
