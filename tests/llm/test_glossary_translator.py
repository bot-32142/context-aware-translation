from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_aware_translation.config import GlossaryTranslationConfig
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.llm.glossary_translator import (
    _build_batch_system_prompt,
    _build_batch_user_payload,
    _validate_batch_response,
    translate_glossary,
)
from context_aware_translation.llm.translator import TranslationValidationError
from context_aware_translation.utils.cjk_normalize import build_normalized_key_mapping


def test_build_batch_system_prompt():
    """Test system prompt building."""
    prompt = _build_batch_system_prompt("日语", "简体中文")

    assert "日语" in prompt
    assert "简体中文" in prompt
    assert "新翻译" in prompt
    assert "待翻译术语组" in prompt
    assert "相似已存在术语" in prompt


def test_build_batch_user_payload():
    """Test user payload building."""
    # Note: The function signature says list[TermRecord] but actual usage passes list[dict]
    # The function accesses term["description"] and term["missing_names"] like a dict
    # This test reflects the actual usage pattern from context_manager.py
    to_translate = [
        {
            "canonical_name": "test1",
            "description": "Description 1",
            "missing_names": "test1",
        },
        {
            "canonical_name": "test2",
            "description": "Description 2",
            "missing_names": "test2",
        },
    ]

    translated_names = {"existing": "已存在"}
    target_language = "简体中文"

    # The function signature expects TermRecord but actual usage passes dicts
    # We'll test with dicts as that's how it's actually called
    payload_str = _build_batch_user_payload(
        to_translate,  # type: ignore
        translated_names,
        target_language,
    )

    payload = json.loads(payload_str)
    assert payload["目标语言"] == target_language
    assert "待翻译术语组" in payload
    assert "相似已存在术语" in payload
    assert payload["相似已存在术语"] == translated_names
    assert len(payload["待翻译术语组"]) == 2
    assert payload["待翻译术语组"][0]["描述"] == "Description 1"
    assert payload["待翻译术语组"][0]["待翻译名称"] == "test1"


def test_validate_batch_response_valid():
    """Test validation with valid response."""
    data = {
        "新翻译": {
            "test1": "测试1",
            "test2": "测试2",
        }
    }

    to_translate = [
        {"missing_names": "test1"},
        {"missing_names": "test2"},
    ]

    result = _validate_batch_response(data, to_translate)
    assert result == {"test1": "测试1", "test2": "测试2"}


def test_validate_batch_response_missing_translation():
    """Test validation fails when translation is missing."""
    data = {
        "新翻译": {
            "test1": "测试1",
        }
    }

    to_translate = [
        {"missing_names": "test1"},
        {"missing_names": "test2"},
    ]

    with pytest.raises(TranslationValidationError, match="Missing 新翻译 for test2"):
        _validate_batch_response(data, to_translate)


def test_validate_batch_response_not_dict():
    """Test validation fails when 新翻译 is not a dict."""
    data = {
        "新翻译": "not a dict",
    }

    to_translate = [{"missing_names": "test1"}]

    with pytest.raises(TranslationValidationError, match="新翻译 must be an object"):
        _validate_batch_response(data, to_translate)


def test_validate_batch_response_empty_translation():
    """Test validation fails when translation is empty."""
    data = {
        "新翻译": {
            "test1": "",
        }
    }

    to_translate = [{"missing_names": "test1"}]

    with pytest.raises(TranslationValidationError, match="Missing 新翻译 for test1"):
        _validate_batch_response(data, to_translate)


def test_validate_batch_response_cjk_variant_keys():
    """Test that CJK variant characters in LLM keys are matched to expected keys."""
    # LLM returns simplified variants, but expected keys are traditional
    data = {
        "新翻译": {
            "种族": "Race",  # simplified 种 (U+79CD)
            "强化": "Strengthen",  # simplified 强 (U+5F3A)
        }
    }

    to_translate = [
        {"missing_names": "種族"},  # traditional 種 (U+7A2E)
        {"missing_names": "強化"},  # traditional 強 (U+5F37)
    ]

    result = _validate_batch_response(data, to_translate)
    # Keys should be remapped to the original expected (traditional) keys
    assert "種族" in result
    assert "強化" in result
    assert result["種族"] == "Race"
    assert result["強化"] == "Strengthen"


