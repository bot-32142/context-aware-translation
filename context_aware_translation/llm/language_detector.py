from __future__ import annotations

import json
import logging
from collections.abc import Callable

from context_aware_translation.config import LLMConfig
from context_aware_translation.core.cancellation import OperationCancelledError, raise_if_cancelled
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.llm.session_trace import llm_session_scope
from context_aware_translation.utils.llm_json_cleaner import clean_llm_response

logger = logging.getLogger(__name__)


class LanguageDetectionError(Exception):
    """Raised when language detection fails."""


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
        # Sample the text if it's too long
        text_sample = text[:sample_size] if len(text) > sample_size else text

        system_prompt = """你是一个语言检测助手。分析提供的文本并确定其主要语言。

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
