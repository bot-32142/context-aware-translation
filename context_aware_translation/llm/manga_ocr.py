"""Manga OCR: extract readable text from manga/comic pages using vision LLM."""

from __future__ import annotations

import base64
import io
import json
import logging
import math
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from PIL import Image

from context_aware_translation.core.cancellation import OperationCancelledError, raise_if_cancelled
from context_aware_translation.llm.session_trace import llm_session_scope
from context_aware_translation.utils.symbol_check import symbol_only

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

MANGA_OCR_BBOX_SYSTEM_PROMPT = """You detect text-region bounding boxes on manga pages.

Coordinate rules:
- Use integer PIXEL coordinates (no normalized values, no 0..1000 grids).
- Coordinates are relative to the exact input image.
- x, y: top-left corner of the box.
- width, height: box size in pixels.

Output rules:
- Return ONLY JSON.
- Include image_width and image_height that exactly match the input image dimensions.
- Return all regions in the same order as provided by the user message.

Required schema:
{
  "image_width": 0,
  "image_height": 0,
  "regions": [
    {"x": 0, "y": 0, "width": 0, "height": 0, "text": ""}
  ]
}"""


def normalize_manga_text_lines(text_or_lines: str | Sequence[str]) -> list[str]:
    """Normalize manga text into non-empty, non-symbol lines."""
    raw_lines: list[str] = []
    if isinstance(text_or_lines, str):
        raw_lines.extend(text_or_lines.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
    else:
        for line in text_or_lines:
            raw_lines.extend(str(line).replace("\r\n", "\n").replace("\r", "\n").split("\n"))

    lines: list[str] = []
    for raw_line in raw_lines:
        line = raw_line.strip()
        if not line:
            continue
        if symbol_only(line):
            continue
        lines.append(line)
    return lines


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


def _parse_json_object(raw: str) -> dict[str, Any]:
    parsed = json.loads(_clean_json_response(raw.strip()))
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected JSON object, got {type(parsed).__name__}")
    return parsed


def _parse_int_pixel(value: Any, *, name: str) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(numeric):
        raise ValueError(f"{name} must be finite")
    if not numeric.is_integer():
        raise ValueError(f"{name} must be an integer pixel value")
    return int(numeric)


def _extract_normalized_regions_from_pixel_payload(
    payload: dict[str, Any],
    *,
    expected_lines: Sequence[str],
    image_w: int,
    image_h: int,
) -> list[dict[str, Any]]:
    declared_w = _parse_int_pixel(payload.get("image_width"), name="image_width")
    declared_h = _parse_int_pixel(payload.get("image_height"), name="image_height")
    if declared_w != image_w or declared_h != image_h:
        raise ValueError(
            f"Declared image dimensions mismatch: got {declared_w}x{declared_h}, expected {image_w}x{image_h}"
        )

    regions = payload.get("regions")
    if not isinstance(regions, list):
        raise ValueError("Missing or invalid 'regions' field")
    if len(regions) != len(expected_lines):
        raise ValueError(f"Expected {len(expected_lines)} regions, got {len(regions)}")

    normalized_regions: list[dict[str, Any]] = []
    for idx, region in enumerate(regions):
        if not isinstance(region, dict):
            raise ValueError(f"Region at index {idx} is not an object")
        for key in ("x", "y", "width", "height"):
            if key not in region:
                raise ValueError(f"Region at index {idx} missing key '{key}'")
        x = _parse_int_pixel(region["x"], name=f"regions[{idx}].x")
        y = _parse_int_pixel(region["y"], name=f"regions[{idx}].y")
        width = _parse_int_pixel(region["width"], name=f"regions[{idx}].width")
        height = _parse_int_pixel(region["height"], name=f"regions[{idx}].height")

        if width <= 0 or height <= 0:
            raise ValueError("Region width/height must be positive")
        if x < 0 or y < 0:
            raise ValueError("Region x/y must be non-negative")
        if x + width > image_w or y + height > image_h:
            raise ValueError("Region exceeds image bounds")

        normalized_regions.append(
            {
                "x": x / image_w,
                "y": y / image_h,
                "width": width / image_w,
                "height": height / image_h,
                "text": expected_lines[idx],
            }
        )
    return normalized_regions


async def _ocr_manga_image_text_lines(
    image_bytes: bytes,
    mime_type: str,
    llm_client: LLMClient,
    ocr_config: OCRConfig,
    *,
    session_id: str,
    cancel_check: Callable[[], bool] | None = None,
) -> list[str]:
    data_uri = _build_image_data_uri(image_bytes, mime_type)
    attempts = ocr_config.max_retries + 1
    for attempt in range(attempts):
        raise_if_cancelled(cancel_check)
        try:
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
            response = await llm_client.chat(
                messages=messages,
                step_config=ocr_config,
                response_format={"type": "json_object"},
                cancel_check=cancel_check,
            )
            payload = _parse_json_object(response)
            return normalize_manga_text_lines(str(payload.get("text", "")))
        except Exception as exc:
            if isinstance(exc, OperationCancelledError):
                raise
            if attempt >= attempts - 1:
                raise Exception(f"[llm_session={session_id}] Manga OCR failed after exhausting all attempts.") from exc
            logger.warning(
                "[llm_session=%s] Manga OCR attempt %s/%s failed: %s",
                session_id,
                attempt + 1,
                attempts,
                exc,
            )
    raise RuntimeError("Unreachable: Manga OCR retry loop did not return")


async def _detect_manga_text_regions(
    image_bytes: bytes,
    mime_type: str,
    llm_client: LLMClient,
    ocr_config: OCRConfig,
    *,
    normalized_lines: Sequence[str],
    session_id: str,
    cancel_check: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    with Image.open(io.BytesIO(image_bytes)) as image:
        image_w, image_h = image.size
    if image_w <= 0 or image_h <= 0:
        raise ValueError("Invalid image dimensions for manga OCR")
    if not normalized_lines:
        return []

    data_uri = _build_image_data_uri(image_bytes, mime_type)
    text_lines_payload = "\n".join(normalized_lines)
    bbox_attempts = max(ocr_config.max_retries + 1, 2)
    bbox_last_error: Exception | None = None

    for bbox_attempt in range(bbox_attempts):
        raise_if_cancelled(cancel_check)
        retry_note = ""
        if bbox_attempt > 0 and bbox_last_error is not None:
            retry_note = f"""

Previous response was invalid: {bbox_last_error}
Please correct and regenerate."""
        bbox_user_prompt = f"""Detected text lines in reading order:
{text_lines_payload}

Image frame:
- image_width: {image_w}
- image_height: {image_h}

Return EXACTLY {len(normalized_lines)} regions in the same order.{retry_note}"""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": MANGA_OCR_BBOX_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": bbox_user_prompt},
                ],
            },
        ]
        response = await llm_client.chat(
            messages=messages,
            step_config=ocr_config,
            response_format={"type": "json_object"},
            cancel_check=cancel_check,
        )
        try:
            payload = _parse_json_object(response)
            return _extract_normalized_regions_from_pixel_payload(
                payload,
                expected_lines=normalized_lines,
                image_w=image_w,
                image_h=image_h,
            )
        except Exception as exc:
            bbox_last_error = exc
            if bbox_attempt >= bbox_attempts - 1:
                raise
            logger.warning(
                "[llm_session=%s] Manga OCR bbox attempt %s/%s invalid output: %s",
                session_id,
                bbox_attempt + 1,
                bbox_attempts,
                exc,
            )

    raise RuntimeError("Unreachable: bbox retry loop did not produce regions")