def test_validate_batch_response_mixed_exact_and_variant():
    """Test mix of exact matches and CJK variant matches."""
    data = {
        "新翻译": {
            "HP": "HP",  # exact match (non-CJK)
            "种族": "Race",  # simplified variant of traditional key
        }
    }

    to_translate = [
        {"missing_names": "HP"},
        {"missing_names": "種族"},  # traditional
    ]

    result = _validate_batch_response(data, to_translate)
    assert result["HP"] == "HP"
    assert result["種族"] == "Race"


def test_validate_batch_response_still_fails_for_truly_missing():
    """Test that normalization doesn't mask genuinely missing keys."""
    data = {
        "新翻译": {
            "种族": "Race",
        }
    }

    to_translate = [
        {"missing_names": "種族"},
        {"missing_names": "完全不同的词"},  # genuinely missing
    ]

    with pytest.raises(TranslationValidationError, match="Missing 新翻译 for 完全不同的词"):
        _validate_batch_response(data, to_translate)


def test_validate_batch_response_extra_keys_dropped():
    """Test that extra keys from LLM not in expected set are dropped."""
    data = {
        "新翻译": {
            "种族": "Race",
            "bonus_term": "Bonus",  # extra key not in expected
        }
    }

    to_translate = [
        {"missing_names": "種族"},
    ]

    result = _validate_batch_response(data, to_translate)
    assert result["種族"] == "Race"
    assert "bonus_term" not in result


def test_validate_batch_response_jp_shinjitai_keys():
    """Test that JP shinjitai chars in LLM keys match expected keys.

    Reproduces the real bug: LLM returned 天ぷら騎士团 (CN simplified 团)
    but expected key was 天ぷら騎士団 (JP shinjitai 団).
    """
    data = {
        "新翻译": {
            "天ぷら騎士团": "Tempura Knights",  # CN simplified 团 (U+56E2)
        }
    }

    to_translate = [
        {"missing_names": "天ぷら騎士団"},  # JP shinjitai 団 (U+56E3)
    ]

    result = _validate_batch_response(data, to_translate)
    assert "天ぷら騎士団" in result
    assert result["天ぷら騎士団"] == "Tempura Knights"


def test_validate_batch_response_fullwidth_keys():
    """Test that fullwidth chars in LLM keys match ASCII expected keys."""
    data = {
        "新翻译": {
            "\uff28\uff30": "Hit Points",  # fullwidth ＨＰ
        }
    }

    to_translate = [
        {"missing_names": "HP"},  # ASCII
    ]

    result = _validate_batch_response(data, to_translate)
    assert "HP" in result
    assert result["HP"] == "Hit Points"


def test_validate_batch_response_diacritics():
    """Test that diacritics-stripped LLM keys match accented expected keys."""
    data = {
        "新翻译": {
            "cafe": "Coffee shop",  # no diacritics
        }
    }

    to_translate = [
        {"missing_names": "caf\u00e9"},  # café with acute accent
    ]

    result = _validate_batch_response(data, to_translate)
    assert "caf\u00e9" in result
    assert result["caf\u00e9"] == "Coffee shop"


@pytest.mark.asyncio
async def test_translate_glossary_empty():
    """Test translate_glossary with empty input."""
    config = GlossaryTranslationConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
    )
    llm_client = MagicMock(spec=LLMClient)

    result = await translate_glossary(
        [],
        {},
        config,
        "简体中文",
        "日语",
        llm_client,
    )

    assert result == {}
    llm_client.chat.assert_not_called()


