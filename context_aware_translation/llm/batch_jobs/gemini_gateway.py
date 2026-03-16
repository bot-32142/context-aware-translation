from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import tempfile
from typing import Any

from google import genai

from context_aware_translation.config import TranslatorBatchConfig
from context_aware_translation.llm.batch_jobs.base import (
    POLL_STATUS_CANCELLED,
    POLL_STATUS_COMPLETED,
    POLL_STATUS_FAILED,
    POLL_STATUS_PENDING,
    BatchJobGateway,
    BatchPollResult,
    BatchSubmitResult,
)
from context_aware_translation.storage.repositories.llm_batch_store import LLMBatchStore

logger = logging.getLogger(__name__)

_PROVIDER = "gemini_ai_studio"
_GEMINI_HTTP_TIMEOUT_SECONDS = 300.0
_CANCELLABLE_STATES = {"QUEUED", "PENDING", "RUNNING", "UPDATING", "PAUSED", "CANCELLING"}
_COMPLETED_STATES = {"SUCCEEDED", "PARTIALLY_SUCCEEDED"}
_FAILED_STATES = {"FAILED", "EXPIRED"}
_OUTPUT_KEY = "key"
_OUTPUT_RESPONSE = "response"
_OUTPUT_ERROR = "error"
_OUTPUT_STATUS = "status"
_OUTPUT_CODE = "code"
_RESP_TEXT = "text"
_RESP_CANDIDATES = "candidates"
_RESP_CONTENT = "content"
_RESP_PARTS = "parts"


def _normalized_job_state(state: Any) -> str:
    raw = getattr(state, "value", state)
    normalized = str(raw or "").strip().upper()
    if normalized.startswith("JOB_STATE_"):
        return normalized[len("JOB_STATE_") :]
    if normalized.startswith("BATCH_STATE_"):
        return normalized[len("BATCH_STATE_") :]
    return normalized


def _poll_status_from_state(state: str) -> str:
    if state in _COMPLETED_STATES:
        return POLL_STATUS_COMPLETED
    if state == "CANCELLED":
        return POLL_STATUS_CANCELLED
    if state in _FAILED_STATES:
        return POLL_STATUS_FAILED
    return POLL_STATUS_PENDING


def _job_error_text(error: Any) -> str:
    if error is None:
        return ""

    if isinstance(error, dict):
        code = error.get("code")
        message = error.get("message")
        details = error.get("details")
    else:
        code = getattr(error, "code", None)
        message = getattr(error, "message", None)
        details = getattr(error, "details", None)

    detail_text = "; ".join(str(item) for item in details) if isinstance(details, list) and details else ""
    parts = [
        f"code={code}" if code is not None else "",
        message if isinstance(message, str) and message else "",
        detail_text,
    ]
    summary = " | ".join(part for part in parts if part)
    return summary or str(error)


def _is_not_found_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code == 404:
        return True
    message = str(exc).lower()
    return "not found" in message or "404" in message


def _json_default(value: Any) -> str:
    return str(value)


def _stable_request_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return str(content)


def _model_supports_explicit_thinking(model: str) -> bool:
    return "gemini-2.5" in model.lower()


def _resolve_thinking_config(*, model: str, thinking_mode: str) -> tuple[dict[str, Any] | None, str | None]:
    mode = thinking_mode.strip().lower()
    if mode == "auto":
        return None, None

    if not _model_supports_explicit_thinking(model):
        return None, f"Thinking mode '{mode}' is not supported for model '{model}'. Falling back to auto."

    if mode == "off":
        return {"thinking_budget": 0}, None
    if mode == "low":
        return {"thinking_budget": 256}, None
    if mode == "medium":
        return {"thinking_budget": 1024}, None
    if mode == "high":
        return {"thinking_budget": 2048}, None
    return None, f"Unknown thinking mode '{thinking_mode}'. Falling back to auto."


def _extract_response_text(response: Any) -> str:
    text = response.get(_RESP_TEXT)
    if isinstance(text, str) and text:
        return text

    pieces = [
        part.get(_RESP_TEXT)
        for candidate in response.get(_RESP_CANDIDATES, [])
        for part in candidate.get(_RESP_CONTENT, {}).get(_RESP_PARTS, [])
        if isinstance(part.get(_RESP_TEXT), str) and part.get(_RESP_TEXT)
    ]
    if pieces:
        return "".join(str(piece) for piece in pieces)

    raise ValueError("Gemini batch response did not include text content.")


