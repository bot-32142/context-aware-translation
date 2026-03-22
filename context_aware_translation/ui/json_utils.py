from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QT_TRANSLATE_NOOP

_JSON_INVALID = QT_TRANSLATE_NOOP("JsonObjectValidation", "Custom parameters must be valid JSON.")
_JSON_NOT_OBJECT = QT_TRANSLATE_NOOP("JsonObjectValidation", "Custom parameters must be a JSON object.")


def parse_json_object_text(raw_text: str, *, tr: Callable[[str], str]) -> dict[str, Any]:
    stripped = raw_text.strip()
    if not stripped:
        return {}
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError(tr(str(_JSON_INVALID))) from exc
    if not isinstance(parsed, dict):
        raise ValueError(tr(str(_JSON_NOT_OBJECT)))
    return {str(key): value for key, value in parsed.items()}
