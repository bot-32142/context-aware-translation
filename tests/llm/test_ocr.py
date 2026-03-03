from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from context_aware_translation.config import OCRConfig
from context_aware_translation.llm.epub_ocr import ocr_epub_image
from context_aware_translation.llm.manga_ocr import MANGA_OCR_SYSTEM_PROMPT, ocr_manga_image
from context_aware_translation.llm.ocr import ocr_image


class _MockLLMClient:
    def __init__(self, response: str) -> None:
        self.chat = AsyncMock(return_value=response)


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
async def test_ocr_manga_image_runs_once_when_max_retries_is_zero():
    llm_client = _MockLLMClient('{"text":"hello"}')
    ocr_config = OCRConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        max_retries=0,
    )

    result = await ocr_manga_image(b"fake-image-bytes", "image/png", llm_client, ocr_config)

    assert llm_client.chat.await_count == 1
    assert result == "hello"


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
