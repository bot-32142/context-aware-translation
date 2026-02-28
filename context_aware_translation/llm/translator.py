from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from context_aware_translation.config import TranslatorConfig
from context_aware_translation.core.cancellation import OperationCancelledError, raise_if_cancelled
from context_aware_translation.documents.epub_support.inline_markers import (
    extract_inline_markers,
    strict_inline_markers,
    validate_inline_marker_sanity,
)
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.llm.session_trace import get_llm_session_id, llm_session_scope
from context_aware_translation.utils.compression_marker import COMPRESSED_LINE_SENTINEL
from context_aware_translation.utils.llm_json_cleaner import clean_llm_response

logger = logging.getLogger(__name__)


class TranslationValidationError(Exception):
    """Raised when the LLM response fails schema or coverage checks."""


def _session_prefix() -> str:
    session_id = get_llm_session_id()
    return f"[llm_session={session_id}] " if session_id else ""


def _is_empty_line(line: str) -> bool:
    """A line is empty if it contains no non-whitespace characters."""
    return not line.strip()


def _first_marker_mismatch(expected_tokens: list[str], actual_tokens: list[str]) -> tuple[str, str]:
    mismatch = 0
    while (
        mismatch < len(expected_tokens)
        and mismatch < len(actual_tokens)
        and expected_tokens[mismatch] == actual_tokens[mismatch]
    ):
        mismatch += 1
    expected_token = expected_tokens[mismatch] if mismatch < len(expected_tokens) else "<end>"
    actual_token = actual_tokens[mismatch] if mismatch < len(actual_tokens) else "<end>"
    return expected_token, actual_token


def _extract_line_inline_tokens(lines: list[str]) -> list[list[str]]:
    return [extract_inline_markers(line, include_unknown=True) for line in lines]


def _validate_source_marker_sanity(source_tokens: list[str], *, label: str, line_no: int) -> None:
    try:
        validate_inline_marker_sanity(source_tokens)
    except ValueError as exc:  # pragma: no cover - defensive guard for extractor bugs
        raise ValueError(f"{label}: source line {line_no} malformed EPUB inline markers — {exc}.") from exc


def _validate_translated_marker_sanity(translated_tokens: list[str], *, label: str, line_no: int) -> None:
    try:
        validate_inline_marker_sanity(translated_tokens)
    except ValueError as exc:
        raise ValueError(
            f"{label}: line {line_no} malformed EPUB inline markers — {exc}. "
            "When present, ⟪RUBY...⟫ / ⟪/RUBY...⟫ must be paired and ordered correctly."
        ) from exc


def _validate_marker_sanity_across_lines(
    tokens_by_line: list[list[str]],
    *,
    label: str,
    where: str,
) -> None:
    merged: list[str] = []
    for tokens in tokens_by_line:
        merged.extend(tokens)
    try:
        validate_inline_marker_sanity(merged)
    except ValueError as exc:
        raise ValueError(f"{label}: {where} malformed EPUB inline markers — {exc}.") from exc


def _assert_strict_marker_match(
    expected_tokens: list[str],
    actual_tokens: list[str],
    *,
    label: str,
    where: str,
    message_suffix: str,
) -> None:
    expected_strict = strict_inline_markers(expected_tokens)
    actual_strict = strict_inline_markers(actual_tokens)
    if actual_strict == expected_strict:
        return

    expected_token, actual_token = _first_marker_mismatch(expected_strict, actual_strict)
    raise ValueError(
        f"{label}: {where} inline marker mismatch — expected {expected_token!r}, got {actual_token!r}. {message_suffix}"
    )


