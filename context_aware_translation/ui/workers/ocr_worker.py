"""Worker for OCR operations."""

import asyncio
import logging

from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.workflow.session import WorkflowSession

from .base_worker import BaseWorker

logger = logging.getLogger(__name__)


class OCRWorker(BaseWorker):
    """Worker for running OCR on document pages."""

    def __init__(self, book_manager: BookManager, book_id: str, source_ids: list[int] | None = None) -> None:
        super().__init__()
        self.book_manager = book_manager
        self.book_id = book_id
        self.source_ids = source_ids

    def _execute(self) -> None:
        self._raise_if_cancelled()
        translator = WorkflowSession.from_book(self.book_manager, self.book_id)
        with translator as session:
            count = asyncio.run(
                session.run_ocr(
                    progress_callback=self._emit_progress,
                    source_ids=self.source_ids,
                    cancel_check=self._is_cancelled,
                )
            )
        self.finished_success.emit(count)
