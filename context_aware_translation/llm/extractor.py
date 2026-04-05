from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import TypedDict

from context_aware_translation.config import ExtractorConfig
from context_aware_translation.core.models import Term, choose_term_type, normalize_term_type
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.llm.session_trace import llm_session_scope
from context_aware_translation.storage.schema.book_db import ChunkRecord

logger = logging.getLogger(__name__)

# Hardcoded delimiters for LLM response parsing
TUPLE_DELIMITER = "<|#|>"
COMPLETION_DELIMITER = "<|COMPLETE|>"


class ExtractedTermData(TypedDict):
    name: str
    description: str
    term_type: str


class MergedExtractedTermData(ExtractedTermData):
    votes: int
    term_type_votes: dict[str, int]


@dataclass
class _MergedTermState:
    description: str = ""
    term_type_votes: Counter[str] = field(default_factory=Counter)


def sanitize_and_normalize(text: str) -> str:
    # Remove inner quotes and normalize whitespace
    cleaned = text.replace('"', " ").replace("'", " ")
    cleaned = " ".join(cleaned.split())
    return cleaned.strip()


def is_valid_term(name: str, description: str, max_len: int) -> tuple[bool, str, str]:
    name_clean = sanitize_and_normalize(name)
    desc_clean = sanitize_and_normalize(description)

    if not name_clean or not desc_clean:
        return False, name_clean, desc_clean
    if TUPLE_DELIMITER in name_clean:
        return False, name_clean, desc_clean
    if len(name_clean) > max_len:
        name_clean = name_clean[:max_len]
    return True, name_clean, desc_clean


def fix_delimiter_corruption(record: str) -> str:
    # Minimal fixer: replace common corrupted tokens
    return record.replace("<|#|>", TUPLE_DELIMITER).replace("<| #|>", TUPLE_DELIMITER)


def parse_delimited_output(response: str, max_len: int) -> list[ExtractedTermData]:
    terms: list[ExtractedTermData] = []
    if not response:
        return terms

    segments = response.split(COMPLETION_DELIMITER)[0].splitlines()
    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        segment = fix_delimiter_corruption(segment)
        parts = segment.split(TUPLE_DELIMITER)
        if len(parts) not in {2, 3}:
            continue
        raw_name = parts[0]
        raw_desc = parts[1]
        raw_type = parts[2] if len(parts) == 3 else None
        valid, name, desc = is_valid_term(raw_name, raw_desc, max_len)
        if valid:
            terms.append({"name": name, "description": desc, "term_type": normalize_term_type(raw_type)})
    return terms


def _pass_winning_term_types(pass_results: list[ExtractedTermData]) -> dict[str, str]:
    pass_type_votes: dict[str, Counter[str]] = {}
    for term in pass_results:
        pass_type_votes.setdefault(term["name"], Counter())[term["term_type"]] += 1
    return {name: choose_term_type(dict(type_votes)) for name, type_votes in pass_type_votes.items()}


def merge_all_with_votes(results_by_pass: list[list[ExtractedTermData]]) -> list[MergedExtractedTermData]:
    """
    Merge multiple extraction passes for one chunk.

    A term found multiple times within the same chunk still contributes only one
    final vote from that chunk. The passes are used to recover missed terms and
    to pick the best description/type for the chunk-local term record.
    """
    if not results_by_pass:
        return []
    merged: dict[str, _MergedTermState] = {}
    for pass_results in results_by_pass:
        for term in pass_results:
            name = term["name"]
            state = merged.setdefault(name, _MergedTermState())
            if len(term["description"]) > len(state.description):
                state.description = term["description"]
        for name, winner in _pass_winning_term_types(pass_results).items():
            state = merged.setdefault(name, _MergedTermState())
            state.term_type_votes[winner] += 1

    final: list[MergedExtractedTermData] = []
    for name, state in merged.items():
        winner = choose_term_type(dict(state.term_type_votes))
        term_type_votes = {winner: 1}
        final.append(
            {
                "name": name,
                "description": state.description,
                "term_type": winner,
                "votes": 1,
                "term_type_votes": term_type_votes,
            }
        )
    return final


