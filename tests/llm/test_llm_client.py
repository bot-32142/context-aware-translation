from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from openai import RateLimitError

from context_aware_translation.config import LLMConfig
from context_aware_translation.llm.client import (
    LLMAuthError,
    LLMClient,
    LLMError,
)


def test_llm_config_defaults():
    config = LLMConfig()
    assert config.api_key is None
    assert config.base_url is None
    assert config.timeout == 120.0
    assert config.max_retries == 3


def test_llm_config_env_overrides():
    config = LLMConfig(
        api_key="test-key",
        base_url="https://custom.example.com/v1",
        api_version="2024-01-01",
    )
    assert config.base_url == "https://custom.example.com/v1"
    assert config.api_version == "2024-01-01"


def test_llm_client_missing_key():
    config = LLMConfig(api_key=None, base_url="https://api.test.com/v1", model="test-model")
    # LLMClient now requires api_key at initialization
    with pytest.raises(LLMAuthError, match="OPENAI_API_KEY not set"):
        LLMClient(config)


@pytest.mark.asyncio
async def test_llm_client_success():
    from context_aware_translation.config import ExtractorConfig

    config = LLMConfig(api_key="test-key", base_url="https://api.test.com/v1")
    step_config = ExtractorConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
    )
    with patch("context_aware_translation.llm.client.OpenAI") as mock_openai:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = "Test response"
        # Set usage to None to avoid MagicMock issues in token extraction
        mock_response.usage = None
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        client = LLMClient(config)
        result = await client.chat(
            messages=[{"role": "user", "content": "test"}],
            step_config=step_config,
        )
        assert result == "Test response"
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["temperature"] == 0.0


@pytest.mark.asyncio
async def test_llm_client_retry_on_rate_limit():
    from context_aware_translation.config import ExtractorConfig

    config = LLMConfig(api_key="test-key", max_retries=2, timeout=30.0)
    step_config = ExtractorConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        max_retries=2,
        timeout=30.0,
    )
    with patch("context_aware_translation.llm.client.OpenAI") as mock_openai:
        from openai import RateLimitError

        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = "Success"
        mock_response.usage = None  # Avoid MagicMock issues
        mock_client.chat.completions.create.side_effect = [
            RateLimitError("Rate limited", response=MagicMock(), body={}),
            RateLimitError("Rate limited", response=MagicMock(), body={}),
            mock_response,
        ]

        client = LLMClient(config)
        result = await client.chat(messages=[{"role": "user", "content": "test"}], step_config=step_config)
        assert result == "Success"
        assert mock_client.chat.completions.create.call_count >= 2


@pytest.mark.asyncio
async def test_llm_client_uses_step_config_retry_budget():
    from context_aware_translation.config import ExtractorConfig

    # Base client has no retries, but step config should still allow retries.
    config = LLMConfig(api_key="test-key", max_retries=0, timeout=30.0)
    step_config = ExtractorConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        max_retries=2,
        timeout=30.0,
    )

    with patch("context_aware_translation.llm.client.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = "Recovered"
        mock_response.usage = None

        mock_client.chat.completions.create.side_effect = [
            RateLimitError("Rate limited", response=MagicMock(), body={}),
            RateLimitError("Rate limited", response=MagicMock(), body={}),
            mock_response,
        ]

        client = LLMClient(config)
        result = await client.chat(messages=[{"role": "user", "content": "test"}], step_config=step_config)

        assert result == "Recovered"
        assert mock_client.chat.completions.create.call_count == 3


@pytest.mark.asyncio
async def test_llm_client_retry_preserves_model_override():
    from context_aware_translation.config import ExtractorConfig

    config = LLMConfig(api_key="test-key", max_retries=1, timeout=30.0)
    step_config = ExtractorConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="default-model",
        max_retries=1,
        timeout=30.0,
    )

    with patch("context_aware_translation.llm.client.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = "ok"
        mock_response.usage = None

        mock_client.chat.completions.create.side_effect = [
            RateLimitError("Rate limited", response=MagicMock(), body={}),
            mock_response,
        ]

        client = LLMClient(config)
        result = await client.chat(
            messages=[{"role": "user", "content": "test"}],
            step_config=step_config,
            model="override-model",
        )

        assert result == "ok"
        assert mock_client.chat.completions.create.call_count == 2
        models = [call.kwargs["model"] for call in mock_client.chat.completions.create.call_args_list]
        assert models == ["override-model", "override-model"]


@pytest.mark.asyncio
async def test_llm_client_retry_on_timeout():
    from context_aware_translation.config import ExtractorConfig

    config = LLMConfig(api_key="test-key", max_retries=2, timeout=30.0)
    step_config = ExtractorConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        max_retries=2,
        timeout=30.0,
    )
    with patch("context_aware_translation.llm.client.OpenAI") as mock_openai:
        from openai import APITimeoutError

        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = "Success"
        mock_response.usage = None  # Avoid MagicMock issues
        timeout_error = APITimeoutError("Timeout")
        mock_client.chat.completions.create.side_effect = [
            timeout_error,
            mock_response,
        ]

        client = LLMClient(config)
        result = await client.chat(messages=[{"role": "user", "content": "test"}], step_config=step_config)
        assert result == "Success"
        assert mock_client.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_llm_client_retry_on_server_error():
    from context_aware_translation.config import ExtractorConfig

    config = LLMConfig(api_key="test-key", max_retries=2, timeout=30.0)
    step_config = ExtractorConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        max_retries=2,
        timeout=30.0,
    )
    with patch("context_aware_translation.llm.client.OpenAI") as mock_openai:
        from openai import APIError

        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        error_500 = APIError("Server error", body={}, request=MagicMock())
        error_500.status_code = 500
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = "Success"
        mock_response.usage = None  # Avoid MagicMock issues
        mock_client.chat.completions.create.side_effect = [error_500, mock_response]

        client = LLMClient(config)
        result = await client.chat(messages=[{"role": "user", "content": "test"}], step_config=step_config)
        assert result == "Success"
        assert mock_client.chat.completions.create.call_count >= 2


