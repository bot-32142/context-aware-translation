from __future__ import annotations

from copy import deepcopy

from context_aware_translation.config import ExtractorConfig
from context_aware_translation.llm.extractor import (
    COMPLETION_DELIMITER,
    TUPLE_DELIMITER,
    build_gleaning_prompts,
    extract_terms,
    merge_all_with_votes,
    parse_delimited_output,
)
from context_aware_translation.storage.schema.book_db import ChunkRecord


def test_parse_delimited_output_parses_three_field_rows() -> None:
    response = (
        f"Alice{TUPLE_DELIMITER}A protagonist.{TUPLE_DELIMITER}character\n"
        f"Guild{TUPLE_DELIMITER}A faction.{TUPLE_DELIMITER}organization"
    )

    terms = parse_delimited_output(response, max_len=100)

    assert terms == [
        {"name": "Alice", "description": "A protagonist.", "term_type": "character"},
        {"name": "Guild", "description": "A faction.", "term_type": "organization"},
    ]


def test_parse_delimited_output_defaults_two_field_rows_to_other() -> None:
    response = f"Relic{TUPLE_DELIMITER}An ancient artifact."

    terms = parse_delimited_output(response, max_len=100)

    assert terms == [{"name": "Relic", "description": "An ancient artifact.", "term_type": "other"}]


def test_parse_delimited_output_normalizes_invalid_types_without_dropping_rows() -> None:
    response = (
        f"Alice{TUPLE_DELIMITER}A protagonist.{TUPLE_DELIMITER}hero\n"
        f"Guild{TUPLE_DELIMITER}A faction.{TUPLE_DELIMITER}organization"
    )

    terms = parse_delimited_output(response, max_len=100)

    assert terms == [
        {"name": "Alice", "description": "A protagonist.", "term_type": "other"},
        {"name": "Guild", "description": "A faction.", "term_type": "organization"},
    ]


def test_parse_delimited_output_discards_rows_with_extra_columns() -> None:
    response = (
        f"Alice{TUPLE_DELIMITER}A protagonist.{TUPLE_DELIMITER}character{TUPLE_DELIMITER}extra\n"
        f"Relic{TUPLE_DELIMITER}An artifact.{TUPLE_DELIMITER}other{TUPLE_DELIMITER}unused"
    )

    terms = parse_delimited_output(response, max_len=100)

    assert terms == []


def test_merge_all_with_votes_picks_most_voted_type_and_tie_breaks() -> None:
    merged = merge_all_with_votes(
        [
            [
                {"name": "Alice", "description": "short", "term_type": "organization"},
                {"name": "Alice", "description": "much longer description", "term_type": "character"},
            ],
            [{"name": "Alice", "description": "mid", "term_type": "character"}],
            [{"name": "Alice", "description": "tiny", "term_type": "organization"}],
        ]
    )

    assert merged == [
        {
            "name": "Alice",
            "description": "much longer description",
            "term_type": "character",
            "term_type_votes": {"character": 1},
            "votes": 1,
        }
    ]


class _FakeLLMClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls = 0
        self.requests: list[list[dict[str, str]]] = []

    async def chat(self, messages: list[dict[str, str]], step_config: ExtractorConfig) -> str:
        self.requests.append(deepcopy(messages))
        del step_config
        response = self._responses[self.calls]
        self.calls += 1
        return response


def test_build_gleaning_prompts_mentions_detected_terms_and_same_output_contract() -> None:
    user_prompt = build_gleaning_prompts()

    assert COMPLETION_DELIMITER in user_prompt
    assert "不要重复" in user_prompt
    assert "遗漏" in user_prompt
    assert "已检测术语" not in user_prompt
    assert "前面对话" not in user_prompt
    assert "<Input Text>" not in user_prompt


def test_extractor_config_defaults_to_one_gleaning_pass() -> None:
    assert ExtractorConfig().max_gleaning == 1
    assert ExtractorConfig.from_dict({}).max_gleaning == 1


async def test_extract_terms_returns_term_type_from_parsed_response() -> None:
    client = _FakeLLMClient([f"Alice{TUPLE_DELIMITER}A protagonist.{TUPLE_DELIMITER}character"])
    chunk = ChunkRecord(chunk_id="chunk-1", hash="hash-1", text="Alice appears.")
    config = ExtractorConfig(model="test-model", max_gleaning=0, max_term_name_length=100)

    terms = await extract_terms(chunk, client, config, source_language="English")

    assert len(terms) == 1
    assert terms[0].key == "Alice"
    assert terms[0].term_type == "character"
    assert terms[0].votes == 1
    assert terms[0].total_api_calls == 1
    assert terms[0].descriptions == {"chunk-1": "A protagonist."}


async def test_extract_terms_runs_real_gleaning_and_keeps_one_vote_per_chunk() -> None:
    client = _FakeLLMClient(
        [
            f"Alice{TUPLE_DELIMITER}A protagonist.{TUPLE_DELIMITER}character",
            f"Relic{TUPLE_DELIMITER}An ancient artifact.{TUPLE_DELIMITER}other",
        ]
    )
    chunk = ChunkRecord(chunk_id="chunk-1", hash="hash-1", text="Alice appears and finds a Relic.")
    config = ExtractorConfig(model="test-model", max_gleaning=1, max_term_name_length=100)

    terms = await extract_terms(chunk, client, config, source_language="English")

    assert client.calls == 2
    assert len(client.requests) == 2
    assert client.requests[1][2] == {
        "role": "assistant",
        "content": f"Alice{TUPLE_DELIMITER}A protagonist.{TUPLE_DELIMITER}character",
    }
    assert "遗漏" in client.requests[1][3]["content"]
    assert "已检测术语" not in client.requests[1][3]["content"]
    assert "前面对话" not in client.requests[1][3]["content"]
    assert {term.key: term.votes for term in terms} == {"Alice": 1, "Relic": 1}
    assert {term.key: term.total_api_calls for term in terms} == {"Alice": 2, "Relic": 2}


async def test_extract_terms_ignores_duplicate_terms_returned_by_gleaning() -> None:
    client = _FakeLLMClient(
        [
            f"Alice{TUPLE_DELIMITER}A protagonist.{TUPLE_DELIMITER}character",
            (
                f"Alice{TUPLE_DELIMITER}A fictional city with a much longer misleading description."
                f"{TUPLE_DELIMITER}organization\n"
                f"Relic{TUPLE_DELIMITER}An ancient artifact.{TUPLE_DELIMITER}other"
            ),
        ]
    )
    chunk = ChunkRecord(chunk_id="chunk-1", hash="hash-1", text="Alice appears and finds a Relic.")
    config = ExtractorConfig(model="test-model", max_gleaning=1, max_term_name_length=100)

    terms = await extract_terms(chunk, client, config, source_language="English")

    term_map = {term.key: term for term in terms}
    assert term_map["Alice"].descriptions == {"chunk-1": "A protagonist."}
    assert term_map["Alice"].term_type == "character"
    assert term_map["Alice"].term_type_votes == {"character": 1}
    assert term_map["Relic"].descriptions == {"chunk-1": "An ancient artifact."}
