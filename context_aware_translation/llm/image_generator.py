"""Image generation backend protocol and factory.

Supports multiple backends: OpenAI, Gemini, Qwen.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from context_aware_translation.core.cancellation import raise_if_cancelled

if TYPE_CHECKING:
    from context_aware_translation.config import ImageReembeddingConfig

logger = logging.getLogger(__name__)

T = TypeVar("T")
TextReplacement = tuple[str, str]


def build_text_replacements(original_text: str, translated_text: str) -> list[TextReplacement]:
    """Build replacement pairs from original and translated embedded text.

    Always returns line-by-line pairs. If line counts differ, shorter side is
    padded with empty strings so mapping remains item-by-item.
    """
    if not original_text and not translated_text:
        return []

    normalized_original = original_text.replace("\r\n", "\n").replace("\r", "\n")
    normalized_translated = translated_text.replace("\r\n", "\n").replace("\r", "\n")
    original_lines = normalized_original.split("\n")
    translated_lines = normalized_translated.split("\n")

    total = max(len(original_lines), len(translated_lines))
    replacements: list[TextReplacement] = []
    for i in range(total):
        original_line = original_lines[i] if i < len(original_lines) else ""
        translated_line = translated_lines[i] if i < len(translated_lines) else ""
        replacements.append((original_line, translated_line))

    return replacements


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

    def _build_prompt(self, text_replacements: list[TextReplacement]) -> str:
        """Build the prompt for image text replacement from explicit mappings."""
        payload = [
            {"index": idx + 1, "original": original, "translated": translated}
            for idx, (original, translated) in enumerate(text_replacements)
        ]
        mapping_json = json.dumps(payload, ensure_ascii=False, indent=2)
        return (
            "Edit this image by replacing text according to the mapping below.\n\n"
            "Text replacement mapping (JSON array):\n"
            f"{mapping_json}\n\n"
            "Rules:\n"
            "1) Match each `original` text and replace it with its `translated` text.\n"
            "2) Preserve the original style, layout, and non-text visual content.\n"
            "3) Keep replacement text in the same regions as the original text.\n"
            "4) Do not invent extra text not present in the mapping.\n"
            "Return only the edited image."
        )

    def _log_edit_prompt(
        self,
        *,
        backend: str,
        mime_type: str,
        text_replacements: list[TextReplacement],
        prompt: str,
    ) -> None:
        """Log image edit prompt at DEBUG level for troubleshooting."""
        logger.debug(
            "Image edit request - backend: %s, model: %s, mime_type: %s, replacements: %d, prompt: %s",
            backend,
            self.config.model,
            mime_type,
            len(text_replacements),
            prompt,
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
        text_replacements: list[TextReplacement],
        cancel_check: Callable[[], bool] | None = None,
    ) -> bytes:
        """Replace text in an image using original->translated mappings.

        Args:
            image_bytes: Original image bytes
            mime_type: MIME type (e.g., "image/png")
            text_replacements: Ordered list of (original, translated) pairs
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
