from __future__ import annotations

import json
import re
from typing import Any


def clean_llm_response(response_text: str) -> str:
    # This pattern matches:
    # 1. Start with ```json (or just ```)
    # 2. Capture everything inside (.*?)
    # 3. End with ```
    # re.DOTALL allows the dot (.) to match newlines
    pattern = r"^```(?:json)?\s*(.*?)\s*```$"

    match = re.search(pattern, response_text.strip(), re.DOTALL)

    if match:
        return match.group(1)

    # If no tags are found, return the original string
    return response_text


def _next_non_whitespace_char(text: str, start: int) -> str | None:
    for idx in range(start, len(text)):
        if not text[idx].isspace():
            return text[idx]
    return None


def _repair_bare_quotes_in_json_strings(text: str) -> tuple[str, int]:
    repaired: list[str] = []
    in_string = False
    escaped = False
    repaired_quotes = 0

    for idx, char in enumerate(text):
        if not in_string:
            repaired.append(char)
            if char == '"':
                in_string = True
            continue

        if escaped:
            repaired.append(char)
            escaped = False
            continue

        if char == "\\":
            repaired.append(char)
            escaped = True
            continue

        if char == '"':
            next_non_whitespace = _next_non_whitespace_char(text, idx + 1)
            if next_non_whitespace is None or next_non_whitespace in {",", "}", "]", ":"}:
                repaired.append(char)
                in_string = False
            else:
                repaired.append('\\"')
                repaired_quotes += 1
            continue

        if char == "\n":
            repaired.append("\\n")
            continue
        if char == "\r":
            repaired.append("\\r")
            continue
        if char == "\t":
            repaired.append("\\t")
            continue

        repaired.append(char)

    return "".join(repaired), repaired_quotes


def parse_llm_json(response_text: str) -> tuple[Any, int]:
    cleaned = clean_llm_response(response_text)
    try:
        return json.loads(cleaned), 0
    except json.JSONDecodeError as original_exc:
        repaired, repaired_quotes = _repair_bare_quotes_in_json_strings(cleaned)
        if repaired_quotes <= 0:
            raise
        try:
            return json.loads(repaired), repaired_quotes
        except json.JSONDecodeError:
            raise original_exc from None