async def detect_manga_text_regions(
    image_bytes: bytes,
    mime_type: str,
    llm_client: LLMClient,
    ocr_config: OCRConfig,
    text_lines: Sequence[str],
    cancel_check: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    """Detect normalized manga text regions for already-extracted OCR lines."""
    normalized_lines = normalize_manga_text_lines(text_lines)
    if not normalized_lines:
        return []
    with llm_session_scope() as session_id:
        return await _detect_manga_text_regions(
            image_bytes=image_bytes,
            mime_type=mime_type,
            llm_client=llm_client,
            ocr_config=ocr_config,
            normalized_lines=normalized_lines,
            session_id=session_id,
            cancel_check=cancel_check,
        )


async def ocr_manga_image_with_regions(
    image_bytes: bytes,
    mime_type: str,
    llm_client: LLMClient,
    ocr_config: OCRConfig,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Extract manga OCR text and detect normalized text-region bboxes."""
    with llm_session_scope() as session_id:
        text_lines = await _ocr_manga_image_text_lines(
            image_bytes=image_bytes,
            mime_type=mime_type,
            llm_client=llm_client,
            ocr_config=ocr_config,
            session_id=session_id,
            cancel_check=cancel_check,
        )
        if not text_lines:
            return {"text": "", "regions": []}
        regions = await _detect_manga_text_regions(
            image_bytes=image_bytes,
            mime_type=mime_type,
            llm_client=llm_client,
            ocr_config=ocr_config,
            normalized_lines=text_lines,
            session_id=session_id,
            cancel_check=cancel_check,
        )
        return {"text": "\n".join(text_lines), "regions": regions}


async def ocr_manga_image(
    image_bytes: bytes,
    mime_type: str,
    llm_client: LLMClient,
    ocr_config: OCRConfig,
    cancel_check: Callable[[], bool] | None = None,
) -> str:
    """Extract plain text from a manga page using a single OCR pass."""
    with llm_session_scope() as session_id:
        text_lines = await _ocr_manga_image_text_lines(
            image_bytes=image_bytes,
            mime_type=mime_type,
            llm_client=llm_client,
            ocr_config=ocr_config,
            session_id=session_id,
            cancel_check=cancel_check,
        )
        return "\n".join(text_lines)
