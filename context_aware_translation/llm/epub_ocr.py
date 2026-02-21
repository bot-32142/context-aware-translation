"""EPUB OCR helpers focused on embedded text inside image resources."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from context_aware_translation.core.cancellation import OperationCancelledError, raise_if_cancelled
from context_aware_translation.llm.session_trace import llm_session_scope
from context_aware_translation.utils.llm_json_cleaner import clean_llm_response

if TYPE_CHECKING:
    from context_aware_translation.config import OCRConfig
    from context_aware_translation.llm.client import LLMClient

logger = logging.getLogger(__name__)

EPUB_OCR_SYSTEM_PROMPT = """Read text that is visually embedded INSIDE this image.
Return a JSON object with one field:
- "embedded_text": text inside the image region only

Rules:
- Do not include surrounding body text or captions outside the image.
- Preserve line breaks when they are visually distinct.
- If no readable embedded text exists, return {"embedded_text": ""}.
- Return ONLY valid JSON."""

EPUB_OCR_USER_PROMPT = "Extract only embedded text inside this image."


def _build_image_data_uri(image_bytes: bytes, mime_type: str) -> str:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{b64}"


def _parse_embedded_text_response(response: str) -> str:
    try:
        payload = json.loads(clean_llm_response(response.strip()))
    except json.JSONDecodeError as ex:
        logger.warning("Failed to parse EPUB OCR JSON")
        raise ex

    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object, got {type(payload).__name__}")
    embedded_text = payload.get("embedded_text", "")
    return str(embedded_text) if embedded_text is not None else ""


async def ocr_epub_image(
    image_bytes: bytes,
    mime_type: str,
    llm_client: LLMClient,
    ocr_config: OCRConfig,
    cancel_check: Callable[[], bool] | None = None,
) -> str:
    """Extract embedded text from a single EPUB image."""
    with llm_session_scope() as session_id:
        data_uri = _build_image_data_uri(image_bytes, mime_type)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": EPUB_OCR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": EPUB_OCR_USER_PROMPT},
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
                return _parse_embedded_text_response(response)
            except Exception as e:
                if isinstance(e, OperationCancelledError):
                    raise
                if attempt >= attempts - 1:
                    raise Exception(f"[llm_session={session_id}] EPUB OCR failed after exhausting all attempts.") from e
                logger.warning(
                    "[llm_session=%s] EPUB OCR attempt %d/%d failed: %s",
                    session_id,
                    attempt + 1,
                    attempts,
                    e,
                )
        raise RuntimeError("Unreachable: EPUB OCR retry loop did not return")


async def ocr_epub_images(
    image_files: list[tuple[bytes, str, str]],
    llm_client: LLMClient,
    ocr_config: OCRConfig,
    on_result: Callable[[int, str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    """Process EPUB images and emit embedded text per image."""
    raise_if_cancelled(cancel_check)
    semaphore = asyncio.Semaphore(ocr_config.concurrency)
    total_images = len(image_files)

    async def process_one(index: int, image_bytes: bytes, mime_type: str, filename: str) -> None:
        raise_if_cancelled(cancel_check)
        async with semaphore:
            raise_if_cancelled(cancel_check)
            embedded_text = await ocr_epub_image(
                image_bytes, mime_type, llm_client, ocr_config, cancel_check=cancel_check
            )
            raise_if_cancelled(cancel_check)
            logger.info("EPUB OCR completed for image %d/%d: %s", index + 1, total_images, filename)
            if on_result is not None:
                on_result(index, embedded_text)
            raise_if_cancelled(cancel_check)

    await asyncio.gather(
        *[
            process_one(i, image_bytes, mime_type, file_name)
            for i, (image_bytes, mime_type, file_name) in enumerate(image_files)
        ]
    )
    raise_if_cancelled(cancel_check)