def _validate_inline_marker_preservation(
    source_blocks: list[str],
    translated_blocks: list[str],
    *,
    label: str,
) -> list[str]:
    """Require strict EPUB markers (inline wrapper tokens) to be preserved."""
    source_tokens_by_line = _extract_line_inline_tokens(source_blocks)
    translated_tokens_by_line = _extract_line_inline_tokens(translated_blocks)

    compressed_indices = [
        idx
        for idx, (source, translated) in enumerate(zip(source_blocks, translated_blocks, strict=True))
        if source.strip() and not translated.strip()
    ]
    if compressed_indices:
        logger.warning(
            "%s%s: detected compressed chunk output on lines %s; using prefix chunk-level marker validation.",
            _session_prefix(),
            label,
            ",".join(str(idx + 1) for idx in compressed_indices),
        )

    for idx, source_tokens in enumerate(source_tokens_by_line, start=1):
        _validate_source_marker_sanity(source_tokens, label=label, line_no=idx)

    if not compressed_indices:
        for idx, (source_tokens, translated_tokens) in enumerate(
            zip(source_tokens_by_line, translated_tokens_by_line, strict=True),
            start=1,
        ):
            _validate_translated_marker_sanity(translated_tokens, label=label, line_no=idx)
            _assert_strict_marker_match(
                source_tokens,
                translated_tokens,
                label=label,
                where=f"line {idx}",
                message_suffix="Strict EPUB markers must be preserved exactly: ⟪tag:path⟫, ⟪/tag:path⟫.",
            )
        return list(translated_blocks)

    prefix_end = max(compressed_indices)
    prefix_source_tokens = source_tokens_by_line[: prefix_end + 1]
    prefix_translated_tokens = translated_tokens_by_line[: prefix_end + 1]
    _validate_marker_sanity_across_lines(
        prefix_translated_tokens,
        label=label,
        where=f"line-prefix (lines 1-{prefix_end + 1})",
    )

    merged_prefix_source: list[str] = []
    merged_prefix_translated: list[str] = []
    for line_tokens in prefix_source_tokens:
        merged_prefix_source.extend(line_tokens)
    for line_tokens in prefix_translated_tokens:
        merged_prefix_translated.extend(line_tokens)
    _assert_strict_marker_match(
        merged_prefix_source,
        merged_prefix_translated,
        label=label,
        where=f"line-prefix (lines 1-{prefix_end + 1})",
        message_suffix="Strict EPUB markers in compressed/reordered prefixes must match at chunk level.",
    )

    for idx, (source_tokens, translated_tokens) in enumerate(
        zip(source_tokens_by_line[prefix_end + 1 :], translated_tokens_by_line[prefix_end + 1 :], strict=True),
        start=prefix_end + 2,
    ):
        _validate_translated_marker_sanity(translated_tokens, label=label, line_no=idx)
        _assert_strict_marker_match(
            source_tokens,
            translated_tokens,
            label=label,
            where=f"line {idx}",
            message_suffix="Strict EPUB markers must be preserved exactly: ⟪tag:path⟫, ⟪/tag:path⟫.",
        )

    return list(translated_blocks)


def preprocess_chunk_text(
    chunk_text: str,
) -> tuple[list[str], list[list[str]]]:
    """
    Preprocess chunk text into translatable blocks.

    NOTE: This function assumes soft wrapping is used in the input text.
    Each non-empty line becomes a separate translation block. If your source
    uses hard line breaks within paragraphs, you should preprocess the text
    to use soft wrapping before passing it to this function.
    """
    blocks: list[str] = []
    separators: list[list[str]] = [[]]

    for line in chunk_text.splitlines():
        if _is_empty_line(line):
            separators[-1].append(line)
        else:
            blocks.append(line)
            separators.append([])

    if not separators:
        separators = [[]]

    return blocks, separators


def postprocess_translated_blocks(
    translated_blocks: list[str],
    empty_line_separators: list[list[str]],
) -> str:
    separators = empty_line_separators or [[]]
    translated_blocks = [re.sub(r"\n+", "\n", block) for block in translated_blocks]

    result_lines: list[str] = []
    result_lines.extend(separators[0])

    for idx, block in enumerate(translated_blocks):
        if block:
            result_lines.extend(block.split("\n"))
        else:
            # Distinguish compressed placeholders ("") from true source empty lines.
            result_lines.append(COMPRESSED_LINE_SENTINEL)

        if idx + 1 < len(separators):
            result_lines.extend(separators[idx + 1])

    return "\n".join(result_lines)