def _sdk_request_to_api_format(request: dict[str, Any]) -> dict[str, Any]:
    """Convert an SDK-format request to Gemini Batch API proto format.

    The SDK uses a convenience ``config`` wrapper with snake_case field names,
    but the Batch API JSONL file format expects proto-compatible camelCase
    fields (``generationConfig``, ``systemInstruction``, etc.) as siblings
    of ``contents``.
    """
    result: dict[str, Any] = {}
    if "model" in request:
        model = request["model"]
        if not model.startswith("models/"):
            model = f"models/{model}"
        result["model"] = model
    if "contents" in request:
        result["contents"] = request["contents"]

    config = request.get("config")
    if not config:
        return result

    generation_config: dict[str, Any] = {}
    if "temperature" in config:
        generation_config["temperature"] = config["temperature"]
    if "response_mime_type" in config:
        generation_config["responseMimeType"] = config["response_mime_type"]
    if "thinking_config" in config:
        tc = config["thinking_config"]
        api_tc: dict[str, Any] = {}
        if "thinking_budget" in tc:
            api_tc["thinkingBudget"] = tc["thinking_budget"]
        if "include_thoughts" in tc:
            api_tc["includeThoughts"] = tc["include_thoughts"]
        if api_tc:
            generation_config["thinkingConfig"] = api_tc
    if generation_config:
        result["generationConfig"] = generation_config

    if "system_instruction" in config:
        text = config["system_instruction"]
        result["systemInstruction"] = {"parts": [{"text": text}]}

    # Warn about unmapped config keys so future additions aren't silently lost.
    _mapped_keys = {"temperature", "response_mime_type", "thinking_config", "system_instruction"}
    unknown = set(config) - _mapped_keys
    if unknown:
        logger.debug("_sdk_request_to_api_format: unmapped config keys ignored: %s", unknown)

    return result


def _extract_output_row(payload: dict[str, Any]) -> tuple[str, Any, Any]:
    request_hash = payload[_OUTPUT_KEY]
    response = payload.get(_OUTPUT_RESPONSE)
    error = payload.get(_OUTPUT_ERROR)
    if error is None:
        status = payload.get(_OUTPUT_STATUS, {})
        code = status.get(_OUTPUT_CODE)
        if code not in (None, 0, "0"):
            error = status

    return request_hash, response, error


def _to_bytes(payload: Any) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return bytes(payload)


def _persist_row_result(
    *,
    batch_store: LLMBatchStore,
    batch_name: str,
    request_hash: str,
    response_payload: Any,
    error_payload: Any,
) -> None:
    if error_payload is not None:
        batch_store.upsert_failed(
            request_hash,
            _PROVIDER,
            _job_error_text(error_payload) or "Gemini batch item failed.",
            batch_name=batch_name,
        )
        return

    text = _extract_response_text(response_payload)
    batch_store.upsert_completed(
        request_hash,
        _PROVIDER,
        text,
        batch_name=batch_name,
    )


