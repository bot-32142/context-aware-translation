from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from context_aware_translation.config import OCRConfig
from context_aware_translation.core.cancellation import OperationCancelledError, raise_if_cancelled
from context_aware_translation.documents.content.ocr_content import parse_ocr_json
from context_aware_translation.llm.session_trace import llm_session_scope
from context_aware_translation.utils.llm_json_cleaner import clean_llm_response

if TYPE_CHECKING:
    from context_aware_translation.llm.client import LLMClient

logger = logging.getLogger(__name__)


OCR_SYSTEM_PROMPT = """Extract content from scanned book pages. Return a JSON array of page objects.

## Page Types
- "content": Normal page
- "cover": Book cover (return empty content immediately. DO NOT bother reading anything inside the cover.)
- "blank": Empty page (return empty content)

## Content Types
- "chapter", "section", "subsection": Headings by level
- "paragraph": Main body text (NOT text inside images)
- "list": Use "items" array
- "table": Markdown table in "text", optional "caption"
- "quote": Block quotes
- "image": bbox (normalized 0-1: {x, y, width, height}), embedded_text (text INSIDE image only), caption (text OUTSIDE image only). Never mix the two fields.
  **Image grouping rule:**
  - Treat neighboring images as a single bbox to best perserve orignal page layout whenever possible, unless images are separated by other content.
  - e.g. if the whole page only consists of images without caption or other elements, based on this rule, you should just return a single bbox for the whole page.
  - If a text is inside the bbox of your image, it should be included in the embedded text section, and it must not belong to any other content type.
## Footnotes
Replace footnote markers (¹²³, *†‡) with inline footnotes: `^[definition]`
Example: "Results were significant¹" → "Results were significant^[p<0.05]"

## Formatting
Use markdown where appropriate. Escape special characters when not intending formatting.
- Math: `$x^2$` or `$$\\int f(x)dx$$`
- Superscript: `^text^` | Subscript: `~text~` | Strikethrough: `~~text~~`
- **Avoid** layout commands (\\hfill, \\vspace, \\centering) — they break export

## Rules
- IGNORE: page numbers, headers, footers, printer marks, table of contents
- Cross-page content: set "continues_to_next": true on the LAST content item, or "continues_from_previous": true on the FIRST content item. These flags go on the content items, NOT on the page object.
- Output only visible content. Never include tokenizer artifacts.

## Example
[{"page_type": "content", "content": [
  {"type": "paragraph", "text": "The sun^[First observed in 1923] cast shadows..."},
  {"type": "image", "bbox": {"x": 0.1, "y": 0.4, "width": 0.8, "height": 0.3}, "embedded_text": "Text in image", "caption": "Figure 1"},
  {"type": "paragraph", "text": "This paragraph continues on the next page...", "continues_to_next": true}
]}]

Return ONLY valid JSON array."""

OCR_USER_PROMPT = "Extract content from this scanned page."


def _image_to_base64_data_uri(image_bytes: bytes, mime_type: str) -> str:
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{b64}"


def _parse_ocr_response(response: str, source_image_bytes: bytes | None) -> list[dict[str, Any]]:
    text = response.strip()

    try:
        parsed: Any = json.loads(clean_llm_response(text))
    except json.JSONDecodeError as ex:
        logger.warning("Failed to parse OCR JSON")
        raise ex

    # Normalize to list format
    if isinstance(parsed, dict):
        # Legacy single-object format - wrap in list
        parsed = [parsed]
    elif isinstance(parsed, list):
        if len(parsed) == 0:
            raise ValueError("OCR returned empty array")
    else:
        raise ValueError(f"Expected JSON array or object, got {type(parsed).__name__}")

    # Validate each page object
    results: list[dict[str, Any]] = []
    for i, page_obj in enumerate(parsed):
        if not isinstance(page_obj, dict):
            raise ValueError(f"Expected page object at index {i}, got {type(page_obj).__name__}")
        # Validate structure (raises ValueError if invalid)
        parse_ocr_json(page_obj, source_image_bytes)
        results.append(page_obj)

    return results


async def ocr_image(
    image_bytes: bytes,
    mime_type: str,
    llm_client: LLMClient,
    ocr_config: OCRConfig,
    cancel_check: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    """Process a single image with OCR, returning one or more page objects.

    Args:
        image_bytes: Raw image bytes
        mime_type: MIME type of the image
        llm_client: LLM client for API calls
        ocr_config: OCR configuration

    Returns:
        List of page objects (usually one, but can be multiple for two-page spreads)
    """
    with llm_session_scope() as session_id:
        data_uri = _image_to_base64_data_uri(image_bytes, mime_type)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": OCR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": OCR_USER_PROMPT},
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

                return _parse_ocr_response(response, image_bytes)
            except Exception as e:
                if isinstance(e, OperationCancelledError):
                    raise
                if attempt >= attempts - 1:
                    raise Exception(f"[llm_session={session_id}] OCR failed after exhausting all attempts.") from e
                logger.warning(
                    "[llm_session=%s] OCR attempt %s/%s failed: %s",
                    session_id,
                    attempt + 1,
                    attempts,
                    e,
                )

        raise RuntimeError("Unreachable: OCR retry loop did not return")


async def ocr_images(
    image_files: list[tuple[bytes, str, str]],
    llm_client: LLMClient,
    ocr_config: OCRConfig,
    on_result: Callable[[int, list[dict[str, Any]]], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    """Process multiple images with OCR concurrently.

    Args:
        image_files: List of tuples containing (image_bytes, mime_type, filename)
        llm_client: LLM client for OCR processing
        ocr_config: OCR configuration (includes concurrency setting)
        on_result: Optional callback invoked after each image completes.
                   Receives (index, ocr_pages) where index is 0-based image index
                   and ocr_pages is a list of page objects (usually one, but can be
                   multiple for two-page spreads). Enables incremental persistence.
    """
    raise_if_cancelled(cancel_check)
    total_images = len(image_files)
    semaphore = asyncio.Semaphore(ocr_config.concurrency)

    async def process_image(index: int, img_bytes: bytes, mime_type: str, filename: str) -> None:
        raise_if_cancelled(cancel_check)
        async with semaphore:
            raise_if_cancelled(cancel_check)
            ocr_pages = await ocr_image(
                img_bytes,
                mime_type,
                llm_client,
                ocr_config,
                cancel_check=cancel_check,
            )
            raise_if_cancelled(cancel_check)
            page_types = ", ".join(p.get("page_type", "unknown") for p in ocr_pages)
            logger.info(
                f"OCR completed for image {index + 1}/{total_images}: {filename} ({len(ocr_pages)} page(s): {page_types})"
            )
            if on_result is not None:
                on_result(index, ocr_pages)
            raise_if_cancelled(cancel_check)

    await asyncio.gather(*[process_image(i, img, mime, fname) for i, (img, mime, fname) in enumerate(image_files)])
    raise_if_cancelled(cancel_check)
