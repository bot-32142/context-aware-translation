from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_aware_translation.config import Config, PolishConfig
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.llm.translator import (
    postprocess_translated_blocks,
    preprocess_chunk_text,
    translate_chunk,
)
from context_aware_translation.utils.compression_marker import COMPRESSED_LINE_SENTINEL


def _make_term(key: str = "爱丽丝") -> tuple[str, str, str]:
    """Create a term tuple (name, translated_name, description)."""
    return (key, "Alice", "desc")


def _indexed_text_entries(texts: list[str]) -> list[dict[str, int | str]]:
    return [{"id": idx, "文本": text} for idx, text in enumerate(texts)]


def _translation_response(texts: list[str]) -> str:
    return json.dumps({"翻译文本": _indexed_text_entries(texts)}, ensure_ascii=False)


def test_preprocess_and_postprocess_preserve_special_lines():
    chunk_text = "Line1\nLine2\n\n---\n\nLine3\n***\n\nLine4"

    blocks, separators = preprocess_chunk_text(chunk_text)

    # With the simplified _is_empty_line (only whitespace/empty = empty),
    # --- and *** are now content blocks, only blank lines are separators
    assert blocks == ["Line1", "Line2", "---", "Line3", "***", "Line4"]
    assert separators == [[], [], [""], [""], [], [""], []]

    translated_blocks = ["T1", "T2", "---", "T3", "***", "T4"]
    reconstructed = postprocess_translated_blocks(translated_blocks, separators)

    assert reconstructed == "T1\nT2\n\n---\n\nT3\n***\n\nT4"


def test_preprocess_treats_cjk_punctuation_lines_as_content():
    """CJK punctuation-only lines (silence dialogue, reactions, dividers) are content blocks."""
    chunk_text = "Line1\n「…………」\n\n◇\n！？\nLine2"

    blocks, separators = preprocess_chunk_text(chunk_text)

    # All non-ASCII punctuation lines should be blocks, not separators
    assert blocks == ["Line1", "「…………」", "◇", "！？", "Line2"]
    assert separators == [[], [], [""], [], [], []]

    translated_blocks = ["T1", "「…………」", "◇", "！？", "T2"]
    reconstructed = postprocess_translated_blocks(translated_blocks, separators)

    assert reconstructed == "T1\n「…………」\n\n◇\n！？\nT2"


def test_preprocess_treats_ascii_symbols_as_content():
    """ASCII symbol lines (---, ***, ===) are now content blocks, not separators."""
    chunk_text = "Line1\n---\n***\n===\nLine2"

    blocks, separators = preprocess_chunk_text(chunk_text)

    assert blocks == ["Line1", "---", "***", "===", "Line2"]
    assert separators == [[], [], [], [], [], []]


def test_postprocess_marks_compressed_placeholders_but_keeps_true_empty_lines():
    translated_blocks = ["A", "", "C"]
    separators = [[""], [], ["", "---", ""], []]

    reconstructed = postprocess_translated_blocks(translated_blocks, separators)

    assert reconstructed == f"\nA\n{COMPRESSED_LINE_SENTINEL}\n\n---\n\nC"


@pytest.mark.asyncio
async def test_translate_chunk_uses_block_lists_and_reconstructs(temp_config: Config):
    chunks = ["A\n\n---\n\nB"]
    terms = [_make_term()]

    llm_client = MagicMock(spec=LLMClient)

    async def mock_chat(*_args, **_kwargs):
        return _translation_response(["A translated", "---", "B translated"])

    llm_client.chat = AsyncMock(side_effect=mock_chat)

    result = await translate_chunk(
        chunks=chunks,
        terms=terms,
        llm_client=llm_client,
        translator_config=temp_config.translator_config,
        source_language="日语",
        target_language=temp_config.translation_target_language,
    )

    assert result == ["A translated\n\n---\n\nB translated"]

    # First call is the translation (with 原文); polish may follow
    translate_call = llm_client.chat.call_args_list[0]
    messages = translate_call[0][0]
    user_payload = json.loads(messages[1]["content"])

    assert user_payload["原文"] == [
        {"id": 0, "文本": "A"},
        {"id": 1, "文本": "---"},
        {"id": 2, "文本": "B"},
    ]
    assert isinstance(user_payload["原文"], list)
    assert translate_call[1]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_translate_chunk_retries_when_inline_markers_are_removed(temp_config: Config):
    chunks = ["This is ⟪a:0⟫link⟪/a:0⟫ text"]
    terms = [_make_term()]
    assert temp_config.translator_config is not None
    temp_config.translator_config.enable_polish = False
    temp_config.translator_config.max_retries = 0

    llm_client = MagicMock(spec=LLMClient)
    llm_client.chat = AsyncMock(
        side_effect=[
            _translation_response(["这是斜体文本"]),
            _translation_response(["这是 ⟪a:0⟫链接⟪/a:0⟫ 文本"]),
        ]
    )

    result = await translate_chunk(
        chunks=chunks,
        terms=terms,
        llm_client=llm_client,
        translator_config=temp_config.translator_config,
        source_language="日语",
        target_language=temp_config.translation_target_language,
    )

    assert result == ["这是 ⟪a:0⟫链接⟪/a:0⟫ 文本"]
    assert llm_client.chat.await_count == 2