@pytest.mark.asyncio
async def test_translate_glossary_success():
    """Test successful glossary translation."""
    config = GlossaryTranslationConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        max_retries=1,
    )
    llm_client = MagicMock(spec=LLMClient)

    response_data = {
        "新翻译": {
            "test1": "测试1",
            "test2": "测试2",
        }
    }

    llm_client.chat = AsyncMock(return_value=json.dumps(response_data))

    to_translate = [
        {"canonical_name": "test1", "description": "desc1", "missing_names": "test1"},
        {"canonical_name": "test2", "description": "desc2", "missing_names": "test2"},
    ]
    translated_names = {"existing": "已存在"}

    result = await translate_glossary(
        to_translate,
        translated_names,
        config,
        "简体中文",
        "日语",
        llm_client,
    )

    assert result == {"test1": "测试1", "test2": "测试2"}
    llm_client.chat.assert_called_once()
    call_args = llm_client.chat.call_args
    assert call_args[1]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_translate_glossary_retry_on_validation_error():
    """Test retry on validation error uses conversational retry."""
    config = GlossaryTranslationConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        max_retries=2,
    )
    llm_client = MagicMock(spec=LLMClient)

    # First call returns invalid response, second returns valid
    invalid_response = {"新翻译": {}}
    valid_response = {
        "新翻译": {
            "test1": "测试1",
        }
    }

    llm_client.chat = AsyncMock(
        side_effect=[
            json.dumps(invalid_response),
            json.dumps(valid_response),
        ]
    )

    to_translate = [{"canonical_name": "test1", "description": "desc1", "missing_names": "test1"}]

    result = await translate_glossary(
        to_translate,
        {},
        config,
        "简体中文",
        "日语",
        llm_client,
    )

    assert result == {"test1": "测试1"}
    assert llm_client.chat.call_count == 2

    # Verify conversational retry: second call should have 4 messages
    # (system + user + assistant with failed response + correction)
    second_call_messages = llm_client.chat.call_args_list[1][0][0]
    assert len(second_call_messages) == 4
    assert second_call_messages[0]["role"] == "system"
    assert second_call_messages[1]["role"] == "user"
    assert second_call_messages[2]["role"] == "assistant"
    assert second_call_messages[2]["content"] == json.dumps(invalid_response)
    assert second_call_messages[3]["role"] == "user"
    assert "error" in second_call_messages[3]["content"].lower()


@pytest.mark.asyncio
async def test_translate_glossary_retry_on_json_error():
    """Test retry on JSON decode error uses fresh messages."""
    config = GlossaryTranslationConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        max_retries=2,
    )
    llm_client = MagicMock(spec=LLMClient)

    # First call returns invalid JSON, second returns valid
    llm_client.chat = AsyncMock(
        side_effect=[
            "not valid json",
            json.dumps({"新翻译": {"test1": "测试1"}}),
        ]
    )

    to_translate = [{"canonical_name": "test1", "description": "desc1", "missing_names": "test1"}]

    result = await translate_glossary(
        to_translate,
        {},
        config,
        "简体中文",
        "日语",
        llm_client,
    )

    assert result == {"test1": "测试1"}
    assert llm_client.chat.call_count == 2

    # Verify fresh retry: second call should have 2 messages (system + user only)
    second_call_messages = llm_client.chat.call_args_list[1][0][0]
    assert len(second_call_messages) == 2
    assert second_call_messages[0]["role"] == "system"
    assert second_call_messages[1]["role"] == "user"


@pytest.mark.asyncio
async def test_translate_glossary_fails_after_max_retries():
    """Test that function raises error after max retries when no valid JSON obtained."""
    config = GlossaryTranslationConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        max_retries=1,
    )
    llm_client = MagicMock(spec=LLMClient)

    # All attempts return invalid JSON (not parseable at all)
    llm_client.chat = AsyncMock(return_value="not valid json")

    to_translate = [{"canonical_name": "test1", "description": "desc1", "missing_names": "test1"}]

    with pytest.raises(TranslationValidationError, match="Failed to obtain valid batch translation"):
        await translate_glossary(
            to_translate,
            {},
            config,
            "简体中文",
            "日语",
            llm_client,
        )

    # Should have tried max_retries + 1 times
    assert llm_client.chat.call_count == 2


def test_validate_batch_response_lenient_returns_partial():
    """Test that strict=False returns partial results instead of raising."""
    data = {
        "新翻译": {
            "test1": "测试1",
        }
    }

    to_translate = [
        {"missing_names": "test1"},
        {"missing_names": "test2"},  # missing from response
    ]

    result = _validate_batch_response(data, to_translate, strict=False)
    assert result == {"test1": "测试1"}


