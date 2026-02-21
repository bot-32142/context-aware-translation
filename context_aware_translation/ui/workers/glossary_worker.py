"""Workers for glossary operations."""

import asyncio
import logging
from pathlib import Path

from context_aware_translation.core.progress import ProgressUpdate, WorkflowStep
from context_aware_translation.glossary_io import export_glossary
from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.workflow.session import WorkflowSession

from .base_worker import BaseWorker

logger = logging.getLogger(__name__)


class BuildGlossaryWorker(BaseWorker):
    """Worker for building glossary (extract + translate terms)."""

    def __init__(self, book_manager: BookManager, book_id: str, document_ids: list[int] | None = None) -> None:
        """Initialize the worker.

        Args:
            book_manager: Book manager instance
            book_id: Book ID to build glossary for
            document_ids: Specific document IDs to process, or None for all
        """
        super().__init__()
        self.book_manager = book_manager
        self.book_id = book_id
        self.document_ids = document_ids

    def _execute(self) -> None:
        """Run the glossary building process."""
        self._raise_if_cancelled()
        translator = WorkflowSession.from_book(self.book_manager, self.book_id)
        with translator as session:
            asyncio.run(
                session.build_glossary(
                    document_ids=self.document_ids,
                    progress_callback=self._emit_progress,
                    cancel_check=self._is_cancelled,
                )
            )
        self.finished_success.emit(None)


class TranslateGlossaryWorker(BaseWorker):
    """Worker for re-translating glossary terms."""

    def __init__(self, book_manager: BookManager, book_id: str) -> None:
        """Initialize the worker.

        Args:
            book_manager: Book manager instance
            book_id: Book ID to translate glossary for
        """
        super().__init__()
        self.book_manager = book_manager
        self.book_id = book_id

    def _execute(self) -> None:
        """Run the glossary translation process."""
        self._raise_if_cancelled()
        translator = WorkflowSession.from_book(self.book_manager, self.book_id)
        with translator as session:
            asyncio.run(
                session.translate_glossary(
                    progress_callback=self._emit_progress,
                    cancel_check=self._is_cancelled,
                )
            )
        self.finished_success.emit(None)


class ReviewTermsWorker(BaseWorker):
    """Worker for reviewing unreviewed terms."""

    def __init__(self, book_manager: BookManager, book_id: str) -> None:
        """Initialize the worker.

        Args:
            book_manager: Book manager instance
            book_id: Book ID to review terms for
        """
        super().__init__()
        self.book_manager = book_manager
        self.book_id = book_id

    def _execute(self) -> None:
        """Run the term review process."""
        self._raise_if_cancelled()
        translator = WorkflowSession.from_book(self.book_manager, self.book_id)
        with translator as session:
            asyncio.run(
                session.review_terms(
                    progress_callback=self._emit_progress,
                    cancel_check=self._is_cancelled,
                )
            )
        self.finished_success.emit(None)


class ExportGlossaryWorker(BaseWorker):
    """Worker for exporting glossary JSON with summarized descriptions."""

    def __init__(
        self,
        book_manager: BookManager,
        book_id: str,
        output_path: Path,
        skip_context: bool = False,
    ) -> None:
        super().__init__()
        self.book_manager = book_manager
        self.book_id = book_id
        self.output_path = output_path
        self.skip_context = skip_context

    def _execute(self) -> None:
        self._raise_if_cancelled()
        translator = WorkflowSession.from_book(self.book_manager, self.book_id)
        with translator as session:
            session.db.refresh()
            summarized_descriptions = session.manager.build_fully_summarized_descriptions(
                cancel_check=self._is_cancelled,
                progress_callback=self._emit_progress,
                skip_context=self.skip_context,
            )
            self._raise_if_cancelled()
            self._emit_progress(
                ProgressUpdate(
                    step=WorkflowStep.EXPORT,
                    current=1,
                    total=1,
                    message="Writing glossary file...",
                )
            )
            count = export_glossary(
                session.db,
                self.output_path,
                summarized_descriptions=summarized_descriptions,
            )
        self.finished_success.emit({"count": count, "path": str(self.output_path)})
