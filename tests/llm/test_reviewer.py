from unittest.mock import AsyncMock, MagicMock

import pytest

from context_aware_translation.config import ReviewConfig
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.llm.reviewer import review_batch
from context_aware_translation.storage.schema.book_db import TermRecord


@pytest.mark.asyncio
async def test_review_batch_mock():
    # Setup
    config = ReviewConfig(api_key="fake", base_url="fake", model="fake-model")
    client = MagicMock(spec=LLMClient)
    client.chat = AsyncMock()

    terms = [
        TermRecord(key="Term1", descriptions={"1": "Desc1"}, occurrence={"1": 5}, votes=1, total_api_calls=1),
        TermRecord(key="Term2", descriptions={"1": "Desc2"}, occurrence={"1": 1}, votes=1, total_api_calls=1),
        TermRecord(key="Term3", descriptions={"1": "Desc3"}, occurrence={"1": 3}, votes=1, total_api_calls=1),
    ]

    # Mock Response
    client.chat.return_value = '{"keep": ["Term1", "Term3"], "ignore": ["Term2"]}'

    # Execute
    result = await review_batch(terms, client, config, "English")

    # Verify
    assert "Term1" in result["keep"]
    assert "Term3" in result["keep"]
    assert "Term2" in result["ignore"]
    assert len(result["keep"]) == 2
    assert len(result["ignore"]) == 1


@pytest.mark.asyncio
async def test_review_batch_missing_keys():
    # Setup
    config = ReviewConfig(api_key="fake", base_url="fake", model="fake-model")
    client = MagicMock(spec=LLMClient)
    client.chat = AsyncMock()

    terms = [
        TermRecord(key="Term1", descriptions={"1": "Desc1"}, occurrence={"1": 5}, votes=1, total_api_calls=1),
        TermRecord(key="Term2", descriptions={"1": "Desc2"}, occurrence={"1": 1}, votes=1, total_api_calls=1),
    ]

    # Mock Response with missing Term2 consistently (retries will fail)
    client.chat.return_value = '{"keep": ["Term1"], "ignore": []}'

    # Execute - should raise after all retries fail
    with pytest.raises(RuntimeError, match="All review attempts failed"):
        await review_batch(terms, client, config, "English")

    # Verify retried 3 times
    assert client.chat.call_count == 3

    # Verify conversational retry: messages grow each attempt
    first_call_messages = client.chat.call_args_list[0][0][0]
    second_call_messages = client.chat.call_args_list[1][0][0]
    third_call_messages = client.chat.call_args_list[2][0][0]
    assert len(first_call_messages) == 2  # system + user
    assert len(second_call_messages) == 4  # + assistant + correction
    assert len(third_call_messages) == 6  # + assistant + correction again


@pytest.mark.asyncio
async def test_review_batch_retry_success():
    # Setup
    config = ReviewConfig(api_key="fake", base_url="fake", model="fake-model")
    client = MagicMock(spec=LLMClient)
    client.chat = AsyncMock()

    terms = [
        TermRecord(key="Term1", descriptions={"1": "Desc1"}, occurrence={"1": 5}, votes=1, total_api_calls=1),
        TermRecord(key="Term2", descriptions={"1": "Desc2"}, occurrence={"1": 1}, votes=1, total_api_calls=1),
    ]

    # First attempt missing Term2, Second attempt success
    client.chat.side_effect = [
        '{"keep": ["Term1"], "ignore": []}',
        '{"keep": ["Term1"], "ignore": ["Term2"]}',
    ]

    # Execute
    result = await review_batch(terms, client, config, "English")

    # Verify success result
    assert "Term1" in result["keep"]
    assert "Term2" in result["ignore"]
    assert len(result["keep"]) == 1
    assert len(result["ignore"]) == 1
    # Verify retried 2 times
    assert client.chat.call_count == 2

    # Verify conversational retry: second call should have 4 messages
    second_call_messages = client.chat.call_args_list[1][0][0]
    assert len(second_call_messages) == 4
    assert second_call_messages[0]["role"] == "system"
    assert second_call_messages[1]["role"] == "user"
    assert second_call_messages[2]["role"] == "assistant"
    assert second_call_messages[2]["content"] == '{"keep": ["Term1"], "ignore": []}'
    assert second_call_messages[3]["role"] == "user"
    assert "error" in second_call_messages[3]["content"].lower()


@pytest.mark.asyncio
async def test_review_batch_error():
    # Setup
    config = ReviewConfig(api_key="fake", base_url="fake", model="fake-model")
    client = MagicMock(spec=LLMClient)
    client.chat = AsyncMock(side_effect=Exception("API Error"))

    terms = [
        TermRecord(key="Term1", descriptions={"1": "Desc1"}, occurrence={"1": 5}, votes=1, total_api_calls=1),
    ]

    # Execute - should raise after all retries fail
    with pytest.raises(RuntimeError, match="All review attempts failed"):
        await review_batch(terms, client, config, "English")

    # Verify fresh retry: all calls should have 2 messages (API errors = fresh start)
    for call in client.chat.call_args_list:
        call_messages = call[0][0]
        assert len(call_messages) == 2


@pytest.mark.asyncio
async def test_review_batch_cjk_variant_keys():
    """Test that CJK variant keys from LLM are remapped to expected keys."""
    config = ReviewConfig(api_key="fake", base_url="fake", model="fake-model")
    client = MagicMock(spec=LLMClient)
    client.chat = AsyncMock()

    terms = [
        TermRecord(key="種族", descriptions={"1": "Race"}, occurrence={"1": 3}, votes=1, total_api_calls=1),
        TermRecord(key="強化", descriptions={"1": "Strengthen"}, occurrence={"1": 2}, votes=1, total_api_calls=1),
        TermRecord(key="HP", descriptions={"1": "Hit Points"}, occurrence={"1": 5}, votes=1, total_api_calls=1),
    ]

    # LLM returns simplified variants instead of traditional
    client.chat.return_value = '{"keep": ["种族", "HP"], "ignore": ["强化"]}'

    result = await review_batch(terms, client, config, "日本語")

    # Keys should be remapped back to expected (traditional) keys
    assert "種族" in result["keep"]
    assert "HP" in result["keep"]
    assert "強化" in result["ignore"]
    assert len(result["keep"]) == 2
    assert len(result["ignore"]) == 1
    # Should succeed on first attempt (no retries needed)
    assert client.chat.call_count == 1