def _examples() -> str:
    return f"""
示例 1:
<Input Text>
```
主角获得了「龙语词典」与「古代铭文石板」，并使用「星辉译码仪」来解读文本。
```
<Output>
龙语词典{TUPLE_DELIMITER}记录龙族语言的词典，用于解读古代文本。{TUPLE_DELIMITER}other
古代铭文石板{TUPLE_DELIMITER}刻有古文明符号的石板，需特殊工具解读。{TUPLE_DELIMITER}other
星辉译码仪{TUPLE_DELIMITER}用于解析和翻译古代符号的装置。{TUPLE_DELIMITER}other
{COMPLETION_DELIMITER}

示例 2:
<Input Text>
```
公司宣布了一款新产品的发布。首席执行官约翰·史密斯在大会上发表了主题演讲。
```
<Output>
约翰·史密斯{TUPLE_DELIMITER}约翰·史密斯是首席执行官，在大会上就新产品发布发表了主题演讲。{TUPLE_DELIMITER}character
{COMPLETION_DELIMITER}

示例 3:
<Input Text>
```
炼金术士佩戴恒温坩埚和流银手套，以星陨矿砂为材料进行提炼。
```
<Output>
恒温坩埚{TUPLE_DELIMITER}可维持恒定温度的炼金器具，用于精细炼制。{TUPLE_DELIMITER}other
流银手套{TUPLE_DELIMITER}强化魔力传导的手套，炼金术士常用装备。{TUPLE_DELIMITER}other
星陨矿砂{TUPLE_DELIMITER}由陨星残片形成的稀有炼金材料。{TUPLE_DELIMITER}other
{COMPLETION_DELIMITER}

示例 4:
<Input Text>
```
“至尊导师”伊莲娜·沃斯博士（第七研究组组长）在“白银议会·极昼研究所”发布了《深空航行规约（试行版）》和《深空航行规约·附录A》。同时，代号#27 的“晨星级-试作三号”飞船在现场完成跃迁测试。
```
<Output>
伊莲娜·沃斯{TUPLE_DELIMITER}担任第七研究组组长的研究员，主导《深空航行规约》起草工作。{TUPLE_DELIMITER}character
白银议会{TUPLE_DELIMITER}负责管理极昼研究所并发布《深空航行规约》的组织。{TUPLE_DELIMITER}organization
极昼研究所{TUPLE_DELIMITER}白银议会下属的研究机构，进行深空航行相关研究与测试。{TUPLE_DELIMITER}organization
《深空航行规约》{TUPLE_DELIMITER}面向深空航行的规范性文档，本次发布为试行版。{TUPLE_DELIMITER}other
《深空航行规约·附录A》{TUPLE_DELIMITER}规约的补充附录，随试行版一同发布。{TUPLE_DELIMITER}other
晨星级-试作三号{TUPLE_DELIMITER}代号#27 的试作飞船，在发布现场完成跃迁测试。{TUPLE_DELIMITER}other
{COMPLETION_DELIMITER}
""".strip()


def _build_extraction_system_prompt(source_language: str) -> str:
    examples = _examples()

    system_prompt = f"""---角色---
你是一名术语抽取助手，负责为翻译建立术语表，确保译文用词一致。

---指令---
1.  术语抽取与输出：
    *   抽取需要统一翻译的关键术语/短语（人物名、地名、组织、称号、技能/法术、物品/神器、专有设定、独特术语等）。
    *   对每个术语提取：
        *   `term_name`：术语名称，保持原文形态。
        *   `term_description`： 用{source_language}，基于输入文本、用**第三人称**撰写的精炼且完整的描述。。
        *   `term_type`：术语类型，只能是 `character`、`organization`、`other` 之一。
    *   **输出格式：** 每个术语一行，共 3 个字段，用 `{TUPLE_DELIMITER}` 分隔。
        *   格式：`term_name{TUPLE_DELIMITER}term_description{TUPLE_DELIMITER}term_type`
        *   若无法确定类型，必须输出 `other`。

2.  分隔符使用规范：
    *   `{TUPLE_DELIMITER}` 是完整的原子标记，不得填入内容，仅作字段分隔。
    *   错误示例：`东京<|location|>{TUPLE_DELIMITER}东京是日本的首都。{TUPLE_DELIMITER}other`
    *   正确示例：`东京{TUPLE_DELIMITER}东京是日本的首都。{TUPLE_DELIMITER}other`

3.  客观性与指代：
    *   名称与描述必须使用**第三人称**。
    *   明确写出主语/客体，避免指代词（如 “本文章”“我们公司”“我/你/他/她” 等）。

4.  语言：
    *   输出必须保持与输入文本相同的语言，**不要翻译任何内容**。

5.  类型判定：
    *   `character`：明确的人物、角色、个体身份。
    *   `organization`：组织、机构、团队、公司、议会、学院等群体实体。
    *   `other`：除上述之外的所有术语，如地名、物品、技能、文档、称号、设定、概念等。

6.  排除项：
    *   不要输出：章节名、段落标题、常用词/日常用语/功能词/标点、纯数字/日期/货币/章节编号、无关叙述。

7.  结束标记：
    *   所有术语输出完成后，输出字面量 `{COMPLETION_DELIMITER}`。

8.  提示：
    *   优先专有名词和独特概念；描述应简洁且基于原文，可包含简短上下文线索（角色/功能/关系）以助译法一致。
    *   术语名需去除所有非固有前后缀（如称谓/敬称、职衔、头衔、级别/数值/状态、顺序标记等），仅保留术语本身固有且不可分的名称；若数字/序号确属专名一部分则保留，被去除的信息可写入描述。

---示例---
{examples}
"""
    return system_prompt.strip()


