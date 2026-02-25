from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from context_aware_translation.workflow.tasks.execution.batch_translation_executor import BatchTranslationExecutor

from context_aware_translation.core.cancellation import OperationCancelledError
from context_aware_translation.core.progress import ProgressCallback, ProgressUpdate, WorkflowStep
from context_aware_translation.llm.batch_jobs import (
    POLL_STATUS_CANCELLED,
    POLL_STATUS_FAILED,
    POLL_STATUS_PENDING,
    BatchPollResult,
)
from context_aware_translation.llm.translator import (
    build_polish_prompt,
    prepare_chunk_translation,
    reconstruct_chunk_translations,
    validated_chat,
)
from context_aware_translation.storage.llm_batch_store import STATUS_FAILED, STATUS_SUBMITTED
from context_aware_translation.storage.task_store import TaskRecord
from context_aware_translation.workflow.tasks.models import (
    PHASE_APPLY,
    PHASE_POLISH_FALLBACK,
    PHASE_POLISH_POLL,
    PHASE_POLISH_SUBMIT,
    PHASE_POLISH_VALIDATE,
    PHASE_TRANSLATION_FALLBACK,
    PHASE_TRANSLATION_POLL,
    PHASE_TRANSLATION_SUBMIT,
    PHASE_TRANSLATION_VALIDATE,
    STATUS_RUNNING,
)

logger = logging.getLogger(__name__)
_PROVIDER_NAME = "gemini_ai_studio"


