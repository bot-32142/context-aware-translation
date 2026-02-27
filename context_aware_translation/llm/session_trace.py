from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_LLM_SESSION_ID: ContextVar[str | None] = ContextVar("llm_session_id", default=None)


def _new_llm_session_id() -> str:
    """Generate a new opaque ID for tracing one LLM processing session."""
    return uuid.uuid4().hex


def get_llm_session_id() -> str | None:
    """Return current LLM session ID from context, if any."""
    return _LLM_SESSION_ID.get()


@contextmanager
def llm_session_scope(session_id: str | None = None) -> Iterator[str]:
    """Ensure one session ID is available in context for nested LLM calls.

    If a session already exists in context, it is reused so retries/polish
    paths share one trace ID.
    """
    existing = _LLM_SESSION_ID.get()
    if existing is not None:
        yield existing
        return

    sid = session_id or _new_llm_session_id()
    token = _LLM_SESSION_ID.set(sid)
    try:
        yield sid
    finally:
        _LLM_SESSION_ID.reset(token)
