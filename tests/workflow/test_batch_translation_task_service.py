from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from context_aware_translation.config import TranslatorBatchConfig, TranslatorConfig
from context_aware_translation.llm.batch_jobs.base import POLL_STATUS_COMPLETED, BatchPollResult, BatchSubmitResult
from context_aware_translation.storage.llm_batch_store import LLMBatchStore
from context_aware_translation.storage.translation_batch_task_store import (
    PHASE_DONE,
    PHASE_PREPARE,
    STATUS_CANCELLED,
    STATUS_CANCELLING,
    STATUS_COMPLETED,
    STATUS_COMPLETED_WITH_ERRORS,
    STATUS_FAILED,
    STATUS_PAUSED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    TranslationBatchTaskRecord,
    TranslationBatchTaskStore,
)
from context_aware_translation.workflow.batch_translation_task_ops import (
    _TRANSLATION_STAGE,
    _execute_stage,
    ensure_payload_prepared,
)
from context_aware_translation.workflow.batch_translation_task_service import (
    BatchTranslationTaskService,
    select_next_auto_run_task,
)


def _build_service(tmp_path) -> BatchTranslationTaskService:
    workflow = MagicMock()
    workflow.book_id = "book-1"
    workflow.config = MagicMock()
    workflow.config.translator_batch_config = TranslatorBatchConfig(
        provider="gemini_ai_studio",
        api_key="k",
        model="gemini-2.5-flash",
    )

    task_store = TranslationBatchTaskStore(tmp_path / "translation_batch_tasks.db")
    llm_batch_store = LLMBatchStore(tmp_path / "llm_batch_cache.db")
    return BatchTranslationTaskService(
        workflow=workflow,
        task_store=task_store,
        llm_batch_store=llm_batch_store,
    )


def test_select_next_auto_run_task_prefers_oldest_runnable_entry():
    tasks = [
        TranslationBatchTaskRecord(
            task_id="newest-terminal",
            book_id="book-1",
            status=STATUS_COMPLETED,
            phase=PHASE_DONE,
            payload_json="{}",
            document_ids_json=None,
            force=False,
            skip_context=False,
            total_items=1,
            completed_items=1,
            failed_items=0,
            cancel_requested=False,
            translation_batch_name=None,
            polish_batch_name=None,
            last_error=None,
            created_at=2.0,
            updated_at=2.0,
        ),
        TranslationBatchTaskRecord(
            task_id="older-runnable",
            book_id="book-1",
            status=STATUS_PAUSED,
            phase=PHASE_DONE,
            payload_json="{}",
            document_ids_json=None,
            force=False,
            skip_context=False,
            total_items=1,
            completed_items=0,
            failed_items=1,
            cancel_requested=False,
            translation_batch_name=None,
            polish_batch_name=None,
            last_error=None,
            created_at=1.0,
            updated_at=1.0,
        ),
    ]

    selected = select_next_auto_run_task(tasks)
    assert selected is not None
    assert selected.task_id == "older-runnable"


def test_select_next_auto_run_task_includes_cancel_requested_cancelling_entry():
    tasks = [
        TranslationBatchTaskRecord(
            task_id="terminal-newer",
            book_id="book-1",
            status=STATUS_COMPLETED,
            phase=PHASE_DONE,
            payload_json="{}",
            document_ids_json=None,
            force=False,
            skip_context=False,
            total_items=1,
            completed_items=1,
            failed_items=0,
            cancel_requested=False,
            translation_batch_name=None,
            polish_batch_name=None,
            last_error=None,
            created_at=2.0,
            updated_at=2.0,
        ),
        TranslationBatchTaskRecord(
            task_id="cancelling-older",
            book_id="book-1",
            status=STATUS_CANCELLING,
            phase=PHASE_DONE,
            payload_json="{}",
            document_ids_json=None,
            force=False,
            skip_context=False,
            total_items=1,
            completed_items=0,
            failed_items=0,
            cancel_requested=True,
            translation_batch_name=None,
            polish_batch_name=None,
            last_error=None,
            created_at=1.0,
            updated_at=1.0,
        ),
    ]

    selected = select_next_auto_run_task(tasks)
    assert selected is not None
    assert selected.task_id == "cancelling-older"