@pytest.mark.asyncio
async def test_llm_client_auth_error():
    from context_aware_translation.config import ExtractorConfig

    config = LLMConfig(api_key="test-key", timeout=30.0)
    step_config = ExtractorConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        timeout=30.0,
    )
    with patch("context_aware_translation.llm.client.OpenAI") as mock_openai:
        from openai import APIError

        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        error_401 = APIError("Unauthorized", body={}, request=MagicMock())
        error_401.status_code = 401
        mock_client.chat.completions.create.side_effect = error_401

        client = LLMClient(config)
        with pytest.raises(LLMAuthError, match="Authentication failed"):
            await client.chat(messages=[{"role": "user", "content": "test"}], step_config=step_config)


@pytest.mark.asyncio
async def test_llm_client_model_override():
    from context_aware_translation.config import ExtractorConfig

    config = LLMConfig(api_key="test-key")
    step_config = ExtractorConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="default-model",
    )
    with patch("context_aware_translation.llm.client.OpenAI") as mock_openai:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = "Test"
        mock_response.usage = None  # Avoid MagicMock issues
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        client = LLMClient(config)
        await client.chat(
            messages=[{"role": "user", "content": "test"}], step_config=step_config, model="override-model"
        )
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "override-model"


@pytest.mark.asyncio
async def test_llm_client_model_default():
    from context_aware_translation.config import ExtractorConfig

    config = LLMConfig(api_key="test-key")
    step_config = ExtractorConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="default-model",
    )
    with patch("context_aware_translation.llm.client.OpenAI") as mock_openai:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = "Test"
        mock_response.usage = None  # Avoid MagicMock issues
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        client = LLMClient(config)
        await client.chat(messages=[{"role": "user", "content": "test"}], step_config=step_config)
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "default-model"


@pytest.mark.asyncio
async def test_llm_client_strips_provider_kwarg_from_openai_create():
    from context_aware_translation.config import ExtractorConfig

    config = LLMConfig(api_key="test-key")
    step_config = ExtractorConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="default-model",
        kwargs={"provider": "deepseek", "top_p": 0.7},
    )
    with patch("context_aware_translation.llm.client.OpenAI") as mock_openai:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = "Test"
        mock_response.usage = None
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        client = LLMClient(config)
        await client.chat(messages=[{"role": "user", "content": "test"}], step_config=step_config)

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert "provider" not in call_kwargs
        assert call_kwargs["top_p"] == 0.7


@pytest.mark.asyncio
async def test_llm_client_empty_response():
    from context_aware_translation.config import ExtractorConfig

    config = LLMConfig(api_key="test-key", timeout=30.0)
    step_config = ExtractorConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        timeout=30.0,
    )
    with patch("context_aware_translation.llm.client.OpenAI") as mock_openai:
        mock_response = MagicMock()
        mock_response.choices = []
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        client = LLMClient(config)
        with pytest.raises(LLMError, match="Empty response"):
            await client.chat(messages=[{"role": "user", "content": "test"}], step_config=step_config)


@pytest.mark.asyncio
async def test_llm_client_null_content():
    from context_aware_translation.config import ExtractorConfig

    config = LLMConfig(api_key="test-key", timeout=30.0)
    step_config = ExtractorConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        timeout=30.0,
    )
    with patch("context_aware_translation.llm.client.OpenAI") as mock_openai:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = None
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        client = LLMClient(config)
        with pytest.raises(LLMError, match="Null content"):
            await client.chat(messages=[{"role": "user", "content": "test"}], step_config=step_config)


@pytest.mark.asyncio
async def test_llm_client_no_max_tokens_when_none():
    """Test that max_tokens is not passed to API when it's None."""
    from context_aware_translation.config import ExtractorConfig

    config = LLMConfig(api_key="test-key")
    step_config = ExtractorConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
    )
    with patch("context_aware_translation.llm.client.OpenAI") as mock_openai:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = "Test"
        mock_response.usage = None  # Avoid MagicMock issues
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        client = LLMClient(config)
        await client.chat(messages=[{"role": "user", "content": "test"}], step_config=step_config)
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert "max_tokens" not in call_kwargs


