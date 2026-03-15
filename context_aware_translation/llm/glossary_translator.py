from __future__ import annotations

import copy
import json
import logging
from collections.abc import Callable

from context_aware_translation.config import GlossaryTranslationConfig
from context_aware_translation.core.cancellation import OperationCancelledError, raise_if_cancelled
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.llm.session_trace import llm_session_scope
from context_aware_translation.llm.translator import TranslationValidationError
from context_aware_translation.utils.cjk_normalize import build_normalized_key_mapping
from context_aware_translation.utils.llm_json_cleaner import clean_llm_response

logger = logging.getLogger(__name__)


def _build_batch_system_prompt(source_language: str, target_language: str) -> str:
    """
    Build system prompt for batch translation of similar terms.
    """
    return (
        "---角色---\n"
        f"你负责翻译{source_language}名称。\n\n"
        "---指令---\n"
        f"1) 翻译：为每个 `待翻译名称` 提供清晰的 `{target_language}` 译名。翻译完成后的文本不得包含{source_language}。\n"
        "2) 保留非源语言文本不翻译：如果原文中出现其他语言的文本（例如日语文本中出现英语），应保持原样不翻译。\n"
        "3) 严格输出 JSON，包含 `新翻译`；不要输出 Markdown 或额外文本。新翻译这个词请保持原样（简体中文），切无更改。\n"
        "4) 数量一致：输出的「新翻译」条目数必须与输入的「待翻译术语组」条目数完全一致。即使多个术语看起来相似，也必须为每个术语分别提供翻译，不得合并或省略。\n"
        "5) 一致性要求：\n"
        '   - 如果"相似已存在术语"中有已翻译的术语，新翻译应与其保持一致。\n'
        '     例如：如果"John Smith"已翻译为"约翰史密斯"，则"John Smith Jr."应翻译为"小约翰史密斯"（保留共同基础）。\n'
        '   - 如果"待翻译术语组"中有多个相似术语，应作为一组统一翻译，确保相似部分翻译一致。\n'
        '     例如：如果同时翻译"John Smith Jr."和"John Smith Sr."，应确保"John Smith"部分翻译一致。\n'
        "---示例---\n"
        "输入:\n"
        "{\n"
        '  "目标语言": "简体中文",\n'
        '  "待翻译术语组": [\n'
        "    {\n"
        '      "描述": "John Smith Jr. is a character.",\n'
        '      "待翻译名称": "John Smith Jr."\n'
        "    }\n"
        "  ],\n"
        '  "相似已存在术语": {\n'
        '    "John Smith": "约翰史密斯"\n'
        "  }\n"
        "}\n"
        "期望输出:\n"
        "{\n"
        '  "新翻译": {"John Smith Jr.": "小约翰史密斯"}\n'
        "}\n\n"
        "示例 2（保留非源语言文本）:\n"
        "输入:\n"
        "{\n"
        '  "目标语言": "简体中文",\n'
        '  "待翻译术语组": [\n'
        "    {\n"
        '      "描述": "角色的体力值。 生命值，代表角色或生物的生命力或耐久度。 ヒットポイント。キャラクターの体力を表す数値。 表示玩家生命值的数值，数值过低会导致角色死亡。",\n'
        '      "待翻译名称": "HP"\n'
        "    }\n"
        "  ],\n"
        '  "相似已存在术语": {}\n'
        "}\n"
        "期望输出:\n"
        "{\n"
        '  "新翻译": {"HP": "HP"}\n'
        "}\n\n"
    )


def _build_batch_user_payload(
    terms: list[dict[str, str]],
    translated_names: dict[str, str],
    target_language: str,
) -> str:
    """
    Build user payload for batch translation of similar terms.
    """
    terms_to_translate = []
    for term in terms:
        term_dict = {"描述": term["description"]}
        if term.get("missing_names") is not None:
            term_dict["待翻译名称"] = term["missing_names"]
        terms_to_translate.append(term_dict)

    payload = {
        "目标语言": target_language,
        "待翻译术语组": terms_to_translate,
        "相似已存在术语": translated_names,
    }

    return json.dumps(payload, ensure_ascii=False, indent=2)


