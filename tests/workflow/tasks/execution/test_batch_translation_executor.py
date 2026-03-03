from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from context_aware_translation.config import TranslatorBatchConfig, TranslatorConfig
from context_aware_translation.core.cancellation import OperationCancelledError
from context_aware_translation.llm.batch_jobs.base import POLL_STATUS_COMPLETED, BatchPollResult, BatchSubmitResult
from context_aware_translation.storage.llm_batch_store import LLMBatchStore
from context_aware_translation.storage.task_store import TaskStore
from context_aware_translation.workflow.tasks.execution.batch_translation_executor import (
    BatchTranslationExecutor,
    prepare_payload_for_rerun,
)
from context_aware_translation.workflow.tasks.execution.batch_translation_ops import (
    _TRANSLATION_STAGE,
    _execute_stage,
    ensure_payload_prepared,
)
from context_aware_translation.workflow.tasks.models import (
    PHASE_DONE,
    PHASE_POLISH_POLL,
    PHASE_PREPARE,
    STATUS_CANCELLED,
    STATUS_CANCELLING,
    STATUS_COMPLETED,
    STATUS_COMPLETED_WITH_ERRORS,
    STATUS_FAILED,
    STATUS_PAUSED,
    STATUS_QUEUED,
)


def _build_executor(tmp_path) -> BatchTranslationExecutor:
    workflow = MagicMock()
    workflow.book_id = "book-1"
    workflow.config = MagicMock()
    workflow.config.translator_batch_config = TranslatorBatchConfig(
        provider="gemini_ai_studio",
        api_key="k",
        model="gemini-2.5-flash",
    )

    task_store = TaskStore(tmp_path / "task_store.db")
    llm_batch_store = LLMBatchStore(tmp_path / "llm_batch_cache.db")
    return BatchTranslationExecutor(
        workflow=workflow,
        task_store=task_store,
        llm_batch_store=llm_batch_store,
    )


def _create_task(
    executor: BatchTranslationExecutor, *, book_id: str = "book-1", payload_json: str | None = None
) -> object:
    """Helper to create a task record in the executor's TaskStore."""
    return executor.task_store.create(
        book_id=book_id,
        task_type="batch_translation",
        payload_json=payload_json,
        phase=PHASE_PREPARE,
    )


def test_cleanup_remote_artifacts_performs_remote_cleanup(tmp_path):
    executor = _build_executor(tmp_path)
    try:
        payload_json = (
            '{"translation":{"batch_name":"batches/root","jobs":[{"batch_name":"batches/a","source_file_name":"files/src-a","output_file_name":"files/out-a","request_hashes":["h1"]}]},'
            '"polish":{"jobs":[{"batch_name":"batches/b","source_file_name":"files/src-b","output_file_name":"files/out-b","request_hashes":["h2"]}]}}'
        )
        created = _create_task(executor, book_id="book-1", payload_json=payload_json)
        executor.task_store.update(created.task_id, status=STATUS_COMPLETED, phase=PHASE_DONE)

        executor.gateway.delete_batch = AsyncMock()
        executor.gateway.delete_file = AsyncMock()

        result = executor.cleanup_remote_artifacts(created.task_id)

        assert result["task_id"] == created.task_id
        assert result["cleanup_warnings"] == []
        assert executor.gateway.delete_batch.await_count == 3
        assert executor.gateway.delete_file.await_count == 4
        # cleanup_remote_artifacts does NOT delete from store
        assert executor.task_store.get(created.task_id) is not None
    finally:
        executor.close()


def test_cleanup_remote_artifacts_returns_warnings_on_remote_failure(tmp_path):
    executor = _build_executor(tmp_path)
    try:
        payload_json = '{"translation":{"jobs":[{"batch_name":"batches/a","source_file_name":"files/src-a","request_hashes":["h1"]}]}}'
        created = _create_task(executor, book_id="book-1", payload_json=payload_json)
        executor.task_store.update(created.task_id, status=STATUS_COMPLETED, phase=PHASE_DONE)

        executor.gateway.delete_batch = AsyncMock(side_effect=RuntimeError("boom"))
        executor.gateway.delete_file = AsyncMock(side_effect=RuntimeError("boom"))

        result = executor.cleanup_remote_artifacts(created.task_id)

        assert any("Failed to delete remote batch" in warning for warning in result["cleanup_warnings"])
        assert any("Failed to delete remote file" in warning for warning in result["cleanup_warnings"])
    finally:
        executor.close()


def test_persist_poll_progress_uses_cached_polish_responses(tmp_path):
    executor = _build_executor(tmp_path)
    try:
        created = _create_task(executor, book_id="book-1")
        payload = {
            "items": [
                {
                    "translation": {"state": "succeeded"},
                    "polish": {"state": "pending", "request_hash": "h1"},
                },
                {
                    "translation": {"state": "succeeded"},
                    "polish": {"state": "pending", "request_hash": "h2"},
                },
                {
                    "translation": {"state": "succeeded"},
                    "polish": {"state": "pending", "request_hash": "h3"},
                },
            ]
        }
        executor.llm_batch_store.upsert_completed("h1", "gemini_ai_studio", '{"ok":1}', batch_name="batches/p")
        executor.llm_batch_store.upsert_failed("h2", "gemini_ai_studio", "failed", batch_name="batches/p")
        executor.llm_batch_store.upsert_submitted("h3", "gemini_ai_studio", "batches/p")

        result = executor.persist_poll_progress(
            created.task_id,
            payload,
            stage="polish",
            phase=PHASE_POLISH_POLL,
        )

        assert result.phase == PHASE_POLISH_POLL
        assert result.status == "running"
        assert result.total_items == 3
        assert result.completed_items == 2
        assert result.failed_items == 1
    finally:
        executor.close()


