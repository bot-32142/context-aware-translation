from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from context_aware_translation.config import LLMConfig, TranslatorConfig
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


def _indexed_text_entries(texts: list[str]) -> list[dict[str, int | str]]:
    return [{"id": idx, "文本": text} for idx, text in enumerate(texts)]


def _render_json_payload(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


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


def _extract_id_based_translation_blocks(
    parsed: object,
    *,
    expected_count: int,
    label: str,
) -> list[str]:
    if not isinstance(parsed, dict):
        raise ValueError(f"{label}: response must be a JSON object")

    result = parsed.get("翻译文本")
    if not isinstance(result, list):
        raise ValueError(f"{label}: '翻译文本' must be a list of objects")
    if len(result) != expected_count:
        raise ValueError(f"{label}: '翻译文本' length mismatch — expected {expected_count}, got {len(result)}")

    translated_blocks: list[str] = []
    for idx, item in enumerate(result):
        if not isinstance(item, dict):
            raise ValueError(f"{label}: every item in '翻译文本' must be an object")

        item_id = item.get("id")
        if not isinstance(item_id, int) or isinstance(item_id, bool):
            raise ValueError(f"{label}: item {idx} in '翻译文本' must have integer 'id'")
        if item_id != idx:
            raise ValueError(f"{label}: '翻译文本' id mismatch — expected {idx}, got {item_id}")

        text = item.get("文本")
        if not isinstance(text, str):
            raise ValueError(f"{label}: item {idx} in '翻译文本' must have string '文本'")

        translated_blocks.append(text)

    return translated_blocks


def _build_retry_correction_message(exc: Exception) -> str:
    return (
        f"错误：{exc}\n"
        "请只修正输出，不要添加任何解释。\n"
    )


def _build_translation_prompt_examples() -> str:
    example_terms = [
        {
            "标准名称": "さくら",
            "翻译名称": "樱",
            "描述": "名前",
        },
        {
            "标准名称": "東京オフィス",
            "翻译名称": "东京办公室",
            "描述": "会社の本社",
        },
    ]
    example_input_1 = {
        "术语列表": example_terms,
        "原文": _indexed_text_entries(
            [
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
                "彼女は「⟪RUBY:0⟫女主角(ヒロイン)⟪/RUBY:0⟫」と呼ばれる。",
            ]
        ),
    }
    example_output_1 = {
        "翻译文本": _indexed_text_entries(
            [
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
                "她被称为「女主角」。",
            ]
        )
    }
    example_input_2 = {
        "术语列表": [],
        "原文": _indexed_text_entries(["意", "义", "不", "明"]),
    }
    example_output_2 = {
        "翻译文本": _indexed_text_entries(["意味が分からない", "", "", ""]),
    }
    return "\n".join(
        [
            "示例：",
            "输入：",
            _render_json_payload(example_input_1),
            "",
            "输出：",
            _render_json_payload(example_output_1),
            "",
            "输入：",
            _render_json_payload(example_input_2),
            "",
            "输出：",
            _render_json_payload(example_output_2),
        ]
    )


def _translation_result_distance(raw: str, expected_count: int) -> float:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return float("inf")
    result = parsed.get("翻译文本") if isinstance(parsed, dict) else None
    return abs(len(result) - expected_count) if isinstance(result, list) else float("inf")


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
    system_prompt = f"""--角色--
你是{source_language}译{target_language}的专业翻译。

--任务--
判断内容背景与文本风格。
结合术语表描述，分析人物特征与性格。
逐元素翻译：
a. 不翻译非{source_language}文本。
b. 对每个 id 对应的文本分别翻译，输出时保留原 id。
c. 结合上下文，在不造成误解、歧义或信息缺失的前提下，选择最符合文风和人物性格的译法；对无自然对应表达的内容，可适度删改。

--格式与标记（必须严格遵守）--
保留所有原始格式，包括 Markdown、换行符，以及除自然语言标点外所有必须逐字符保留的结构标记、控制符和特殊符号。
若原文含 EPUB 内联标记，按以下规则处理：

非样式标记（如 a/abbr/img 等）：⟪tag:n⟫ 与 ⟪/tag:n⟫ 必须成对保留、顺序不变，不得删除或改写。
样式标记（b,big,code,del,dfn,em,i,ins,kbd,mark,q,s,samp,small,strong,sub,sup,u,var）：可按语义整对保留、删除或新增，但不得只保留一半。
⟪RUBY:n⟫ 正文（内容） ⟪/RUBY:n⟫：可整对保留、删除或新增，不得只保留一半。若 RUBY 内括号中的内容为同义词、注音，或在目标语言中无直接对应的自然译法，可删除起止标记以及括号和括号内内容，但括号外正文必须保留。
⟪BR:n⟫：可按语义需要保留或删除。

所有标记均为结构控制符，不是可翻译内容；无论自然语言文本位于标记外还是被标记包裹，只翻译文本本身，不翻译标记、编号或符号。
--数组结构约束（仅跨元素）--
输出中必须保留输入里的每一个 id，且每个 id 恰好出现一次。id 与文本一一对应，不得新增、删除、重复、修改、合并或重排任何 id；不得去除重复元素或空字符串。
仅当原文一句话被拆成多个连续元素，且无法一一对应翻译时，才允许压缩：将译文放入第一条对应 id，其余相关 id 的 "文本" 填 ""。

--输出--
只输出一个 JSON 对象，且仅包含字段 "翻译文本"。
"翻译文本" 中的每个元素必须包含字段 "id" 和 "文本"。
不得输出任何额外说明、前后缀文本或代码块围栏。

{_build_translation_prompt_examples()}
"""

    # Build JSON payload for user prompt with Chinese keys
    terms_json = []
    for name, translated_name, description in terms:
        entry: dict[str, str] = {"标准名称": name, "翻译名称": translated_name}
        if description:
            entry["描述"] = description
        terms_json.append(entry)

    user_payload = {
        "术语列表": terms_json,
        "原文": _indexed_text_entries(chunk_blocks),
    }

    user_prompt = _render_json_payload(user_payload)

    return system_prompt, user_prompt


def build_polish_prompt(
    translated_blocks: list[str],
    target_language: str,
    source_language: str,
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
你是{target_language}母语的资深编辑。

--任务--
1. 识别每句话中的{source_language}残留、翻译腔，以及不规范的标点和断句。
2. 明确每句话中不得改变的内容：不得改变事实、人物关系、称谓、术语专名、叙述视角、情绪走向、信息揭示顺序；不得新增原文没有的信息，不得擅自解释留白、补出潜台词，或把不同角色润成同一种口气。
3. 逐元素润色：
   a. 去除{source_language}残留，修正标点与断句。
   b. 在遵守第2条的前提下，比较多种表达方式，选择最符合{target_language}习惯的说法。
   c. 可在不违反第2条的前提下大胆重写。

--格式与标记（必须严格遵守）--
保留所有原始格式，包括 Markdown、换行符，以及除自然语言标点外所有必须逐字符保留的结构标记、控制符和特殊符号。
若原文含 EPUB 内联标记，按以下规则处理：

非样式标记（如 a/abbr/img 等）：⟪tag:n⟫ 与 ⟪/tag:n⟫ 必须成对保留、顺序不变，不得删除、改写或移动。
样式标记（b,big,code,del,dfn,em,i,ins,kbd,mark,q,s,samp,small,strong,sub,sup,u,var）：只允许整对保留或整对删除，不得新增，不得只保留一半，不得改变其包裹范围，也不得跨元素移动。
⟪RUBY:n⟫ 正文（内容） ⟪/RUBY:n⟫：只允许整对保留或整对删除，不得新增，不得只保留一半；n 必须保持原数字不变。若 RUBY 内括号中的内容为同义词、注音，或在目标语言中无直接对应的自然译法，可删除起止标记以及括号和括号内内容，但括号外正文必须保留。
⟪BR:n⟫：可按语义需要保留或删除，但不得改写其中的 n，不得跨元素移动。

所有标记均为结构控制符，不是可润色内容；无论自然语言文本位于标记外还是被标记包裹，只润色文本本身，不改动标记、编号或符号。

--数组结构约束（仅跨元素）--
输出中必须保留输入里的每一个 id，且每个 id 恰好出现一次。id 与文本一一对应，不得新增、删除、重复、修改、合并或重排任何 id。
即使某些元素的 "文本" 为空字符串，或与其他元素完全相同，也必须保留对应 id。

--输出--
只输出一个 JSON 对象，且仅包含字段 "翻译文本"。
"翻译文本" 中的每个元素都必须包含字段 "id" 和 "文本"。
不得输出任何额外说明、前后缀文本或代码块围栏。"""

    user_payload = {"翻译文本": _indexed_text_entries(translated_blocks)}
    user_prompt = _render_json_payload(user_payload)

    return system_prompt, user_prompt


async def validated_chat(
    messages: list[dict[str, str]],
    expected_count: int,
    source_blocks: list[str],
    llm_client: LLMClient,
    config: LLMConfig,
    cancel_check: Callable[[], bool] | None,
    max_corrections: int = 2,
    label: str = "translation",
    initial_raw: str | None = None,
) -> list[str]:
    """Call the LLM and validate that '翻译文本' covers *expected_count* id-based items.

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
            translated_blocks = _extract_id_based_translation_blocks(
                parsed,
                expected_count=expected_count,
                label=label,
            )
            translated_blocks = _validate_inline_marker_preservation(source_blocks, translated_blocks, label=label)
            return translated_blocks
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            # Update best response if this one's list length is closer to expected
            distance = _translation_result_distance(raw, expected_count)
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
                        "content": _build_retry_correction_message(exc),
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
    polish_config: LLMConfig | None = None,
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
        effective_polish_config = polish_config or translator_config
        polish_enabled = translator_config.enable_polish and effective_polish_config is not None
        logger.debug(
            "[llm_session=%s] Translating %s chunk(s), %s block(s), attempts=%s, polish=%s",
            session_id,
            len(chunks),
            expected,
            attempts,
            polish_enabled,
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
                if polish_enabled:
                    polish_sys, polish_usr = build_polish_prompt(translated_text, target_language, source_language)
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
                            effective_polish_config,
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
