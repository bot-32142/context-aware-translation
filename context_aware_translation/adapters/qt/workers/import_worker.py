"""Worker for document import operations."""

from pathlib import Path

from context_aware_translation.adapters.qt.workers.base_worker import BaseWorker
from context_aware_translation.core.progress import ProgressUpdate, WorkflowStep
from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.repositories.document_repository import DocumentRepository
from context_aware_translation.storage.schema.book_db import SQLiteBookDB
from context_aware_translation.workflow.ops.import_support import (
    import_via_repository,
    normalize_import_paths,
)


class ImportWorker(BaseWorker):
    """Worker for importing documents into a book."""

    def __init__(
        self,
        book_manager: BookManager,
        book_id: str,
        path: Path | list[Path],
        document_type: str | None = None,
    ) -> None:
        super().__init__()
        self.book_manager = book_manager
        self.book_id = book_id
        self.paths = normalize_import_paths(path)
        self.document_type = document_type

    def _execute(self) -> None:
        self._raise_if_cancelled()
        db_path = self.book_manager.get_book_db_path(self.book_id)
        db = SQLiteBookDB(db_path)
        try:
            repo = DocumentRepository(db)
            self._emit_progress(ProgressUpdate(step=WorkflowStep.EXPORT, current=0, total=1, message="Importing..."))
            result = import_via_repository(
                repo,
                paths=self.paths,
                document_type=self.document_type,
                cancel_check=self._is_cancelled,
                progress_callback=self._emit_progress,
            )
            self._emit_progress(ProgressUpdate(step=WorkflowStep.EXPORT, current=1, total=1, message="Import complete"))
        finally:
            db.close()
        self.finished_success.emit(result)