def decode_task_payload(record: TaskRecord) -> dict[str, Any]:
    """Decode a task record's payload_json into a dict, returning {} on failure."""
    if not record.payload_json:
        return {}
    try:
        value = json.loads(record.payload_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


class StageItemState(TypedDict):
    """Per-item state for one pipeline stage (translation or polish)."""

    messages: list[dict[str, str]] | None
    request_hash: str | None
    inlined_request: dict[str, Any] | None
    state: str
    error: str | None
    fallback_attempted: bool
    output_blocks: list[str] | None


class PayloadStage(TypedDict):
    """Payload-level metadata for one pipeline stage."""

    batch_name: str | None
    batch_display_name: str | None
    jobs: list[dict[str, Any]]


def new_stage_state(*, messages: Any = None) -> StageItemState:
    """Create a fresh per-item stage state dict."""
    return StageItemState(
        messages=messages,
        request_hash=None,
        inlined_request=None,
        state="pending",
        error=None,
        fallback_attempted=False,
        output_blocks=None,
    )


def new_payload_stage() -> PayloadStage:
    """Create a fresh payload-level stage metadata dict."""
    return PayloadStage(
        batch_name=None,
        batch_display_name=None,
        jobs=[],
    )


@dataclass(frozen=True)
class _StageSpec:
    stage: str
    phase_submit: str
    phase_poll: str
    phase_validate: str
    phase_fallback: str
    fallback_requires_translation_success: bool = False


_TRANSLATION_STAGE = _StageSpec(
    stage="translation",
    phase_submit=PHASE_TRANSLATION_SUBMIT,
    phase_poll=PHASE_TRANSLATION_POLL,
    phase_validate=PHASE_TRANSLATION_VALIDATE,
    phase_fallback=PHASE_TRANSLATION_FALLBACK,
)

_POLISH_STAGE = _StageSpec(
    stage="polish",
    phase_submit=PHASE_POLISH_SUBMIT,
    phase_poll=PHASE_POLISH_POLL,
    phase_validate=PHASE_POLISH_VALIDATE,
    phase_fallback=PHASE_POLISH_FALLBACK,
    fallback_requires_translation_success=True,
)


def is_item_translation_success(item: dict[str, Any]) -> bool:
    return str(item.get("translation", {}).get("state", "")) == "succeeded"


def is_item_polish_success(item: dict[str, Any]) -> bool:
    return str(item.get("polish", {}).get("state", "")) == "succeeded"


def _stage_request_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    """Return per-request batch options with enforced JSON response format."""
    resolved = dict(payload["batch_request_kwargs"])
    # Validation expects a JSON object payload for both translation and polish stages.
    resolved["response_format"] = {"type": "json_object"}
    return resolved


async def ensure_payload_prepared(
    service: BatchTranslationExecutor,
    task: TaskRecord,
    payload: dict[str, Any],
    *,
    cancel_check: Callable[[], bool] | None,
) -> dict[str, Any]:
    """Build and cache task payload items from current book chunks if missing."""
    existing_items = payload.get("items")
    if isinstance(existing_items, list) and existing_items:
        return payload

    service.raise_if_local_pause(task.task_id, cancel_check)

    document_ids = service.document_ids_for_task(task)
    preflight_document_ids = service.workflow.resolve_preflight_document_ids(document_ids)
    await service.workflow.prepare_llm_prerequisites(preflight_document_ids, cancel_check=cancel_check)
    service.raise_if_local_pause(task.task_id, cancel_check)

    skip_context = service._get_skip_context(task)
    if not skip_context:
        service.workflow.check_cancel(cancel_check)
        service.workflow.manager.build_context_tree(cancel_check=cancel_check)

    translator_config = service.translator_config()
    batch_config = service.batch_config()
    batch_model = batch_config.model or translator_config.model
    if not batch_model:
        raise ValueError("translator_batch_config.model is required for async batch tasks.")
    batch_request_kwargs = {"thinking_mode": str(batch_config.thinking_mode or "auto")}
    source_language = service.workflow.manager.term_repo.get_source_language()
    if not source_language:
        raise ValueError("Source language not found in database.")

    inputs = service.workflow.manager.collect_chunk_translation_inputs(
        batch_size=translator_config.num_of_chunks_per_llm_call,
        document_ids=document_ids,
        force=service._get_force(task),
        cancel_check=cancel_check,
        source_language=source_language,
    )
    if inputs is None:
        return {
            "source_language": source_language,
            "target_language": service.workflow.config.translation_target_language,
            "model": batch_model,
            "batch_request_kwargs": batch_request_kwargs,
            "items": [],
            "translation": new_payload_stage(),
            "polish": new_payload_stage(),
        }

    items: list[dict[str, Any]] = []
    for index, batch in enumerate(inputs.batches):
        batch_texts, batch_terms = service.workflow.manager.build_batch_request_payload(
            batch,
            inputs.all_terms,
            skip_context=skip_context,
        )
        prepared = prepare_chunk_translation(
            batch_texts,
            batch_terms,
            inputs.source_language,
            service.workflow.config.translation_target_language,
        )
        items.append(
            {
                "index": index,
                "chunk_ids": [int(chunk.chunk_id) for chunk in batch],
                "chunks": list(prepared.chunks),
                "all_blocks": list(prepared.all_blocks),
                "chunk_boundaries": list(prepared.chunk_boundaries),
                "chunk_separators": prepared.chunk_separators,
                "translation": new_stage_state(messages=prepared.translate_messages),
                "polish": new_stage_state(),
                "applied": False,
            }
        )

    return {
        "source_language": inputs.source_language,
        "target_language": service.workflow.config.translation_target_language,
        "model": batch_model,
        "batch_request_kwargs": batch_request_kwargs,
        "items": items,
        "translation": new_payload_stage(),
        "polish": new_payload_stage(),
    }


async def run_translation_stage(
    service: BatchTranslationExecutor,
    task_id: str,
    payload: dict[str, Any],
    *,
    force: bool = False,
    cancel_check: Callable[[], bool] | None,
    progress_callback: ProgressCallback | None,
) -> dict[str, Any]:
    """Create translation batch requests and execute the translation stage lifecycle."""
    items: list[dict[str, Any]] = payload["items"]

    # Build request hashes and inlined requests once.
    for item in items:
        sd: StageItemState = item["translation"]
        if not item["all_blocks"]:
            sd["state"] = "succeeded"
            sd["output_blocks"] = []
            continue
        if sd.get("request_hash"):
            continue
        request_hash, inlined_request = service.gateway.build_inlined_request(
            messages=list(sd["messages"] or []),
            model=str(payload["model"]),
            request_kwargs=_stage_request_kwargs(payload),
            metadata={"request_hash": "pending"},
        )
        inlined_request["metadata"] = {"request_hash": request_hash}
        sd["request_hash"] = request_hash
        sd["inlined_request"] = inlined_request

    # When force-retranslating, clear cached LLM responses so items are re-submitted.
    if force:
        _clear_cached_stage_responses(service, items, stage="translation")

    return await _execute_stage(
        service,
        task_id,
        payload,
        items,
        spec=_TRANSLATION_STAGE,
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    )


async def run_polish_stage(
    service: BatchTranslationExecutor,
    task_id: str,
    payload: dict[str, Any],
    *,
    force: bool = False,
    cancel_check: Callable[[], bool] | None,
    progress_callback: ProgressCallback | None,
) -> dict[str, Any]:
    """Create polish batch requests (when enabled) and execute the polish stage."""
    translator_config = service.translator_config()
    if not translator_config.enable_polish:
        for item in payload["items"]:
            if is_item_translation_success(item):
                item["polish"]["state"] = "skipped"
        return payload

    items: list[dict[str, Any]] = payload["items"]

    for item in items:
        sd: StageItemState = item["polish"]
        if not is_item_translation_success(item):
            sd["state"] = "skipped"
            continue
        if sd.get("request_hash"):
            continue
        translated_blocks = item["translation"].get("output_blocks")
        if not isinstance(translated_blocks, list):
            sd["state"] = "failed"
            sd["error"] = "Missing translated blocks for polish."
            continue
        polish_system, polish_user = build_polish_prompt(translated_blocks, str(payload["target_language"]))
        polish_messages = [
            {"role": "system", "content": polish_system},
            {"role": "user", "content": polish_user},
        ]
        request_hash, inlined_request = service.gateway.build_inlined_request(
            messages=polish_messages,
            model=str(payload["model"]),
            request_kwargs=_stage_request_kwargs(payload),
            metadata={"request_hash": "pending"},
        )
        inlined_request["metadata"] = {"request_hash": request_hash}
        sd["messages"] = polish_messages
        sd["request_hash"] = request_hash
        sd["inlined_request"] = inlined_request

    # When force-retranslating, clear cached LLM responses so items are re-submitted.
    if force:
        _clear_cached_stage_responses(service, items, stage="polish")

    return await _execute_stage(
        service,
        task_id,
        payload,
        items,
        spec=_POLISH_STAGE,
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    )


async def _execute_stage(
    service: BatchTranslationExecutor,
    task_id: str,
    payload: dict[str, Any],
    items: list[dict[str, Any]],
    *,
    spec: _StageSpec,
    cancel_check: Callable[[], bool] | None,
    progress_callback: ProgressCallback | None,
) -> dict[str, Any]:
    """Run submit/poll/validate/fallback for one stage (translation or polish)."""
    translator_config = service.translator_config()
    batch_config = service.batch_config()
    batch_size = max(1, int(batch_config.batch_size))

    task = service.persist_payload(task_id, payload, phase=spec.phase_submit, status=STATUS_RUNNING)
    stage_meta: PayloadStage = payload[spec.stage]
    jobs = stage_meta.setdefault("jobs", [])

    unresolved = set(_ordered_pending_stage_hashes(service, items, spec=spec))
    if unresolved:
        # First resume polling any previously submitted stage jobs that still have unresolved requests.
        for job in jobs:
            batch_name = job["batch_name"]
            request_hashes = job["request_hashes"]
            job_hashes = {request_hash for request_hash in request_hashes if request_hash in unresolved}
            if not job_hashes:
                continue
            stage_meta["batch_name"] = batch_name
            display_name = job.get("display_name")
            if display_name:
                stage_meta["batch_display_name"] = display_name
            task = service.persist_payload(task_id, payload, phase=spec.phase_poll, status=STATUS_RUNNING)
            result = await poll_until_terminal(
                service,
                task,
                payload,
                stage=spec.stage,
                batch_name=batch_name,
                request_hashes=job_hashes,
                submitted_at=job["submitted_at"],
                cancel_check=cancel_check,
                progress_callback=progress_callback,
            )
            output_file_name = result.output_file_name
            if output_file_name:
                job["output_file_name"] = output_file_name
            if result.warnings:
                _merge_job_warnings(job, result.warnings)
            unresolved = set(_ordered_pending_stage_hashes(service, items, spec=spec))

        # Submit and poll new provider jobs sequentially by batch_size slices.
        while unresolved:
            ordered_unresolved = _ordered_pending_stage_hashes(service, items, spec=spec)
            slice_hashes = set(ordered_unresolved[:batch_size])
            if not slice_hashes:
                break

            recovered_batch_name = _recover_submitted_batch_name(service, slice_hashes, spec=spec)
            if recovered_batch_name is not None:
                display_name = _build_batch_display_name(
                    task_id=task_id,
                    stage=spec.stage,
                    model=str(payload["model"]),
                    request_hashes=slice_hashes,
                )
                job_entry: dict[str, Any] = {
                    "batch_name": recovered_batch_name,
                    "display_name": display_name,
                    "source_file_name": None,
                    "output_file_name": None,
                    "request_hashes": sorted(slice_hashes),
                    "submitted_at": time.time(),
                }
                jobs.append(job_entry)
                stage_meta["batch_name"] = recovered_batch_name
                stage_meta["batch_display_name"] = display_name
                for request_hash in slice_hashes:
                    record = service.llm_batch_store.get(request_hash)
                    if record is None or record.status != STATUS_SUBMITTED:
                        service.llm_batch_store.upsert_submitted(
                            request_hash,
                            _PROVIDER_NAME,
                            recovered_batch_name,
                        )
            else:
                to_submit = _collect_stage_inlined_requests(items, slice_hashes, spec=spec)
                display_name = _build_batch_display_name(
                    task_id=task_id,
                    stage=spec.stage,
                    model=str(payload["model"]),
                    request_hashes=slice_hashes,
                )
                submit_result = await service.gateway.submit_batch(
                    batch_config=batch_config,
                    model=str(payload["model"]),
                    inlined_requests=to_submit,
                    display_name=display_name,
                )
                stage_meta["batch_name"] = submit_result.batch_name
                stage_meta["batch_display_name"] = display_name
                jobs.append(
                    {
                        "batch_name": submit_result.batch_name,
                        "display_name": display_name,
                        "source_file_name": submit_result.source_file_name,
                        "output_file_name": None,
                        "request_hashes": sorted(slice_hashes),
                        "submitted_at": time.time(),
                    }
                )
                for request_hash in slice_hashes:
                    service.llm_batch_store.upsert_submitted(request_hash, _PROVIDER_NAME, submit_result.batch_name)

            task = service.persist_payload(task_id, payload, phase=spec.phase_poll, status=STATUS_RUNNING)
            active_job = jobs[-1]
            batch_name = stage_meta["batch_name"]
            assert batch_name is not None

            result = await poll_until_terminal(
                service,
                task,
                payload,
                stage=spec.stage,
                batch_name=batch_name,
                request_hashes=slice_hashes,
                submitted_at=active_job["submitted_at"],
                cancel_check=cancel_check,
                progress_callback=progress_callback,
            )
            output_file_name = result.output_file_name
            if output_file_name:
                active_job["output_file_name"] = output_file_name
            if result.warnings:
                _merge_job_warnings(active_job, result.warnings)

            unresolved = set(_ordered_pending_stage_hashes(service, items, spec=spec))

    task = service.persist_payload(task_id, payload, phase=spec.phase_validate, status=STATUS_RUNNING)
    for item in items:
        sd: StageItemState = item[spec.stage]
        if sd.get("state") != "pending":
            continue
        service.raise_if_local_pause(task_id, cancel_check)

        item_hash: str | None = sd["request_hash"]
        if not item_hash:
            sd["state"] = "failed"
            sd["error"] = f"Missing {spec.stage} request hash."
            continue

        raw = service.llm_batch_store.get_completed_response(item_hash)
        if raw is None:
            record = service.llm_batch_store.get(item_hash)
            if record is not None and record.status == STATUS_FAILED:
                sd["state"] = "failed"
                sd["error"] = record.error_text or f"Batch {spec.stage} item failed."
            else:
                sd["state"] = "failed"
                sd["error"] = f"Batch {spec.stage} response unavailable."
            continue

        messages = sd["messages"]

        try:
            blocks = await validated_chat(
                list(messages or []),
                len(item["all_blocks"]),
                list(item["all_blocks"]),
                service.workflow.llm_client,
                translator_config,
                cancel_check,
                label=spec.stage,
                initial_raw=raw,
            )
            sd["output_blocks"] = blocks
            sd["state"] = "succeeded"
            sd["error"] = None
        except OperationCancelledError:
            raise
        except Exception as exc:
            sd["state"] = "failed"
            sd["error"] = f"{type(exc).__name__}: {exc}"

    task = service.persist_payload(task_id, payload, phase=spec.phase_fallback, status=STATUS_RUNNING)
    for item in items:
        sd_fb: StageItemState = item[spec.stage]
        if sd_fb.get("state") != "failed" or bool(sd_fb.get("fallback_attempted")):
            continue
        if spec.fallback_requires_translation_success and not is_item_translation_success(item):
            continue
        current = service.task_store.get(task_id)
        if current is not None and current.cancel_requested:
            continue
        service.raise_if_local_pause(task_id, cancel_check)
        sd_fb["fallback_attempted"] = True

        fb_messages = sd_fb["messages"]
        try:
            blocks = await validated_chat(
                list(fb_messages or []),
                len(item["all_blocks"]),
                list(item["all_blocks"]),
                service.workflow.llm_client,
                translator_config,
                cancel_check,
                label=spec.stage,
                initial_raw=None,
            )
            sd_fb["output_blocks"] = blocks
            sd_fb["state"] = "succeeded"
            sd_fb["error"] = None
        except OperationCancelledError:
            raise
        except Exception as exc:
            sd_fb["error"] = f"{type(exc).__name__}: {exc}"

    return payload


_POLL_TIMEOUT_SEC = 24 * 60 * 60  # 24 hours


async def poll_until_terminal(
    service: BatchTranslationExecutor,
    task: TaskRecord,
    payload: dict[str, Any],
    *,
    stage: str,
    batch_name: str,
    request_hashes: set[str],
    submitted_at: float,
    cancel_check: Callable[[], bool] | None,
    progress_callback: ProgressCallback | None,
) -> BatchPollResult:
    """Poll one provider batch until terminal status, handling cancellation and state persistence."""
    task_id = task.task_id
    phase = PHASE_TRANSLATION_POLL if stage == "translation" else PHASE_POLISH_POLL

    batch_config = service.batch_config()

    cancel_sent = False
    while True:
        current = service.task_store.get(task_id)
        if current is None:
            raise ValueError(f"Task not found: {task_id}")

        service.raise_if_local_pause(task_id, cancel_check)
        if current.cancel_requested and not cancel_sent:
            try:
                await service.gateway.cancel_batch(batch_config=batch_config, batch_name=batch_name)
            except Exception as exc:
                logger.warning("Cancel request for task %s (%s) failed: %s", task_id, stage, exc)
            cancel_sent = True

        result = await service.gateway.poll_once(
            batch_config=batch_config,
            batch_name=batch_name,
            request_hashes=request_hashes,
            batch_store=service.llm_batch_store,
        )

        if progress_callback:
            progress_callback(
                ProgressUpdate(
                    step=WorkflowStep.TRANSLATE_CHUNKS,
                    current=0,
                    total=max(1, len(payload["items"])),
                    message=f"Batch task {task_id[:8]} {stage}: {result.status}",
                )
            )

        if result.status == POLL_STATUS_PENDING:
            if (time.time() - submitted_at) >= _POLL_TIMEOUT_SEC:
                logger.warning(
                    "Batch submitted at %.0f exceeded %ds timeout for task %s (%s); cancelling.",
                    submitted_at,
                    _POLL_TIMEOUT_SEC,
                    task_id,
                    stage,
                )
                try:
                    await service.gateway.cancel_batch(batch_config=batch_config, batch_name=batch_name)
                except Exception as exc:
                    logger.warning("Timeout cancel for task %s (%s) failed: %s", task_id, stage, exc)
                return BatchPollResult(
                    status=POLL_STATUS_FAILED, error_text=f"{stage} batch timed out after {_POLL_TIMEOUT_SEC}s"
                )
            service.persist_payload(task_id, payload, phase=phase, status=STATUS_RUNNING)
            await asyncio.sleep(service.poll_interval_sec)
            continue

        if result.status in {POLL_STATUS_FAILED, POLL_STATUS_CANCELLED}:
            error_text = result.error_text or f"{stage} batch ended with {result.status}"
            for request_hash in request_hashes:
                record = service.llm_batch_store.get(request_hash)
                if record is None or record.status != STATUS_FAILED:
                    service.llm_batch_store.upsert_failed(
                        request_hash,
                        _PROVIDER_NAME,
                        error_text,
                        batch_name=batch_name,
                    )
        return result


def apply_results(
    service: BatchTranslationExecutor,
    task_id: str,
    payload: dict[str, Any],
    *,
    progress_callback: ProgressCallback | None,
) -> dict[str, Any]:
    """Apply validated translated/polished blocks back into persisted chunk records."""
    service.persist_payload(task_id, payload, phase=PHASE_APPLY, status=STATUS_RUNNING)
    items: list[dict[str, Any]] = payload["items"]
    total = len(items)
    completed = sum(1 for item in items if bool(item.get("applied")))

    for item in items:
        if bool(item.get("applied")):
            continue
        if not is_item_translation_success(item):
            continue

        translated_blocks = item["translation"].get("output_blocks")
        if not isinstance(translated_blocks, list):
            item["translation"]["state"] = "failed"
            item["translation"]["error"] = "Missing translated blocks before apply."
            continue

        final_blocks = translated_blocks
        if is_item_polish_success(item):
            polished_blocks = item["polish"].get("output_blocks")
            if isinstance(polished_blocks, list):
                final_blocks = polished_blocks

        translated_chunks = reconstruct_chunk_translations(
            chunks=list(item["chunks"]),
            translated_blocks=final_blocks,
            chunk_boundaries=list(item["chunk_boundaries"]),
            chunk_separators=item["chunk_separators"],
        )

        chunk_ids = item["chunk_ids"]

        update_chunks: list[Any] = []
        for chunk_id, translation in zip(chunk_ids, translated_chunks, strict=True):
            chunk = service.workflow.db.get_chunk_by_id(int(chunk_id))
            if chunk is None:
                item["translation"]["state"] = "failed"
                item["translation"]["error"] = f"Chunk not found during apply: {chunk_id}"
                update_chunks = []
                break
            chunk.translation = translation
            chunk.is_translated = True
            update_chunks.append(chunk)

        if not update_chunks:
            continue

        service.workflow.update_chunk_records(update_chunks)
        item["applied"] = True
        completed += 1
        if progress_callback:
            progress_callback(
                ProgressUpdate(
                    step=WorkflowStep.TRANSLATE_CHUNKS,
                    current=completed,
                    total=max(1, total),
                    message=f"Applying task results {completed}/{total}",
                )
            )

    return payload


def _merge_job_warnings(job: dict[str, Any], warnings: list[str]) -> None:
    """Merge and de-duplicate stage job warnings in insertion order."""
    merged = [str(value) for value in job.get("warnings", [])]
    merged.extend(str(warning) for warning in warnings if str(warning))

    deduped = list(dict.fromkeys(merged))
    if deduped:
        job["warnings"] = deduped


def _clear_cached_stage_responses(
    service: BatchTranslationExecutor,
    items: list[dict[str, Any]],
    *,
    stage: str,
) -> None:
    """Delete cached LLM batch store entries for a stage so items are re-submitted."""
    for item in items:
        sd = item.get(stage)
        if sd is None:
            continue
        request_hash = sd.get("request_hash")
        if request_hash:
            service.llm_batch_store.delete(request_hash)


def _ordered_pending_stage_hashes(
    service: BatchTranslationExecutor,
    items: list[dict[str, Any]],
    *,
    spec: _StageSpec,
) -> list[str]:
    """Return unresolved request hashes in item order for deterministic slicing."""
    ordered: list[str] = []
    seen: set[str] = set()
    for item in items:
        sd: StageItemState = item[spec.stage]
        if sd.get("state") != "pending":
            continue
        request_hash = sd["request_hash"]
        if not request_hash or request_hash in seen:
            continue
        if service.llm_batch_store.get_completed_response(request_hash) is not None:
            continue
        record = service.llm_batch_store.get(request_hash)
        if record is not None and record.status == STATUS_FAILED and not _is_retryable_failure(record.error_text):
            continue
        ordered.append(request_hash)
        seen.add(request_hash)
    return ordered


def _is_retryable_failure(error_text: str | None) -> bool:
    """Treat cancellation-shaped failures as retryable; other failures stay terminal."""
    if not isinstance(error_text, str):
        return False
    normalized = error_text.strip().lower()
    if not normalized:
        return False
    return "cancel" in normalized


def _collect_stage_inlined_requests(
    items: list[dict[str, Any]],
    unresolved: set[str],
    *,
    spec: _StageSpec,
) -> list[dict[str, Any]]:
    """Collect unique inlined requests for unresolved hashes, preserving item order."""
    to_submit_by_hash: dict[str, dict[str, Any]] = {}
    ordered_hashes: list[str] = []
    for item in items:
        sd: StageItemState = item[spec.stage]
        if sd.get("state") != "pending":
            continue
        request_hash = sd["request_hash"]
        if request_hash is None or request_hash not in unresolved:
            continue
        inlined_request = sd["inlined_request"]
        assert inlined_request is not None
        if request_hash not in to_submit_by_hash:
            ordered_hashes.append(request_hash)
            to_submit_by_hash[request_hash] = inlined_request

    missing_hashes = unresolved - set(to_submit_by_hash.keys())
    if missing_hashes:
        missing_preview = ", ".join(sorted(hash_value[:12] for hash_value in missing_hashes))
        raise ValueError(f"Missing {spec.stage} inlined request payload for request(s): {missing_preview}.")
    return [to_submit_by_hash[request_hash] for request_hash in ordered_hashes]


def _recover_submitted_batch_name(
    service: BatchTranslationExecutor,
    unresolved: set[str],
    *,
    spec: _StageSpec,
) -> str | None:
    """Recover a single provider batch name if unresolved hashes were already submitted."""
    batch_names: set[str] = set()
    for request_hash in unresolved:
        record = service.llm_batch_store.get(request_hash)
        if record is None or record.status != STATUS_SUBMITTED:
            continue
        if not record.batch_name:
            raise ValueError(f"Found submitted {spec.stage} request without provider batch name: {request_hash[:12]}.")
        batch_names.add(str(record.batch_name))

    if not batch_names:
        return None
    if len(batch_names) > 1:
        joined = ", ".join(sorted(batch_names))
        raise ValueError(f"Found multiple provider batch names for pending {spec.stage} requests: {joined}.")
    return next(iter(batch_names))


def _build_batch_display_name(
    *,
    task_id: str,
    stage: str,
    model: str,
    request_hashes: set[str],
) -> str:
    """Build a deterministic provider display name for one stage slice."""
    digest_input = "|".join([task_id, stage, model, *sorted(request_hashes)])
    digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:16]
    return f"cat-{stage}-{task_id[:8]}-{digest}"
