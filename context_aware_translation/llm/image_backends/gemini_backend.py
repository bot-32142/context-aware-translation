"""Google Gemini backend for image editing.

Uses the google-genai SDK with Google AI Studio (API key authentication).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

from google import genai
from google.genai import types

from context_aware_translation.llm.image_generator import BaseImageGenerator

if TYPE_CHECKING:
    from context_aware_translation.config import ImageReembeddingConfig


class GeminiImageGenerator(BaseImageGenerator):
    """Image generator using Google's Gemini models.

    Uses the google-genai SDK with per-client configuration (no global state).
    """

    def __init__(self, config: ImageReembeddingConfig) -> None:
        """Initialize Gemini image generator.

        Args:
            config: Image reembedding configuration
        """
        super().__init__(config)
        # Per-instance client - no global state
        # Support custom base_url via http_options.
        # The google-genai SDK appends its own /v1beta/models/... path,
        # so strip any OpenAI-compat or versioned suffixes from the base_url
        # to avoid double-pathing (e.g. /v1beta/openai/v1beta/models/...).
        base_url = self._clean_base_url(config.base_url) if config.base_url else None
        http_opts = types.HttpOptions(base_url=base_url) if base_url else None
        self.client = genai.Client(api_key=config.api_key, http_options=http_opts)
        self.model_name = config.model or "gemini-2.0-flash-exp-image-generation"

    @staticmethod
    def _clean_base_url(base_url: str) -> str:
        """Extract the origin (scheme + host) from a base URL.

        The google-genai SDK appends its own ``/v1beta/models/...`` path,
        so we only need the origin — any path component is discarded.
        """
        from urllib.parse import urlparse

        parsed = urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    async def edit_image(
        self,
        image_bytes: bytes,
        mime_type: str,
        text_replacements: list[tuple[str, str]],
        cancel_check: Callable[[], bool] | None = None,
    ) -> bytes:
        """Replace text in an image using mapping pairs via Gemini's API.

        Args:
            image_bytes: Original image bytes
            mime_type: MIME type (e.g., "image/png")
            text_replacements: Ordered list of (original, translated) pairs

        Returns:
            Modified image bytes (PNG format)

        Raises:
            ValueError: If no image in response
            Exception: Various API errors after retries
        """
        prompt = self._build_prompt(text_replacements)
        self._log_edit_prompt(
            backend="gemini",
            mime_type=mime_type,
            text_replacements=text_replacements,
            prompt=prompt,
        )

        # Create parts for the request
        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        text_part = types.Part.from_text(text=prompt)

        async def _call() -> bytes:
            """Inner function for retry logic."""
            # Use asyncio.to_thread for sync client call
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model_name,
                contents=[image_part, text_part],  # type: ignore[arg-type]
                config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
            )

            # Extract image from response parts
            if response.candidates is None:
                raise ValueError("No candidates in Gemini response")

            candidate = response.candidates[0]
            if candidate.content is None or candidate.content.parts is None:
                raise ValueError("No content in Gemini response")

            # Record token usage if available
            usage_meta = getattr(response, "usage_metadata", None)
            if usage_meta is not None:
                prompt_tokens = getattr(usage_meta, "prompt_token_count", 0) or 0
                cached_tokens = getattr(usage_meta, "cached_content_token_count", 0) or 0
                candidates_tokens = getattr(usage_meta, "candidates_token_count", None)
                if candidates_tokens is None:
                    candidates_tokens = getattr(usage_meta, "response_token_count", 0)
                candidates_tokens = candidates_tokens or 0
                thoughts_tokens = getattr(usage_meta, "thoughts_token_count", 0) or 0
                tool_use_prompt_tokens = getattr(usage_meta, "tool_use_prompt_token_count", 0) or 0
                total = getattr(usage_meta, "total_token_count", 0) or (
                    prompt_tokens + tool_use_prompt_tokens + candidates_tokens + thoughts_tokens
                )

                uncached_input_tokens = max(prompt_tokens - cached_tokens, 0) + tool_use_prompt_tokens
                token_usage = {
                    "total_tokens": total,
                    "cached_input_tokens": cached_tokens,
                    "uncached_input_tokens": uncached_input_tokens,
                    "output_tokens": candidates_tokens,
                }
                if thoughts_tokens > 0:
                    token_usage["reasoning_tokens"] = thoughts_tokens

                # Some Gemini responses include additional internal tokens in total.
                # Reconcile the remainder into reasoning so profile totals stay coherent.
                accounted = (
                    token_usage["cached_input_tokens"]
                    + token_usage["uncached_input_tokens"]
                    + token_usage["output_tokens"]
                    + token_usage.get("reasoning_tokens", 0)
                )
                if total > accounted:
                    token_usage["reasoning_tokens"] = token_usage.get("reasoning_tokens", 0) + (total - accounted)

                self._record_token_usage(token_usage)

            for part in candidate.content.parts:
                if part.inline_data is not None and part.inline_data.data is not None:
                    # SDK already decodes base64 - data is raw bytes
                    return part.inline_data.data

            raise ValueError("No image in Gemini response")

        return await self._retry_with_backoff(_call, cancel_check=cancel_check)
