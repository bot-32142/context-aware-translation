from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from context_aware_translation.config import ImageReembeddingConfig
from context_aware_translation.llm.image_backends.gemini_backend import GeminiImageGenerator


def _build_response(usage_meta: object) -> object:
    image_part = SimpleNamespace(inline_data=SimpleNamespace(data=b"edited-image"))
    candidate = SimpleNamespace(content=SimpleNamespace(parts=[image_part]))
    return SimpleNamespace(candidates=[candidate], usage_metadata=usage_meta)


@pytest.mark.asyncio
async def test_edit_image_records_thought_tokens_in_reasoning_usage() -> None:
    usage_meta = SimpleNamespace(
        prompt_token_count=2791,
        cached_content_token_count=0,
        candidates_token_count=818,
        thoughts_token_count=8410,
        tool_use_prompt_token_count=0,
        total_token_count=12019,
    )
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _build_response(usage_meta)

    with patch(
        "context_aware_translation.llm.image_backends.gemini_backend.genai.Client",
        return_value=mock_client,
    ):
        generator = GeminiImageGenerator(
            ImageReembeddingConfig(
                api_key="test-key",
                model="gemini-2.0-flash-exp-image-generation",
            )
        )

    generator._record_token_usage = MagicMock()
    result = await generator.edit_image(b"fake-bytes", "image/png", [("原文", "translated text")])

    assert result == b"edited-image"
    token_usage = generator._record_token_usage.call_args.args[0]
    assert token_usage["total_tokens"] == 12019
    assert token_usage["cached_input_tokens"] == 0
    assert token_usage["uncached_input_tokens"] == 2791
    assert token_usage["output_tokens"] == 818
    assert token_usage["reasoning_tokens"] == 8410


@pytest.mark.asyncio
async def test_edit_image_reconciles_unattributed_total_tokens_into_reasoning() -> None:
    usage_meta = SimpleNamespace(
        prompt_token_count=100,
        cached_content_token_count=20,
        candidates_token_count=30,
        thoughts_token_count=0,
        tool_use_prompt_token_count=0,
        total_token_count=200,
    )
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _build_response(usage_meta)

    with patch(
        "context_aware_translation.llm.image_backends.gemini_backend.genai.Client",
        return_value=mock_client,
    ):
        generator = GeminiImageGenerator(
            ImageReembeddingConfig(
                api_key="test-key",
                model="gemini-2.0-flash-exp-image-generation",
            )
        )

    generator._record_token_usage = MagicMock()
    await generator.edit_image(b"fake-bytes", "image/png", [("原文", "translated text")])

    token_usage = generator._record_token_usage.call_args.args[0]
    accounted = (
        token_usage["cached_input_tokens"]
        + token_usage["uncached_input_tokens"]
        + token_usage["output_tokens"]
        + token_usage["reasoning_tokens"]
    )
    assert token_usage["reasoning_tokens"] == 70
    assert accounted == token_usage["total_tokens"] == 200