@pytest.mark.asyncio
async def test_request_cancel_without_provider_batches_marks_task_cancelled(tmp_path):
    executor = _build_executor(tmp_path)
    try:
        created = _create_task(executor, book_id="book-1")
        executor.gateway.cancel_batch = AsyncMock()

        result = await executor.request_cancel(created.task_id)

        assert result.status == STATUS_CANCELLED
        assert result.phase == PHASE_DONE
        assert result.cancel_requested is True
        executor.gateway.cancel_batch.assert_not_awaited()
    finally:
        executor.close()


@pytest.mark.asyncio
async def test_request_cancel_without_batch_config_marks_task_cancelled_locally(tmp_path):
    executor = _build_executor(tmp_path)
    try:
        created = _create_task(
            executor,
            book_id="book-1",
            payload_json='{"translation":{"batch_name":"batches/active","batch_display_name":"cat-translation-task"}}',
        )
        executor.workflow.config.translator_batch_config = None
        executor.gateway.cancel_batch = AsyncMock()

        result = await executor.request_cancel(created.task_id)

        assert result.status == STATUS_CANCELLED
        assert result.phase == PHASE_DONE
        assert result.last_error is not None
        assert "translator_batch_config" in result.last_error
        executor.gateway.cancel_batch.assert_not_awaited()
    finally:
        executor.close()


@pytest.mark.asyncio
async def test_request_cancel_resolves_provider_batches_by_display_name(tmp_path):
    executor = _build_executor(tmp_path)
    try:
        created = _create_task(
            executor,
            book_id="book-1",
            payload_json='{"model":"models/gemini-2.5-pro","translation":{"batch_display_name":"cat-translation-task"}}',
        )
        executor.gateway.find_batch_names = AsyncMock(return_value=["batches/a", "batches/b"])
        executor.gateway.cancel_batch = AsyncMock()
        executor.gateway.get_batch_state = AsyncMock(side_effect=["RUNNING", "CANCELLED", "RUNNING", "CANCELLED"])

        result = await executor.request_cancel(created.task_id)

        assert result.status == STATUS_CANCELLED
        assert result.phase == PHASE_DONE
        executor.gateway.find_batch_names.assert_awaited_once()
        assert executor.gateway.cancel_batch.await_count == 2
        assert executor.gateway.get_batch_state.await_count == 4
    finally:
        executor.close()


@pytest.mark.asyncio
async def test_request_cancel_recovers_known_batch_responses_before_cancel(tmp_path):
    executor = _build_executor(tmp_path)
    try:
        created = _create_task(
            executor,
            book_id="book-1",
            payload_json=('{"translation":{"jobs":[{"batch_name":"batches/active","request_hashes":["h1","h2"]}]}}'),
        )
        executor.gateway.poll_once = AsyncMock(return_value=BatchPollResult(status=POLL_STATUS_COMPLETED))
        executor.gateway.cancel_batch = AsyncMock()
        executor.gateway.get_batch_state = AsyncMock(side_effect=["RUNNING", "CANCELLED"])

        result = await executor.request_cancel(created.task_id)

        assert result.status == STATUS_CANCELLED
        executor.gateway.poll_once.assert_awaited_once()
        kwargs = executor.gateway.poll_once.await_args.kwargs
        assert kwargs["batch_name"] == "batches/active"
        assert kwargs["request_hashes"] == {"h1", "h2"}
        executor.gateway.cancel_batch.assert_awaited_once()
    finally:
        executor.close()


@pytest.mark.asyncio
async def test_request_cancel_keeps_cancelling_when_provider_batch_is_still_active(tmp_path):
    executor = _build_executor(tmp_path)
    try:
        created = _create_task(
            executor,
            book_id="book-1",
            payload_json='{"translation":{"batch_name":"batches/active"}}',
        )
        executor.gateway.cancel_batch = AsyncMock()
        executor.gateway.get_batch_state = AsyncMock(side_effect=["RUNNING", "CANCELLING"])

        result = await executor.request_cancel(created.task_id)

        assert result.status == STATUS_CANCELLING
        assert result.phase != PHASE_DONE
        executor.gateway.cancel_batch.assert_awaited_once()
        assert executor.gateway.get_batch_state.await_count == 2
    finally:
        executor.close()


@pytest.mark.asyncio
async def test_run_task_short_circuits_when_cancel_requested(tmp_path):
    executor = _build_executor(tmp_path)
    try:
        created = _create_task(executor, book_id="book-1")
        executor.task_store.mark_cancel_requested(created.task_id)
        with patch(
            "context_aware_translation.workflow.tasks.execution.batch_translation_executor.ensure_payload_prepared",
            new_callable=AsyncMock,
        ) as mock_prepare:
            result = await executor.run_task(created.task_id)

            assert result.status == STATUS_CANCELLED
            assert result.phase == PHASE_DONE
            mock_prepare.assert_not_awaited()
    finally:
        executor.close()


@pytest.mark.asyncio
async def test_run_task_cancel_requested_retries_provider_cancel_when_batch_exists(tmp_path):
    executor = _build_executor(tmp_path)
    try:
        created = _create_task(
            executor,
            book_id="book-1",
            payload_json='{"translation":{"batch_name":"batch/jobs/123"}}',
        )
        executor.task_store.mark_cancel_requested(created.task_id)
        executor.gateway.cancel_batch = AsyncMock()
        executor.gateway.get_batch_state = AsyncMock(side_effect=["RUNNING", "CANCELLED"])

        result = await executor.run_task(created.task_id)

        assert result.status == STATUS_CANCELLED
        assert result.phase == PHASE_DONE
        executor.gateway.cancel_batch.assert_awaited_once()
        assert executor.gateway.get_batch_state.await_count == 2
    finally:
        executor.close()


