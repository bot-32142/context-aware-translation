from __future__ import annotations

import io
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from context_aware_translation.config import OCRConfig
from context_aware_translation.llm.epub_ocr import ocr_epub_image
from context_aware_translation.llm.manga_ocr import (
    MANGA_OCR_SYSTEM_PROMPT,
    ocr_manga_image,
    ocr_manga_image_with_regions,
)
from context_aware_translation.llm.ocr import ocr_image


class _MockLLMClient:
    def __init__(self, response: str | list[str]) -> None:
        if isinstance(response, list):
            self.chat = AsyncMock(side_effect=response)
        else:
            self.chat = AsyncMock(return_value=response)


def _png_bytes(width: int, height: int) -> bytes:
    img = Image.new("RGB", (width, height), "white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_manga_ocr_prompt_enforces_one_line_per_text_box_output():
    assert "one line per text box" in MANGA_OCR_SYSTEM_PROMPT
    assert "same box on a single line" in MANGA_OCR_SYSTEM_PROMPT
    assert "Do not merge multiple boxes into one line" in MANGA_OCR_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_ocr_image_runs_once_when_max_retries_is_zero():
    llm_client = _MockLLMClient('{"page_type":"content","content":[]}')
    ocr_config = OCRConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        max_retries=0,
    )

    result = await ocr_image(b"fake-image-bytes", "image/png", llm_client, ocr_config)

    assert llm_client.chat.await_count == 1
    assert len(result) == 1
    assert result[0]["page_type"] == "content"


@pytest.mark.asyncio
async def test_ocr_manga_image_runs_two_passes_when_max_retries_is_zero():
    image_bytes = _png_bytes(100, 100)
    llm_client = _MockLLMClient(
        [
            '{"text":"hello"}',
            '{"image_width":100,"image_height":100,"regions":[{"x":10,"y":10,"width":30,"height":20,"text":"hello"}]}',
        ]
    )
    ocr_config = OCRConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        max_retries=0,
    )

    result = await ocr_manga_image(image_bytes, "image/png", llm_client, ocr_config)

    assert llm_client.chat.await_count == 2
    assert result == "hello"


@pytest.mark.asyncio
async def test_ocr_manga_image_with_regions_filters_symbol_only_lines() -> None:
    image_bytes = _png_bytes(100, 100)
    llm_client = _MockLLMClient(
        [
            '{"text":"line1\\n!!!\\nline2"}',
            '{"image_width":100,"image_height":100,"regions":['
            '{"x":5,"y":10,"width":20,"height":10,"text":"line1"},'
            '{"x":10,"y":35,"width":25,"height":15,"text":"line2"}'
            "]}",
        ]
    )
    ocr_config = OCRConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        max_retries=0,
    )

    payload = await ocr_manga_image_with_regions(image_bytes, "image/png", llm_client, ocr_config)

    assert payload["text"] == "line1\nline2"
    assert len(payload["regions"]) == 2


@pytest.mark.asyncio
async def test_ocr_manga_image_with_regions_retries_bbox_on_non_normalized_coordinates() -> None:
    image_bytes = _png_bytes(100, 100)
    llm_client = _MockLLMClient(
        [
            '{"text":"line1"}',
            '{"image_width":100,"image_height":100,"regions":[{"x":0.10,"y":20,"width":30,"height":40,"text":"line1"}]}',
            '{"image_width":100,"image_height":100,"regions":[{"x":10,"y":20,"width":30,"height":40,"text":"line1"}]}',
        ]
    )
    ocr_config = OCRConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        max_retries=0,
    )

    payload = await ocr_manga_image_with_regions(image_bytes, "image/png", llm_client, ocr_config)

    assert llm_client.chat.await_count == 3
    assert payload["text"] == "line1"
    assert payload["regions"][0]["x"] == pytest.approx(0.10)
    third_call_messages = llm_client.chat.await_args_list[2].kwargs["messages"]
    third_call_user_prompt = third_call_messages[1]["content"][1]["text"]
    assert "Previous response was invalid" in third_call_user_prompt


@pytest.mark.asyncio
async def test_ocr_manga_image_with_regions_strips_newlines_in_region_text() -> None:
    image_bytes = _png_bytes(100, 100)
    llm_client = _MockLLMClient(
        [
            '{"text":"line1"}',
            '{"image_width":100,"image_height":100,"regions":[{"x":10,"y":10,"width":30,"height":20,"text":"A\\nB"}]}',
        ]
    )
    ocr_config = OCRConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        max_retries=0,
    )

    payload = await ocr_manga_image_with_regions(image_bytes, "image/png", llm_client, ocr_config)

    assert payload["text"] == "AB"
    assert payload["regions"][0]["text"] == "AB"


@pytest.mark.asyncio
async def test_ocr_epub_image_runs_once_when_max_retries_is_zero():
    llm_client = _MockLLMClient('{"embedded_text":"inside image"}')
    ocr_config = OCRConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        max_retries=0,
    )

    result = await ocr_epub_image(b"fake-image-bytes", "image/png", llm_client, ocr_config)

    assert llm_client.chat.await_count == 1
    assert result == "inside image"