def test_delete_task_removes_terminal_task(tmp_path):
    service = _build_service(tmp_path)
    try:
        created = service.task_store.create_task(book_id="book-1")
        service.task_store.update(created.task_id, status=STATUS_COMPLETED, phase=PHASE_DONE)

        service.delete_task(created.task_id)

        assert service.task_store.get(created.task_id) is None
    finally:
        service.close()


def test_delete_task_rejects_active_task(tmp_path):
    service = _build_service(tmp_path)
    try:
        created = service.task_store.create_task(book_id="book-1")
        service.task_store.update(created.task_id, status=STATUS_RUNNING)

        with pytest.raises(ValueError, match="Cannot delete active task"):
            service.delete_task(created.task_id)

        assert service.task_store.get(created.task_id) is not None
    finally:
        service.close()


def test_delete_task_attempts_remote_cleanup_and_deletes_locally(tmp_path):
    service = _build_service(tmp_path)
    try:
        payload_json = (
            '{"translation":{"batch_name":"batches/root","jobs":[{"batch_name":"batches/a","source_file_name":"files/src-a","output_file_name":"files/out-a","request_hashes":["h1"]}]},'
            '"polish":{"jobs":[{"batch_name":"batches/b","source_file_name":"files/src-b","output_file_name":"files/out-b","request_hashes":["h2"]}]}}'
        )
        created = service.task_store.create_task(book_id="book-1", payload_json=payload_json)
        service.task_store.update(created.task_id, status=STATUS_COMPLETED, phase=PHASE_DONE)

        service.gateway.delete_batch = AsyncMock()
        service.gateway.delete_file = AsyncMock()

        result = service.delete_task(created.task_id)

        assert service.task_store.get(created.task_id) is None
        assert result["task_id"] == created.task_id
        assert result["cleanup_warnings"] == []
        assert service.gateway.delete_batch.await_count == 3
        assert service.gateway.delete_file.await_count == 4
    finally:
        service.close()


def test_delete_task_keeps_local_delete_when_remote_cleanup_fails(tmp_path):
    service = _build_service(tmp_path)
    try:
        payload_json = '{"translation":{"jobs":[{"batch_name":"batches/a","source_file_name":"files/src-a","request_hashes":["h1"]}]}}'
        created = service.task_store.create_task(book_id="book-1", payload_json=payload_json)
        service.task_store.update(created.task_id, status=STATUS_COMPLETED, phase=PHASE_DONE)

        service.gateway.delete_batch = AsyncMock(side_effect=RuntimeError("boom"))
        service.gateway.delete_file = AsyncMock(side_effect=RuntimeError("boom"))

        result = service.delete_task(created.task_id)

        assert service.task_store.get(created.task_id) is None
        assert any("Failed to delete remote batch" in warning for warning in result["cleanup_warnings"])
        assert any("Failed to delete remote file" in warning for warning in result["cleanup_warnings"])
    finally:
        service.close()


@pytest.mark.asyncio
async def test_request_cancel_without_provider_batches_marks_task_cancelled(tmp_path):
    service = _build_service(tmp_path)
    try:
        created = service.task_store.create_task(book_id="book-1")
        service.gateway.cancel_batch = AsyncMock()

        result = await service.request_cancel(created.task_id)

        assert result.status == STATUS_CANCELLED
        assert result.phase == PHASE_DONE
        assert result.cancel_requested is True
        service.gateway.cancel_batch.assert_not_awaited()
    finally:
        service.close()


@pytest.mark.asyncio
async def test_request_cancel_without_batch_config_marks_task_cancelled_locally(tmp_path):
    service = _build_service(tmp_path)
    try:
        created = service.task_store.create_task(
            book_id="book-1",
            payload_json='{"translation":{"batch_name":"batches/active","batch_display_name":"cat-translation-task"}}',
        )
        service.workflow.config.translator_batch_config = None
        service.gateway.cancel_batch = AsyncMock()

        result = await service.request_cancel(created.task_id)

        assert result.status == STATUS_CANCELLED
        assert result.phase == PHASE_DONE
        assert result.last_error is not None
        assert "translator_batch_config" in result.last_error
        service.gateway.cancel_batch.assert_not_awaited()
    finally:
        service.close()


