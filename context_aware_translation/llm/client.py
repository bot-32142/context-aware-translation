from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Callable, Sequence
from typing import Any

from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from context_aware_translation.config import LLMConfig
from context_aware_translation.core.cancellation import OperationCancelledError, raise_if_cancelled
from context_aware_translation.llm.session_trace import get_llm_session_id, llm_session_scope
from context_aware_translation.llm.token_tracker import TokenTracker

logger = logging.getLogger(__name__)

_UNSUPPORTED_OPENAI_CREATE_KWARGS = frozenset({"provider", "_ui_display_name", "_wizard_template_key"})
_OPENAI_BASE_URL_PREFIX = "https://api.openai.com/"


def _openai_supports_reasoning_effort_none(model: str) -> bool:
    normalized = model.strip().lower()
    return normalized.startswith("o") or normalized.startswith("gpt-5")


# Suppress OpenAI library's DEBUG/INFO/WARNING logging to avoid duplicate logs
# Our custom logger already logs all necessary information
logging.getLogger("openai").setLevel(logging.ERROR)
logging.getLogger("openai._base_client").setLevel(logging.ERROR)


class LLMError(Exception):
    pass


class LLMAuthError(LLMError):
    pass


def _sanitize_openai_create_kwargs(
    *,
    model: str,
    base_url: str | None,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    removed = set(_UNSUPPORTED_OPENAI_CREATE_KWARGS.intersection(kwargs))
    if (
        kwargs.get("reasoning_effort") == "none"
        and isinstance(base_url, str)
        and base_url.startswith(_OPENAI_BASE_URL_PREFIX)
        and not _openai_supports_reasoning_effort_none(model)
    ):
        removed.add("reasoning_effort")
    if not removed:
        return kwargs
    sanitized = {key: value for key, value in kwargs.items() if key not in removed}
    logger.debug("Dropping unsupported OpenAI create kwargs: %s", ", ".join(sorted(removed)))
    return sanitized


def _to_int(value: Any) -> int:
    """Safely coerce provider usage fields to int."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _usage_get(container: Any, *path: str) -> Any:
    """Read nested usage fields from both SDK objects and dict payloads."""
    current = container
    for key in path:
        if current is None:
            return None
        current = current.get(key) if isinstance(current, dict) else getattr(current, key, None)
    return current


def _first_nonzero(container: Any, field_paths: Sequence[tuple[str, ...]]) -> int:
    """Return first non-zero usage field from candidate paths."""
    for field_path in field_paths:
        value = _to_int(_usage_get(container, *field_path))
        if value > 0:
            return value
    return 0


def _cache_creation_tokens(usage: Any) -> int:
    """Read cache-creation token fields used by Anthropic/Qwen variants."""
    direct = _to_int(_usage_get(usage, "cache_creation_input_tokens"))
    if direct > 0:
        return direct

    prompt_details_direct = _to_int(_usage_get(usage, "prompt_tokens_details", "cache_creation_input_tokens"))
    if prompt_details_direct > 0:
        return prompt_details_direct

    # Providers may nest creation details under cache_creation with either a
    # rolled-up field or split fields by TTL.
    nested_direct = _to_int(_usage_get(usage, "cache_creation", "cache_creation_input_tokens"))
    if nested_direct > 0:
        return nested_direct

    prompt_nested_direct = _to_int(
        _usage_get(usage, "prompt_tokens_details", "cache_creation", "cache_creation_input_tokens")
    )
    if prompt_nested_direct > 0:
        return prompt_nested_direct

    return (
        _to_int(_usage_get(usage, "cache_creation", "ephemeral_5m_input_tokens"))
        + _to_int(_usage_get(usage, "cache_creation", "ephemeral_1h_input_tokens"))
        + _to_int(_usage_get(usage, "prompt_tokens_details", "cache_creation", "ephemeral_5m_input_tokens"))
        + _to_int(_usage_get(usage, "prompt_tokens_details", "cache_creation", "ephemeral_1h_input_tokens"))
    )


def _extract_token_usage(response: Any) -> dict[str, int] | None:
    """
    Extract token usage information from provider responses.

    Args:
        response: Chat completion response object

    Returns:
        Dictionary with token usage information, or None if not available.
        Fields:
        - cached_input_tokens: Input tokens served from cache
        - uncached_input_tokens: Input tokens not from cache
        - output_tokens: Output tokens (excluding reasoning)
        - reasoning_tokens: Tokens used for reasoning (if applicable)
        - total_tokens: Total tokens (for reference)
    """
    if not hasattr(response, "usage") or not response.usage:
        return None

    usage = response.usage
    prompt_tokens = _first_nonzero(usage, (("prompt_tokens",), ("input_tokens",)))
    completion_tokens = _first_nonzero(usage, (("completion_tokens",), ("output_tokens",)))

    # Provider cache field variants:
    # - DeepSeek: prompt_cache_hit_tokens / prompt_cache_miss_tokens
    # - OpenAI/Qwen/Z.ai: prompt_tokens_details.cached_tokens
    # - Anthropic native: cache_read_input_tokens / cache_creation_input_tokens
    cached_input = _to_int(_usage_get(usage, "prompt_cache_hit_tokens"))
    uncached_input = _to_int(_usage_get(usage, "prompt_cache_miss_tokens"))

    if cached_input == 0 and uncached_input == 0:
        cached_input = _to_int(_usage_get(usage, "prompt_tokens_details", "cached_tokens"))
        if cached_input > 0:
            uncached_input = max(prompt_tokens - cached_input, 0)

    if cached_input == 0 and uncached_input == 0:
        cache_read = _to_int(_usage_get(usage, "cache_read_input_tokens"))
        cache_creation = _cache_creation_tokens(usage)
        anthropic_input = _to_int(_usage_get(usage, "input_tokens"))
        if cache_read > 0 or cache_creation > 0 or anthropic_input > 0:
            cached_input = cache_read
            uncached_input = anthropic_input + cache_creation
            if prompt_tokens == 0:
                prompt_tokens = cached_input + uncached_input

    # If no cache detail is available, treat all input as uncached.
    if cached_input == 0 and uncached_input == 0 and prompt_tokens > 0:
        uncached_input = prompt_tokens

    # Reasoning token field variants.
    reasoning_tokens = _first_nonzero(
        usage,
        (
            ("completion_tokens_details", "reasoning_tokens"),
            ("output_tokens_details", "reasoning_tokens"),
            ("reasoning_tokens",),
            ("completion_tokens_details", "thinking_tokens"),
            ("output_tokens_details", "thinking_tokens"),
            ("completion_tokens_details", "thoughts_token_count"),
            ("output_tokens_details", "thoughts_token_count"),
        ),
    )

    # Calculate output tokens (excluding reasoning).
    output_tokens = max(completion_tokens - reasoning_tokens, 0)
    total_tokens = _to_int(_usage_get(usage, "total_tokens"))
    if total_tokens <= 0:
        inferred_input = cached_input + uncached_input
        total_tokens = inferred_input + completion_tokens if inferred_input > 0 else prompt_tokens + completion_tokens

    # Some providers report hidden internal/reasoning tokens only in total.
    # Reconcile the delta to reasoning so tracked totals match billing totals.
    accounted = cached_input + uncached_input + output_tokens + reasoning_tokens
    if total_tokens > accounted:
        reasoning_tokens += total_tokens - accounted

    token_usage: dict[str, int] = {
        "cached_input_tokens": cached_input,
        "uncached_input_tokens": uncached_input,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }

    if reasoning_tokens > 0:
        token_usage["reasoning_tokens"] = reasoning_tokens

    return token_usage


class LLMClient:
    def __init__(self, config: LLMConfig) -> None:
        if not config.api_key:
            raise LLMAuthError("OPENAI_API_KEY not set")
        self.config = config
        client_kwargs: dict[str, Any] = {
            "api_key": config.api_key,
            "base_url": config.base_url,
            "timeout": config.timeout,
        }
        if config.api_version:
            client_kwargs["api_version"] = config.api_version
        self.client = OpenAI(**client_kwargs)
        # Map of (api_key, base_url, api_version, timeout) -> OpenAI client for caching
        # These are all client initialization parameters that can't be changed per-request
        self._client_cache: dict[tuple[str | None, str | None, str | None, float], OpenAI] = {
            (config.api_key, config.base_url, config.api_version, config.timeout): self.client
        }

    def _get_client_for_step(self, step_config: LLMConfig) -> OpenAI:
        """
        Get the appropriate OpenAI client for a step configuration.
        Creates a new client if API connection settings (key, URL, version, timeout) differ.
        step_config should already be resolved at config initialization time.
        """

        # Create cache key from step config (already resolved)
        cache_key = (
            step_config.api_key,
            step_config.base_url,
            step_config.api_version,
            step_config.timeout,
        )

        # Return cached client if available
        if cache_key in self._client_cache:
            return self._client_cache[cache_key]

        # Create new client for this API connection combination
        client_kwargs: dict[str, Any] = {
            "api_key": step_config.api_key,
            "base_url": step_config.base_url,
            "timeout": step_config.timeout,
        }
        if step_config.api_version:
            client_kwargs["api_version"] = step_config.api_version

        new_client = OpenAI(**client_kwargs)
        self._client_cache[cache_key] = new_client
        return new_client

    def _should_retry_server_error(self, error: BaseException) -> bool:
        if isinstance(error, APIError):
            status_code = getattr(error, "status_code", None)
            if status_code and status_code >= 500:
                return True
        return False

    def _chat_impl(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        client: OpenAI,
        endpoint_profile_name: str | None = None,
        **kwargs: Any,
    ) -> str:
        session_id = get_llm_session_id()
        session_prefix = f"[llm_session={session_id}] " if session_id else ""
        # Log user prompts only; skip system prompts to avoid leaking them
        logger.debug(
            "%sLLM request - Model: %s, Temperature: %s, Kwargs: %s", session_prefix, model, temperature, kwargs
        )
        for i, msg in enumerate(messages):
            role = (msg.get("role") or "unknown").lower()
            if role != "user":
                continue
            content = msg.get("content", "")
            logger.info("%sLLM user message[%d]: %s", session_prefix, i, content)

        create_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            **kwargs,
        }

        response = client.chat.completions.create(**create_kwargs)
        if not response.choices or not response.choices[0].message:
            raise LLMError("Empty response from LLM")
        content = response.choices[0].message.content
        if content is None:
            raise LLMError("Null content in LLM response")

        # Extract token usage if available
        token_usage = _extract_token_usage(response)

        # Record token usage for endpoint profile tracking
        if token_usage:
            tracker = TokenTracker.get()
            if tracker is not None:
                tracker.record_usage(endpoint_profile_name, token_usage)

        # Log full response at DEBUG level (no truncation - full content goes to file)
        logger.debug("%sLLM response: %s", session_prefix, content)
        # Log token usage at DEBUG level if available
        if token_usage:
            usage_parts = [
                f"Cached input: {token_usage['cached_input_tokens']}",
                f"Uncached input: {token_usage['uncached_input_tokens']}",
                f"Output: {token_usage['output_tokens']}",
            ]
            if token_usage.get("reasoning_tokens", 0) > 0:
                usage_parts.append(f"Reasoning: {token_usage['reasoning_tokens']}")
            usage_parts.append(f"Total: {token_usage['total_tokens']}")
            logger.debug("%sLLM token usage - %s", session_prefix, ", ".join(usage_parts))

        # Log preview at INFO (visible on console); full content already at DEBUG above
        response_preview = content[:200] if len(content) > 200 else content
        if token_usage:
            summary_parts = [
                f"Model: {model}",
                f"Response length: {len(content)} chars",
                f"Tokens: cached_input={token_usage['cached_input_tokens']}, "
                f"uncached_input={token_usage['uncached_input_tokens']}, "
                f"output={token_usage['output_tokens']}",
            ]
            if token_usage.get("reasoning_tokens", 0) > 0:
                summary_parts.append(f"reasoning={token_usage['reasoning_tokens']}")
            logger.info("%sLLM call completed - %s", session_prefix, ", ".join(summary_parts))
        else:
            logger.info(
                "%sLLM call completed - Model: %s, Response length: %d chars",
                session_prefix,
                model,
                len(content),
            )
        # Preview to console only (not log file, which already has the full response)
        print(f"Preview: {response_preview}{'...' if len(content) > 200 else ''}", file=sys.stderr)

        return str(content)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        step_config: LLMConfig,
        cancel_check: Callable[[], bool] | None = None,
        **kwargs: Any,
    ) -> str:
        with llm_session_scope() as session_id:
            # Get the appropriate client (may be override client if step_config has different API settings)
            client = self._get_client_for_step(step_config)
            # Merge step_config.kwargs with passed kwargs (passed kwargs take precedence)
            # step_config is already resolved at config initialization time, so all values are filled
            merged_kwargs = _sanitize_openai_create_kwargs(
                model=str(kwargs.get("model") or step_config.model or ""),
                base_url=step_config.base_url,
                kwargs={**step_config.kwargs, **kwargs},
            )

            # Check token limit before making the call
            tracker = TokenTracker.get()
            if tracker is not None:
                tracker.check_limit(step_config.endpoint_profile)

            async def _call() -> str:
                request_kwargs = dict(merged_kwargs)
                return await asyncio.to_thread(
                    self._chat_impl,
                    messages,
                    request_kwargs.pop("model", step_config.model),
                    request_kwargs.pop("temperature", step_config.temperature),
                    client,
                    endpoint_profile_name=step_config.endpoint_profile,
                    **request_kwargs,
                )

            retryer = AsyncRetrying(
                stop=stop_after_attempt(step_config.max_retries + 1),
                wait=wait_exponential(multiplier=2, min=2, max=10),
                retry=retry_if_exception_type((RateLimitError, APITimeoutError, APIConnectionError))
                | retry_if_exception(self._should_retry_server_error),
                reraise=True,
            )

            try:
                async for attempt in retryer:
                    with attempt:
                        raise_if_cancelled(cancel_check)
                        return await _call()
            except OperationCancelledError:
                raise
            except RateLimitError as e:
                raise LLMError(f"[llm_session={session_id}] Rate limit exceeded: {e}") from e
            except APITimeoutError as e:
                raise LLMError(f"[llm_session={session_id}] Request timeout: {e}") from e
            except APIConnectionError as e:
                raise LLMError(f"[llm_session={session_id}] Connection error: {e}") from e
            except APIError as e:
                status_code = getattr(e, "status_code", None)
                if status_code == 401:
                    raise LLMAuthError(f"[llm_session={session_id}] Authentication failed: {e}") from e
                if status_code == 403:
                    raise LLMAuthError(f"[llm_session={session_id}] Forbidden - check API key permissions: {e}") from e
                raise LLMError(f"[llm_session={session_id}] API error (status {status_code}): {e}") from e
            except Exception as e:
                raise LLMError(f"[llm_session={session_id}] Unexpected error: {e}") from e
            raise AssertionError("Unreachable")
