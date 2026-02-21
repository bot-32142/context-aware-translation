from __future__ import annotations

import json

from context_aware_translation.utils.llm_json_cleaner import clean_llm_response


def test_strip_json_markdown():
    llm_output = """```json
    {
    "key": "value"
    }
    ```"""
    assert json.loads(clean_llm_response(llm_output)) == json.loads('{ "key": "value" }')