@pytest.mark.asyncio
async def test_request_cancel_skips_terminal_provider_batches(tmp_path):
    executor = _build_executor(tmp_path)
    try:
        created = _create_task(
            executor,
            book_id="book-1",
            payload_json='{"translation":{"batch_name":"batches/succeeded"}}',
        )
        executor.gateway.cancel_batch = AsyncMock()
        executor.gateway.get_batch_state = AsyncMock(return_value="SUCCEEDED")

        result = await executor.request_cancel(created.task_id)

        assert result.status == STATUS_CANCELLED
        assert result.phase == PHASE_DONE
        executor.gateway.cancel_batch.assert_not_awaited()
        executor.gateway.get_batch_state.assert_awaited_once()
    finally:
        executor.close()


@pytest.mark.asyncio
async def test_run_task_reruns_cancelled_task_with_reset_pending_payload(tmp_path):
    executor = _build_executor(tmp_path)
    try:
        created = _create_task(
            executor,
            book_id="book-1",
            payload_json=(
                '{"items":[{"applied":false,'
                '"translation":{"state":"failed","error":"cancelled","fallback_attempted":true,"output_blocks":["x"],"messages":null,"request_hash":null,"inlined_request":null},'
                '"polish":{"state":"failed","error":"cancelled","fallback_attempted":true,"output_blocks":["x"],"messages":null,"request_hash":null,"inlined_request":null}}],'
                '"translation":{"batch_name":"batches/old","batch_display_name":"cat-translation-old","jobs":[]},'
                '"polish":{"batch_name":"batches/old-polish","batch_display_name":"cat-polish-old","jobs":[]}}'
            ),
        )
        executor.task_store.update(created.task_id, status=STATUS_CANCELLED, cancel_requested=True, phase=PHASE_DONE)

        async def _pass_translation(_service, _task_id, payload, **_kwargs):  # noqa: ANN001
            return payload

        async def _pass_polish(_service, _task_id, payload, **_kwargs):  # noqa: ANN001
            return payload

        def _pass_apply(_service, _task_id, payload, **_kwargs):  # noqa: ANN001
            return payload

        with (
            patch(
                "context_aware_translation.workflow.tasks.execution.batch_translation_executor.run_translation_stage",
                new_callable=AsyncMock,
                side_effect=_pass_translation,
            ) as mock_translation,
            patch(
                "context_aware_translation.workflow.tasks.execution.batch_translation_executor.run_polish_stage",
                new_callable=AsyncMock,
                side_effect=_pass_polish,
            ),
            patch(
                "context_aware_translation.workflow.tasks.execution.batch_translation_executor.apply_results",
                side_effect=_pass_apply,
            ),
        ):
            result = await executor.run_task(created.task_id)

            assert result.status == STATUS_COMPLETED_WITH_ERRORS
            assert result.cancel_requested is False
            call_payload = mock_translation.await_args.args[2]
            assert call_payload["translation"]["batch_name"] is None
            assert call_payload["translation"]["batch_display_name"] is None
            assert call_payload["polish"]["batch_name"] is None
            assert call_payload["polish"]["batch_display_name"] is None
            assert call_payload["items"][0]["translation"]["state"] == "pending"
            assert call_payload["items"][0]["polish"]["state"] == "pending"
    finally:
        executor.close()


def test_prepare_payload_for_rerun_preserves_final_stage_outputs():
    payload = {
        "items": [
            {
                "applied": False,
                "translation": {
                    "state": "succeeded",
                    "messages": [{"role": "user", "content": "x"}],
                    "output_blocks": ["ok"],
                    "error": None,
                    "fallback_attempted": False,
                    "request_hash": "h1",
                    "inlined_request": {"metadata": {"request_hash": "h1"}},
                },
                "polish": {
                    "state": "pending",
                    "messages": [{"role": "user", "content": "p"}],
                    "output_blocks": None,
                    "error": None,
                    "fallback_attempted": False,
                    "request_hash": "p1",
                    "inlined_request": {"metadata": {"request_hash": "p1"}},
                },
            },
            {
                "applied": False,
                "translation": {
                    "state": "failed",
                    "messages": [{"role": "user", "content": "y"}],
                    "output_blocks": None,
                    "error": "bad",
                    "fallback_attempted": True,
                    "request_hash": "h2",
                    "inlined_request": {"metadata": {"request_hash": "h2"}},
                },
                "polish": {
                    "state": "succeeded",
                    "messages": [{"role": "user", "content": "p2"}],
                    "output_blocks": ["polished"],
                    "error": None,
                    "fallback_attempted": False,
                    "request_hash": "p2",
                    "inlined_request": {"metadata": {"request_hash": "p2"}},
                },
            },
        ],
        "translation": {"batch_name": "b-old", "batch_display_name": "old", "jobs": [{"x": 1}]},
        "polish": {"batch_name": "p-old", "batch_display_name": "old", "jobs": [{"y": 1}]},
    }

    reset = prepare_payload_for_rerun(payload)
    first = reset["items"][0]
    second = reset["items"][1]

    # Final translation output must be preserved for unapplied items.
    assert first["translation"]["state"] == "succeeded"
    assert first["translation"]["output_blocks"] == ["ok"]
    # Non-final polish should reset.
    assert first["polish"]["state"] == "pending"
    assert first["polish"]["output_blocks"] is None

    # Non-final translation should reset.
    assert second["translation"]["state"] == "pending"
    assert second["translation"]["output_blocks"] is None
    # When translation resets, polish resets too (avoid stale derived output).
    assert second["polish"]["state"] == "pending"
    assert second["polish"]["output_blocks"] is None

    # Stage metadata is reset for fresh provider job tracking.
    assert reset["translation"]["batch_name"] is None
    assert reset["polish"]["batch_name"] is None


@pytest.mark.asyncio
async def test_run_task_pauses_on_transient_timeout(tmp_path):
    executor = _build_executor(tmp_path)
    try:
        created = _create_task(executor, book_id="book-1")
        with patch(
            "context_aware_translation.workflow.tasks.execution.batch_translation_executor.ensure_payload_prepared",
            new_callable=AsyncMock,
            side_effect=httpx.ReadTimeout("timed out"),
        ):
            result = await executor.run_task(created.task_id)

            assert result.status == STATUS_PAUSED
            assert result.phase == PHASE_PREPARE
            assert "ReadTimeout" in (result.last_error or "")
    finally:
        executor.close()