@pytest.mark.asyncio
async def test_request_cancel_resolves_provider_batches_by_display_name(tmp_path):
    service = _build_service(tmp_path)
    try:
        created = service.task_store.create_task(
            book_id="book-1",
            payload_json='{"model":"models/gemini-2.5-pro","translation":{"batch_display_name":"cat-translation-task"}}',
        )
        service.gateway.find_batch_names = AsyncMock(return_value=["batches/a", "batches/b"])
        service.gateway.cancel_batch = AsyncMock()
        service.gateway.get_batch_state = AsyncMock(side_effect=["CANCELLED", "CANCELLED"])

        result = await service.request_cancel(created.task_id)

        assert result.status == STATUS_CANCELLED
        assert result.phase == PHASE_DONE
        service.gateway.find_batch_names.assert_awaited_once()
        assert service.gateway.cancel_batch.await_count == 2
        assert service.gateway.get_batch_state.await_count == 2
    finally:
        service.close()


@pytest.mark.asyncio
async def test_request_cancel_keeps_cancelling_when_provider_batch_is_still_active(tmp_path):
    service = _build_service(tmp_path)
    try:
        created = service.task_store.create_task(
            book_id="book-1",
            payload_json='{"translation":{"batch_name":"batches/active"}}',
        )
        service.gateway.cancel_batch = AsyncMock()
        service.gateway.get_batch_state = AsyncMock(return_value="CANCELLING")

        result = await service.request_cancel(created.task_id)

        assert result.status == STATUS_CANCELLING
        assert result.phase != PHASE_DONE
        service.gateway.cancel_batch.assert_awaited_once()
        service.gateway.get_batch_state.assert_awaited_once()
    finally:
        service.close()


@pytest.mark.asyncio
async def test_run_task_short_circuits_when_cancel_requested(tmp_path):
    service = _build_service(tmp_path)
    try:
        created = service.task_store.create_task(book_id="book-1")
        service.task_store.mark_cancel_requested(created.task_id)
        with patch(
            "context_aware_translation.workflow.batch_translation_task_service.ensure_payload_prepared",
            new_callable=AsyncMock,
        ) as mock_prepare:
            result = await service.run_task(created.task_id)

            assert result.status == STATUS_CANCELLED
            assert result.phase == PHASE_DONE
            mock_prepare.assert_not_awaited()
    finally:
        service.close()


@pytest.mark.asyncio
async def test_run_task_cancel_requested_retries_provider_cancel_when_batch_exists(tmp_path):
    service = _build_service(tmp_path)
    try:
        created = service.task_store.create_task(
            book_id="book-1",
            payload_json='{"translation":{"batch_name":"batch/jobs/123"}}',
        )
        service.task_store.mark_cancel_requested(created.task_id)
        service.gateway.cancel_batch = AsyncMock()
        service.gateway.get_batch_state = AsyncMock(return_value="CANCELLED")

        result = await service.run_task(created.task_id)

        assert result.status == STATUS_CANCELLED
        assert result.phase == PHASE_DONE
        service.gateway.cancel_batch.assert_awaited_once()
        service.gateway.get_batch_state.assert_awaited_once()
    finally:
        service.close()


@pytest.mark.asyncio
async def test_run_task_reruns_cancelled_task_with_reset_pending_payload(tmp_path):
    service = _build_service(tmp_path)
    try:
        created = service.task_store.create_task(
            book_id="book-1",
            payload_json=(
                '{"items":[{"applied":false,'
                '"translation":{"state":"failed","error":"cancelled","fallback_attempted":true,"output_blocks":["x"],"messages":null,"request_hash":null,"inlined_request":null},'
                '"polish":{"state":"failed","error":"cancelled","fallback_attempted":true,"output_blocks":["x"],"messages":null,"request_hash":null,"inlined_request":null}}],'
                '"translation":{"batch_name":"batches/old","batch_display_name":"cat-translation-old","jobs":[]},'
                '"polish":{"batch_name":"batches/old-polish","batch_display_name":"cat-polish-old","jobs":[]}}'
            ),
        )
        service.task_store.update(created.task_id, status=STATUS_CANCELLED, cancel_requested=True, phase=PHASE_DONE)

        async def _pass_translation(_service, _task_id, payload, **_kwargs):  # noqa: ANN001
            return payload

        async def _pass_polish(_service, _task_id, payload, **_kwargs):  # noqa: ANN001
            return payload

        def _pass_apply(_service, _task_id, payload, **_kwargs):  # noqa: ANN001
            return payload

        with (
            patch(
                "context_aware_translation.workflow.batch_translation_task_service.run_translation_stage",
                new_callable=AsyncMock,
                side_effect=_pass_translation,
            ) as mock_translation,
            patch(
                "context_aware_translation.workflow.batch_translation_task_service.run_polish_stage",
                new_callable=AsyncMock,
                side_effect=_pass_polish,
            ),
            patch(
                "context_aware_translation.workflow.batch_translation_task_service.apply_results",
                side_effect=_pass_apply,
            ),
        ):
            result = await service.run_task(created.task_id)

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
        service.close()


