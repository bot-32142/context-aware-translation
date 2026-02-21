from __future__ import annotations

from types import SimpleNamespace

from context_aware_translation.llm.image_backends.openai_backend import OpenAIImageGenerator
from context_aware_translation.llm.image_backends.qwen_backend import QwenImageGenerator


def test_openai_image_extract_usage_with_cache_and_reasoning() -> None:
    usage = SimpleNamespace(
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        input_tokens_details=SimpleNamespace(cached_tokens=30),
        output_tokens_details=SimpleNamespace(reasoning_tokens=10),
    )

    assert OpenAIImageGenerator._extract_token_usage(usage) == {
        "total_tokens": 150,
        "cached_input_tokens": 30,
        "uncached_input_tokens": 70,
        "output_tokens": 40,
        "reasoning_tokens": 10,
    }


def test_openai_image_extract_usage_reconciles_total_delta() -> None:
    usage = SimpleNamespace(
        input_tokens=2791,
        output_tokens=818,
        total_tokens=12019,
    )

    assert OpenAIImageGenerator._extract_token_usage(usage) == {
        "total_tokens": 12019,
        "cached_input_tokens": 0,
        "uncached_input_tokens": 2791,
        "output_tokens": 818,
        "reasoning_tokens": 8410,
    }


def test_qwen_image_extract_usage_with_cache_and_reasoning() -> None:
    usage = {
        "input_tokens": 3019,
        "output_tokens": 104,
        "total_tokens": 3123,
        "input_tokens_details": {"cached_tokens": 2048},
        "output_tokens_details": {"reasoning_tokens": 12},
    }

    assert QwenImageGenerator._extract_token_usage(usage) == {
        "total_tokens": 3123,
        "cached_input_tokens": 2048,
        "uncached_input_tokens": 971,
        "output_tokens": 92,
        "reasoning_tokens": 12,
    }


def test_qwen_image_extract_usage_reconciles_total_delta() -> None:
    usage = {
        "prompt_tokens": 2791,
        "completion_tokens": 818,
        "total_tokens": 12019,
    }

    assert QwenImageGenerator._extract_token_usage(usage) == {
        "total_tokens": 12019,
        "cached_input_tokens": 0,
        "uncached_input_tokens": 2791,
        "output_tokens": 818,
        "reasoning_tokens": 8410,
    }