@dataclass(frozen=True)
class PreparedChunkTranslation:
    chunks: list[str]
    all_blocks: list[str]
    chunk_boundaries: list[int]
    chunk_separators: list[list[list[str]]]
    translate_messages: list[dict[str, str]]


def prepare_chunk_translation(
    chunks: list[str],
    terms: list[tuple[str, str, str]],
    source_language: str,
    target_language: str,
) -> PreparedChunkTranslation:
    all_blocks: list[str] = []
    chunk_boundaries: list[int] = [0]
    chunk_separators: list[list[list[str]]] = []

    for chunk_text in chunks:
        chunk_blocks, empty_separators = preprocess_chunk_text(chunk_text)
        all_blocks.extend(chunk_blocks)
        chunk_boundaries.append(len(all_blocks))
        chunk_separators.append(empty_separators)

    system_prompt, user_prompt = build_translation_prompt(
        all_blocks,
        terms,
        source_language,
        target_language,
    )
    translate_messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return PreparedChunkTranslation(
        chunks=chunks,
        all_blocks=all_blocks,
        chunk_boundaries=chunk_boundaries,
        chunk_separators=chunk_separators,
        translate_messages=translate_messages,
    )


def reconstruct_chunk_translations(
    *,
    chunks: list[str],
    translated_blocks: list[str],
    chunk_boundaries: list[int],
    chunk_separators: list[list[list[str]]],
) -> list[str]:
    results: list[str] = []
    for i in range(len(chunks)):
        start, end = chunk_boundaries[i], chunk_boundaries[i + 1]
        results.append(
            postprocess_translated_blocks(
                translated_blocks[start:end],
                chunk_separators[i],
            )
        )
    return results


def build_translation_prompt(
    chunk_blocks: list[str],
    terms: list[tuple[str, str, str]],
    source_language: str,
    target_language: str,
) -> tuple[str, str]:
    """
    Build system and user prompts for translation with term context.

    Args:
        chunk_blocks: List of grouped non-empty lines to translate
        terms: List of Term objects with key, translated_name, descriptions
        target_language: Target language for translation

    Returns:
        Tuple of (system_prompt, user_prompt)
    """
    system_prompt = f"""--角色-- 你是专业翻译, 将以下{source_language}文本翻译为{target_language}。

--规则--
    你的目标受众是拥有大学学位的{target_language}母语人士。
    {source_language}应当全部翻译。
    只翻译{source_language}：如果原文中出现其他语言的文本，应保持原样不翻译。
    保持译文与术语表的一致性。（注意，术语表的描述实质是按照文章顺序总结的前后文。如果前后矛盾，可以以后面的总结为主。）
    严禁去除重复内容。
    保留所有原始格式，包括 Markdown、换行符和特殊字符。
    如果原文中出现EPUB内联标记，请按下列规则处理：
    1) 对非样式内联标记（如 a/abbr/img 等）：⟪tag:n⟫ 与 ⟪/tag:n⟫ 必须成对保留、顺序不变，不得删除/改写。
    2) 对样式内联标记（b,big,code,del,dfn,em,i,ins,kbd,mark,q,s,samp,small,strong,sub,sup,u,var）：
       可按语义整对保留/删除/新增，但不能只留一半。
    3) ⟪RUBY:n⟫ ... ⟪/RUBY:n⟫：可整对保留、整对删除或整对新增，不能只留一半；n 只需为数字。
    4) ⟪BR:n⟫：可按语义需要保留或删除。
    所有标记都是结构控制符，不是可翻译内容；只翻译标记外或标记包裹的自然语言文本。

--输出--
严格输出JSON格式，包含"翻译文本"字段,不得去重！
原文以列表提供，所有条目同属于一篇文章，内容连续。翻译时必须严格一对一：原文第1条对应翻译第1条，原文第2条对应翻译第2条，以此类推。禁止合并多条原文为一条翻译，也禁止将一条原文拆分为多条翻译。输出列表长度必须与原文列表长度完全相同。
若把连续多条内容压成一条：译文放在第一条，其余索引填 ""。

示例：
输入：
{{
  "术语列表": [
    {{
      "标准名称": "さくら",
      "翻译名称": "樱",
      "描述": "名前"
    }},
    {{
      "标准名称": "東京オフィス",
      "翻译名称": "东京办公室",
      "描述": "会社の本社"
    }}
  ],
  "原文": [
    "さくらは「Tokyo Office」で「Machine Learning」プロジェクトに取り組んでいる。",
    "彼は「⟪RUBY:0⟫断罪飛び蹴り(パニッシュメントドロップ)⟪/RUBY:0⟫」を放った。",
    "意",
    "味",
    "が",
    "分",
    "か",
    "ら",
    "な",
    "い",
    "彼女は「⟪RUBY:0⟫女主角(ヒロイン)⟪/RUBY:0⟫」と呼ばれる。"
  ]
}}

输出：
{{
  "翻译文本": [
    "樱在「Tokyo Office」从事「Machine Learning」项目。",
    "他使出了「⟪RUBY:0⟫断罪飞踢(惩罚坠击)⟪/RUBY:0⟫」。",
    "意",
    "义",
    "不",
    "明",
    "",
    "",
    "",
    "",
    "她被称为「女主角」。"
  ]
}}"""

    # Build JSON payload for user prompt with Chinese keys
    terms_json = []
    for name, translated_name, description in terms:
        entry: dict[str, str] = {"标准名称": name, "翻译名称": translated_name}
        if description:
            entry["描述"] = description
        terms_json.append(entry)

    user_payload = {
        "术语列表": terms_json,
        "原文": chunk_blocks,
    }

    user_prompt = json.dumps(user_payload, ensure_ascii=False, indent=2)

    return system_prompt, user_prompt


