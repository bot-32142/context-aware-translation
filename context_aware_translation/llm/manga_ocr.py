"""Manga OCR: extract readable text from manga/comic pages using vision LLM."""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from context_aware_translation.core.cancellation import OperationCancelledError, raise_if_cancelled
from context_aware_translation.llm.session_trace import llm_session_scope

if TYPE_CHECKING:
    from context_aware_translation.config import OCRConfig
    from context_aware_translation.llm.client import LLMClient

logger = logging.getLogger(__name__)

MANGA_OCR_SYSTEM_PROMPT = """Extract all readable text from this manga/comic page.
Return a JSON object with a single "text" field containing all readable text on the page.
Include dialogue, narration, sound effects, and any other visible text.
Preserve the reading order.
Formatting requirements for the "text" field:
- Output one line per text box/speech bubble/caption/SFX group.
- Keep text from the same box on a single line (merge wrapped lines with spaces).
- Use newline characters only to separate different boxes.
- Do not merge multiple boxes into one line.
- If uncertain whether two fragments are from the same box, keep them on separate lines.
If there is no readable text, return {"text": ""}.
Return ONLY valid JSON."""


def _build_image_data_uri(image_bytes: bytes, mime_type: str) -> str:
    """Encode image bytes as a base64 data URI."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{b64}"


def _clean_json_response(text: str) -> str:
    """Strip markdown code fences from LLM JSON responses."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


async def ocr_manga_image(
    image_bytes: bytes,
    mime_type: str,
    llm_client: LLMClient,
    ocr_config: OCRConfig,
    cancel_check: Callable[[], bool] | None = None,
) -> str:
    """Extract plain text from a manga page using vision LLM.

    Returns plain text string (not structured OCR items).
    """
    with llm_session_scope() as session_id:
        data_uri = _build_image_data_uri(image_bytes, mime_type)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": MANGA_OCR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": "Extract all readable text from this manga page."},
                ],
            },
        ]
        attempts = ocr_config.max_retries + 1
        for attempt in range(attempts):
            raise_if_cancelled(cancel_check)
            try:
                response = await llm_client.chat(
                    messages=messages,
                    step_config=ocr_config,
                    response_format={"type": "json_object"},
                    cancel_check=cancel_check,
                )
                parsed = json.loads(_clean_json_response(response.strip()))
                return str(parsed.get("text", ""))
            except Exception as e:
                if isinstance(e, OperationCancelledError):
                    raise
                if attempt >= attempts - 1:
                    raise Exception(
                        f"[llm_session={session_id}] Manga OCR failed after exhausting all attempts."
                    ) from e
                logger.warning(
                    "[llm_session=%s] Manga OCR attempt %s/%s failed: %s",
                    session_id,
                    attempt + 1,
                    attempts,
                    e,
                )
        raise RuntimeError("Unreachable: Manga OCR retry loop did not return")
