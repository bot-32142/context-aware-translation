from unittest.mock import AsyncMock, MagicMock

import pytest

from context_aware_translation.config import Config
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.llm.language_detector import (
    LanguageDetectionError,
    detect_source_language,
)


@pytest.fixture
def config(tmp_path):
    """Create a test config."""
    from context_aware_translation.config import (
        ExtractorConfig,
        GlossaryTranslationConfig,
        ReviewConfig,
        SummarizorConfig,
        TranslatorConfig,
    )

    base_settings = {
        "api_key": "DUMMY_API_KEY",
        "base_url": "https://api.test.com/v1",
        "model": "test-model",
        "max_retries": 3,
    }
    return Config(
        translation_target_language="简体中文",
        working_dir=tmp_path / "data",
        extractor_config=ExtractorConfig(**base_settings),
        summarizor_config=SummarizorConfig(**base_settings),
        translator_config=TranslatorConfig(**base_settings),
        glossary_config=GlossaryTranslationConfig(**base_settings),
        review_config=ReviewConfig(**base_settings),
    )


@pytest.fixture
def mock_llm_client(config):
    """Create a mock LLM client."""
    client = MagicMock(spec=LLMClient)
    client.config = config.extractor_config
    return client


@pytest.mark.asyncio
async def test_detect_japanese_language(mock_llm_client, config):
    """Test detecting Japanese text."""
    japanese_text = "これは日本語のテキストです。"

    # Mock the chat response
    mock_llm_client.chat = AsyncMock(return_value='{"语言": "日语"}')

    result = await detect_source_language(japanese_text, mock_llm_client, config.extractor_config)

    assert result == "日语"
    mock_llm_client.chat.assert_called_once()


@pytest.mark.asyncio
async def test_detect_english_language(mock_llm_client, config):
    """Test detecting English text."""
    english_text = "This is an English text."

    # Mock the chat response
    mock_llm_client.chat = AsyncMock(return_value='{"语言": "英语"}')

    result = await detect_source_language(english_text, mock_llm_client, config.extractor_config)

    assert result == "英语"
    mock_llm_client.chat.assert_called_once()


@pytest.mark.asyncio
async def test_detect_chinese_language(mock_llm_client, config):
    """Test detecting Chinese text."""
    chinese_text = "这是一段中文文本。"

    # Mock the chat response
    mock_llm_client.chat = AsyncMock(return_value='{"语言": "中文"}')

    result = await detect_source_language(chinese_text, mock_llm_client, config.extractor_config)

    assert result == "中文"
    mock_llm_client.chat.assert_called_once()


@pytest.mark.asyncio
async def test_detect_language_with_long_text(mock_llm_client, config):
    """Test that long text is sampled across the full input, not just the prefix."""
    english_front_matter = "ENGLISH_LICENSE_TEXT " * 120
    french_body = "FRENCH_BODY_TEXT " * 120
    french_ending = "FRENCH_ENDING_TEXT " * 120
    long_text = english_front_matter + french_body + french_ending

    # Mock the chat response
    mock_llm_client.chat = AsyncMock(return_value='{"语言": "日语"}')

    result = await detect_source_language(long_text, mock_llm_client, config.extractor_config, sample_size=1000)

    assert result == "日语"
    # Check that the text sent is sampled (check via call args)
    call_args = mock_llm_client.chat.call_args
    user_message = call_args[0][0][1]["content"]
    assert "ENGLISH_LICENSE_TEXT" in user_message
    assert "FRENCH_BODY_TEXT" in user_message
    assert "FRENCH_ENDING_TEXT" in user_message
    assert len(user_message) < len(long_text)


@pytest.mark.asyncio
async def test_detect_language_strips_whitespace(mock_llm_client, config):
    """Test that detected language is stripped of whitespace."""
    text = "This is a test."

    # Mock the chat response with extra whitespace
    mock_llm_client.chat = AsyncMock(return_value='{"语言": "  英语  "}')

    result = await detect_source_language(text, mock_llm_client, config.extractor_config)

    assert result == "英语"
    assert result == result.strip()


@pytest.mark.asyncio
async def test_detect_language_invalid_json(mock_llm_client, config):
    """Test that invalid JSON raises LanguageDetectionError after retries."""
    text = "This is a test."

    # Mock the chat to return invalid JSON
    mock_llm_client.chat = AsyncMock(return_value="not valid json")

    with pytest.raises(LanguageDetectionError):
        await detect_source_language(text, mock_llm_client, config.extractor_config)

    # Should retry max_retries + 1 times
    assert mock_llm_client.chat.call_count == config.extractor_config.max_retries + 1


@pytest.mark.asyncio
async def test_detect_language_missing_field(mock_llm_client, config):
    """Test that missing '语言' field raises LanguageDetectionError after retries."""
    text = "This is a test."

    # Mock the chat to return JSON without '语言' field
    mock_llm_client.chat = AsyncMock(return_value='{"other_field": "value"}')

    with pytest.raises(LanguageDetectionError):
        await detect_source_language(text, mock_llm_client, config.extractor_config)

    # Should retry max_retries + 1 times
    assert mock_llm_client.chat.call_count == config.extractor_config.max_retries + 1


@pytest.mark.asyncio
async def test_detect_language_retry_on_error_then_succeed(mock_llm_client, config):
    """Test that detection retries on error and succeeds eventually."""
    text = "This is a test."

    # Mock the chat to fail first, then succeed
    mock_llm_client.chat = AsyncMock(
        side_effect=[
            "not valid json",  # First attempt fails
            '{"语言": "英语"}',  # Second attempt succeeds
        ]
    )

    result = await detect_source_language(text, mock_llm_client, config.extractor_config)

    assert result == "英语"
    assert mock_llm_client.chat.call_count == 2


@pytest.mark.asyncio
async def test_detect_language_uses_correct_model(mock_llm_client, config):
    """Test that language detection uses the correct model."""
    text = "This is a test."

    # Mock the chat response
    mock_llm_client.chat = AsyncMock(return_value='{"语言": "英语"}')

    await detect_source_language(text, mock_llm_client, config.extractor_config)

    # Check that the correct model was used
    call_args = mock_llm_client.chat.call_args
    # step_config is the second positional argument
    step_config_arg = call_args[0][1] if len(call_args[0]) > 1 else None
    assert step_config_arg is not None
    # Check kwargs for model override or use step_config model
    if "model" in call_args[1]:
        assert call_args[1]["model"] == config.extractor_config.model
    else:
        assert step_config_arg.model == config.extractor_config.model
    assert call_args[1].get("temperature", step_config_arg.temperature) == 0.0  # Should use low temperature
    assert call_args[1]["response_format"] == {"type": "json_object"}
