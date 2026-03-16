"""OpenAI GPT Image backend for image editing."""

from __future__ import annotations

import asyncio
import base64
import io
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from context_aware_translation.core.cancellation import raise_if_cancelled
from context_aware_translation.llm.image_backend_base import BaseImageGenerator

if TYPE_CHECKING:
    from context_aware_translation.config import ImageReembeddingConfig


class OpenAIImageGenerator(BaseImageGenerator):
    """Image generator using OpenAI's GPT Image models (gpt-image-1, etc.)."""

    def __init__(self, config: ImageReembeddingConfig) -> None:
        """Initialize OpenAI image generator.

        Args:
            config: Image reembedding configuration
        """
        super().__init__(config)
        self.client = OpenAI(api_key=config.api_key, base_url=config.base_url)

    @staticmethod
    def _extract_token_usage(usage: Any) -> dict[str, int]:
        """Extract token usage from OpenAI-compatible image responses."""
        input_tokens = getattr(usage, "input_tokens", 0) or getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "output_tokens", 0) or getattr(usage, "completion_tokens", 0) or 0

        input_details = getattr(usage, "input_tokens_details", None) or getattr(usage, "prompt_tokens_details", None)
        cached_input = getattr(input_details, "cached_tokens", 0) if input_details is not None else 0
        uncached_input = max(input_tokens - cached_input, 0)

        output_details = getattr(usage, "output_tokens_details", None) or getattr(
            usage, "completion_tokens_details", None
        )
        reasoning_tokens = getattr(output_details, "reasoning_tokens", 0) if output_details is not None else 0

        output_tokens = max(completion_tokens - reasoning_tokens, 0)
        total = getattr(usage, "total_tokens", 0) or (input_tokens + completion_tokens)

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
        """Replace text in an image using mapping pairs via OpenAI's API.

        Args:
            image_bytes: Original image bytes
            mime_type: MIME type (e.g., "image/png")
            text_replacements: Ordered list of (original, translated) pairs
            cancel_check: Optional callable returning True when cancelled

        Returns:
            Modified image bytes (PNG format)

        Raises:
            OperationCancelledError: If cancel_check indicates cancellation
            RateLimitError: If rate limit exceeded after retries
            APITimeoutError: If request times out after retries
            APIConnectionError: If connection fails after retries
        """
        prompt = self._build_prompt(text_replacements)
        self._log_edit_prompt(
            backend="openai",
            mime_type=mime_type,
            text_replacements=text_replacements,
            prompt=prompt,
        )

        async def _call() -> bytes:
            """Inner function for retry logic."""
            image_file = io.BytesIO(image_bytes)
            image_file.name = f"image.{mime_type.split('/')[-1]}"

            response = await asyncio.to_thread(
                self.client.images.edit,
                model=self.config.model or "gpt-image-1",
                image=image_file,
                prompt=prompt,
                n=1,
                response_format="b64_json",
            )
            if not response.data or not response.data[0].b64_json:
                raise ValueError("No image data in OpenAI response")

            # Record token usage if available (gpt-image-1 returns usage)
            usage = getattr(response, "usage", None)
            if usage is not None:
                self._record_token_usage(self._extract_token_usage(usage))

            return base64.b64decode(response.data[0].b64_json)

        retryer = AsyncRetrying(
            stop=stop_after_attempt(self.config.max_retries + 1),
            wait=wait_exponential(multiplier=2, min=2, max=10),
            retry=retry_if_exception_type((RateLimitError, APITimeoutError, APIConnectionError)),
            reraise=True,
        )

        async for attempt in retryer:
            with attempt:
                raise_if_cancelled(cancel_check)
                return await _call()

        # This line should never be reached due to reraise=True,
        # but makes type checkers happy
        raise RuntimeError("Retry loop exited unexpectedly")
