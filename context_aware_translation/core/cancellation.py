"""Cancellation primitives shared across workflow, core, and UI workers."""

from __future__ import annotations

from collections.abc import Callable


class OperationCancelledError(Exception):
    """Raised when a user-requested cooperative cancellation is observed."""

    pass


def raise_if_cancelled(cancel_check: Callable[[], bool] | None) -> None:
    """Raise OperationCancelledError if cancel_check indicates cancellation."""
    if cancel_check is not None and cancel_check():
        raise OperationCancelledError("Operation cancelled by user request.")