def build_polish_prompt(
    translated_blocks: list[str],
    target_language: str,
) -> tuple[str, str]:
    """Build standalone system and user prompts for polishing a translation.

    Unlike the translation prompt, this does NOT include the original source
    text or glossary terms. The LLM only sees the translation to polish.

    Args:
        translated_blocks: The translated text blocks to polish.
        target_language: Target language of the translation.

    Returns:
        Tuple of (system_prompt, user_prompt)
    """
    system_prompt = f"""--角色--
    你是{target_language}母语的资深润色编辑。

    --任务--
    对输入JSON中的"翻译文本"数组逐元素进行润色改写（每个元素视为一个独立段落/句群），使其更符合{target_language}母语表达习惯与文体一致性。
    允许在单个元素内部：拆句/合句、调整信息顺序、补足省略主语、替换连接词、改写措辞、调整标点与断句。

    --核心原则（通用流畅性）--
    在不改变含义与逻辑关系的前提下，优先采用{target_language}自然语序、常见搭配与段落组织方式；避免照搬源语言句法骨架（避免“翻译腔”）。
    改写强度自适应：原句已自然则轻改；存在生硬/拗口/翻译腔则可大幅重组，但不得引入推断性新增信息。

    --禁止（语义保真）--
    不得改变任何事实、条件、约束、因果/转折/并列/递进/条件等逻辑关系、语气强度（例如可能/必须/建议等强弱）、立场与叙述视角。
    不得新增原文未包含的事实、解释、评价或结论；不得删去关键信息点。
    不得改变术语译法与专名写法：专有名词、作品名、人名地名、怪物/技能/道具名、带括号的别名（如 X(Y)）、引号/书名号/特殊括号内的专名，均视为术语，除非明显是普通叙述用语。

    --数组结构约束（仅跨元素）--
    必须保持输入数组结构不变：
    1) 输出数组长度必须与输入数组长度完全相同，索引一一对应。
    2) 不得删除、合并、重排任何元素。
    3) 即使某些元素为空字符串或与其他元素完全相同，也必须在对应索引保留（可为空字符串）。
    4) 禁止“把多条内容压成一条并清空后续索引”的行为，除非输入明确指示允许压缩。

    --格式与标记（必须严格遵守）--
    必须保留所有原始格式，包括 Markdown、换行符、空格数量（除非为提升可读性在元素内部做极小调整且不影响标记位置）、以及所有特殊字符。
    任何形如 ⟪...⟫ 的标记都是结构控制符，不是可翻译内容：不得翻译、不得改名、不得改数字、不得拆分、不得跨元素移动；必须保持逐字符一致。

    若出现EPUB内联标记，按以下规则：
    1) 非样式内联标记（如 a/abbr/img 等）：⟪tag:n⟫ 与 ⟪/tag:n⟫ 必须成对保留、顺序不变，不得删除/改写/移动。
    2) 样式内联标记（b,big,code,del,dfn,em,i,ins,kbd,mark,q,s,samp,small,strong,sub,sup,u,var）：
    只允许“整对保留”或“整对删除”，不得新增；不得只保留一半；不得改变其包裹范围导致标记跨越到别的元素。
    3) ⟪RUBY:n⟫ ... ⟪/RUBY:n⟫：只允许“整对保留”或“整对删除”，不得新增；n 必须保持为原来的数字；不得只留一半。
    4) ⟪BR:n⟫：可按语义需要保留或删除，但不得改写其中的n，不得跨元素移动。

    --不确定处理--
    若某处指代/关系不清，任何“为了更顺而改写”可能改变含义时：优先保持原译文或做最小改动，不得擅自补全推断。

    --输出--
    只输出一个JSON对象，且仅包含字段："翻译文本"。
    "翻译文本"必须是字符串数组，数组长度必须与输入完全一致,不得去重！
    不得输出任何额外说明、前后缀文本或代码块围栏。"""

    user_payload = {"翻译文本": translated_blocks}
    user_prompt = json.dumps(user_payload, ensure_ascii=False, indent=2)

    return system_prompt, user_prompt