@pytest.mark.asyncio
async def test_translate_chunk_retries_when_ids_are_reordered(temp_config: Config):
    chunks = ["甲", "乙"]
    terms = [_make_term()]
    assert temp_config.translator_config is not None
    temp_config.translator_config.enable_polish = False
    temp_config.translator_config.max_retries = 0

    llm_client = MagicMock(spec=LLMClient)
    llm_client.chat = AsyncMock(
        side_effect=[
            json.dumps(
                {
                    "翻译文本": [
                        {"id": 1, "文本": "乙"},
                        {"id": 0, "文本": "甲"},
                    ]
                },
                ensure_ascii=False,
            ),
            _translation_response(["甲", "乙"]),
        ]
    )

    result = await translate_chunk(
        chunks=chunks,
        terms=terms,
        llm_client=llm_client,
        translator_config=temp_config.translator_config,
        source_language="日语",
        target_language=temp_config.translation_target_language,
    )

    assert result == ["甲", "乙"]
    assert llm_client.chat.await_count == 2


@pytest.mark.asyncio
async def test_translate_chunk_accepts_fullwidth_delimiters_for_strict_markers(temp_config: Config):
    chunks = ["This is ⟪a:0⟫link⟪/a:0⟫ text"]
    terms = [_make_term()]
    assert temp_config.translator_config is not None
    temp_config.translator_config.enable_polish = False
    temp_config.translator_config.max_retries = 0

    llm_client = MagicMock(spec=LLMClient)
    llm_client.chat = AsyncMock(side_effect=[_translation_response(["这是 《a:0》链接《/a:0》 文本"])])

    result = await translate_chunk(
        chunks=chunks,
        terms=terms,
        llm_client=llm_client,
        translator_config=temp_config.translator_config,
        source_language="日语",
        target_language=temp_config.translation_target_language,
    )

    assert result == ["这是 《a:0》链接《/a:0》 文本"]
    assert llm_client.chat.await_count == 1


@pytest.mark.asyncio
async def test_translate_chunk_does_not_retry_when_lenient_style_marker_is_removed(temp_config: Config):
    chunks = ["This is ⟪em:0⟫italic⟪/em:0⟫ text"]
    terms = [_make_term()]
    assert temp_config.translator_config is not None
    temp_config.translator_config.enable_polish = False
    temp_config.translator_config.max_retries = 0

    llm_client = MagicMock(spec=LLMClient)
    llm_client.chat = AsyncMock(side_effect=[_translation_response(["这是斜体文本"])])

    result = await translate_chunk(
        chunks=chunks,
        terms=terms,
        llm_client=llm_client,
        translator_config=temp_config.translator_config,
        source_language="日语",
        target_language=temp_config.translation_target_language,
    )

    assert result == ["这是斜体文本"]
    assert llm_client.chat.await_count == 1


@pytest.mark.asyncio
async def test_translate_chunk_does_not_retry_when_only_ruby_marker_is_removed(temp_config: Config):
    chunks = ["前文 ⟪RUBY:0⟫漢字(かんじ)⟪/RUBY:0⟫ 后文"]
    terms = [_make_term()]
    assert temp_config.translator_config is not None
    temp_config.translator_config.enable_polish = False
    temp_config.translator_config.max_retries = 0

    llm_client = MagicMock(spec=LLMClient)
    llm_client.chat = AsyncMock(side_effect=[_translation_response(["前文 汉字 后文"])])

    result = await translate_chunk(
        chunks=chunks,
        terms=terms,
        llm_client=llm_client,
        translator_config=temp_config.translator_config,
        source_language="日语",
        target_language=temp_config.translation_target_language,
    )

    assert result == ["前文 汉字 后文"]
    assert llm_client.chat.await_count == 1