@pytest.mark.asyncio
async def test_translate_glossary_returns_partial_after_retries():
    """Test that partial results are returned when some terms are missing after all retries."""
    config = GlossaryTranslationConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        max_retries=1,
    )
    llm_client = MagicMock(spec=LLMClient)

    # LLM consistently returns only one of two expected terms
    partial_response = {"新翻译": {"test1": "测试1"}}
    llm_client.chat = AsyncMock(return_value=json.dumps(partial_response))

    to_translate = [
        {"canonical_name": "test1", "description": "desc1", "missing_names": "test1"},
        {"canonical_name": "test2", "description": "desc2", "missing_names": "test2"},
    ]

    result = await translate_glossary(
        to_translate,
        {},
        config,
        "简体中文",
        "日语",
        llm_client,
    )

    # Should return partial results instead of raising
    assert result == {"test1": "测试1"}
    assert "test2" not in result
    # Should have tried all attempts (max_retries=1 means 2 total attempts)
    assert llm_client.chat.call_count == 2

    # Verify conversational retry was used
    # First call should start with 2 messages, second call should have 4
    # (original 2 + assistant response + correction)
    call_history = llm_client.chat.call_args_list
    first_call_messages = call_history[0][0][0]
    second_call_messages = call_history[1][0][0]

    # First attempt: fresh start
    assert len(first_call_messages) == 2
    assert first_call_messages[0]["role"] == "system"
    assert first_call_messages[1]["role"] == "user"

    # Second attempt: conversational retry with appended messages
    assert len(second_call_messages) == 4
    assert second_call_messages[0]["role"] == "system"
    assert second_call_messages[1]["role"] == "user"
    assert second_call_messages[2]["role"] == "assistant"
    assert second_call_messages[3]["role"] == "user"
    assert "error" in second_call_messages[3]["content"].lower()


# --- Tests for build_normalized_key_mapping helper ---


def test_build_normalized_key_mapping_exact_match():
    """Fast path: all expected keys found exactly in LLM keys."""
    result = build_normalized_key_mapping(["HP", "種族"], {"HP", "種族"})
    assert result == {"HP": "HP", "種族": "種族"}


def test_build_normalized_key_mapping_cjk_variants():
    """Simplified/traditional CJK variant matching."""
    result = build_normalized_key_mapping(
        ["种族", "强化"],  # simplified from LLM
        {"種族", "強化"},  # traditional expected
    )
    assert result == {"種族": "种族", "強化": "强化"}


def test_build_normalized_key_mapping_mixed():
    """Mix of exact and normalized matches."""
    result = build_normalized_key_mapping(
        ["HP", "种族"],
        {"HP", "種族"},
    )
    assert result == {"HP": "HP", "種族": "种族"}


def test_build_normalized_key_mapping_no_match():
    """Expected keys with no match are omitted."""
    result = build_normalized_key_mapping(
        ["种族"],
        {"種族", "完全不同"},
    )
    assert result == {"種族": "种族"}
    assert "完全不同" not in result


def test_build_normalized_key_mapping_fullwidth():
    """Fullwidth characters match ASCII."""
    result = build_normalized_key_mapping(
        ["\uff28\uff30"],  # fullwidth ＨＰ
        {"HP"},
    )
    assert result == {"HP": "\uff28\uff30"}


def test_build_normalized_key_mapping_jp_shinjitai():
    """JP shinjitai matches through OpenCC normalization."""
    result = build_normalized_key_mapping(
        ["天ぷら騎士团"],  # CN simplified 团
        {"天ぷら騎士団"},  # JP shinjitai 団
    )
    assert result == {"天ぷら騎士団": "天ぷら騎士团"}


def test_build_normalized_key_mapping_ambiguous_skipped():
    """Skip normalized matching when multiple expected keys share the same normalized form."""
    result = build_normalized_key_mapping(
        ["resume"],  # LLM returns without diacritics
        {"résumé", "resume"},  # both normalize to "resume"
    )
    # "resume" gets exact match, "résumé" is skipped (ambiguous normalized form)
    assert result == {"resume": "resume"}
    assert "résumé" not in result