def build_extraction_prompts(chunk_text: str, source_language: str) -> tuple[str, str]:
    system_prompt = _build_extraction_system_prompt(source_language)
    user_prompt = f"""---任务---
从下方文本中抽取需要统一翻译的术语。不要翻译！

---指令---
1.  **严格遵守格式：** 使用系统提示指定的字段分隔符和格式。
2.  **只输出内容：** 仅输出术语列表，不要添加任何开头或结尾说明。
3.  **结束标记：** 所有术语输出完毕后，输出 `{COMPLETION_DELIMITER}` 作为最后一行。
4.  **语言：** 输出语言必须与输入文本一致，禁止翻译。
5.  **类型：** 每条术语都必须输出 `character`、`organization`、`other` 之一；不能确定时输出 `other`。
6.  **排除：** 不要输出章节名、常用词、纯数字/日期/货币/编号或无信息项；术语名去除非固有的等级/数值/状态后缀（等级信息可放在描述里）。

<Input Text>
{chunk_text}

<Output>"""
    return system_prompt.strip(), user_prompt.strip()


def build_gleaning_prompts() -> str:
    user_prompt = (
        f"只补充此前遗漏、且仍需要统一翻译的术语。不要翻译！"
        f"不要重复或重写完整列表；如果没有遗漏，只输出 `{COMPLETION_DELIMITER}`。"
    )
    return user_prompt.strip()


async def _run_gleaning_passes(
    count: int,
    detected_terms: list[str],
    messages: list[dict[str, str]],
    llm_client: LLMClient,
    step_config: ExtractorConfig,
) -> list[list[ExtractedTermData]]:
    if count <= 0:
        return []

    seen_terms: set[str] = set()
    for detected_name in detected_terms:
        normalized = detected_name.strip()
        if not normalized or normalized in seen_terms:
            continue
        seen_terms.add(normalized)

    gleaned_passes: list[list[ExtractedTermData]] = []
    for _ in range(count):
        user_prompt = build_gleaning_prompts()
        messages.append({"role": "user", "content": user_prompt})
        response = await llm_client.chat(messages, step_config)
        gleaned_terms = parse_delimited_output(response, step_config.max_term_name_length)
        new_terms: list[ExtractedTermData] = []
        for extracted_term in gleaned_terms:
            name = extracted_term["name"]
            if name in seen_terms:
                continue
            seen_terms.add(name)
            new_terms.append(extracted_term)
        messages.append({"role": "assistant", "content": response})
        gleaned_passes.append(new_terms)
    return gleaned_passes


async def extract_terms(
    chunk_record: ChunkRecord,
    llm_client: LLMClient,
    extractor_config: ExtractorConfig,
    source_language: str,
) -> list[Term]:
    with llm_session_scope() as session_id:
        system_prompt, user_prompt = build_extraction_prompts(chunk_record.text, source_language)
        logger.debug("[llm_session=%s] Extracting terms for chunk_id=%s", session_id, chunk_record.chunk_id)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Initial extraction (sync to ensure it's cached by LLM provider)
        # extractor_config is always resolved at Config initialization
        response = await llm_client.chat(messages, extractor_config)
        initial_terms = parse_delimited_output(response, extractor_config.max_term_name_length)
        messages.append({"role": "assistant", "content": response})

        results_by_pass: list[list[ExtractedTermData]] = [initial_terms]
        glean_count = max(0, extractor_config.max_gleaning)
        total_api_calls = 1  # initial extraction
        if glean_count > 0:
            gleaned_passes = await _run_gleaning_passes(
                glean_count,
                [term["name"] for term in initial_terms],
                messages,
                llm_client,
                extractor_config,
            )
            total_api_calls += glean_count
            results_by_pass.extend(gleaned_passes)

        final_terms = merge_all_with_votes(results_by_pass)
        merged_terms: list[Term] = []
        for term in final_terms:
            merged_terms.append(
                Term(
                    key=term["name"],
                    descriptions={chunk_record.chunk_id: term["description"].replace("\n", " ")},
                    occurrence={},
                    votes=term["votes"],
                    total_api_calls=total_api_calls,
                    term_type=term["term_type"],
                    term_type_votes=term.get("term_type_votes", {}),
                )
            )
        return merged_terms
