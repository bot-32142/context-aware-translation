"""Worker for export operations."""

import asyncio
import logging
from pathlib import Path

from context_aware_translation.core.progress import ProgressUpdate, WorkflowStep
from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.workflow.services import export_ops
from context_aware_translation.workflow.session import WorkflowSession

from .base_worker import BaseWorker

logger = logging.getLogger(__name__)


class ExportWorker(BaseWorker):
    """Worker for exporting translated content."""

    def __init__(
        self,
        book_manager: BookManager,
        book_id: str,
        output_path: Path,
        export_format: str | None = None,
        document_ids: list[int] | None = None,
        preserve_structure: bool = False,
        allow_original_fallback: bool = False,
    ) -> None:
        super().__init__()
        self.book_manager = book_manager
        self.book_id = book_id
        self.output_path = output_path
        self.export_format = export_format
        self.document_ids = document_ids
        self.preserve_structure = preserve_structure
        self.allow_original_fallback = allow_original_fallback

    def _execute(self) -> None:
        self._raise_if_cancelled()
        translator = WorkflowSession.from_book(self.book_manager, self.book_id)
        with translator as context:
            if self.preserve_structure:
                self._emit_progress(
                    ProgressUpdate(
                        step=WorkflowStep.EXPORT,
                        current=0,
                        total=1,
                        message="Exporting with preserved structure...",
                    )
                )
                asyncio.run(
                    export_ops.export_preserve_structure(
                        context,
                        output_folder=self.output_path,
                        document_ids=self.document_ids,
                        allow_original_fallback=self.allow_original_fallback,
                        cancel_check=self._is_cancelled,
                    )
                )
                # Avoid cancellation checks after side effects have completed.
                self.progress.emit(1, 1, "Export complete")
            else:
                asyncio.run(
                    export_ops.export(
                        context,
                        file_path=self.output_path,
                        export_format=self.export_format,
                        document_ids=self.document_ids,
                        allow_original_fallback=self.allow_original_fallback,
                        progress_callback=self._emit_progress,
                        cancel_check=self._is_cancelled,
                    )
                )
        # Emit success after context manager closes
        self.finished_success.emit(str(self.output_path))
