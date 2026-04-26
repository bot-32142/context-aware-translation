from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any

from context_aware_translation.application.errors import ApplicationError, ApplicationErrorCode

EXIT_INTERNAL = 1
EXIT_USAGE = 2
EXIT_PRECONDITION = 3
EXIT_NOT_FOUND = 4
EXIT_BLOCKED = 5
EXIT_TASK_FAILED = 6


@dataclass
class CliError(Exception):
    code: str
    message: str
    exit_code: int = EXIT_PRECONDITION
    details: dict[str, str | int | float | bool | None] = field(default_factory=dict)


def application_exit_code(code: ApplicationErrorCode) -> int:
    if code in {ApplicationErrorCode.VALIDATION, ApplicationErrorCode.PRECONDITION, ApplicationErrorCode.UNSUPPORTED}:
        return EXIT_PRECONDITION
    if code is ApplicationErrorCode.NOT_FOUND:
        return EXIT_NOT_FOUND
    if code in {ApplicationErrorCode.CONFLICT, ApplicationErrorCode.BLOCKED}:
        return EXIT_BLOCKED
    return EXIT_INTERNAL


def error_from_exception(exc: Exception) -> tuple[dict[str, Any], int]:
    if isinstance(exc, CliError):
        return (
            {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
            exc.exit_code,
        )
    if isinstance(exc, ApplicationError):
        payload = exc.payload
        return (
            {
                "code": payload.code.value,
                "message": payload.message,
                "details": payload.details,
            },
            application_exit_code(payload.code),
        )
    return (
        {
            "code": "internal",
            "message": str(exc) or type(exc).__name__,
            "details": {},
        },
        EXIT_INTERNAL,
    )


def print_json_envelope(
    *,
    ok: bool,
    command: str,
    data: Any | None = None,
    error: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> None:
    if ok:
        payload = {
            "ok": True,
            "command": command,
            "data": data if data is not None else {},
            "warnings": list(warnings or []),
        }
    else:
        payload = {
            "ok": False,
            "command": command,
            "error": error or {"code": "internal", "message": "Unknown error.", "details": {}},
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def print_human_error(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
