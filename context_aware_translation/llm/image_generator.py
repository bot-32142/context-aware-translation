"""Image generation backend protocol and factory.

Supports multiple backends: OpenAI, Gemini, Qwen.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from context_aware_translation.core.cancellation import raise_if_cancelled

if TYPE_CHECKING:
    from context_aware_translation.config import ImageReembeddingConfig

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ImageBackend(str, Enum):
    """Supported image generation backends."""

    OPENAI = "openai"
    GEMINI = "gemini"
    QWEN = "qwen"


class BaseImageGenerator:
    """Base class with shared implementation for image generators."""

    def __init__(self, config: ImageReembeddingConfig) -> None:
        """Initialize with config.

        Args:
            config: Image reembedding configuration
        """
        self.config = config

    def _build_prompt(self, translated_text: str) -> str:
        """Build the prompt for image text replacement.

        Args:
            translated_text: The translated text to embed in the image

        Returns:
            Formatted prompt string for the image editing API
        """
        return (
            f"Edit this image to replace the text.\n"
            f"New text: {translated_text}\n"
            f"Preserve the original style and adjust accordingly. "
            f"Return the edited image."
        )

    def _record_token_usage(self, token_usage: dict[str, Any]) -> None:
        """Record token usage for the endpoint profile if configured.

        Args:
            token_usage: Dict with keys like total_tokens, cached_input_tokens,
                uncached_input_tokens, output_tokens, reasoning_tokens.
        """
        from context_aware_translation.llm.token_tracker import TokenTracker

        tracker = TokenTracker.get()
        if tracker is not None:
            tracker.check_limit(self.config.endpoint_profile)
            tracker.record_usage(self.config.endpoint_profile, token_usage)

    async def _retry_with_backoff(
        self,
        func: Callable[[], Awaitable[T]],
        base_delay: float = 2.0,
        cancel_check: Callable[[], bool] | None = None,
    ) -> T:
        """Execute an async function with exponential backoff retry.

        Args:
            func: Async function to execute
            base_delay: Base delay multiplier for exponential backoff
            cancel_check: Optional callable returning True when cancelled

        Returns:
            Result from the function

        Raises:
            OperationCancelledError: If cancel_check indicates cancellation
            Exception: The last exception if all retries fail
        """
        for attempt in range(self.config.max_retries + 1):
            try:
                return await func()
            except Exception:
                if attempt == self.config.max_retries:
                    raise
                raise_if_cancelled(cancel_check)
                await asyncio.sleep(base_delay**attempt)
        raise RuntimeError("Retry loop exited unexpectedly")


class ImageGenerator(Protocol):
    """Protocol for image generation backends."""

    async def edit_image(
        self,
        image_bytes: bytes,
        mime_type: str,
        translated_text: str,
        cancel_check: Callable[[], bool] | None = None,
    ) -> bytes:
        """Replace text in an image with translated text.

        Args:
            image_bytes: Original image bytes
            mime_type: MIME type (e.g., "image/png")
            translated_text: Translated text to embed
            cancel_check: Optional callable returning True when cancelled

        Returns:
            Modified image bytes (PNG format)
        """
        ...


def create_image_generator(config: ImageReembeddingConfig) -> ImageGenerator:
    """Factory to create the appropriate image generator backend.

    Args:
        config: Image reembedding configuration

    Returns:
        ImageGenerator implementation based on config.backend

    Raises:
        ValueError: If backend is not recognized
    """
    backend = ImageBackend(config.backend)

    if backend == ImageBackend.OPENAI:
        from context_aware_translation.llm.image_backends.openai_backend import (
            OpenAIImageGenerator,
        )

        return OpenAIImageGenerator(config)
    elif backend == ImageBackend.GEMINI:
        from context_aware_translation.llm.image_backends.gemini_backend import (
            GeminiImageGenerator,
        )

        return GeminiImageGenerator(config)
    elif backend == ImageBackend.QWEN:
        from context_aware_translation.llm.image_backends.qwen_backend import (
            QwenImageGenerator,
        )

        return QwenImageGenerator(config)
    else:
        raise ValueError(f"Unknown image backend: {config.backend}")