class GeminiBatchJobGateway(BatchJobGateway):
    """Gemini AI Studio implementation of provider batch jobs."""

    def __init__(self) -> None:
        self._client_cache: dict[str, Any] = {}
        self._request_warnings: dict[str, list[str]] = {}
        self._batch_warnings: dict[str, list[str]] = {}

    def _get_client(self, batch_config: TranslatorBatchConfig) -> Any:
        if str(batch_config.provider or "").lower() != _PROVIDER:
            raise ValueError(f"Unsupported batch provider for Gemini gateway: {batch_config.provider}")

        cache_key = hashlib.sha256(batch_config.api_key.encode()).hexdigest()
        cached = self._client_cache.get(cache_key)
        if cached is not None:
            return cached

        client_kwargs: dict[str, Any] = {
            "api_key": batch_config.api_key,
            "http_options": {"timeout": int(_GEMINI_HTTP_TIMEOUT_SECONDS * 1000)},
        }

        client = genai.Client(**client_kwargs)
        self._client_cache[cache_key] = client
        return client

    @staticmethod
    def _request_hash_from_inlined_request(inlined_request: dict[str, Any]) -> str | None:
        metadata = inlined_request.get("metadata")
        request_hash = metadata.get("request_hash") if isinstance(metadata, dict) else None
        if isinstance(request_hash, str) and request_hash:
            return request_hash
        return None

    def _extract_batch_warnings_for_requests(self, inlined_requests: list[dict[str, Any]]) -> list[str]:
        warnings: list[str] = []
        for inlined_request in inlined_requests:
            request_hash = self._request_hash_from_inlined_request(inlined_request)
            if request_hash is None:
                continue
            warnings.extend(self._request_warnings.pop(request_hash, []))

        return list(dict.fromkeys(warnings))

    def _remember_batch_warnings(self, batch_name: str, warnings: list[str]) -> None:
        if warnings:
            self._batch_warnings[batch_name] = warnings

    def _consume_batch_warnings(self, batch_name: str, *, terminal: bool) -> list[str]:
        if terminal:
            return list(self._batch_warnings.pop(batch_name, []))
        return list(self._batch_warnings.get(batch_name, []))

    def build_inlined_request(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        request_kwargs: dict[str, Any],
        metadata: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        request_kwargs = dict(request_kwargs)

        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role", "")).lower()
            content_text = _message_content_to_text(message.get("content", ""))
            if role == "system":
                system_parts.append(content_text)
                continue
            gemini_role = "model" if role == "assistant" else "user"
            contents.append({"role": gemini_role, "parts": [{"text": content_text}]})

        if not contents:
            raise ValueError("Gemini batch request requires at least one non-system message.")

        config_kwargs: dict[str, Any] = {"temperature": 0.0}
        if system_parts:
            config_kwargs["system_instruction"] = "\n\n".join(system_parts)

        response_format = request_kwargs.pop("response_format", None)
        if isinstance(response_format, dict) and response_format.get("type") == "json_object":
            config_kwargs["response_mime_type"] = "application/json"

        thinking_mode = str(request_kwargs.pop("thinking_mode", "auto") or "auto")
        thinking_config, thinking_warning = _resolve_thinking_config(model=model, thinking_mode=thinking_mode)
        if thinking_config is not None:
            config_kwargs["thinking_config"] = thinking_config
        if thinking_warning:
            logger.warning(thinking_warning)

        if request_kwargs:
            logger.debug(
                "Ignoring unsupported Gemini batch request options: %s",
                ", ".join(sorted(request_kwargs)),
            )

        inlined_request: dict[str, Any] = {
            "model": model,
            "contents": contents,
            "config": config_kwargs,
        }
        if metadata:
            inlined_request["metadata"] = metadata

        request_hash = _stable_request_hash(
            {
                "provider": _PROVIDER,
                "model": model,
                "contents": contents,
                "config": config_kwargs,
            }
        )

        if thinking_warning:
            self._request_warnings.setdefault(request_hash, []).append(thinking_warning)

        return request_hash, inlined_request

    async def _upload_jsonl_source_file(
        self,
        *,
        client: Any,
        inlined_requests: list[dict[str, Any]],
        display_name: str | None,
    ) -> str:
        fd, temp_path = tempfile.mkstemp(suffix=".jsonl", prefix="cat-gemini-batch-")
        os.close(fd)
        try:
            with open(temp_path, "w", encoding="utf-8") as fp:
                for inlined_request in inlined_requests:
                    request_hash = self._request_hash_from_inlined_request(inlined_request)
                    if request_hash is None:
                        request_hash = _stable_request_hash(inlined_request)
                    request_payload = dict(inlined_request)
                    request_payload.pop("metadata", None)
                    request_payload = _sdk_request_to_api_format(request_payload)
                    fp.write(
                        json.dumps(
                            {"key": request_hash, "request": request_payload},
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        + "\n"
                    )

            upload_config: dict[str, Any] = {"mime_type": "application/jsonl"}
            if display_name:
                upload_config["display_name"] = f"{display_name}-src"
            file_obj = await asyncio.to_thread(client.files.upload, file=temp_path, config=upload_config)
        finally:
            with contextlib.suppress(Exception):
                os.unlink(temp_path)

        source_file_name = file_obj.name
        if not source_file_name:
            raise ValueError("Gemini file upload returned an empty file name.")
        return str(source_file_name)

    @staticmethod
    def _submit_request_id(display_name: str) -> str:
        return hashlib.sha256(display_name.encode("utf-8")).hexdigest()[:32]

    async def submit_batch(
        self,
        *,
        batch_config: TranslatorBatchConfig,
        model: str,
        inlined_requests: list[dict[str, Any]],
        display_name: str | None = None,
    ) -> BatchSubmitResult:
        if not inlined_requests:
            raise ValueError("No inlined requests provided for Gemini batch submission.")

        client = self._get_client(batch_config)
        submit_warnings = self._extract_batch_warnings_for_requests(inlined_requests)

        source_file_name = await self._upload_jsonl_source_file(
            client=client,
            inlined_requests=inlined_requests,
            display_name=display_name,
        )

        create_kwargs: dict[str, Any] = {"model": model, "src": source_file_name}
        if display_name:
            create_kwargs["config"] = {
                "display_name": display_name,
                "http_options": {"headers": {"X-Goog-Request-Id": self._submit_request_id(display_name)}},
            }

        batch_job = await asyncio.to_thread(client.batches.create, **create_kwargs)
        batch_name = batch_job.name
        if not batch_name:
            raise ValueError("Gemini batch create returned an empty batch job name.")

        self._remember_batch_warnings(batch_name, submit_warnings)
        return BatchSubmitResult(batch_name=batch_name, source_file_name=source_file_name)

    def _persist_output_file_responses(
        self,
        *,
        output_bytes: bytes,
        request_hashes: set[str],
        batch_store: LLMBatchStore,
        batch_name: str,
    ) -> None:
        unresolved = set(request_hashes)

        for raw_line in output_bytes.decode("utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line:
                continue

            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSONL line in batch output: %s", line[:200])
                continue
            request_hash, response_payload, error_payload = _extract_output_row(payload)
            if request_hash not in unresolved:
                continue

            _persist_row_result(
                batch_store=batch_store,
                batch_name=batch_name,
                request_hash=request_hash,
                response_payload=response_payload,
                error_payload=error_payload,
            )
            unresolved.discard(request_hash)

        if unresolved:
            unresolved_list = ", ".join(sorted(h[:12] for h in unresolved))
            raise ValueError(f"Gemini output file missing responses for request(s): {unresolved_list}")

    async def poll_once(
        self,
        *,
        batch_config: TranslatorBatchConfig,
        batch_name: str,
        request_hashes: set[str],
        batch_store: LLMBatchStore,
    ) -> BatchPollResult:
        client = self._get_client(batch_config)
        batch_job = await asyncio.to_thread(client.batches.get, name=batch_name)

        state_name = _normalized_job_state(batch_job.state)
        poll_status = _poll_status_from_state(state_name)
        poll_warnings = self._consume_batch_warnings(batch_name, terminal=poll_status != POLL_STATUS_PENDING)
        warnings = poll_warnings or None

        if poll_status == POLL_STATUS_PENDING:
            return BatchPollResult(status=poll_status, warnings=warnings)
        elif poll_status == POLL_STATUS_CANCELLED:
            return BatchPollResult(
                status=poll_status,
                error_text="Provider batch cancelled.",
                warnings=warnings,
            )
        elif poll_status == POLL_STATUS_FAILED:
            error_text = _job_error_text(batch_job.error)
            if error_text == "":
                error_text = f"Gemini batch ended with state {state_name}."
            return BatchPollResult(status=poll_status, error_text=error_text, warnings=warnings)
        elif poll_status != POLL_STATUS_COMPLETED:
            return BatchPollResult(status=poll_status, warnings=warnings)

        output_file_name = batch_job.dest.file_name

        output_bytes = _to_bytes(await asyncio.to_thread(client.files.download, file=output_file_name))

        self._persist_output_file_responses(
            output_bytes=output_bytes,
            request_hashes=request_hashes,
            batch_store=batch_store,
            batch_name=batch_name,
        )

        return BatchPollResult(
            status=POLL_STATUS_COMPLETED,
            output_file_name=output_file_name,
            warnings=poll_warnings or None,
        )

    async def get_batch_state(
        self,
        *,
        batch_config: TranslatorBatchConfig,
        batch_name: str,
    ) -> str:
        client = self._get_client(batch_config)
        batch_job = await asyncio.to_thread(client.batches.get, name=batch_name)
        return _normalized_job_state(batch_job.state)

    async def cancel_batch(
        self,
        *,
        batch_config: TranslatorBatchConfig,
        batch_name: str,
    ) -> None:
        client = self._get_client(batch_config)
        await asyncio.to_thread(client.batches.cancel, name=batch_name)

    async def delete_batch(
        self,
        *,
        batch_config: TranslatorBatchConfig,
        batch_name: str,
    ) -> None:
        client = self._get_client(batch_config)
        try:
            await asyncio.to_thread(client.batches.delete, name=batch_name)
        except Exception as exc:
            if _is_not_found_error(exc):
                logger.info("Gemini batch already absent during cleanup: %s", batch_name)
                return
            raise

    async def delete_file(
        self,
        *,
        batch_config: TranslatorBatchConfig,
        file_name: str,
    ) -> None:
        client = self._get_client(batch_config)
        try:
            await asyncio.to_thread(client.files.delete, name=file_name)
        except Exception as exc:
            if _is_not_found_error(exc):
                logger.info("Gemini file already absent during cleanup: %s", file_name)
                return
            raise

    async def find_batch_names(
        self,
        *,
        batch_config: TranslatorBatchConfig,
        display_name: str,
        model: str | None = None,
    ) -> list[str]:
        client = self._get_client(batch_config)
        wanted_model = model or ""

        resolved: list[str] = []
        for batch_job in client.batches.list(config={"page_size": 100}):
            if batch_job.display_name != display_name:
                continue

            job_model = batch_job.model
            if wanted_model and job_model and job_model != wanted_model:
                continue

            state = _normalized_job_state(batch_job.state)
            if state and state not in _CANCELLABLE_STATES:
                continue

            name = batch_job.name
            if not name:
                continue

            resolved.append(name)

        return resolved
