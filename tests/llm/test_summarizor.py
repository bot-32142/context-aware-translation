from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_aware_translation.config import SummarizorConfig
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.llm.summarizor import (
    _build_batch_system_prompt,
    _build_batch_user_payload,
    _validate_batch_response,
    summarize_descriptions,
)
from context_aware_translation.llm.translator import TranslationValidationError


def test_build_batch_system_prompt():
    """Test system prompt building."""
    prompt = _build_batch_system_prompt()

    assert "合并描述" in prompt
    assert "待合并描述" in prompt


def test_build_batch_user_payload():
    """Test user payload building."""
    descriptions = [
        "Description 1",
        "Description 2",
        "Description 3",
    ]

    payload_str = _build_batch_user_payload(descriptions)
    payload = json.loads(payload_str)

    assert "待合并描述" in payload
    assert payload["待合并描述"] == descriptions


def test_validate_batch_response_valid():
    """Test validation with valid response."""
    data = {"合并描述": "This is a merged description."}

    result = _validate_batch_response(data)
    assert result == "This is a merged description."


def test_validate_batch_response_empty():
    """Test validation fails when 合并描述 is empty."""
    data = {"合并描述": ""}

    with pytest.raises(TranslationValidationError, match="合并描述 must be a string"):
        _validate_batch_response(data)


def test_validate_batch_response_missing():
    """Test validation fails when 合并描述 is missing."""
    data = {}

    with pytest.raises(TranslationValidationError, match="合并描述 must be a string"):
        _validate_batch_response(data)


def test_validate_batch_response_not_string():
    """Test validation fails when 合并描述 is not a string."""
    data = {"合并描述": 123}

    with pytest.raises(TranslationValidationError, match="合并描述 must be a string"):
        _validate_batch_response(data)


@pytest.mark.asyncio
async def test_summarize_descriptions_empty():
    """Test summarize_descriptions with empty input."""
    config = SummarizorConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
    )
    llm_client = MagicMock(spec=LLMClient)

    result = await summarize_descriptions(
        [],
        config,
        llm_client,
    )

    assert result == ""
    llm_client.chat.assert_not_called()


@pytest.mark.asyncio
async def test_summarize_descriptions_success():
    """Test successful description summarization."""
    config = SummarizorConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        max_retries=1,
    )
    llm_client = MagicMock(spec=LLMClient)

    response_data = {"合并描述": "This is a merged description."}

    llm_client.chat = AsyncMock(return_value=json.dumps(response_data))

    descriptions = [
        "Description 1",
        "Description 2",
    ]

    result = await summarize_descriptions(
        descriptions,
        config,
        llm_client,
    )

    assert result == "This is a merged description."
    llm_client.chat.assert_called_once()
    call_args = llm_client.chat.call_args
    assert call_args[1]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_summarize_descriptions_retry_on_validation_error():
    """Test retry on validation error."""
    config = SummarizorConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        max_retries=2,
    )
    llm_client = MagicMock(spec=LLMClient)

    # First call returns invalid response, second returns valid
    invalid_response = {"合并描述": ""}
    valid_response = {"合并描述": "Merged description."}

    llm_client.chat = AsyncMock(
        side_effect=[
            json.dumps(invalid_response),
            json.dumps(valid_response),
        ]
    )

    descriptions = ["Description 1"]

    result = await summarize_descriptions(
        descriptions,
        config,
        llm_client,
    )

    assert result == "Merged description."
    assert llm_client.chat.call_count == 2


@pytest.mark.asyncio
async def test_summarize_descriptions_retry_on_json_error():
    """Test retry on JSON decode error."""
    config = SummarizorConfig(
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
            json.dumps({"合并描述": "Merged description."}),
        ]
    )

    descriptions = ["Description 1"]

    result = await summarize_descriptions(
        descriptions,
        config,
        llm_client,
    )

    assert result == "Merged description."
    assert llm_client.chat.call_count == 2


@pytest.mark.asyncio
async def test_summarize_descriptions_fails_after_max_retries():
    """Test that function raises error after max retries."""
    config = SummarizorConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        max_retries=1,
    )
    llm_client = MagicMock(spec=LLMClient)

    # All attempts return invalid response
    llm_client.chat = AsyncMock(return_value="not valid json")

    descriptions = ["Description 1"]

    with pytest.raises(TranslationValidationError, match="Failed to obtain valid batch translation"):
        await summarize_descriptions(
            descriptions,
            config,
            llm_client,
        )

    # Should have tried max_retries + 1 times
    assert llm_client.chat.call_count == 2
