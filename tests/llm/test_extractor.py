from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from context_aware_translation.config import Config
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.llm.extractor import extract_terms
from context_aware_translation.storage.schema.book_db import ChunkRecord

logger = logging.getLogger(__name__)


RUN_LIVE = os.getenv("RUN_LIVE_LLM_TESTS") == "1"
API_KEY = os.getenv("OPENAI_API_KEY")

should_skip = not (RUN_LIVE and API_KEY)
skip_reason = "Set RUN_LIVE_LLM_TESTS=1 and OPENAI_API_KEY to run live LLM integration tests"

EXPECTED_NAMES_CH1 = {
    "奥義書",
    "世界の真理書「墓守編」",
    "格納鍵インベントリア",
}

EXPECTED_NAMES_CH2 = {
    "サンラク",
    "無尽連斬",
    "グローイング・ピアス",
    "インファイト",
    "ドリフトステップ",
    "セツナノミキリ",
    "ハンド・オブ・フォーチュン",
    "グレイトオブクライム",
    "クライマックス・ブースト",
    "六艘跳び",
    "リコシェット・ステップ",
}


def _load_chunk(rel_name: str) -> str:
    chunk_path = Path(__file__).resolve().parent.parent / "data" / rel_name
    return chunk_path.read_text(encoding="utf-8")


def _assert_expected_terms(result: list, expected: set[str]) -> None:
    names = {r.canonical_name for r in result}
    missing = expected - names
    assert not missing, f"Missing expected terms: {missing}"


@pytest.mark.skipif(should_skip, reason=skip_reason)
@pytest.mark.asyncio
async def test_live_extraction_deepseek_reasoner_chunk1() -> None:
    from context_aware_translation.config import (
        ExtractorConfig,
        GlossaryTranslationConfig,
        ReviewConfig,
        SummarizorConfig,
        TranslatorConfig,
    )

    base_settings = {"api_key": API_KEY, "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"}
    cfg = Config(
        translation_target_language="简体中文",
        extractor_config=ExtractorConfig(**base_settings),
        summarizor_config=SummarizorConfig(**base_settings),
        translator_config=TranslatorConfig(**base_settings),
        glossary_config=GlossaryTranslationConfig(**base_settings),
        review_config=ReviewConfig(**base_settings),
    )

    client = LLMClient(cfg.extractor_config)
    chunk_text = _load_chunk("test_chunk.txt")

    chunk_record = ChunkRecord(chunk_id="test1", hash="hash1", text=chunk_text)
    result = await extract_terms(chunk_record, client, cfg)
    assert result, "LLM should return at least one term"
    _assert_expected_terms(result, EXPECTED_NAMES_CH1)
    # Verify new fields are present
    for ent in result:
        assert ent.votes > 0
        assert ent.total_api_calls > 0
    logger.info(result)


@pytest.mark.skipif(should_skip, reason=skip_reason)
@pytest.mark.asyncio
async def test_live_extraction_deepseek_reasoner_chunk2() -> None:
    from context_aware_translation.config import (
        ExtractorConfig,
        GlossaryTranslationConfig,
        ReviewConfig,
        SummarizorConfig,
        TranslatorConfig,
    )

    base_settings = {"api_key": API_KEY, "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"}
    cfg = Config(
        translation_target_language="简体中文",
        extractor_config=ExtractorConfig(**base_settings),
        summarizor_config=SummarizorConfig(**base_settings),
        translator_config=TranslatorConfig(**base_settings),
        glossary_config=GlossaryTranslationConfig(**base_settings),
        review_config=ReviewConfig(**base_settings),
    )

    client = LLMClient(cfg.extractor_config)
    chunk_text = _load_chunk("test_chunk2.txt")

    chunk_record = ChunkRecord(chunk_id="test1", hash="hash1", text=chunk_text)
    result = await extract_terms(chunk_record, client, cfg)
    assert result, "LLM should return at least one term"
    _assert_expected_terms(result, EXPECTED_NAMES_CH2)
    # Verify new fields are present
    for ent in result:
        assert ent.votes > 0
        assert ent.total_api_calls > 0
    logger.info(result)