async def validated_chat(
    messages: list[dict[str, str]],
    expected_count: int,
    source_blocks: list[str],
    llm_client: LLMClient,
    config: TranslatorConfig,
    cancel_check: Callable[[], bool] | None,
    max_corrections: int = 2,
    label: str = "translation",
    initial_raw: str | None = None,
) -> list[str]:
    """Call the LLM and validate that '翻译文本' has exactly *expected_count* items.

    On validation failure, the response whose list length is closest to
    *expected_count* (among all attempts so far) is sent back together with an
    error correction message, and the LLM is asked to fix its output.  Up to
    *max_corrections* additional attempts are made.  If all attempts fail the
    last exception is re-raised.
    """
    base_len = len(messages)
    total = 1 + max_corrections
    # Track the best (closest-length) bad response for correction context
    best_raw: str | None = None
    best_distance: float = float("inf")

    for attempt in range(total):
        raise_if_cancelled(cancel_check)
        if attempt == 0 and initial_raw is not None:
            raw = initial_raw
        else:
            raw = await llm_client.chat(
                messages,
                config,
                response_format={"type": "json_object"},
                cancel_check=cancel_check,
            )
        raw = clean_llm_response(raw)
        try:
            parsed = json.loads(raw)
            result = parsed.get("翻译文本")
            if not isinstance(result, list):
                raise ValueError(f"{label}: '翻译文本' must be a list of strings")
            if len(result) != expected_count:
                raise ValueError(f"{label}: '翻译文本' length mismatch — expected {expected_count}, got {len(result)}")
            if not all(isinstance(s, str) for s in result):
                raise ValueError(f"{label}: every item in '翻译文本' must be a string")
            result = _validate_inline_marker_preservation(source_blocks, result, label=label)
            return result
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            # Update best response if this one's list length is closer to expected
            distance: float
            try:
                distance = abs(len(json.loads(raw).get("翻译文本", [])) - expected_count)
            except Exception:
                distance = float("inf")
            if distance < best_distance:
                best_distance = distance
                best_raw = raw

            logger.warning(
                "%sError parsing %s response (attempt %s/%s): %s",
                _session_prefix(),
                label,
                attempt + 1,
                total,
                exc,
            )
            if attempt < total - 1:
                # Reset to original conversation, append best response for correction
                del messages[base_len:]
                messages.append({"role": "assistant", "content": best_raw or raw})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"错误：{exc}\n"
                            f'注意翻译时不得去除重复文本，输出要与输入原文数量一致。\n'
                            '若把多条内容压成一条，请把译文放在第一条，其余索引填 ""。\n'
                            "若原文包含 EPUB 严格内联标记（非样式 tag 的 ⟪tag:n⟫/⟪/tag:n⟫），"
                            "必须在对应条目中按相同顺序原样保留这些标记；样式 tag 可按语义整对调整。\n"
                            "若使用 ⟪RUBY:n⟫ 标记，必须与 ⟪/RUBY:n⟫ 成对且开闭一致，且 n 必须是数字。"
                        ),
                    }
                )
                continue
            raise

    raise AssertionError("unreachable")  # pragma: no cover


