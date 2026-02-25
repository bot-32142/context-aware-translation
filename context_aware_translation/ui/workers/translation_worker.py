"""Worker for translation operations."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.workflow.session import WorkflowSession

from .base_worker import BaseWorker
from .batch_task_overlap_guard import has_any_batch_task_overlap
from .operation_tracker import DocumentOperationTracker

if TYPE_CHECKING:
    from context_aware_translation.storage.task_store import TaskStore

logger = logging.getLogger(__name__)


class TranslationWorker(BaseWorker):
    """Worker for translating chunks."""

    def __init__(
        self,
        book_manager: BookManager,
        book_id: str,
        document_ids: list[int] | None = None,
        force: bool = False,
        skip_context: bool = False,
        task_store: TaskStore | None = None,
    ) -> None:
        super().__init__()
        self.book_manager = book_manager
        self.book_id = book_id
        self.document_ids = document_ids
        self.force = force
        self.skip_context = skip_context
        self.task_store = task_store

    def run(self) -> None:
        op_id = DocumentOperationTracker.try_start_operation(self.book_id, self.document_ids)
        if op_id is None:
            logger.info("Skipping translation for %s due to active selected-doc overlap", self.book_id)
            self.error.emit("Selected documents have active operations. Please wait for them to complete.")
            return
        try:
            if self.task_store is not None and has_any_batch_task_overlap(self.task_store, self.book_id, self.document_ids):
                logger.info("Skipping translation for %s due to existing batch-task reservation", self.book_id)
                self.error.emit(
                    "Selected documents are reserved by existing batch tasks. Delete overlapping task(s) first."
                )
                return
            super().run()
        finally:
            DocumentOperationTracker.finish_operation(self.book_id, op_id)

    def _execute(self) -> None:
        """Execute translation."""
        self._raise_if_cancelled()
        translator = WorkflowSession.from_book(self.book_manager, self.book_id)
        with translator as session:
            asyncio.run(
                session.translate(
                    document_ids=self.document_ids,
                    progress_callback=self._emit_progress,
                    force=self.force,
                    skip_context=self.skip_context,
                    cancel_check=self._is_cancelled,
                )
            )
        self.finished_success.emit(None)


class RetranslateChunkWorker(BaseWorker):
    """Worker for retranslating a single chunk."""

    def __init__(
        self,
        book_manager: BookManager,
        book_id: str,
        chunk_id: int,
        document_id: int,
        skip_context: bool = False,
    ) -> None:
        super().__init__()
        self.book_manager = book_manager
        self.book_id = book_id
        self.chunk_id = chunk_id
        self.document_id = document_id
        self.skip_context = skip_context

    def run(self) -> None:
        op_id = DocumentOperationTracker.try_start_operation(self.book_id, [self.document_id])
        if op_id is None:
            logger.info("Skipping retranslation for %s due to active selected-doc overlap", self.book_id)
            return
        try:
            super().run()
        finally:
            DocumentOperationTracker.finish_operation(self.book_id, op_id)

    def _execute(self) -> None:
        """Retranslate a single chunk."""
        self._raise_if_cancelled()
        translator = WorkflowSession.from_book(self.book_manager, self.book_id)
        with translator as session:
            new_translation = asyncio.run(
                session.retranslate_chunk(
                    chunk_id=self.chunk_id,
                    document_id=self.document_id,
                    skip_context=self.skip_context,
                    cancel_check=self._is_cancelled,
                )
            )
        self.finished_success.emit(new_translation)