@pytest.mark.asyncio
async def test_run_task_pauses_on_quota_error(tmp_path):
    executor = _build_executor(tmp_path)
    try:
        created = _create_task(executor, book_id="book-1")
        with patch(
            "context_aware_translation.workflow.tasks.execution.batch_translation_executor.ensure_payload_prepared",
            new_callable=AsyncMock,
            side_effect=RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded"),
        ):
            result = await executor.run_task(created.task_id)

            assert result.status == STATUS_PAUSED
            assert "RESOURCE_EXHAUSTED" in (result.last_error or "")
    finally:
        executor.close()


@pytest.mark.asyncio
async def test_run_task_persists_latest_payload_when_interrupted_mid_stage(tmp_path):
    executor = _build_executor(tmp_path)
    try:
        created = _create_task(executor, book_id="book-1")
        prepared_payload = {
            "model": "batch-model",
            "items": [
                {
                    "index": 0,
                    "chunk_ids": [1],
                    "chunks": [],
                    "all_blocks": ["x"],
                    "chunk_boundaries": [1],
                    "chunk_separators": "\n",
                    "translation": {
                        "state": "pending",
                        "error": None,
                        "request_hash": "h1",
                        "inlined_request": {"metadata": {"request_hash": "h1"}},
                        "messages": [{"role": "user", "content": "x"}],
                        "output_blocks": None,
                        "fallback_attempted": False,
                    },
                    "polish": {
                        "state": "pending",
                        "error": None,
                        "request_hash": None,
                        "inlined_request": None,
                        "messages": None,
                        "output_blocks": None,
                        "fallback_attempted": False,
                    },
                    "applied": False,
                }
            ],
            "translation": {"batch_name": None, "batch_display_name": None, "jobs": []},
            "polish": {"batch_name": None, "batch_display_name": None, "jobs": []},
        }

        async def _interrupt_after_mutation(_service, _task_id, payload, **_kwargs):  # noqa: ANN001
            payload["items"][0]["translation"]["state"] = "succeeded"
            payload["items"][0]["translation"]["output_blocks"] = ["ok"]
            raise OperationCancelledError("interrupted")

        with (
            patch(
                "context_aware_translation.workflow.tasks.execution.batch_translation_executor.ensure_payload_prepared",
                new_callable=AsyncMock,
                return_value=prepared_payload,
            ),
            patch(
                "context_aware_translation.workflow.tasks.execution.batch_translation_executor.run_translation_stage",
                new_callable=AsyncMock,
                side_effect=_interrupt_after_mutation,
            ),
        ):
            result = await executor.run_task(created.task_id)

        assert result.status == STATUS_PAUSED
        reloaded = executor.task_store.get(created.task_id)
        assert reloaded is not None
        payload = json.loads(reloaded.payload_json or "{}")
        assert payload["items"][0]["translation"]["state"] == "succeeded"
        assert payload["items"][0]["translation"]["output_blocks"] == ["ok"]
    finally:
        executor.close()


@pytest.mark.asyncio
async def test_run_task_resume_keeps_existing_stage_state(tmp_path):
    executor = _build_executor(tmp_path)
    try:
        payload_json = json.dumps(
            {
                "model": "batch-model",
                "items": [
                    {
                        "index": 0,
                        "chunk_ids": [1],
                        "chunks": [],
                        "all_blocks": ["x"],
                        "chunk_boundaries": [1],
                        "chunk_separators": "\n",
                        "translation": {
                            "state": "succeeded",
                            "error": None,
                            "request_hash": "h1",
                            "inlined_request": {"metadata": {"request_hash": "h1"}},
                            "messages": [{"role": "user", "content": "x"}],
                            "output_blocks": ["ok"],
                            "fallback_attempted": False,
                        },
                        "polish": {
                            "state": "skipped",
                            "error": None,
                            "request_hash": None,
                            "inlined_request": None,
                            "messages": None,
                            "output_blocks": None,
                            "fallback_attempted": False,
                        },
                        "applied": False,
                    }
                ],
                "translation": {"batch_name": "batch/jobs/1", "batch_display_name": "d1", "jobs": []},
                "polish": {"batch_name": None, "batch_display_name": None, "jobs": []},
            },
            ensure_ascii=False,
        )
        created = _create_task(executor, book_id="book-1", payload_json=payload_json)
        executor.task_store.update(created.task_id, status=STATUS_PAUSED)

        async def _pass_translation(_service, _task_id, payload, **_kwargs):  # noqa: ANN001
            assert payload["items"][0]["translation"]["state"] == "succeeded"
            assert payload["items"][0]["translation"]["output_blocks"] == ["ok"]
            return payload

        async def _pass_polish(_service, _task_id, payload, **_kwargs):  # noqa: ANN001
            return payload

        def _pass_apply(_service, _task_id, payload, **_kwargs):  # noqa: ANN001
            return payload

        with (
            patch(
                "context_aware_translation.workflow.tasks.execution.batch_translation_executor.run_translation_stage",
                new_callable=AsyncMock,
                side_effect=_pass_translation,
            ) as mock_translation,
            patch(
                "context_aware_translation.workflow.tasks.execution.batch_translation_executor.run_polish_stage",
                new_callable=AsyncMock,
                side_effect=_pass_polish,
            ),
            patch(
                "context_aware_translation.workflow.tasks.execution.batch_translation_executor.apply_results",
                side_effect=_pass_apply,
            ),
        ):
            result = await executor.run_task(created.task_id)

        assert result.status == STATUS_COMPLETED
        assert mock_translation.await_count == 1
    finally:
        executor.close()


