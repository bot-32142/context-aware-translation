"""Worker for translation operations."""

import asyncio
import logging

from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.workflow.session import WorkflowSession

from .base_worker import BaseWorker

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
    ) -> None:
        super().__init__()
        self.book_manager = book_manager
        self.book_id = book_id
        self.document_ids = document_ids
        self.force = force
        self.skip_context = skip_context

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