@pytest.mark.asyncio
async def test_translate_chunk_retries_when_ruby_marker_is_malformed(temp_config: Config):
    chunks = ["前文 ⟪RUBY:0⟫漢字(かんじ)⟪/RUBY:0⟫ 后文"]
    terms = [_make_term()]
    assert temp_config.translator_config is not None
    temp_config.translator_config.enable_polish = False
    temp_config.translator_config.max_retries = 0

    llm_client = MagicMock(spec=LLMClient)
    llm_client.chat = AsyncMock(
        side_effect=[
            _translation_response(["前文 ⟪RUBY:0⟫汉字 后文"]),
            _translation_response(["前文 汉字 后文"]),
        ]
    )

    result = await translate_chunk(
        chunks=chunks,
        terms=terms,
        llm_client=llm_client,
        translator_config=temp_config.translator_config,
        source_language="日语",
        target_language=temp_config.translation_target_language,
    )

    assert result == ["前文 汉字 后文"]
    assert llm_client.chat.await_count == 2


@pytest.mark.asyncio
async def test_translate_chunk_retries_when_unknown_inline_marker_is_present(temp_config: Config):
    chunks = ["前文 ⟪RUBY:0⟫漢字(かんじ)⟪/RUBY:0⟫ 后文"]
    terms = [_make_term()]
    assert temp_config.translator_config is not None
    temp_config.translator_config.enable_polish = False
    temp_config.translator_config.max_retries = 0

    llm_client = MagicMock(spec=LLMClient)
    llm_client.chat = AsyncMock(
        side_effect=[
            _translation_response(["前文 ⟪UNKNOWN⟫汉字 后文"]),
            _translation_response(["前文 汉字 后文"]),
        ]
    )

    result = await translate_chunk(
        chunks=chunks,
        terms=terms,
        llm_client=llm_client,
        translator_config=temp_config.translator_config,
        source_language="日语",
        target_language=temp_config.translation_target_language,
    )

    assert result == ["前文 汉字 后文"]
    assert llm_client.chat.await_count == 2


@pytest.mark.asyncio
async def test_translate_chunk_retries_when_shifted_strict_markers_touch_compressed_lines(temp_config: Config):
    chunks = ["甲 ⟪a:0⟫一⟪/a:0⟫\n乙\n丙"]
    terms = [_make_term()]
    assert temp_config.translator_config is not None
    temp_config.translator_config.enable_polish = False
    temp_config.translator_config.max_retries = 0

    llm_client = MagicMock(spec=LLMClient)
    llm_client.chat = AsyncMock(
        side_effect=[
            _translation_response(
                [
                    "",
                    "甲 ⟪a:0⟫壹⟪/a:0⟫",
                    "丙",
                ]
            ),
            _translation_response(
                [
                    "甲 ⟪a:0⟫壹⟪/a:0⟫",
                    "",
                    "丙",
                ]
            ),
        ]
    )

    result = await translate_chunk(
        chunks=chunks,
        terms=terms,
        llm_client=llm_client,
        translator_config=temp_config.translator_config,
        source_language="日语",
        target_language=temp_config.translation_target_language,
    )

    assert result == [f"甲 ⟪a:0⟫壹⟪/a:0⟫\n{COMPRESSED_LINE_SENTINEL}\n丙"]
    assert llm_client.chat.await_count == 2


@pytest.mark.asyncio
async def test_translate_chunk_retries_when_empty_placeholder_drops_strict_marker_line(temp_config: Config):
    chunks = ["甲 ⟪a:0⟫一⟪/a:0⟫\n乙"]
    terms = [_make_term()]
    assert temp_config.translator_config is not None
    temp_config.translator_config.enable_polish = False
    temp_config.translator_config.max_retries = 0

    llm_client = MagicMock(spec=LLMClient)
    llm_client.chat = AsyncMock(
        side_effect=[
            _translation_response(["", "乙"]),
            _translation_response(["甲 ⟪a:0⟫壹⟪/a:0⟫", "乙"]),
        ]
    )

    result = await translate_chunk(
        chunks=chunks,
        terms=terms,
        llm_client=llm_client,
        translator_config=temp_config.translator_config,
        source_language="日语",
        target_language=temp_config.translation_target_language,
    )

    assert result == ["甲 ⟪a:0⟫壹⟪/a:0⟫\n乙"]
    assert llm_client.chat.await_count == 2