@pytest.mark.asyncio
async def test_run_task_persists_latest_payload_before_cancel_finalize(tmp_path):
    executor = _build_executor(tmp_path)
    try:
        created = _create_task(executor, book_id="book-1")
        prepared_payload = {
            "model": "batch-model",
            "items": [
                {
                    "index": 0,
                    "chunk_ids": [1],
                    "chunks": [],
                    "all_blocks": ["x"],
                    "chunk_boundaries": [1],
                    "chunk_separators": "\n",
                    "translation": {
                        "state": "pending",
                        "error": None,
                        "request_hash": "h1",
                        "inlined_request": {"metadata": {"request_hash": "h1"}},
                        "messages": [{"role": "user", "content": "x"}],
                        "output_blocks": None,
                        "fallback_attempted": False,
                    },
                    "polish": {
                        "state": "pending",
                        "error": None,
                        "request_hash": None,
                        "inlined_request": None,
                        "messages": None,
                        "output_blocks": None,
                        "fallback_attempted": False,
                    },
                    "applied": False,
                }
            ],
            "translation": {"batch_name": None, "batch_display_name": None, "jobs": []},
            "polish": {"batch_name": None, "batch_display_name": None, "jobs": []},
        }

        async def _cancel_after_mutation(_service, _task_id, payload, **_kwargs):  # noqa: ANN001
            payload["items"][0]["translation"]["state"] = "succeeded"
            payload["items"][0]["translation"]["output_blocks"] = ["ok"]
            executor.task_store.mark_cancel_requested(created.task_id)
            raise OperationCancelledError("cancel requested")

        with (
            patch(
                "context_aware_translation.workflow.tasks.execution.batch_translation_executor.ensure_payload_prepared",
                new_callable=AsyncMock,
                return_value=prepared_payload,
            ),
            patch(
                "context_aware_translation.workflow.tasks.execution.batch_translation_executor.run_translation_stage",
                new_callable=AsyncMock,
                side_effect=_cancel_after_mutation,
            ),
        ):
            result = await executor.run_task(created.task_id)

        assert result.status == STATUS_CANCELLED
        reloaded = executor.task_store.get(created.task_id)
        assert reloaded is not None
        payload = json.loads(reloaded.payload_json or "{}")
        assert payload["items"][0]["translation"]["state"] == "succeeded"
        assert payload["items"][0]["translation"]["output_blocks"] == ["ok"]
    finally:
        executor.close()


@pytest.mark.asyncio
async def test_run_task_marks_failed_on_non_transient_error(tmp_path):
    executor = _build_executor(tmp_path)
    try:
        created = _create_task(executor, book_id="book-1")
        with patch(
            "context_aware_translation.workflow.tasks.execution.batch_translation_executor.ensure_payload_prepared",
            new_callable=AsyncMock,
            side_effect=ValueError("bad payload"),
        ):
            result = await executor.run_task(created.task_id)

            assert result.status == STATUS_FAILED
            assert result.phase == PHASE_DONE
            assert result.last_error == "ValueError: bad payload"
    finally:
        executor.close()


@pytest.mark.asyncio
async def test_ensure_payload_prepared_uses_batch_model_with_fixed_temperature():
    from context_aware_translation.storage.task_store import TaskRecord

    task = TaskRecord(
        task_id="task-1",
        book_id="book-1",
        task_type="batch_translation",
        status=STATUS_QUEUED,
        phase=PHASE_PREPARE,
        payload_json="{}",
        document_ids_json=None,
        config_snapshot_json=None,
        cancel_requested=False,
        total_items=0,
        completed_items=0,
        failed_items=0,
        last_error=None,
        created_at=0.0,
        updated_at=0.0,
    )

    translator_config = TranslatorConfig(
        model="translator-model",
        temperature=0.15,
        num_of_chunks_per_llm_call=7,
    )
    batch_config = TranslatorBatchConfig(
        provider="gemini_ai_studio",
        model="batch-model",
        api_key="k",
    )

    manager = MagicMock()
    manager.term_repo.get_source_language.return_value = "Japanese"
    manager.collect_chunk_translation_inputs.return_value = None

    workflow = MagicMock()
    workflow.resolve_preflight_document_ids.return_value = None
    workflow.prepare_llm_prerequisites = AsyncMock()
    workflow.check_cancel = MagicMock()
    workflow.manager = manager
    workflow.config = SimpleNamespace(translation_target_language="English")

    service = MagicMock()
    service.workflow = workflow
    service.raise_if_local_pause = MagicMock()
    service.document_ids_for_task.return_value = None
    service.translator_config.return_value = translator_config
    service.batch_config.return_value = batch_config
    service._get_force.return_value = False

    payload = await ensure_payload_prepared(service, task, {}, cancel_check=None)

    manager.collect_chunk_translation_inputs.assert_called_once_with(
        batch_size=0,
        max_tokens_per_batch=4000,
        document_ids=None,
        force=False,
        cancel_check=None,
        source_language="Japanese",
    )
    assert payload["model"] == "batch-model"
    assert "temperature" not in payload
    assert payload["batch_request_kwargs"] == {"thinking_mode": "auto"}


