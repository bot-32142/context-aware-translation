from __future__ import annotations

from context_aware_translation.config import ExtractorConfig
from context_aware_translation.llm.extractor import (
    TUPLE_DELIMITER,
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
            "term_type_votes": {"character": 2, "organization": 1},
            "votes": 3,
        }
    ]


class _FakeLLMClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls = 0

    async def chat(self, messages: list[dict[str, str]], step_config: ExtractorConfig) -> str:
        del messages, step_config
        response = self._responses[self.calls]
        self.calls += 1
        return response


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
