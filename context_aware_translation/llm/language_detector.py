from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable

from context_aware_translation.config import LLMConfig
from context_aware_translation.core.cancellation import OperationCancelledError, raise_if_cancelled
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.llm.session_trace import llm_session_scope
from context_aware_translation.utils.llm_json_cleaner import clean_llm_response

logger = logging.getLogger(__name__)


class LanguageDetectionError(Exception):
    """Raised when language detection fails."""


def _build_representative_text_sample(text: str, sample_size: int) -> str:
    """Return a representative sample spread across the full input text."""
    if sample_size <= 0:
        return text

    normalized_text = text.strip()
    if len(normalized_text) <= sample_size:
        return normalized_text

    window_count = min(5, max(2, math.ceil(len(normalized_text) / sample_size)))
    separator = "\n"
    text_budget = max(window_count, sample_size - (len(separator) * (window_count - 1)))
    window_budget = max(1, text_budget // window_count)
    span_size = math.ceil(len(normalized_text) / window_count)

    snippets: list[str] = []
    for index in range(window_count):
        span_start = index * span_size
        span_end = min(len(normalized_text), span_start + span_size)
        if span_start >= span_end:
            break

        while span_start < span_end and normalized_text[span_start].isspace():
            span_start += 1
        if span_start >= span_end:
            continue

        snippet = normalized_text[span_start : min(span_end, span_start + window_budget)].strip()
        if snippet:
            snippets.append(snippet)

    if not snippets:
        return normalized_text[:sample_size]
    return separator.join(snippets)


async def detect_source_language(
    text: str,
    llm_client: LLMClient,
    extractor_config: LLMConfig,
    sample_size: int = 1000,
    cancel_check: Callable[[], bool] | None = None,
) -> str:
    """
    Detect the source language of the given text using LLM.

    Args:
        text: The text to detect language from
        llm_client: LLM client for making API calls
        extractor_config: Extractor configuration object
        sample_size: Number of characters to sample from the text for detection

    Returns:
        Detected language name in Chinese (e.g., "日语", "英语", "中文")

    Raises:
        LanguageDetectionError: If language detection fails after retries
    """
    with llm_session_scope() as session_id:
        # Sample the text if it's too long, keeping coverage across the whole input.
        text_sample = _build_representative_text_sample(text, sample_size)

        system_prompt = """你是一个语言检测助手。分析提供的文本并确定其主要语言。

如果文本包含封面、版权页、目录、许可证、网站模板、导航、作者信息等前后附加内容，请忽略这些噪声，判断正文/主体内容的主要语言。

仅返回一个JSON对象，包含单个字段"语言"，值为中文语言名称。

示例：
- 日语文本：{"语言": "日语"}
- 英语文本：{"语言": "英语"}
- 中文文本：{"语言": "中文"}
- 韩语文本：{"语言": "韩语"}
- 混合语言文本，返回主要语言

要求简洁准确。仅返回JSON对象，不要添加任何解释。"""

        user_prompt = f"""检测以下文本的语言：

{text_sample}"""

        attempts = extractor_config.max_retries + 1
        last_error: Exception | None = None

        for attempt in range(attempts):
            raise_if_cancelled(cancel_check)
            try:
                response = await llm_client.chat(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    extractor_config,
                    temperature=0.0,  # Use low temperature for deterministic results
                    response_format={"type": "json_object"},
                    cancel_check=cancel_check,
                )

                parsed = json.loads(clean_llm_response(response))
                language = parsed.get("语言")

                if not language or not isinstance(language, str):
                    raise ValueError("Response missing or invalid '语言' field")

                logger.info("[llm_session=%s] Detected source language: %s", session_id, language)
                return str(language).strip()

            except (json.JSONDecodeError, ValueError, KeyError) as e:
                last_error = e
                logger.warning(
                    "[llm_session=%s] Error parsing language detection response (attempt %s/%s): %s",
                    session_id,
                    attempt + 1,
                    attempts,
                    e,
                )
                if attempt < attempts - 1:
                    continue
                raise LanguageDetectionError(
                    f"[llm_session={session_id}] Failed to detect language after {attempts} attempts: {last_error}"
                ) from e

            except Exception as e:
                if isinstance(e, OperationCancelledError):
                    raise
                last_error = e
                logger.warning(
                    "[llm_session=%s] Unexpected error during language detection (attempt %s/%s): %s",
                    session_id,
                    attempt + 1,
                    attempts,
                    e,
                )
                if attempt < attempts - 1:
                    continue
                raise LanguageDetectionError(
                    f"[llm_session={session_id}] Failed to detect language after {attempts} attempts: {last_error}"
                ) from e

        raise LanguageDetectionError(
            f"[llm_session={session_id}] Failed to detect language after {attempts} attempts: {last_error}"
        )
