"""Tests for WorkflowSession.from_snapshot() classmethod."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from context_aware_translation.workflow.session import WorkflowSession


def _v1_envelope(config_dict: dict) -> str:
    """Build a valid v1 snapshot envelope."""
    return json.dumps({"snapshot_version": 1, "config": config_dict})


class TestFromSnapshot:
    def test_from_snapshot_creates_valid_session_with_v1_envelope(self):
        """from_snapshot() should create a WorkflowSession from a v1 envelope."""
        config_dict = {"translation_target_language": "English"}
        snapshot_json = _v1_envelope(config_dict)
        mock_config = MagicMock()

        with patch(
            "context_aware_translation.workflow.session.Config.from_dict",
            return_value=mock_config,
        ) as mock_from_dict:
            session = WorkflowSession.from_snapshot(snapshot_json, "book-42")

        assert isinstance(session, WorkflowSession)
        assert session._book_id == "book-42"
        assert session.config is mock_config
        mock_from_dict.assert_called_once_with(config_dict)

    def test_from_snapshot_accepts_legacy_raw_config_dict(self):
        """from_snapshot() should accept a raw config dict without version envelope."""
        config_dict = {"translation_target_language": "Japanese", "some_extra_key": 1}
        snapshot_json = json.dumps(config_dict)
        mock_config = MagicMock()

        with patch(
            "context_aware_translation.workflow.session.Config.from_dict",
            return_value=mock_config,
        ) as mock_from_dict:
            session = WorkflowSession.from_snapshot(snapshot_json, "book-99")

        assert isinstance(session, WorkflowSession)
        assert session._book_id == "book-99"
        mock_from_dict.assert_called_once_with(config_dict)

    def test_from_snapshot_rejects_unsupported_snapshot_version(self):
        """from_snapshot() should raise ValueError for unknown snapshot versions."""
        bad_envelope = json.dumps({"snapshot_version": 999, "config": {}})

        with pytest.raises(ValueError, match="999"):
            WorkflowSession.from_snapshot(bad_envelope, "book-1")

    def test_from_snapshot_raises_on_invalid_json(self):
        """from_snapshot() should raise json.JSONDecodeError for malformed JSON."""
        import json as _json

        with pytest.raises(_json.JSONDecodeError):
            WorkflowSession.from_snapshot("not-valid-json{{{", "book-1")
