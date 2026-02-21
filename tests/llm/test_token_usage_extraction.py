from __future__ import annotations

from types import SimpleNamespace

from context_aware_translation.llm.client import _extract_token_usage


def test_extract_token_usage_openai_cached_and_reasoning() -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            prompt_tokens_details=SimpleNamespace(cached_tokens=30),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=10),
        )
    )

    assert _extract_token_usage(response) == {
        "cached_input_tokens": 30,
        "uncached_input_tokens": 70,
        "output_tokens": 40,
        "reasoning_tokens": 10,
        "total_tokens": 150,
    }


def test_extract_token_usage_deepseek_cache_fields() -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=60,
            total_tokens=160,
            prompt_cache_hit_tokens=80,
            prompt_cache_miss_tokens=20,
        )
    )

    assert _extract_token_usage(response) == {
        "cached_input_tokens": 80,
        "uncached_input_tokens": 20,
        "output_tokens": 60,
        "total_tokens": 160,
    }


def test_extract_token_usage_anthropic_native_cache_fields() -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=40,
            cache_creation_input_tokens=30,
            cache_read_input_tokens=50,
        )
    )

    assert _extract_token_usage(response) == {
        "cached_input_tokens": 50,
        "uncached_input_tokens": 130,
        "output_tokens": 40,
        "total_tokens": 220,
    }


def test_extract_token_usage_qwen_cache_creation_nested_fields() -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=3019,
            completion_tokens=104,
            total_tokens=3123,
            prompt_tokens_details=SimpleNamespace(
                cached_tokens=2048,
                cache_creation=SimpleNamespace(cache_creation_input_tokens=64),
            ),
        )
    )

    assert _extract_token_usage(response) == {
        "cached_input_tokens": 2048,
        "uncached_input_tokens": 971,
        "output_tokens": 104,
        "total_tokens": 3123,
    }


def test_extract_token_usage_reconciles_unattributed_total_to_reasoning() -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=2791,
            completion_tokens=818,
            total_tokens=12019,
        )
    )

    assert _extract_token_usage(response) == {
        "cached_input_tokens": 0,
        "uncached_input_tokens": 2791,
        "output_tokens": 818,
        "reasoning_tokens": 8410,
        "total_tokens": 12019,
    }


def test_extract_token_usage_output_details_reasoning_alias() -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=500,
            output_tokens=300,
            total_tokens=800,
            output_tokens_details=SimpleNamespace(reasoning_tokens=120),
        )
    )

    assert _extract_token_usage(response) == {
        "cached_input_tokens": 0,
        "uncached_input_tokens": 500,
        "output_tokens": 180,
        "reasoning_tokens": 120,
        "total_tokens": 800,
    }


def test_extract_token_usage_none_without_usage() -> None:
    response = SimpleNamespace(usage=None)
    assert _extract_token_usage(response) is None
