"""Alibaba Qwen backend for image editing."""

from __future__ import annotations

import base64
from collections.abc import Callable
from typing import TYPE_CHECKING

import httpx

from context_aware_translation.llm.image_generator import BaseImageGenerator

if TYPE_CHECKING:
    from context_aware_translation.config import ImageReembeddingConfig


def _coerce_int(value: object) -> int:
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


class QwenImageGenerator(BaseImageGenerator):
    """Image generator using Alibaba's Qwen models via DashScope API."""

    # Regional endpoints
    ENDPOINTS = {
        "intl": "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        "cn": "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
    }

    def __init__(self, config: ImageReembeddingConfig) -> None:
        """Initialize Qwen image generator.

        Args:
            config: Image reembedding configuration
        """
        super().__init__(config)
        # Use base_url to select region, default to intl
        self.endpoint = config.base_url or self.ENDPOINTS["intl"]
        # Reuse client for efficiency under concurrent requests
        self._client: httpx.AsyncClient | None = None
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        }

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy-initialize and reuse httpx client.

        Returns:
            Shared httpx.AsyncClient instance
        """
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.config.timeout)
        return self._client

    @staticmethod
    def _extract_token_usage(usage: dict[str, object]) -> dict[str, int]:
        """Extract token usage from Qwen/OpenAI-compatible payloads."""
        input_tokens = _coerce_int(usage.get("input_tokens", usage.get("prompt_tokens", 0)))
        completion_tokens = _coerce_int(usage.get("output_tokens", usage.get("completion_tokens", 0)))

        input_details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details")
        cached_input = 0
        if isinstance(input_details, dict):
            cached_input = _coerce_int(input_details.get("cached_tokens", 0))
        uncached_input = max(input_tokens - cached_input, 0)

        output_details = usage.get("output_tokens_details") or usage.get("completion_tokens_details")
        reasoning_tokens = 0
        if isinstance(output_details, dict):
            reasoning_tokens = _coerce_int(output_details.get("reasoning_tokens", 0))

        output_tokens = max(completion_tokens - reasoning_tokens, 0)
        total = _coerce_int(usage.get("total_tokens", 0)) or (input_tokens + completion_tokens)

        accounted = cached_input + uncached_input + output_tokens + reasoning_tokens
        if total > accounted:
            reasoning_tokens += total - accounted

        token_usage = {
            "total_tokens": total,
            "cached_input_tokens": cached_input,
            "uncached_input_tokens": uncached_input,
            "output_tokens": output_tokens,
        }
        if reasoning_tokens > 0:
            token_usage["reasoning_tokens"] = reasoning_tokens
        return token_usage

    async def edit_image(
        self,
        image_bytes: bytes,
        mime_type: str,
        text_replacements: list[tuple[str, str]],
        cancel_check: Callable[[], bool] | None = None,
    ) -> bytes:
        """Replace text in an image using mapping pairs via Qwen's API.

        Args:
            image_bytes: Original image bytes
            mime_type: MIME type (e.g., "image/png")
            text_replacements: Ordered list of (original, translated) pairs

        Returns:
            Modified image bytes (PNG format)

        Raises:
            httpx.HTTPStatusError: If API returns error status after retries
            Exception: Various API errors after retries
        """
        prompt = self._build_prompt(text_replacements)
        self._log_edit_prompt(
            backend="qwen",
            mime_type=mime_type,
            text_replacements=text_replacements,
            prompt=prompt,
        )

        # Encode image as base64 data URI
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        data_uri = f"data:{mime_type};base64,{b64_image}"

        payload = {
            "model": self.config.model or "qwen-image-edit-max",
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"image": data_uri},
                            {"text": prompt},
                        ],
                    }
                ]
            },
            "parameters": {
                "n": 1,
            },
        }

        async def _call() -> bytes:
            """Inner function for retry logic."""
            client = await self._get_client()
            response = await client.post(self.endpoint, json=payload, headers=self._headers)
            response.raise_for_status()
            data = response.json()

            # Record token usage if available
            usage = data.get("usage")
            if isinstance(usage, dict):
                self._record_token_usage(self._extract_token_usage(usage))

            # Extract image URL from response
            image_url = data["output"]["choices"][0]["message"]["content"][0]["image"]

            # Download image (URL expires in 24h)
            img_response = await client.get(image_url)
            img_response.raise_for_status()
            return img_response.content

        return await self._retry_with_backoff(_call, cancel_check=cancel_check)
