from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from context_aware_translation.config import TranslatorBatchConfig
from context_aware_translation.llm.batch_jobs.base import POLL_STATUS_CANCELLED, POLL_STATUS_COMPLETED
from context_aware_translation.llm.batch_jobs.gemini_gateway import GeminiBatchJobGateway
from context_aware_translation.storage.llm_batch_store import STATUS_COMPLETED, STATUS_FAILED, LLMBatchStore


def _messages() -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "hello"},
    ]


def _batch_job(
    *,
    name: str,
    display_name: str,
    model: str,
    state: str = "JOB_STATE_PENDING",
    output_file_name: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        display_name=display_name,
        model=model,
        state=SimpleNamespace(value=state),
        dest=SimpleNamespace(file_name=output_file_name),
    )


def _batch_config() -> TranslatorBatchConfig:
    return TranslatorBatchConfig(
        provider="gemini_ai_studio",
        api_key="k",
        model="gemini-2.5-flash",
    )


def test_build_inlined_request_applies_explicit_thinking_mode() -> None:
    gateway = GeminiBatchJobGateway()
    _, request = gateway.build_inlined_request(
        messages=_messages(),
        model="gemini-2.5-flash",
        request_kwargs={"thinking_mode": "off"},
    )

    assert request["config"]["thinking_config"] == {"thinking_budget": 0}


def test_build_inlined_request_unsupported_thinking_mode_emits_warning(caplog) -> None:
    gateway = GeminiBatchJobGateway()
    _, request = gateway.build_inlined_request(
        messages=_messages(),
        model="gemini-1.5-flash",
        request_kwargs={"thinking_mode": "high"},
    )

    assert "thinking_config" not in request["config"]
    assert any("Falling back to auto" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_submit_batch_uploads_jsonl_and_uses_file_source() -> None:
    gateway = GeminiBatchJobGateway()
    client = MagicMock()
    display_name = "cat-translation-task1234"
    model = "models/gemini-2.5-pro"
    captured_lines: list[str] = []

    client.batches.list.return_value = []

    def _upload_side_effect(*, file, config):  # noqa: ANN001
        with open(file, encoding="utf-8") as fp:
            captured_lines.extend([line.strip() for line in fp.readlines() if line.strip()])
        assert config["mime_type"] == "application/jsonl"
        return SimpleNamespace(name="files/src-1")

    client.files.upload.side_effect = _upload_side_effect
    client.batches.create.return_value = _batch_job(name="batches/new", display_name=display_name, model=model)

    request_hash, inlined_request = gateway.build_inlined_request(
        messages=_messages(),
        model=model,
        request_kwargs={"thinking_mode": "auto"},
    )
    inlined_request["metadata"] = {"request_hash": request_hash}

    with patch.object(gateway, "_get_client", return_value=client):
        result = await gateway.submit_batch(
            batch_config=_batch_config(),
            model=model,
            inlined_requests=[inlined_request],
            display_name=display_name,
        )

    assert result.batch_name == "batches/new"
    assert result.source_file_name == "files/src-1"
    _, create_kwargs = client.batches.create.call_args
    assert create_kwargs["src"] == "files/src-1"

    assert len(captured_lines) == 1
    row = json.loads(captured_lines[0])
    assert row["key"] == request_hash
    assert isinstance(row["request"], dict)


@pytest.mark.asyncio
async def test_poll_once_parses_output_file_jsonl_and_persists_results(tmp_path: Path) -> None:
    gateway = GeminiBatchJobGateway()
    client = MagicMock()
    batch_name = "batches/job-1"

    request_hash_ok = "hash-ok"
    request_hash_err = "hash-err"

    output_lines = [
        json.dumps({"key": request_hash_ok, "response": {"text": "translated"}}),
        json.dumps({"key": request_hash_err, "error": {"code": 429, "message": "quota"}}),
    ]

    client.batches.get.return_value = _batch_job(
        name=batch_name,
        display_name="cat-translation",
        model="models/gemini-2.5-pro",
        state="BATCH_STATE_SUCCEEDED",
        output_file_name="files/out-1",
    )
    client.files.download.return_value = ("\n".join(output_lines) + "\n").encode("utf-8")

    store = LLMBatchStore(tmp_path / "llm_batch_cache.db")
    try:
        with patch.object(gateway, "_get_client", return_value=client):
            result = await gateway.poll_once(
                batch_config=_batch_config(),
                batch_name=batch_name,
                request_hashes={request_hash_ok, request_hash_err},
                batch_store=store,
            )

        assert result.status == POLL_STATUS_COMPLETED
        assert result.output_file_name == "files/out-1"

        ok_record = store.get(request_hash_ok)
        err_record = store.get(request_hash_err)
        assert ok_record is not None and ok_record.status == STATUS_COMPLETED
        assert ok_record.response_text == "translated"
        assert err_record is not None and err_record.status == STATUS_FAILED
        assert "quota" in (err_record.error_text or "")
    finally:
        store.close()


@pytest.mark.asyncio
async def test_poll_once_handles_batch_state_cancelled() -> None:
    gateway = GeminiBatchJobGateway()
    client = MagicMock()
    client.batches.get.return_value = _batch_job(
        name="batches/cancelled",
        display_name="cat-translation",
        model="models/gemini-2.5-pro",
        state="BATCH_STATE_CANCELLED",
    )

    with patch.object(gateway, "_get_client", return_value=client):
        result = await gateway.poll_once(
            batch_config=_batch_config(),
            batch_name="batches/cancelled",
            request_hashes=set(),
            batch_store=MagicMock(),
        )

    assert result.status == POLL_STATUS_CANCELLED


@pytest.mark.asyncio
async def test_delete_batch_and_file_delegate_to_provider() -> None:
    gateway = GeminiBatchJobGateway()
    client = MagicMock()

    with patch.object(gateway, "_get_client", return_value=client):
        await gateway.delete_batch(batch_config=_batch_config(), batch_name="batches/abc")
        await gateway.delete_file(batch_config=_batch_config(), file_name="files/xyz")

    client.batches.delete.assert_called_once_with(name="batches/abc")
    client.files.delete.assert_called_once_with(name="files/xyz")
