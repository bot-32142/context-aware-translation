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
from context_aware_translation.llm.batch_jobs.base import POLL_STATUS_COMPLETED
from context_aware_translation.storage.repositories.llm_batch_store import (
    STATUS_COMPLETED as LLM_BATCH_STATUS_COMPLETED,
)
from context_aware_translation.storage.repositories.llm_batch_store import (
    STATUS_FAILED as LLM_BATCH_STATUS_FAILED,
)
from context_aware_translation.storage.repositories.llm_batch_store import (
    LLMBatchStore,
)
from context_aware_translation.storage.repositories.task_store import TaskRecord, TaskStore
from context_aware_translation.workflow.runtime import WorkflowContext
from context_aware_translation.workflow.tasks.execution.batch_translation_ops import (
    StageItemState,
    apply_results,
    compute_phase_progress,
    decode_task_payload,
    ensure_payload_prepared,
    is_item_translation_success,
    new_payload_stage,
    new_stage_state,
    run_polish_stage,
    run_translation_stage,
)
from context_aware_translation.workflow.tasks.models import (
    PHASE_DONE,
    PHASE_TRANSLATION_SUBMIT,
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

    def _normalize_stage(existing: dict[str, Any]) -> StageItemState:
        normalized = new_stage_state(messages=existing.get("messages") if existing else None)

        messages = existing.get("messages")
        if messages is None or isinstance(messages, list):
            normalized["messages"] = messages

        request_hash = existing.get("request_hash")
        if request_hash is None or isinstance(request_hash, str):
            normalized["request_hash"] = request_hash

        inlined_request = existing.get("inlined_request")
        if inlined_request is None or isinstance(inlined_request, dict):
            normalized["inlined_request"] = inlined_request

        state = existing.get("state")
        if isinstance(state, str) and state:
            normalized["state"] = state

        error = existing.get("error")
        if error is None or isinstance(error, str):
            normalized["error"] = error

        fallback_attempted = existing.get("fallback_attempted")
        if isinstance(fallback_attempted, bool):
            normalized["fallback_attempted"] = fallback_attempted

        output_blocks = existing.get("output_blocks")
        if output_blocks is None or isinstance(output_blocks, list):
            normalized["output_blocks"] = output_blocks

        return normalized

    def _is_stage_final(existing: dict[str, Any]) -> bool:
        state = str(existing.get("state") or "")
        return state in {"succeeded", "skipped"}

    payload = dict(payload)
    items = payload.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            if bool(item.get("applied")):
                continue
            translation_raw = item.get("translation")
            existing_translation: dict[str, Any] = translation_raw if isinstance(translation_raw, dict) else {}
            translation_final = _is_stage_final(existing_translation)
            if translation_final:
                item["translation"] = _normalize_stage(existing_translation)
            else:
                item["translation"] = new_stage_state(
                    messages=existing_translation.get("messages") if existing_translation else None
                )

            polish_raw = item.get("polish")
            existing_polish: dict[str, Any] = polish_raw if isinstance(polish_raw, dict) else {}
            polish_final = _is_stage_final(existing_polish)
            if translation_final and polish_final:
                item["polish"] = _normalize_stage(existing_polish)
            else:
                item["polish"] = new_stage_state(messages=existing_polish.get("messages") if existing_polish else None)
    payload["translation"] = new_payload_stage()
    payload["polish"] = new_payload_stage()
    return payload


class BatchTranslationExecutor:
    """Persistent task orchestrator for async Gemini initial-call batch translation."""

    def __init__(
        self,
        *,
        workflow: WorkflowContext,
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
        workflow: WorkflowContext,
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

    def _persist(self, task_id: str, **kwargs: object) -> TaskRecord:
        current = self.task_store.get(task_id)
        if current is None:
            raise ValueError(f"Task not found: {task_id}")

        changed: dict[str, object] = {}
        for key, value in kwargs.items():
            if getattr(current, key) != value:
                changed[key] = value

        if not changed:
            return current

        record = self.task_store.update(task_id, **changed)
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
        batch_hashes = self._collect_batch_request_hashes(payload)
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
            request_hashes = batch_hashes.get(batch_name, set())
            if request_hashes:
                try:
                    poll_result = await self.gateway.poll_once(
                        batch_config=batch_config,
                        batch_name=batch_name,
                        request_hashes=set(request_hashes),
                        batch_store=self.llm_batch_store,
                    )
                    if poll_result.status == POLL_STATUS_COMPLETED:
                        logger.info(
                            "Recovered %d cached responses from provider batch %s before cancellation.",
                            len(request_hashes),
                            batch_name,
                        )
                except Exception as exc:
                    logger.warning(
                        "Failed to recover responses for provider batch %s before cancel of task %s: %s",
                        batch_name,
                        task_id,
                        exc,
                    )

            try:
                pre_state = await self.gateway.get_batch_state(
                    batch_config=batch_config,
                    batch_name=batch_name,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to inspect Gemini batch %s before cancel for task %s: %s",
                    batch_name,
                    task_id,
                    exc,
                )
                has_active_batches = True
                if last_error is None:
                    last_error = f"{type(exc).__name__}: {exc}"
                continue

            # Never issue cancel for terminal provider states. Some providers
            # surface terminal-completed jobs as cancelled when cancel is sent
            # late; that is noisy and can confuse users.
            if pre_state not in _ACTIVE_PROVIDER_BATCH_STATES:
                continue

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
        payload: dict[str, Any] | None = None
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
            # Do NOT reset payload for normal queued/paused resume. Resetting
            # here would discard checkpointed stage state (e.g. validate
            # outputs) and re-trigger avoidable LLM work on restart.
            payload = await ensure_payload_prepared(
                self,
                task,
                payload,
                cancel_check=cancel_check,
                progress_callback=progress_callback,
            )
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
                if payload is not None:
                    self._persist(task_id, payload_json=json.dumps(payload, ensure_ascii=False))
                return await self.request_cancel(task_id)
            pause_updates: dict[str, object] = {"status": STATUS_PAUSED}
            if payload is not None:
                pause_updates["payload_json"] = json.dumps(payload, ensure_ascii=False)
            return self._persist(task_id, **pause_updates)
        except OperationCancelledError:
            refreshed = self.task_store.get(task_id)
            if refreshed is not None and refreshed.cancel_requested:
                if payload is not None:
                    self._persist(task_id, payload_json=json.dumps(payload, ensure_ascii=False))
                return await self.request_cancel(task_id)
            cancel_pause_updates: dict[str, object] = {"status": STATUS_PAUSED}
            if payload is not None:
                cancel_pause_updates["payload_json"] = json.dumps(payload, ensure_ascii=False)
            return self._persist(task_id, **cancel_pause_updates)
        except Exception as exc:
            if _is_transient_batch_error(exc):
                logger.warning("Batch translation task paused on transient error: %s (%s)", task_id, exc)
                transient_updates: dict[str, object] = {
                    "status": STATUS_PAUSED,
                    "last_error": f"{type(exc).__name__}: {exc}",
                }
                if payload is not None:
                    transient_updates["payload_json"] = json.dumps(payload, ensure_ascii=False)
                return self._persist(task_id, **transient_updates)
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

    def _decode_payload(self, task: TaskRecord) -> dict[str, Any]:
        return decode_task_payload(task)

    def persist_poll_progress(
        self,
        task_id: str,
        payload: dict[str, Any],
        *,
        stage: str,
        phase: str,
    ) -> TaskRecord:
        """Persist poll-phase counters from llm_batch_store cache state.

        This updates only row-level counters/phase/status and avoids rewriting
        potentially large payload_json on every poll tick.
        """
        items = payload.get("items")
        if not isinstance(items, list):
            items = []

        if stage == "polish":
            relevant = [item for item in items if is_item_translation_success(item)]
        else:
            relevant = [item for item in items if isinstance(item, dict)]

        total_items = len(relevant)
        completed_items = 0
        failed_items = 0

        for item in relevant:
            sd = item.get(stage) if isinstance(item, dict) else None
            if not isinstance(sd, dict):
                continue

            # If in-memory payload already left "pending", trust that first.
            state = str(sd.get("state") or "")
            if state and state != "pending":
                completed_items += 1
                if state == "failed":
                    failed_items += 1
                continue

            request_hash = sd.get("request_hash")
            if not isinstance(request_hash, str) or not request_hash:
                continue
            record = self.llm_batch_store.get(request_hash)
            if record is None:
                continue
            if record.status == LLM_BATCH_STATUS_COMPLETED:
                completed_items += 1
            elif record.status == LLM_BATCH_STATUS_FAILED:
                completed_items += 1
                failed_items += 1

        return self._persist(
            task_id,
            status=STATUS_RUNNING,
            phase=phase,
            total_items=total_items,
            completed_items=completed_items,
            failed_items=failed_items,
        )

    @staticmethod
    def _collect_batch_request_hashes(payload: dict[str, Any]) -> dict[str, set[str]]:
        batch_hashes: dict[str, set[str]] = {}
        for stage in ("translation", "polish"):
            stage_meta = payload.get(stage)
            if not isinstance(stage_meta, dict):
                continue
            jobs = stage_meta.get("jobs")
            if not isinstance(jobs, list):
                continue
            for job in jobs:
                if not isinstance(job, dict):
                    continue
                batch_name = job.get("batch_name")
                request_hashes = job.get("request_hashes")
                if not isinstance(batch_name, str) or not batch_name:
                    continue
                if not isinstance(request_hashes, list):
                    continue
                bucket = batch_hashes.setdefault(batch_name, set())
                for request_hash in request_hashes:
                    if isinstance(request_hash, str) and request_hash:
                        bucket.add(request_hash)
        return batch_hashes

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
        if not isinstance(items, list):
            items = []
        total_items, completed_items, failed_items = compute_phase_progress(items, phase)
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