@pytest.mark.asyncio
async def test_execute_stage_reuses_cached_submitted_batch_without_resubmitting(tmp_path):
    llm_batch_store = LLMBatchStore(tmp_path / "llm_batch_cache.db")
    request_hash = "hash-1"
    existing_batch_name = "batch/jobs/existing"
    llm_batch_store.upsert_submitted(request_hash, "gemini_ai_studio", existing_batch_name)

    service = MagicMock()
    service.llm_batch_store = llm_batch_store
    service.gateway = MagicMock()
    service.gateway.submit_batch = AsyncMock()
    service.translator_config.return_value = MagicMock()
    service.batch_config.return_value = SimpleNamespace(batch_size=500)
    service.raise_if_local_pause = MagicMock()
    service.persist_payload.return_value = SimpleNamespace(task_id="task-1")
    service.workflow = SimpleNamespace(llm_client=MagicMock())

    item = {
        "all_blocks": ["x"],
        "translation": {
            "state": "pending",
            "error": None,
            "request_hash": request_hash,
            "inlined_request": {"model": "batch-model"},
            "messages": [{"role": "user", "content": "x"}],
            "output_blocks": None,
            "fallback_attempted": False,
        },
    }
    payload = {
        "model": "batch-model",
        "translation": {"batch_name": None, "batch_display_name": None, "jobs": []},
        "items": [item],
    }

    async def fake_poll(*_args, **_kwargs):
        llm_batch_store.upsert_completed(
            request_hash,
            "gemini_ai_studio",
            '{"翻译文本":["ok"]}',
            batch_name=existing_batch_name,
        )
        return BatchPollResult(status=POLL_STATUS_COMPLETED)

    try:
        with (
            patch(
                "context_aware_translation.workflow.tasks.execution.batch_translation_ops.poll_until_terminal",
                new=AsyncMock(side_effect=fake_poll),
            ),
            patch(
                "context_aware_translation.workflow.tasks.execution.batch_translation_ops.validated_chat",
                new=AsyncMock(return_value=["ok"]),
            ),
        ):
            result = await _execute_stage(
                service,
                "task-1",
                payload,
                [item],
                spec=_TRANSLATION_STAGE,
                cancel_check=None,
                progress_callback=None,
            )
    finally:
        llm_batch_store.close()

    service.gateway.submit_batch.assert_not_awaited()
    assert result["translation"]["batch_name"] == existing_batch_name
    assert item["translation"]["state"] == "succeeded"


@pytest.mark.asyncio
async def test_execute_stage_deduplicates_duplicate_request_hashes(tmp_path):
    llm_batch_store = LLMBatchStore(tmp_path / "llm_batch_cache.db")
    request_hash = "hash-dup"

    service = MagicMock()
    service.llm_batch_store = llm_batch_store
    service.gateway = MagicMock()
    service.gateway.submit_batch = AsyncMock(
        return_value=BatchSubmitResult(batch_name="batch/jobs/dup", source_file_name="files/source")
    )
    service.translator_config.return_value = MagicMock()
    service.batch_config.return_value = SimpleNamespace(batch_size=500)
    service.raise_if_local_pause = MagicMock()
    service.persist_payload.return_value = SimpleNamespace(task_id="task-dup")
    service.workflow = SimpleNamespace(llm_client=MagicMock())

    item_1 = {
        "all_blocks": ["x"],
        "translation": {
            "state": "pending",
            "error": None,
            "request_hash": request_hash,
            "inlined_request": {"model": "batch-model", "metadata": {"request_hash": request_hash}},
            "messages": [{"role": "user", "content": "x"}],
            "output_blocks": None,
            "fallback_attempted": False,
        },
    }
    item_2 = {
        "all_blocks": ["x"],
        "translation": {
            "state": "pending",
            "error": None,
            "request_hash": request_hash,
            "inlined_request": {"model": "batch-model", "metadata": {"request_hash": request_hash}},
            "messages": [{"role": "user", "content": "x"}],
            "output_blocks": None,
            "fallback_attempted": False,
        },
    }
    payload = {
        "model": "batch-model",
        "translation": {"batch_name": None, "batch_display_name": None, "jobs": []},
        "items": [item_1, item_2],
    }

    async def fake_poll(*_args, **_kwargs):
        llm_batch_store.upsert_completed(
            request_hash,
            "gemini_ai_studio",
            '{"翻译文本":["ok"]}',
            batch_name="batch/jobs/dup",
        )
        return BatchPollResult(status=POLL_STATUS_COMPLETED)

    try:
        with (
            patch(
                "context_aware_translation.workflow.tasks.execution.batch_translation_ops.poll_until_terminal",
                new=AsyncMock(side_effect=fake_poll),
            ),
            patch(
                "context_aware_translation.workflow.tasks.execution.batch_translation_ops.validated_chat",
                new=AsyncMock(return_value=["ok"]),
            ),
        ):
            result = await _execute_stage(
                service,
                "task-dup",
                payload,
                [item_1, item_2],
                spec=_TRANSLATION_STAGE,
                cancel_check=None,
                progress_callback=None,
            )
    finally:
        llm_batch_store.close()

    assert service.gateway.submit_batch.await_count == 1
    _, submit_kwargs = service.gateway.submit_batch.await_args
    assert len(submit_kwargs["inlined_requests"]) == 1
    assert result["translation"]["batch_name"] == "batch/jobs/dup"
    assert item_1["translation"]["state"] == "succeeded"
    assert item_2["translation"]["state"] == "succeeded"


