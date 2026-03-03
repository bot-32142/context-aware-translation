from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from context_aware_translation.config import MangaTranslatorConfig
from context_aware_translation.llm.manga_translator import translate_manga_pages


def _manga_config(max_retries: int = 0) -> MangaTranslatorConfig:
    return MangaTranslatorConfig(
        api_key="k",
        base_url="https://example.invalid/v1",
        model="test-model",
        max_retries=max_retries,
    )


class _MockLLMClient:
    def __init__(self, response: str) -> None:
        self.chat = AsyncMock(return_value=response)


@pytest.mark.asyncio
async def test_translate_manga_single_page_uses_extracted_line_mapping() -> None:
    llm = _MockLLMClient('{"translations":["第一行","第二行"]}')
    result = await translate_manga_pages(
        page_images=[(b"img", "image/png")],
        terms=[("A", "甲", "name")],
        llm_client=llm,
        manga_config=_manga_config(),
        source_language="Japanese",
        target_language="Chinese",
        extracted_texts=["line1\nline2"],
    )

    assert result == ["第一行\n第二行"]
    assert llm.chat.await_count == 1
    sent_messages = llm.chat.await_args.kwargs["messages"]
    user_content = sent_messages[1]["content"]
    assert '"source_lines": [' in user_content[1]["text"]


@pytest.mark.asyncio
async def test_translate_manga_single_page_rejects_line_count_mismatch() -> None:
    llm = _MockLLMClient('{"translations":["only one line"]}')
    with pytest.raises(ValueError, match="line translations"):
        await translate_manga_pages(
            page_images=[(b"img", "image/png")],
            terms=[],
            llm_client=llm,
            manga_config=_manga_config(),
            source_language="Japanese",
            target_language="Chinese",
            extracted_texts=["a\nb"],
        )


@pytest.mark.asyncio
async def test_translate_manga_rejects_multi_page_input() -> None:
    llm = _MockLLMClient('{"translations":["x"]}')
    with pytest.raises(ValueError, match="exactly 1 page"):
        await translate_manga_pages(
            page_images=[(b"img1", "image/png"), (b"img2", "image/png")],
            terms=[],
            llm_client=llm,
            manga_config=_manga_config(),
            source_language="Japanese",
            target_language="Chinese",
            extracted_texts=["line1", "line2"],
        )


@pytest.mark.asyncio
async def test_translate_manga_requires_extracted_texts() -> None:
    llm = _MockLLMClient('{"translations":["x"]}')
    with pytest.raises(ValueError, match="requires extracted_texts"):
        await translate_manga_pages(
            page_images=[(b"img", "image/png")],
            terms=[],
            llm_client=llm,
            manga_config=_manga_config(),
            source_language="Japanese",
            target_language="Chinese",
            extracted_texts=None,
        )
