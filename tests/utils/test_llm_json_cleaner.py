from __future__ import annotations

import json

from context_aware_translation.utils.llm_json_cleaner import clean_llm_response, parse_llm_json


def test_strip_json_markdown():
    llm_output = """```json
    {
    "key": "value"
    }
    ```"""
    assert json.loads(clean_llm_response(llm_output)) == json.loads('{ "key": "value" }')


def test_parse_llm_json_repairs_bare_dialogue_quotes():
    llm_output = """{
  "翻译文本": [
    {
      "id": 0,
      "文本": "—Sire," said Villefort, "Your Majesty is mistaken."
    }
  ]
}"""

    parsed, repaired_quotes = parse_llm_json(llm_output)

    assert repaired_quotes == 2
    assert parsed == {
        "翻译文本": [
            {
                "id": 0,
                "文本": '—Sire," said Villefort, "Your Majesty is mistaken.',
            }
        ]
    }