@pytest.mark.asyncio
async def test_execute_stage_resubmits_when_cached_failed_record_was_cancelled(tmp_path):
    llm_batch_store = LLMBatchStore(tmp_path / "llm_batch_cache.db")
    request_hash = "hash-cancelled"
    llm_batch_store.upsert_failed(
        request_hash,
        "gemini_ai_studio",
        "Provider batch cancelled.",
        batch_name="batch/jobs/old-cancelled",
    )

    service = MagicMock()
    service.llm_batch_store = llm_batch_store
    service.gateway = MagicMock()
    service.gateway.submit_batch = AsyncMock(
        return_value=BatchSubmitResult(batch_name="batch/jobs/new", source_file_name="files/source")
    )
    service.translator_config.return_value = MagicMock()
    service.batch_config.return_value = SimpleNamespace(batch_size=500)
    service.raise_if_local_pause = MagicMock()
    service.persist_payload.return_value = SimpleNamespace(task_id="task-cancelled")
    service.task_store = MagicMock()
    service.task_store.get.return_value = SimpleNamespace(cancel_requested=False)
    service.workflow = SimpleNamespace(llm_client=MagicMock())

    item = {
        "all_blocks": ["x"],
        "translation": {
            "state": "pending",
            "error": None,
            "request_hash": request_hash,
            "inlined_request": {"model": "batch-model", "metadata": {"request_hash": request_hash}},
            "messages": [{"role": "user", "content": "x"}],
            "output_blocks": None,
            "fallback_attempted": False,
        },
    }
    payload = {
        "model": "batch-model",
        "translation": {"batch_name": None, "batch_display_name": None, "jobs": []},
        "items": [item],
    }

    async def fake_poll(*_args, **_kwargs):
        llm_batch_store.upsert_completed(
            request_hash,
            "gemini_ai_studio",
            '{"翻译文本":["ok"]}',
            batch_name="batch/jobs/new",
        )
        return BatchPollResult(status=POLL_STATUS_COMPLETED)

    try:
        with (
            patch(
                "context_aware_translation.workflow.tasks.execution.batch_translation_ops.poll_until_terminal",
                new=AsyncMock(side_effect=fake_poll),
            ),
            patch(
                "context_aware_translation.workflow.tasks.execution.batch_translation_ops.validated_chat",
                new=AsyncMock(return_value=["ok"]),
            ),
        ):
            result = await _execute_stage(
                service,
                "task-cancelled",
                payload,
                [item],
                spec=_TRANSLATION_STAGE,
                cancel_check=None,
                progress_callback=None,
            )
    finally:
        llm_batch_store.close()

    service.gateway.submit_batch.assert_awaited_once()
    assert result["translation"]["batch_name"] == "batch/jobs/new"
    assert item["translation"]["state"] == "succeeded"


@pytest.mark.asyncio
async def test_execute_stage_submits_sequential_slices_by_batch_size(tmp_path):
    llm_batch_store = LLMBatchStore(tmp_path / "llm_batch_cache.db")
    service = MagicMock()
    service.llm_batch_store = llm_batch_store
    service.gateway = MagicMock()
    service.gateway.submit_batch = AsyncMock(
        side_effect=[
            BatchSubmitResult(batch_name="batch/jobs/1", source_file_name="files/src-1"),
            BatchSubmitResult(batch_name="batch/jobs/2", source_file_name="files/src-2"),
            BatchSubmitResult(batch_name="batch/jobs/3", source_file_name="files/src-3"),
        ]
    )
    service.translator_config.return_value = MagicMock()
    service.batch_config.return_value = SimpleNamespace(batch_size=2)
    service.raise_if_local_pause = MagicMock()
    service.persist_payload.return_value = SimpleNamespace(task_id="task-slices")
    service.workflow = SimpleNamespace(llm_client=MagicMock())
    service.task_store = MagicMock()
    service.task_store.get.return_value = SimpleNamespace(cancel_requested=False)

    items: list[dict[str, object]] = []
    for idx in range(5):
        request_hash = f"hash-{idx}"
        items.append(
            {
                "all_blocks": ["x"],
                "translation": {
                    "state": "pending",
                    "error": None,
                    "request_hash": request_hash,
                    "inlined_request": {
                        "model": "batch-model",
                        "metadata": {"request_hash": request_hash},
                    },
                    "messages": [{"role": "user", "content": f"x-{idx}"}],
                    "output_blocks": None,
                    "fallback_attempted": False,
                },
            }
        )

    payload = {
        "model": "batch-model",
        "translation": {"batch_name": None, "batch_display_name": None, "jobs": []},
        "items": items,
    }

    async def fake_poll(_service, _task, _payload, **kwargs):  # noqa: ANN001
        for request_hash in kwargs["request_hashes"]:
            llm_batch_store.upsert_completed(
                request_hash,
                "gemini_ai_studio",
                '{"翻译文本":["ok"]}',
                batch_name=str(kwargs["batch_name"]),
            )
        return BatchPollResult(status=POLL_STATUS_COMPLETED, output_file_name="files/out")

    try:
        with (
            patch(
                "context_aware_translation.workflow.tasks.execution.batch_translation_ops.poll_until_terminal",
                new=AsyncMock(side_effect=fake_poll),
            ),
            patch(
                "context_aware_translation.workflow.tasks.execution.batch_translation_ops.validated_chat",
                new=AsyncMock(return_value=["ok"]),
            ),
        ):
            result = await _execute_stage(
                service,
                "task-slices",
                payload,
                items,
                spec=_TRANSLATION_STAGE,
                cancel_check=None,
                progress_callback=None,
            )
    finally:
        llm_batch_store.close()

    assert service.gateway.submit_batch.await_count == 3
    assert result["translation"]["batch_name"] == "batch/jobs/3"
    jobs = result["translation"]["jobs"]
    assert isinstance(jobs, list)
    assert [len(job["request_hashes"]) for job in jobs] == [2, 2, 1]


