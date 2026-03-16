from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from context_aware_translation.application.contracts.common import ContractModel


class ApplicationErrorCode(StrEnum):
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    PRECONDITION = "precondition"
    CONFLICT = "conflict"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"
    INTERNAL = "internal"


class ApplicationErrorPayload(ContractModel):
    code: ApplicationErrorCode
    message: str
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class ApplicationError(Exception):
    """Base exception raised by application services."""

    def __init__(self, payload: ApplicationErrorPayload):
        super().__init__(payload.message)
        self.payload = payload


class BlockedOperationError(ApplicationError):
    """Raised when an operation is denied by a stable application precondition."""
