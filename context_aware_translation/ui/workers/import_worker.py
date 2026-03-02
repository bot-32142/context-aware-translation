"""Worker for document import operations."""

import inspect
from pathlib import Path
from typing import Any

from context_aware_translation.core.cancellation import raise_if_cancelled
from context_aware_translation.core.progress import ProgressUpdate, WorkflowStep
from context_aware_translation.documents.base import get_document_classes
from context_aware_translation.storage.book_db import SQLiteBookDB
from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.document_repository import DocumentRepository
from context_aware_translation.ui.workers.base_worker import BaseWorker


class ImportWorker(BaseWorker):
    """Worker for importing documents into a book."""

    def __init__(
        self,
        book_manager: BookManager,
        book_id: str,
        path: Path,
        document_type: str | None = None,
    ) -> None:
        super().__init__()
        self.book_manager = book_manager
        self.book_id = book_id
        self.path = path
        self.document_type = document_type

    def _resolve_imported_document_id(
        self,
        repo: DocumentRepository,
        existing_document_ids: set[int],
        imported_count: int,
    ) -> int | None:
        """Resolve the newly created document_id after an import operation."""
        if imported_count <= 0:
            return None

        after_documents = repo.list_documents()
        new_ids = sorted(
            int(doc["document_id"]) for doc in after_documents if int(doc["document_id"]) not in existing_document_ids
        )
        if not new_ids:
            return None
        return new_ids[-1]

    def _import_path(self, repo: DocumentRepository) -> dict[str, int | None]:
        """Import path directly via document classes (no workflow runtime needed)."""
        raise_if_cancelled(self._is_cancelled)
        if not self.path.exists():
            raise ValueError(f"Path does not exist: {self.path}")

        raise_if_cancelled(self._is_cancelled)
        if self.path.is_dir() and not any(self.path.iterdir()):
            raise ValueError(f"Cannot import empty folder: {self.path}")

        classes = get_document_classes()
        existing_document_ids = {int(doc["document_id"]) for doc in repo.list_documents()}

        def run_import(document_cls: type) -> dict[str, int]:
            self._emit_progress(ProgressUpdate(step=WorkflowStep.EXPORT, current=0, total=1, message="Importing..."))
            kwargs: dict[str, Any] = {"cancel_check": self._is_cancelled}
            try:
                params = inspect.signature(document_cls.do_import).parameters
            except (TypeError, ValueError):
                params = {}
            if "progress_callback" in params:
                kwargs["progress_callback"] = self._emit_progress
            result = document_cls.do_import(repo, self.path, **kwargs)
            self._emit_progress(ProgressUpdate(step=WorkflowStep.EXPORT, current=1, total=1, message="Import complete"))
            return result

        if self.document_type:
            for cls in classes:
                raise_if_cancelled(self._is_cancelled)
                if cls.document_type != self.document_type:
                    continue
                if not cls.can_import(self.path):
                    raise ValueError(f"Path cannot be imported as {self.document_type}")
                result = run_import(cls)
                document_id = self._resolve_imported_document_id(repo, existing_document_ids, int(result["imported"]))
                return {
                    "imported": int(result["imported"]),
                    "skipped": int(result["skipped"]),
                    "document_id": document_id,
                }
            raise ValueError(f"Unknown document type: {self.document_type}")

        matches = [cls for cls in classes if cls.can_import(self.path)]
        if len(matches) > 1:
            names = [cls.__name__.replace("Document", "").lower() for cls in matches]
            raise ValueError(f"Path can be imported as: {', '.join(names)}. Please specify document_type.")
        if not matches:
            raise ValueError("Cannot import path: no supported document type matches.")

        result = run_import(matches[0])
        document_id = self._resolve_imported_document_id(repo, existing_document_ids, int(result["imported"]))
        return {
            "imported": int(result["imported"]),
            "skipped": int(result["skipped"]),
            "document_id": document_id,
        }

    def _execute(self) -> None:
        self._raise_if_cancelled()
        db_path = self.book_manager.get_book_db_path(self.book_id)
        db = SQLiteBookDB(db_path)
        try:
            repo = DocumentRepository(db)
            result = self._import_path(repo)
        finally:
            db.close()
        self.finished_success.emit(result)