@pytest.mark.asyncio
async def test_llm_client_max_tokens_when_provided():
    """Test that max_tokens is passed to API when provided."""
    from context_aware_translation.config import ExtractorConfig

    config = LLMConfig(api_key="test-key")
    step_config = ExtractorConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
    )
    with patch("context_aware_translation.llm.client.OpenAI") as mock_openai:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = "Test"
        mock_response.usage = None  # Avoid MagicMock issues
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        client = LLMClient(config)
        await client.chat(messages=[{"role": "user", "content": "test"}], step_config=step_config, max_tokens=2048)
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["max_tokens"] == 2048


@pytest.mark.asyncio
async def test_llm_client_checks_token_limit():
    """Test that chat() calls TokenTracker.check_limit when tracker is initialized."""
    from context_aware_translation.config import ExtractorConfig
    from context_aware_translation.llm.token_tracker import TokenLimitExceededError, TokenTracker

    config = LLMConfig(api_key="test-key", base_url="https://api.test.com/v1")
    step_config = ExtractorConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        endpoint_profile="my-profile",
    )

    with patch("context_aware_translation.llm.client.OpenAI") as mock_openai:
        mock_openai.return_value = MagicMock()
        client = LLMClient(config)

    # Mock the tracker to raise TokenLimitExceededError
    mock_tracker = MagicMock()
    mock_tracker.check_limit.side_effect = TokenLimitExceededError("limit exceeded")

    with (
        patch.object(TokenTracker, "get", return_value=mock_tracker),
        pytest.raises(TokenLimitExceededError, match="limit exceeded"),
    ):
        await client.chat(
            messages=[{"role": "user", "content": "test"}],
            step_config=step_config,
        )
    mock_tracker.check_limit.assert_called_once_with("my-profile")


@pytest.mark.asyncio
async def test_llm_client_records_token_usage():
    """Test that _chat_impl calls TokenTracker.record_usage after successful call."""
    from context_aware_translation.config import ExtractorConfig
    from context_aware_translation.llm.token_tracker import TokenTracker

    config = LLMConfig(api_key="test-key", base_url="https://api.test.com/v1")
    step_config = ExtractorConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
        endpoint_profile="my-profile",
    )

    with patch("context_aware_translation.llm.client.OpenAI") as mock_openai:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = "Test response"
        # Set up usage data
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 50
        mock_usage.total_tokens = 150
        mock_usage.prompt_cache_hit_tokens = 0
        mock_usage.prompt_cache_miss_tokens = 0
        mock_usage.prompt_tokens_details = None
        mock_usage.completion_tokens_details = None
        mock_usage.output_tokens_details = None
        mock_response.usage = mock_usage
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        client = LLMClient(config)

        mock_tracker = MagicMock()
        mock_tracker.check_limit.return_value = None

        with patch.object(TokenTracker, "get", return_value=mock_tracker):
            result = await client.chat(
                messages=[{"role": "user", "content": "test"}],
                step_config=step_config,
            )
            assert result == "Test response"

        mock_tracker.record_usage.assert_called_once_with(
            "my-profile",
            {"cached_input_tokens": 0, "uncached_input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        )


@pytest.mark.asyncio
async def test_llm_client_noop_when_tracker_not_initialized():
    """Test that both check_limit and record_usage are no-ops when tracker is None."""
    from context_aware_translation.config import ExtractorConfig
    from context_aware_translation.llm.token_tracker import TokenTracker

    config = LLMConfig(api_key="test-key", base_url="https://api.test.com/v1")
    step_config = ExtractorConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
    )

    with patch("context_aware_translation.llm.client.OpenAI") as mock_openai:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = "Test response"
        mock_response.usage = None
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        client = LLMClient(config)

        # Ensure tracker is not initialized
        TokenTracker.shutdown()
        result = await client.chat(
            messages=[{"role": "user", "content": "test"}],
            step_config=step_config,
        )
        assert result == "Test response"


@pytest.mark.asyncio
async def test_llm_client_chat_assigns_session_id_when_missing():
    from context_aware_translation.config import ExtractorConfig
    from context_aware_translation.llm.session_trace import get_llm_session_id

    config = LLMConfig(api_key="test-key", base_url="https://api.test.com/v1")
    step_config = ExtractorConfig(
        api_key="test-key",
        base_url="https://api.test.com/v1",
        model="test-model",
    )

    with patch("context_aware_translation.llm.client.OpenAI") as mock_openai:
        mock_openai.return_value = MagicMock()
        client = LLMClient(config)

        def _fake_chat_impl(*_args, **_kwargs):
            return get_llm_session_id() or ""

        with patch.object(client, "_chat_impl", side_effect=_fake_chat_impl):
            session_id = await client.chat(
                messages=[{"role": "user", "content": "test"}],
                step_config=step_config,
            )

    assert isinstance(session_id, str)
    assert len(session_id) == 32
