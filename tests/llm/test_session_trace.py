from __future__ import annotations

from context_aware_translation.llm.session_trace import get_llm_session_id, llm_session_scope


def test_llm_session_scope_generates_and_resets_context():
    assert get_llm_session_id() is None
    with llm_session_scope() as session_id:
        assert session_id
        assert get_llm_session_id() == session_id
    assert get_llm_session_id() is None


def test_llm_session_scope_reuses_existing_session():
    with llm_session_scope("fixed-session-id") as outer_id:
        assert outer_id == "fixed-session-id"
        with llm_session_scope() as inner_id:
            assert inner_id == outer_id
            assert get_llm_session_id() == outer_id
        assert get_llm_session_id() == outer_id