@pytest.mark.asyncio
async def test_translate_chunk_allows_empty_placeholder_for_plain_line(temp_config: Config):
    chunks = ["甲\n乙"]
    terms = [_make_term()]
    assert temp_config.translator_config is not None
    temp_config.translator_config.enable_polish = False
    temp_config.translator_config.max_retries = 0

    llm_client = MagicMock(spec=LLMClient)
    llm_client.chat = AsyncMock(side_effect=[_translation_response(["", "乙"])])

    result = await translate_chunk(
        chunks=chunks,
        terms=terms,
        llm_client=llm_client,
        translator_config=temp_config.translator_config,
        source_language="日语",
        target_language=temp_config.translation_target_language,
    )

    assert result == [f"{COMPRESSED_LINE_SENTINEL}\n乙"]
    assert llm_client.chat.await_count == 1


@pytest.mark.asyncio
async def test_translate_chunk_allows_compressed_lines_with_lenient_markers_only(temp_config: Config):
    chunks = ["甲\n乙 ⟪RUBY:0⟫漢字(かんじ)⟪/RUBY:0⟫"]
    terms = [_make_term()]
    assert temp_config.translator_config is not None
    temp_config.translator_config.enable_polish = False
    temp_config.translator_config.max_retries = 0

    llm_client = MagicMock(spec=LLMClient)
    llm_client.chat = AsyncMock(side_effect=[_translation_response(["甲", ""])])

    result = await translate_chunk(
        chunks=chunks,
        terms=terms,
        llm_client=llm_client,
        translator_config=temp_config.translator_config,
        source_language="日语",
        target_language=temp_config.translation_target_language,
    )

    assert result == [f"甲\n{COMPRESSED_LINE_SENTINEL}"]
    assert llm_client.chat.await_count == 1


@pytest.mark.asyncio
async def test_translate_chunk_retries_when_multiple_compressed_lines_drop_strict_markers(temp_config: Config):
    chunks = ["前言\n甲 ⟪a:0⟫一⟪/a:0⟫\n乙 ⟪abbr:1⟫二⟪/abbr:1⟫"]
    terms = [_make_term()]
    assert temp_config.translator_config is not None
    temp_config.translator_config.enable_polish = False
    temp_config.translator_config.max_retries = 0

    llm_client = MagicMock(spec=LLMClient)
    llm_client.chat = AsyncMock(
        side_effect=[
            _translation_response(["前言", "", ""]),
            _translation_response(["前言", "甲 ⟪a:0⟫壹⟪/a:0⟫", "乙 ⟪abbr:1⟫贰⟪/abbr:1⟫"]),
        ]
    )

    result = await translate_chunk(
        chunks=chunks,
        terms=terms,
        llm_client=llm_client,
        translator_config=temp_config.translator_config,
        source_language="日语",
        target_language=temp_config.translation_target_language,
    )

    assert result == ["前言\n甲 ⟪a:0⟫壹⟪/a:0⟫\n乙 ⟪abbr:1⟫贰⟪/abbr:1⟫"]
    assert llm_client.chat.await_count == 2


@pytest.mark.asyncio
async def test_translate_chunk_strict_mismatch_without_compression_still_raises(temp_config: Config):
    chunks = ["甲 ⟪a:0⟫一⟪/a:0⟫\n乙\n丙"]
    terms = [_make_term()]
    assert temp_config.translator_config is not None
    temp_config.translator_config.enable_polish = False
    temp_config.translator_config.max_retries = 0

    llm_client = MagicMock(spec=LLMClient)
    llm_client.chat = AsyncMock(
        side_effect=[
            _translation_response(["甲 壹", "乙", "丙"]),
            _translation_response(["甲 壹", "乙", "丙"]),
            _translation_response(["甲 壹", "乙", "丙"]),
        ]
    )

    with pytest.raises(ValueError, match="inline marker mismatch"):
        await translate_chunk(
            chunks=chunks,
            terms=terms,
            llm_client=llm_client,
            translator_config=temp_config.translator_config,
            source_language="日语",
            target_language=temp_config.translation_target_language,
        )


