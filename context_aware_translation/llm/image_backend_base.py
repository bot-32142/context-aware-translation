"""Shared base implementation for image generation backends."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, TypeVar

from context_aware_translation.core.cancellation import raise_if_cancelled
from context_aware_translation.llm.token_tracker import TokenTracker

if TYPE_CHECKING:
    from context_aware_translation.config import ImageReembeddingConfig

logger = logging.getLogger(__name__)

T = TypeVar("T")
TextReplacement = tuple[str, str]


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
            "5) Make sure all original text is cleared and all translated text is added.\n"

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
        """Record token usage for the endpoint profile if configured."""
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
        """Execute an async function with exponential backoff retry."""
        for attempt in range(self.config.max_retries + 1):
            try:
                return await func()
            except Exception:
                if attempt == self.config.max_retries:
                    raise
                raise_if_cancelled(cancel_check)
                await asyncio.sleep(base_delay**attempt)
        raise RuntimeError("Retry loop exited unexpectedly")
