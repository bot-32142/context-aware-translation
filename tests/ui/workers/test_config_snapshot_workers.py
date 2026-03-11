"""Tests for config_snapshot_json support in task workers."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from context_aware_translation.storage.repositories.task_store import TaskRecord

_VALID_SNAPSHOT = json.dumps({"snapshot_version": 1, "config": {"key": "value"}})


def _make_record(
    status: str = "queued",
    task_id: str = "task-1",
    book_id: str = "book-1",
    config_snapshot_json: str | None = None,
) -> TaskRecord:
    now = time.time()
    return TaskRecord(
        task_id=task_id,
        book_id=book_id,
        task_type="batch_translation",
        status=status,
        phase=None,
        document_ids_json=None,
        payload_json=None,
        config_snapshot_json=config_snapshot_json,
        cancel_requested=False,
        total_items=0,
        completed_items=0,
        failed_items=0,
        last_error=None,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# ChunkRetranslationTaskWorker
# ---------------------------------------------------------------------------


class TestChunkRetranslationTaskWorkerSnapshot:
    def _make_worker(self, snapshot: str | None = None):
        from context_aware_translation.adapters.qt.workers.chunk_retranslation_task_worker import (
            ChunkRetranslationTaskWorker,
        )

        book_manager = MagicMock()
        return ChunkRetranslationTaskWorker(
            book_manager,
            "book-1",
            action="run",
            chunk_id=42,
            document_id=1,
            config_snapshot_json=snapshot,
        )

    def test_uses_from_snapshot_when_snapshot_provided(self):
        worker = self._make_worker(snapshot=_VALID_SNAPSHOT)
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "context_aware_translation.adapters.qt.workers.chunk_retranslation_task_worker.WorkflowSession.from_snapshot",
                return_value=mock_session,
            ) as mock_from_snapshot,
            patch(
                "context_aware_translation.adapters.qt.workers.chunk_retranslation_task_worker.WorkflowSession.from_book",
            ) as mock_from_book,
            patch("asyncio.run", return_value="translation"),
        ):
            worker._run_retranslation()

        mock_from_snapshot.assert_called_once_with(_VALID_SNAPSHOT, "book-1")
        mock_from_book.assert_not_called()

    def test_falls_back_to_from_book_when_snapshot_is_none(self):
        worker = self._make_worker(snapshot=None)
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "context_aware_translation.adapters.qt.workers.chunk_retranslation_task_worker.WorkflowSession.from_book",
                return_value=mock_session,
            ) as mock_from_book,
            patch(
                "context_aware_translation.adapters.qt.workers.chunk_retranslation_task_worker.WorkflowSession.from_snapshot",
            ) as mock_from_snapshot,
            patch("asyncio.run", return_value="translation"),
        ):
            worker._run_retranslation()

        mock_from_book.assert_called_once()
        mock_from_snapshot.assert_not_called()


# ---------------------------------------------------------------------------
# GlossaryExtractionTaskWorker
# ---------------------------------------------------------------------------


class TestGlossaryExtractionTaskWorkerSnapshot:
    def _make_worker(self, snapshot: str | None = None):
        from context_aware_translation.adapters.qt.workers.glossary_extraction_task_worker import (
            GlossaryExtractionTaskWorker,
        )

        book_manager = MagicMock()
        return GlossaryExtractionTaskWorker(
            book_manager,
            "book-1",
            action="run",
            config_snapshot_json=snapshot,
        )

    def test_uses_from_snapshot_when_snapshot_provided(self):
        worker = self._make_worker(snapshot=_VALID_SNAPSHOT)
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "context_aware_translation.adapters.qt.workers.glossary_extraction_task_worker.WorkflowSession.from_snapshot",
                return_value=mock_session,
            ) as mock_from_snapshot,
            patch(
                "context_aware_translation.adapters.qt.workers.glossary_extraction_task_worker.WorkflowSession.from_book",
            ) as mock_from_book,
            patch("asyncio.run"),
        ):
            worker._run_extraction()

        mock_from_snapshot.assert_called_once_with(_VALID_SNAPSHOT, "book-1")
        mock_from_book.assert_not_called()

    def test_falls_back_to_from_book_when_snapshot_is_none(self):
        worker = self._make_worker(snapshot=None)
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "context_aware_translation.adapters.qt.workers.glossary_extraction_task_worker.WorkflowSession.from_book",
                return_value=mock_session,
            ) as mock_from_book,
            patch(
                "context_aware_translation.adapters.qt.workers.glossary_extraction_task_worker.WorkflowSession.from_snapshot",
            ) as mock_from_snapshot,
            patch("asyncio.run"),
        ):
            worker._run_extraction()

        mock_from_book.assert_called_once()
        mock_from_snapshot.assert_not_called()


# ---------------------------------------------------------------------------
# BatchTranslationTaskWorker
# ---------------------------------------------------------------------------


class TestBatchTranslationTaskWorkerSnapshot:
    def _make_worker(self, snapshot: str | None = None, action: str = "run"):
        from context_aware_translation.adapters.qt.workers.batch_translation_task_worker import (
            BatchTranslationTaskWorker,
        )

        book_manager = MagicMock()
        task_store = MagicMock()
        return BatchTranslationTaskWorker(
            book_manager,
            "book-1",
            action=action,
            task_id="task-1",
            task_store=task_store,
            config_snapshot_json=snapshot,
        )

    def test_run_uses_from_snapshot_when_snapshot_provided(self):
        worker = self._make_worker(snapshot=_VALID_SNAPSHOT, action="run")
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_executor = MagicMock()
        mock_executor.run_task = MagicMock(return_value=MagicMock())

        with (
            patch(
                "context_aware_translation.adapters.qt.workers.batch_translation_task_worker.WorkflowSession.from_snapshot",
                return_value=mock_session,
            ) as mock_from_snapshot,
            patch(
                "context_aware_translation.adapters.qt.workers.batch_translation_task_worker.WorkflowSession.from_book",
            ) as mock_from_book,
            patch(
                "context_aware_translation.adapters.qt.workers.batch_translation_task_worker.BatchTranslationExecutor.from_workflow",
                return_value=mock_executor,
            ),
            patch("asyncio.run", return_value=MagicMock()),
        ):
            worker._execute()

        mock_from_snapshot.assert_called_once_with(_VALID_SNAPSHOT, "book-1")
        mock_from_book.assert_not_called()

    def test_run_fails_fast_when_snapshot_restore_fails(self):
        worker = self._make_worker(snapshot=_VALID_SNAPSHOT, action="run")

        with (
            patch(
                "context_aware_translation.adapters.qt.workers.batch_translation_task_worker.WorkflowSession.from_snapshot",
                side_effect=ValueError("bad snapshot"),
            ),
            pytest.raises(ValueError, match="bad snapshot"),
        ):
            worker._execute()

        # Task store should be updated with failed status
        worker.task_store.update.assert_called_once_with(
            "task-1",
            status="failed",
            last_error=pytest.approx("Config snapshot restore failed: bad snapshot", rel=0),
        )

    def test_cancel_falls_back_to_from_book_when_snapshot_fails(self):
        worker = self._make_worker(snapshot=_VALID_SNAPSHOT, action="cancel")
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_executor = MagicMock()
        mock_executor.request_cancel = MagicMock(return_value=MagicMock())
        mock_book_session = MagicMock()
        mock_book_session.__enter__ = MagicMock(return_value=MagicMock())
        mock_book_session.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "context_aware_translation.adapters.qt.workers.batch_translation_task_worker.WorkflowSession.from_snapshot",
                side_effect=ValueError("corrupt snapshot"),
            ),
            patch(
                "context_aware_translation.adapters.qt.workers.batch_translation_task_worker.WorkflowSession.from_book",
                return_value=mock_book_session,
            ) as mock_from_book,
            patch(
                "context_aware_translation.adapters.qt.workers.batch_translation_task_worker.BatchTranslationExecutor.from_workflow",
                return_value=mock_executor,
            ),
            patch("asyncio.run", return_value=MagicMock()),
        ):
            worker._execute()

        # Should fall back to from_book for cancel flow
        mock_from_book.assert_called_once()

    def test_falls_back_to_from_book_when_snapshot_is_none(self):
        worker = self._make_worker(snapshot=None, action="run")
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=MagicMock())
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_executor = MagicMock()

        with (
            patch(
                "context_aware_translation.adapters.qt.workers.batch_translation_task_worker.WorkflowSession.from_book",
                return_value=mock_session,
            ) as mock_from_book,
            patch(
                "context_aware_translation.adapters.qt.workers.batch_translation_task_worker.WorkflowSession.from_snapshot",
            ) as mock_from_snapshot,
            patch(
                "context_aware_translation.adapters.qt.workers.batch_translation_task_worker.BatchTranslationExecutor.from_workflow",
                return_value=mock_executor,
            ),
            patch("asyncio.run", return_value=MagicMock()),
        ):
            worker._execute()

        mock_from_book.assert_called_once()
        mock_from_snapshot.assert_not_called()