def _validate_batch_response(
    data: dict,
    to_translate: list[dict[str, str]],
    *,
    strict: bool = True,
) -> dict[str, str]:
    """
    Validate batch translation response.

    Args:
        strict: If True, raise on missing terms. If False, skip missing terms
                and return partial results.

    Returns:
        Dict mapping canonical_name -> translated_name
    """
    translations = data.get("新翻译", {})
    # Validate translations
    if not isinstance(translations, dict):
        raise TranslationValidationError("新翻译 must be an object")

    # Build expected key set
    expected_keys = {ent["missing_names"] for ent in to_translate if ent["missing_names"] is not None}

    # Fast path: check if all keys match exactly
    if expected_keys <= translations.keys():
        for name in expected_keys:
            if strict and (not isinstance(translations[name], str) or not translations[name].strip()):
                raise TranslationValidationError(f"Missing 新翻译 for {name}")
        return {
            k: translations[k] for k in expected_keys if isinstance(translations[k], str) and translations[k].strip()
        }

    # Slow path: normalize CJK variants and remap
    key_map = build_normalized_key_mapping(translations.keys(), expected_keys)

    remapped: dict[str, str] = {}
    for name in expected_keys:
        llm_key = key_map.get(name)
        val = translations[llm_key] if llm_key else None
        if not isinstance(val, str) or not val.strip():
            if strict:
                raise TranslationValidationError(f"Missing 新翻译 for {name}")
            continue
        remapped[name] = val

    return remapped


async def translate_glossary(
    to_translate: list[dict[str, str]],
    translated_names: dict[str, str],
    glossary_config: GlossaryTranslationConfig,
    translation_target_language: str,
    source_language: str,
    llm_client: LLMClient,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, str]:
    """
    Translate a group of similar terms together for consistency.
    """
    if not to_translate:
        return {}

    with llm_session_scope() as session_id:
        system_prompt = _build_batch_system_prompt(source_language, translation_target_language)
        user_payload = _build_batch_user_payload(
            to_translate,
            translated_names,
            translation_target_language,
        )

        initial_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_payload},
        ]
        messages = copy.deepcopy(initial_messages)

        attempts = glossary_config.max_retries + 1
        last_error: Exception | None = None
        last_parsed: dict | None = None
        for attempt in range(attempts):
            try:
                raise_if_cancelled(cancel_check)
                response = await llm_client.chat(
                    copy.deepcopy(messages),
                    glossary_config,
                    response_format={"type": "json_object"},
                    cancel_check=cancel_check,
                )
                raw_response = clean_llm_response(response)
                parsed = json.loads(raw_response)
                last_parsed = parsed
                return _validate_batch_response(parsed, to_translate)
            except TranslationValidationError as e:
                last_error = e
                # Conversational retry: append response + correction
                messages.append({"role": "assistant", "content": raw_response})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your previous response had an error: {e}. "
                            "Please correct it and return the complete JSON response again. "
                            "Follow exactly the same format and return JSON only."
                        ),
                    }
                )
                logger.warning(
                    "[llm_session=%s] Validation error during batch translation (attempt %s/%s): %s",
                    session_id,
                    attempt + 1,
                    attempts,
                    e,
                )
            except json.JSONDecodeError as e:
                last_error = e
                # Fresh start — no valid response to reference
                messages = copy.deepcopy(initial_messages)
                logger.warning(
                    "[llm_session=%s] JSON decode error during batch translation (attempt %s/%s): %s",
                    session_id,
                    attempt + 1,
                    attempts,
                    e,
                )
            except Exception as e:
                if isinstance(e, OperationCancelledError):
                    raise
                last_error = e
                # Fresh start for unexpected errors
                messages = copy.deepcopy(initial_messages)
                logger.warning(
                    "[llm_session=%s] Unexpected error during batch translation (attempt %s/%s): %s",
                    session_id,
                    attempt + 1,
                    attempts,
                    e,
                )

        # All retries exhausted — return partial results if we got any valid JSON
        if last_parsed is not None:
            partial = _validate_batch_response(last_parsed, to_translate, strict=False)
            expected_keys = {ent["missing_names"] for ent in to_translate if ent["missing_names"] is not None}
            missing = expected_keys - partial.keys()
            if missing:
                logger.warning(
                    "[llm_session=%s] Glossary terms left untranslated after %s attempts: %s",
                    session_id,
                    attempts,
                    missing,
                )
            return partial

        raise TranslationValidationError(
            f"[llm_session={session_id}] Failed to obtain valid batch translation/merge after "
            f"{attempts} attempts: {last_error}"
        )