@pytest.mark.asyncio
async def test_translate_chunk_allows_extra_ruby_markers_mixed_inline(temp_config: Config):
    chunks = ["A ⟪a:0⟫x⟪/a:0⟫ B ⟪RUBY:1⟫漢字(かんじ)⟪/RUBY:1⟫ C"]
    terms = [_make_term()]
    assert temp_config.translator_config is not None
    temp_config.translator_config.enable_polish = False
    temp_config.translator_config.max_retries = 0

    llm_client = MagicMock(spec=LLMClient)
    llm_client.chat = AsyncMock(
        side_effect=[
            _translation_response(["A ⟪a:0⟫y⟪/a:0⟫ B ⟪RUBY:1⟫漢字(a)⟪/RUBY:1⟫ ⟪RUBY:9⟫追加(b)⟪/RUBY:9⟫ C"]),
        ]
    )

    result = await translate_chunk(
        chunks=chunks,
        terms=terms,
        llm_client=llm_client,
        translator_config=temp_config.translator_config,
        source_language="日语",
        target_language=temp_config.translation_target_language,
    )

    assert result == ["A ⟪a:0⟫y⟪/a:0⟫ B ⟪RUBY:1⟫漢字(a)⟪/RUBY:1⟫ ⟪RUBY:9⟫追加(b)⟪/RUBY:9⟫ C"]
    assert llm_client.chat.await_count == 1


@pytest.mark.asyncio
async def test_translate_chunk_allows_extra_ruby_markers_ruby_only(temp_config: Config):
    chunks = ["前文 ⟪RUBY:0⟫漢字(かんじ)⟪/RUBY:0⟫ 后文"]
    terms = [_make_term()]
    assert temp_config.translator_config is not None
    temp_config.translator_config.enable_polish = False
    temp_config.translator_config.max_retries = 0

    llm_client = MagicMock(spec=LLMClient)
    llm_client.chat = AsyncMock(
        side_effect=[
            _translation_response(["前文 ⟪RUBY:0⟫汉字(a)⟪/RUBY:0⟫ ⟪RUBY:2⟫额外(b)⟪/RUBY:2⟫ 后文"]),
        ]
    )

    result = await translate_chunk(
        chunks=chunks,
        terms=terms,
        llm_client=llm_client,
        translator_config=temp_config.translator_config,
        source_language="日语",
        target_language=temp_config.translation_target_language,
    )

    assert result == ["前文 ⟪RUBY:0⟫汉字(a)⟪/RUBY:0⟫ ⟪RUBY:2⟫额外(b)⟪/RUBY:2⟫ 后文"]
    assert llm_client.chat.await_count == 1


@pytest.mark.asyncio
async def test_translate_chunk_raises_on_length_mismatch(temp_config: Config):
    chunks = ["A\n\nB"]
    terms = [_make_term()]

    llm_client = MagicMock(spec=LLMClient)

    async def mock_chat(*_args, **_kwargs):
        return _translation_response(["only one"])

    llm_client.chat = AsyncMock(side_effect=mock_chat)

    with pytest.raises(ValueError, match="length mismatch"):
        await translate_chunk(
            chunks=chunks,
            terms=terms,
            llm_client=llm_client,
            translator_config=temp_config.translator_config,
            source_language="日语",
            target_language=temp_config.translation_target_language,
        )


@pytest.mark.asyncio
async def test_translate_chunk_multiple_chunks(temp_config: Config):
    """Test that multiple chunks are processed together and split correctly."""
    chunks = [
        "Chunk1\n\n---\n\nPart1",
        "Chunk2\n\n***\n\nPart2",
    ]
    terms = [_make_term()]

    llm_client = MagicMock(spec=LLMClient)

    async def mock_chat(*_args, **_kwargs):
        return _translation_response(
            [
                "Chunk1 translated",
                "---",
                "Part1 translated",
                "Chunk2 translated",
                "***",
                "Part2 translated",
            ]
        )

    llm_client.chat = AsyncMock(side_effect=mock_chat)

    result = await translate_chunk(
        chunks=chunks,
        terms=terms,
        llm_client=llm_client,
        translator_config=temp_config.translator_config,
        source_language="日语",
        target_language=temp_config.translation_target_language,
    )

    # Should return one translated string per input chunk
    assert len(result) == 2
    assert result[0] == "Chunk1 translated\n\n---\n\nPart1 translated"
    assert result[1] == "Chunk2 translated\n\n***\n\nPart2 translated"

    # Verify all blocks were sent together (first call is translation)
    translate_call = llm_client.chat.call_args_list[0]
    messages = translate_call[0][0]
    user_payload = json.loads(messages[1]["content"])
    assert user_payload["原文"] == [
        {"id": 0, "文本": "Chunk1"},
        {"id": 1, "文本": "---"},
        {"id": 2, "文本": "Part1"},
        {"id": 3, "文本": "Chunk2"},
        {"id": 4, "文本": "***"},
        {"id": 5, "文本": "Part2"},
    ]


