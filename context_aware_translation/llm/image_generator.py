"""Image generation backend protocol and factory.

Supports multiple backends: OpenAI, Gemini, Qwen.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from context_aware_translation.llm.image_backend_base import BaseImageGenerator, TextReplacement

if TYPE_CHECKING:
    from context_aware_translation.config import ImageReembeddingConfig


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
        from context_aware_translation.llm.image_backends import openai_backend

        return openai_backend.OpenAIImageGenerator(config)
    if backend == ImageBackend.GEMINI:
        from context_aware_translation.llm.image_backends import gemini_backend

        return gemini_backend.GeminiImageGenerator(config)
    if backend == ImageBackend.QWEN:
        from context_aware_translation.llm.image_backends import qwen_backend

        return qwen_backend.QwenImageGenerator(config)
    raise ValueError(f"Unknown image backend: {config.backend}")


__all__ = [
    "BaseImageGenerator",
    "ImageBackend",
    "ImageGenerator",
    "build_text_replacements",
    "create_image_generator",
]