async def translate_chunk(
    chunks: list[str],
    terms: list[tuple[str, str, str]],
    llm_client: LLMClient,
    translator_config: TranslatorConfig,
    source_language: str,
    target_language: str,
    cancel_check: Callable[[], bool] | None = None,
) -> list[str]:
    """Translate multiple chunks with term context."""
    with llm_session_scope() as session_id:
        prepared = prepare_chunk_translation(chunks, terms, source_language, target_language)
        if not prepared.all_blocks:
            return [postprocess_translated_blocks([], separators) for separators in prepared.chunk_separators]

        # -- Translation (with conversation-based correction) -----------------
        expected = len(prepared.all_blocks)
        attempts = translator_config.max_retries + 1
        logger.debug(
            "[llm_session=%s] Translating %s chunk(s), %s block(s), attempts=%s, polish=%s",
            session_id,
            len(chunks),
            expected,
            attempts,
            translator_config.enable_polish,
        )

        for attempt in range(attempts):
            try:
                translate_messages = list(prepared.translate_messages)
                translated_text = await validated_chat(
                    translate_messages,
                    expected,
                    prepared.all_blocks,
                    llm_client,
                    translator_config,
                    cancel_check,
                    label="translation",
                )

                # -- Optional polish (standalone, no original text or terms) ---
                if translator_config.enable_polish:
                    polish_sys, polish_usr = build_polish_prompt(translated_text, target_language)
                    polish_messages: list[dict[str, str]] = [
                        {"role": "system", "content": polish_sys},
                        {"role": "user", "content": polish_usr},
                    ]
                    try:
                        translated_blocks = await validated_chat(
                            polish_messages,
                            expected,
                            prepared.all_blocks,
                            llm_client,
                            translator_config,
                            cancel_check,
                            label="polish",
                        )
                    except (json.JSONDecodeError, ValueError, KeyError):
                        logger.warning(
                            "[llm_session=%s] Polish failed, falling back to unpolished translation",
                            session_id,
                        )
                        translated_blocks = translated_text
                else:
                    translated_blocks = translated_text

                # -- Reconstruct per-chunk results ----------------------------
                return reconstruct_chunk_translations(
                    chunks=prepared.chunks,
                    translated_blocks=translated_blocks,
                    chunk_boundaries=prepared.chunk_boundaries,
                    chunk_separators=prepared.chunk_separators,
                )

            except OperationCancelledError:
                raise
            except Exception as e:
                logger.warning(
                    "[llm_session=%s] Translation failed (attempt %s/%s): %s",
                    session_id,
                    attempt + 1,
                    attempts,
                    e,
                )
                if attempt < attempts - 1:
                    continue
                raise

        raise ValueError(f"[llm_session={session_id}] Failed to obtain valid translation after {attempts} attempts")