@pytest.mark.asyncio
async def test_translate_chunk_empty_chunks(temp_config: Config):
    """Test handling of empty chunks."""
    chunks = ["", "Non-empty\n\n---\n\nText", ""]
    terms = [_make_term()]

    llm_client = MagicMock(spec=LLMClient)

    async def mock_chat(*_args, **_kwargs):
        return _translation_response(["Non-empty translated", "---", "Text translated"])

    llm_client.chat = AsyncMock(side_effect=mock_chat)

    result = await translate_chunk(
        chunks=chunks,
        terms=terms,
        llm_client=llm_client,
        translator_config=temp_config.translator_config,
        source_language="日语",
        target_language=temp_config.translation_target_language,
    )

    assert len(result) == 3
    assert result[0] == ""  # Empty chunk returns empty string
    assert result[1] == "Non-empty translated\n\n---\n\nText translated"
    assert result[2] == ""  # Empty chunk returns empty string


@pytest.mark.asyncio
async def test_translate_chunk_uses_polished_response_when_enabled(temp_config: Config):
    chunks = ["A"]
    terms = [_make_term()]
    assert temp_config.translator_config is not None
    temp_config.translator_config.enable_polish = True
    temp_config.translator_config.max_retries = 0

    llm_client = MagicMock(spec=LLMClient)
    llm_client.chat = AsyncMock(
        side_effect=[
            _translation_response(["First pass"]),
            _translation_response(["Polished pass"]),
        ]
    )

    result = await translate_chunk(
        chunks=chunks,
        terms=terms,
        llm_client=llm_client,
        translator_config=temp_config.translator_config,
        source_language="日语",
        target_language=temp_config.translation_target_language,
    )

    assert result == ["Polished pass"]
    assert llm_client.chat.await_count == 2


@pytest.mark.asyncio
async def test_translate_chunk_uses_separate_polish_config_when_provided(temp_config: Config):
    chunks = ["A"]
    terms = [_make_term()]
    assert temp_config.translator_config is not None
    temp_config.translator_config.enable_polish = True
    temp_config.translator_config.max_retries = 0
    polish_config = PolishConfig(
        api_key="POLISH_KEY",
        base_url="https://polish.example/v1",
        model="polish-reasoner",
        max_retries=0,
    )

    llm_client = MagicMock(spec=LLMClient)
    llm_client.chat = AsyncMock(
        side_effect=[
            _translation_response(["First pass"]),
            _translation_response(["Polished pass"]),
        ]
    )

    result = await translate_chunk(
        chunks=chunks,
        terms=terms,
        llm_client=llm_client,
        translator_config=temp_config.translator_config,
        source_language="日语",
        target_language=temp_config.translation_target_language,
        polish_config=polish_config,
    )

    assert result == ["Polished pass"]
    assert llm_client.chat.await_count == 2
    assert llm_client.chat.await_args_list[0].args[1] is temp_config.translator_config
    assert llm_client.chat.await_args_list[1].args[1] is polish_config


@pytest.mark.asyncio
async def test_translate_chunk_reuses_same_llm_session_id_for_translate_and_polish(temp_config: Config):
    from context_aware_translation.llm.session_trace import get_llm_session_id

    chunks = ["A"]
    terms = [_make_term()]
    assert temp_config.translator_config is not None
    temp_config.translator_config.enable_polish = True
    temp_config.translator_config.max_retries = 0

    llm_client = MagicMock(spec=LLMClient)
    seen_session_ids: list[str | None] = []

    async def _mock_chat(*_args, **_kwargs):
        seen_session_ids.append(get_llm_session_id())
        if len(seen_session_ids) == 1:
            return _translation_response(["First pass"])
        return _translation_response(["Polished pass"])

    llm_client.chat = AsyncMock(side_effect=_mock_chat)

    result = await translate_chunk(
        chunks=chunks,
        terms=terms,
        llm_client=llm_client,
        translator_config=temp_config.translator_config,
        source_language="日语",
        target_language=temp_config.translation_target_language,
    )

    assert result == ["Polished pass"]
    assert llm_client.chat.await_count == 2
    assert all(sid is not None for sid in seen_session_ids)
    assert len(set(seen_session_ids)) == 1
