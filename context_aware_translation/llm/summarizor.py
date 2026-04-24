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


def _build_update_system_prompt() -> str:
    return """\
---角色---
你负责维护术语的翻译记忆摘要。

---目标---
判断新增描述是否应当更新当前摘要。只有当新增信息会影响术语翻译、身份理解、称谓、关系、类别或关键区分时才更新。注意：`当前摘要` 只是暂存假设，不保证正确。

---规则---
1) 只保留对翻译有帮助的信息：身份、角色、类别、别名、关键关系、重要区分。
2) 忽略纯情节推进、重复表述、场景细节、一次性事件。
3) 如果新增描述只是补充情节、态度、一次性行为、战斗经历、对话内容或其他不影响称呼/理解/区分的细节，默认不要更新。
4) 只有当新增描述改变了该术语的翻译相关理解（如身份、角色、类别、别名、稳定关系、关键区分）时，才更新摘要。
5) 如果新增描述看起来仍然指向同一对象或同一含义，就合并成一个更好的短摘要；不要因为存在潜在隐藏剧情就强行拆分。
6) 只有当描述本身已经明确显示这是两个不同对象/不同含义，而且这种区分会影响翻译时，才用极短分点列出；每点只写最小区分信息。
7) 若无需更新，输出 {"u":0}；若需要更新，输出 {"u":1,"s":"..."}。`s` 保持原文语言，尽量 1-2句。严格输出 JSON，不要输出额外文本。

---示例---
若同一个术语在当前文档中确实同时指代两个仍然有效的不同对象，例如一个是“王都的老年司祭”，另一个是“边境军所属的年轻骑兵”，则可以这样输出：
{"u":1,"s":"- 王都的老年司祭。\n- 边境军所属的年轻骑兵。"}
"""


def _build_update_user_payload(
    current_summary: str,
    new_descriptions: list[tuple[int, str]],
) -> str:
    payload = {
        "当前摘要": current_summary,
        "新增描述": [
            {
                "chunk": chunk,
                "description": description,
            }
            for chunk, description in new_descriptions
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _validate_update_response(data: dict) -> tuple[bool, str]:
    should_update = data.get("u")
    if should_update not in (0, 1, False, True):
        raise TranslationValidationError("u must be 0 or 1")
    if not should_update:
        return False, ""
    summary = data.get("s", "")
    if not isinstance(summary, str) or not summary.strip():
        raise TranslationValidationError("s must be a non-empty string when u=1")
    return True, summary.strip()


def _build_local_chunk_summary_system_prompt() -> str:
    return """\
---角色---
你为正文翻译系统写“前文微摘要”。

---任务---
只阅读一个 source_chunk，并用 target_language 写一句很短的事实摘要。

---规则---
1) 只写这个 chunk 中明确发生或明确表达的事。
2) 优先保留会帮助后续翻译的事实：谁对谁说了什么、谁做了什么、请求/拒绝/回答、交付物、当前位置变化。
3) 不写人物履历、世界观设定、文学分析、猜测、未来信息。
4) 不翻译整段原文，不复述无意义寒暄；没有有用信息时 summary 为空字符串。

---输出格式---
严格输出 JSON：
{"summary":"..."}
"""


def _build_local_chunk_summary_user_payload(
    *,
    chunk_id: int,
    chunk_text: str,
    source_language: str,
    target_language: str,
) -> str:
    payload = {
        "source_language": source_language,
        "target_language": target_language,
        "source_chunk": {
            "chunk": chunk_id,
            "text": chunk_text,
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _validate_local_chunk_summary_response(data: dict) -> str:
    summary = data.get("summary", "")
    if not isinstance(summary, str):
        raise TranslationValidationError("summary must be a string")
    compact = " ".join(summary.strip().split())
    return compact


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


async def update_term_summary(
    current_summary: str,
    new_descriptions: list[tuple[int, str]],
    summarizor_config: SummarizorConfig,
    llm_client: LLMClient,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[bool, str]:
    if not new_descriptions:
        return False, ""

    with llm_session_scope() as session_id:
        system_prompt = _build_update_system_prompt()
        user_payload = _build_update_user_payload(current_summary, new_descriptions)

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
                return _validate_update_response(parsed)
            except (json.JSONDecodeError, TranslationValidationError) as e:
                last_error = e
                logger.warning(
                    "[llm_session=%s] Validation error during term-memory update (attempt %s/%s): %s",
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
                    "[llm_session=%s] Unexpected error during term-memory update (attempt %s/%s): %s",
                    session_id,
                    attempt + 1,
                    attempts,
                    e,
                )
                continue

        raise TranslationValidationError(
            f"[llm_session={session_id}] Failed to obtain valid term-memory update after "
            f"{attempts} attempts: {last_error}"
        )


async def summarize_local_chunk(
    *,
    chunk_id: int,
    chunk_text: str,
    source_language: str,
    target_language: str,
    summarizor_config: SummarizorConfig,
    llm_client: LLMClient,
    cancel_check: Callable[[], bool] | None = None,
) -> str:
    if not chunk_text.strip():
        return ""

    with llm_session_scope() as session_id:
        system_prompt = _build_local_chunk_summary_system_prompt()
        user_payload = _build_local_chunk_summary_user_payload(
            chunk_id=chunk_id,
            chunk_text=chunk_text,
            source_language=source_language,
            target_language=target_language,
        )

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
                if not isinstance(parsed, dict):
                    raise TranslationValidationError("local chunk summary response must be a JSON object")
                return _validate_local_chunk_summary_response(parsed)
            except (json.JSONDecodeError, TranslationValidationError) as e:
                last_error = e
                logger.warning(
                    "[llm_session=%s] Validation error during local chunk summary (attempt %s/%s): %s",
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
                    "[llm_session=%s] Unexpected error during local chunk summary (attempt %s/%s): %s",
                    session_id,
                    attempt + 1,
                    attempts,
                    e,
                )
                continue

        raise TranslationValidationError(
            f"[llm_session={session_id}] Failed to obtain valid local chunk summary after {attempts} attempts: "
            f"{last_error}"
        )