@pytest.mark.asyncio
async def test_run_task_pauses_on_transient_timeout(tmp_path):
    service = _build_service(tmp_path)
    try:
        created = service.task_store.create_task(book_id="book-1")
        with patch(
            "context_aware_translation.workflow.batch_translation_task_service.ensure_payload_prepared",
            new_callable=AsyncMock,
            side_effect=httpx.ReadTimeout("timed out"),
        ):
            result = await service.run_task(created.task_id)

            assert result.status == STATUS_PAUSED
            assert result.phase == PHASE_PREPARE
            assert "ReadTimeout" in (result.last_error or "")
    finally:
        service.close()


@pytest.mark.asyncio
async def test_run_task_pauses_on_quota_error(tmp_path):
    service = _build_service(tmp_path)
    try:
        created = service.task_store.create_task(book_id="book-1")
        with patch(
            "context_aware_translation.workflow.batch_translation_task_service.ensure_payload_prepared",
            new_callable=AsyncMock,
            side_effect=RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded"),
        ):
            result = await service.run_task(created.task_id)

            assert result.status == STATUS_PAUSED
            assert "RESOURCE_EXHAUSTED" in (result.last_error or "")
    finally:
        service.close()


@pytest.mark.asyncio
async def test_run_task_marks_failed_on_non_transient_error(tmp_path):
    service = _build_service(tmp_path)
    try:
        created = service.task_store.create_task(book_id="book-1")
        with patch(
            "context_aware_translation.workflow.batch_translation_task_service.ensure_payload_prepared",
            new_callable=AsyncMock,
            side_effect=ValueError("bad payload"),
        ):
            result = await service.run_task(created.task_id)

            assert result.status == STATUS_FAILED
            assert result.phase == PHASE_DONE
            assert result.last_error == "ValueError: bad payload"
    finally:
        service.close()


@pytest.mark.asyncio
async def test_ensure_payload_prepared_uses_batch_model_with_fixed_temperature():
    task = TranslationBatchTaskRecord(
        task_id="task-1",
        book_id="book-1",
        status=STATUS_QUEUED,
        phase=PHASE_PREPARE,
        payload_json="{}",
        document_ids_json=None,
        force=False,
        skip_context=False,
        total_items=0,
        completed_items=0,
        failed_items=0,
        cancel_requested=False,
        translation_batch_name=None,
        polish_batch_name=None,
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

    payload = await ensure_payload_prepared(service, task, {}, cancel_check=None)

    manager.collect_chunk_translation_inputs.assert_called_once_with(
        batch_size=7,
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
                "context_aware_translation.workflow.batch_translation_task_ops.poll_until_terminal",
                new=AsyncMock(side_effect=fake_poll),
            ),
            patch(
                "context_aware_translation.workflow.batch_translation_task_ops.validated_chat",
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
                "context_aware_translation.workflow.batch_translation_task_ops.poll_until_terminal",
                new=AsyncMock(side_effect=fake_poll),
            ),
            patch(
                "context_aware_translation.workflow.batch_translation_task_ops.validated_chat",
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
                "context_aware_translation.workflow.batch_translation_task_ops.poll_until_terminal",
                new=AsyncMock(side_effect=fake_poll),
            ),
            patch(
                "context_aware_translation.workflow.batch_translation_task_ops.validated_chat",
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
                "context_aware_translation.workflow.batch_translation_task_ops.poll_until_terminal",
                new=AsyncMock(side_effect=fake_poll),
            ),
            patch(
                "context_aware_translation.workflow.batch_translation_task_ops.validated_chat",
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
