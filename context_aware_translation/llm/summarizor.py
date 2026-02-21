from __future__ import annotations

import json
import logging
from collections.abc import Callable

from context_aware_translation.config import SummarizorConfig
from context_aware_translation.core.cancellation import OperationCancelledError, raise_if_cancelled
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.llm.session_trace import llm_session_scope
from context_aware_translation.llm.translator import TranslationValidationError
from context_aware_translation.utils.llm_json_cleaner import clean_llm_response

logger = logging.getLogger(__name__)


def _build_batch_system_prompt() -> str:
    """
    Build system prompt for merging descriptions.
    """
    return """\
---角色---
你负责合并描述，生成简短的术语定义供翻译参考。

---指令---
1) 只保留对翻译有帮助的信息：定义、身份、类别、关键关系、区分性特征。
2) 省略情节细节、叙事事件、重复信息。尽量控制在1-2句以内。若前后信息矛盾，以后文为主。
3) 不要翻译任何内容，使用原文描述的语言。
4) 严格输出 JSON，包含 `合并描述`；不要输出 Markdown 或额外文本。合并描述这个词请保持原样（简体中文），切勿更改。
---示例---
输入:
{
  "待合并描述": [
    "John Smith Jr. is a character."
  ]
}
期望输出:
{
  "合并描述": "John Smith Jr. is a character."
}

示例 2（合并多个重复描述）:
输入:
{
  "待合并描述": [
    "キャラメイクで選択可能な、やけに目力の強い鳥を模った覆面。",
    "プレイヤーキャラクターが装備している頭防具で、VITを2上昇させる効果がある。",
    "头部装备，提供VIT（耐久力）+2的加成。",
    "サンラクが頭に装備している防具で、VITを2上昇させる効果を持つ。",
    "VIT+2の効果を持つ頭部装備。",
    "一种头部装备，能增加VIT属性。",
    "ゲーム内の装備品または外観の一部。サンラクの特徴の一つ。",
    "凝視の鳥面はサンラクサンが装着していた頭装備で、外すことができる覆面。",
    "サンラクが装備している頭防具。VITを1上昇させる。",
    "凝視の鳥面是角色装备在头部的防具，可提供VIT+1的属性加成。",
    "サンラクが装備している頭防具で、VIT（耐久力）を1上昇させる効果を持つ。",
    "一个鸟形面具，装备在头部，能增加VIT属性。"
  ]
}
期望输出:
{
  "合并描述": "鳥を模した頭部防具（覆面）。サンラクが装備。"
}"""


def _build_batch_user_payload(
    descriptions: list[str],
) -> str:
    """
    Build user payload for merging descriptions.
    """
    payload = {
        "待合并描述": descriptions,
    }

    return json.dumps(payload, ensure_ascii=False, indent=2)


def _validate_batch_response(
    data: dict,
) -> str:
    """
    Validate batch summarization response.

    Returns:
        Merged description string.
    """
    merged_description = data.get("合并描述", "")
    if not isinstance(merged_description, str) or not merged_description.strip():
        raise TranslationValidationError("合并描述 must be a string")
    return merged_description


async def summarize_descriptions(
    descriptions: list[str],
    summarizor_config: SummarizorConfig,
    llm_client: LLMClient,
    cancel_check: Callable[[], bool] | None = None,
) -> str:
    if not descriptions:
        return ""

    with llm_session_scope() as session_id:
        system_prompt = _build_batch_system_prompt()
        user_payload = _build_batch_user_payload(descriptions)

        attempts = summarizor_config.max_retries + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                raise_if_cancelled(cancel_check)
                response = await llm_client.chat(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_payload},
                    ],
                    summarizor_config,
                    response_format={"type": "json_object"},
                    cancel_check=cancel_check,
                )
                response = clean_llm_response(response)
                parsed = json.loads(response)
                return _validate_batch_response(parsed)
            except (json.JSONDecodeError, TranslationValidationError) as e:
                last_error = e
                logger.warning(
                    "[llm_session=%s] Validation error during batch translation/merge (attempt %s/%s): %s",
                    session_id,
                    attempt + 1,
                    attempts,
                    e,
                )
                continue
            except Exception as e:
                if isinstance(e, OperationCancelledError):
                    raise
                last_error = e
                logger.warning(
                    "[llm_session=%s] Unexpected error during batch translation/merge (attempt %s/%s): %s",
                    session_id,
                    attempt + 1,
                    attempts,
                    e,
                )
                continue

        raise TranslationValidationError(
            f"[llm_session={session_id}] Failed to obtain valid batch translation/merge after "
            f"{attempts} attempts: {last_error}"
        )