@pytest.mark.asyncio
async def test_execute_stage_persists_final_fallback_state_before_return(tmp_path):
    llm_batch_store = LLMBatchStore(tmp_path / "llm_batch_cache.db")
    request_hash = "hash-fallback-final-persist"
    llm_batch_store.upsert_completed(
        request_hash,
        "gemini_ai_studio",
        '{"翻译文本":["raw"]}',
        batch_name="batch/jobs/existing",
    )

    persisted_snapshots: list[tuple[str, dict[str, object]]] = []

    def _persist_side_effect(task_id, payload, *, phase, status):  # noqa: ANN001
        persisted_snapshots.append((phase, json.loads(json.dumps(payload))))
        return SimpleNamespace(task_id=task_id, status=status, phase=phase)

    service = MagicMock()
    service.llm_batch_store = llm_batch_store
    service.gateway = MagicMock()
    service.gateway.submit_batch = AsyncMock()
    service.translator_config.return_value = MagicMock()
    service.batch_config.return_value = SimpleNamespace(batch_size=500)
    service.raise_if_local_pause = MagicMock()
    service.persist_payload.side_effect = _persist_side_effect
    service.workflow = SimpleNamespace(llm_client=MagicMock())
    service.task_store = MagicMock()
    service.task_store.get.return_value = SimpleNamespace(cancel_requested=False)

    item = {
        "all_blocks": ["x"],
        "translation": {
            "state": "pending",
            "error": None,
            "request_hash": request_hash,
            "inlined_request": {"model": "batch-model"},
            "messages": [{"role": "user", "content": "x"}],
            "output_blocks": None,
            "fallback_attempted": False,
        },
    }
    payload = {
        "model": "batch-model",
        "translation": {"batch_name": None, "batch_display_name": None, "jobs": []},
        "items": [item],
    }

    try:
        with patch(
            "context_aware_translation.workflow.tasks.execution.batch_translation_ops.validated_chat",
            new=AsyncMock(side_effect=[RuntimeError("bad-json"), ["ok"]]),
        ):
            result = await _execute_stage(
                service,
                "task-fallback-final",
                payload,
                [item],
                spec=_TRANSLATION_STAGE,
                cancel_check=None,
                progress_callback=None,
            )
    finally:
        llm_batch_store.close()

    assert result["items"][0]["translation"]["state"] == "succeeded"
    assert result["items"][0]["translation"]["fallback_attempted"] is True
    assert persisted_snapshots
    last_phase, last_payload = persisted_snapshots[-1]
    assert last_phase == _TRANSLATION_STAGE.phase_fallback
    last_item = last_payload["items"][0]
    assert last_item["translation"]["state"] == "succeeded"
    assert last_item["translation"]["fallback_attempted"] is True


@pytest.mark.asyncio
async def test_execute_stage_validation_respects_translator_concurrency(tmp_path):
    llm_batch_store = LLMBatchStore(tmp_path / "llm_batch_cache.db")

    service = MagicMock()
    service.llm_batch_store = llm_batch_store
    service.gateway = MagicMock()
    service.gateway.submit_batch = AsyncMock()
    service.translator_config.return_value = SimpleNamespace(concurrency=2)
    service.batch_config.return_value = SimpleNamespace(batch_size=500)
    service.raise_if_local_pause = MagicMock()
    service.persist_payload.return_value = SimpleNamespace(task_id="task-validate-concurrency")
    service.workflow = SimpleNamespace(llm_client=MagicMock())

    items: list[dict[str, object]] = []
    for idx in range(4):
        request_hash = f"hash-validate-{idx}"
        llm_batch_store.upsert_completed(
            request_hash,
            "gemini_ai_studio",
            '{"翻译文本":["ok"]}',
            batch_name="batch/jobs/validate",
        )
        items.append(
            {
                "all_blocks": ["x"],
                "translation": {
                    "state": "pending",
                    "error": None,
                    "request_hash": request_hash,
                    "inlined_request": {"model": "batch-model"},
                    "messages": [{"role": "user", "content": f"x-{idx}"}],
                    "output_blocks": None,
                    "fallback_attempted": False,
                },
            }
        )

    payload = {
        "model": "batch-model",
        "translation": {"batch_name": None, "batch_display_name": None, "jobs": []},
        "items": items,
    }

    active = 0
    max_active = 0

    async def _validated_chat(*_args, **_kwargs):  # noqa: ANN001
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        return ["ok"]

    try:
        with patch(
            "context_aware_translation.workflow.tasks.execution.batch_translation_ops.validated_chat",
            new=AsyncMock(side_effect=_validated_chat),
        ):
            result = await _execute_stage(
                service,
                "task-validate-concurrency",
                payload,
                items,
                spec=_TRANSLATION_STAGE,
                cancel_check=None,
                progress_callback=None,
            )
    finally:
        llm_batch_store.close()

    assert max_active >= 2
    assert all(item["translation"]["state"] == "succeeded" for item in result["items"])


@pytest.mark.asyncio
async def test_execute_stage_fallback_respects_translator_concurrency(tmp_path):
    llm_batch_store = LLMBatchStore(tmp_path / "llm_batch_cache.db")

    service = MagicMock()
    service.llm_batch_store = llm_batch_store
    service.gateway = MagicMock()
    service.gateway.submit_batch = AsyncMock()
    service.translator_config.return_value = SimpleNamespace(concurrency=2)
    service.batch_config.return_value = SimpleNamespace(batch_size=500)
    service.raise_if_local_pause = MagicMock()
    service.persist_payload.return_value = SimpleNamespace(task_id="task-fallback-concurrency")
    service.workflow = SimpleNamespace(llm_client=MagicMock())
    service.task_store = MagicMock()
    service.task_store.get.return_value = SimpleNamespace(cancel_requested=False)

    items: list[dict[str, object]] = []
    for idx in range(4):
        items.append(
            {
                "all_blocks": ["x"],
                "translation": {
                    "state": "failed",
                    "error": "bad-json",
                    "request_hash": f"hash-fallback-{idx}",
                    "inlined_request": {"model": "batch-model"},
                    "messages": [{"role": "user", "content": f"x-{idx}"}],
                    "output_blocks": None,
                    "fallback_attempted": False,
                },
            }
        )

    payload = {
        "model": "batch-model",
        "translation": {"batch_name": None, "batch_display_name": None, "jobs": []},
        "items": items,
    }

    active = 0
    max_active = 0

    async def _validated_chat(*_args, **_kwargs):  # noqa: ANN001
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        return ["ok"]

    try:
        with patch(
            "context_aware_translation.workflow.tasks.execution.batch_translation_ops.validated_chat",
            new=AsyncMock(side_effect=_validated_chat),
        ):
            result = await _execute_stage(
                service,
                "task-fallback-concurrency",
                payload,
                items,
                spec=_TRANSLATION_STAGE,
                cancel_check=None,
                progress_callback=None,
            )
    finally:
        llm_batch_store.close()

    assert max_active >= 2
    assert all(item["translation"]["state"] == "succeeded" for item in result["items"])
    assert all(item["translation"]["fallback_attempted"] is True for item in result["items"])
