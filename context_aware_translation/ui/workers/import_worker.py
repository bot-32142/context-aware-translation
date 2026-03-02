"""Worker for document import operations."""

import inspect
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from context_aware_translation.core.cancellation import raise_if_cancelled
from context_aware_translation.core.progress import ProgressUpdate, WorkflowStep
from context_aware_translation.documents.base import get_document_classes
from context_aware_translation.storage.book_db import SQLiteBookDB
from context_aware_translation.storage.book_manager import BookManager
from context_aware_translation.storage.document_repository import DocumentRepository
from context_aware_translation.ui.workers.base_worker import BaseWorker


def _deduplicate_paths(paths: list[Path]) -> list[Path]:
    """Preserve order while removing duplicates."""
    unique_paths: list[Path] = []
    seen_paths: set[Path] = set()
    for path in paths:
        normalized = Path(path)
        if normalized in seen_paths:
            continue
        seen_paths.add(normalized)
        unique_paths.append(normalized)
    return unique_paths


def normalize_import_paths(path: Path | list[Path]) -> list[Path]:
    """Normalize import input into a non-empty list of paths."""
    normalized = _deduplicate_paths([Path(p) for p in path]) if isinstance(path, list) else [Path(path)]

    if not normalized:
        raise ValueError("No files selected for import.")

    return normalized


def _link_or_copy_file(source: Path, target: Path) -> None:
    """Stage source file into target path using hardlink/symlink/copy fallback."""
    try:
        os.link(source, target)
        return
    except OSError:
        pass

    try:
        os.symlink(source, target)
        return
    except OSError:
        pass

    shutil.copy2(source, target)


def _compute_common_parent(paths: list[Path]) -> Path | None:
    """Return common parent directory for selected files when available."""
    parent_strings = [str(path.parent) for path in paths]
    try:
        common = os.path.commonpath(parent_strings)
    except ValueError:
        return None
    return Path(common)


def _relative_stage_path(source: Path, common_parent: Path | None, index: int) -> Path:
    """Build a stable relative path for staging selected files."""
    if common_parent is not None:
        try:
            relative = source.relative_to(common_parent)
            if not relative.is_absolute():
                return relative
        except ValueError:
            pass
    return Path(f"{index:04d}_{source.name}")


@contextmanager
def stage_selected_files_as_folder(paths: list[Path]) -> Iterator[Path]:
    """Create a temporary folder view of selected files for folder-style import."""
    normalized = normalize_import_paths(paths)
    for path in normalized:
        if not path.exists():
            raise ValueError(f"Path does not exist: {path}")
        if not path.is_file():
            raise ValueError(f"Expected file path for multi-file import: {path}")

    with tempfile.TemporaryDirectory(prefix="cat-import-") as temp_dir:
        staged_root = Path(temp_dir)
        common_parent = _compute_common_parent(normalized)

        for index, source in enumerate(normalized):
            relative_path = _relative_stage_path(source, common_parent, index)
            target = staged_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)

            # Keep paths unique if selected files would collide after staging.
            candidate = target
            suffix = 1
            while candidate.exists():
                candidate = target.with_name(f"{target.stem}_{suffix}{target.suffix}")
                suffix += 1

            _link_or_copy_file(source, candidate)

        yield staged_root


def get_compatible_document_classes_for_paths(paths: list[Path]) -> list[type]:
    """Return document classes that can import selected file(s)."""
    normalized = normalize_import_paths(paths)
    classes = get_document_classes()

    if len(normalized) == 1:
        candidate_path = normalized[0]
        return [cls for cls in classes if cls.can_import(candidate_path)]

    with stage_selected_files_as_folder(normalized) as staged_root:
        return [cls for cls in classes if cls.can_import(staged_root)]


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

    @contextmanager
    def _resolve_import_path(self) -> Iterator[Path]:
        if len(self.paths) == 1:
            yield self.paths[0]
            return

        with stage_selected_files_as_folder(self.paths) as staged_root:
            yield staged_root

    def _import_path(self, repo: DocumentRepository, path: Path) -> dict[str, int | None]:
        """Import path directly via document classes (no workflow runtime needed)."""
        raise_if_cancelled(self._is_cancelled)
        if not path.exists():
            raise ValueError(f"Path does not exist: {path}")

        raise_if_cancelled(self._is_cancelled)
        if path.is_dir() and not any(path.iterdir()):
            raise ValueError(f"Cannot import empty folder: {path}")

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
            result = document_cls.do_import(repo, path, **kwargs)
            self._emit_progress(ProgressUpdate(step=WorkflowStep.EXPORT, current=1, total=1, message="Import complete"))
            return result

        if self.document_type:
            for cls in classes:
                raise_if_cancelled(self._is_cancelled)
                if cls.document_type != self.document_type:
                    continue
                if not cls.can_import(path):
                    raise ValueError(f"Path cannot be imported as {self.document_type}")
                result = run_import(cls)
                document_id = self._resolve_imported_document_id(repo, existing_document_ids, int(result["imported"]))
                return {
                    "imported": int(result["imported"]),
                    "skipped": int(result["skipped"]),
                    "document_id": document_id,
                }
            raise ValueError(f"Unknown document type: {self.document_type}")

        matches = [cls for cls in classes if cls.can_import(path)]
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
            with self._resolve_import_path() as import_path:
                result = self._import_path(repo, import_path)
        finally:
            db.close()
        self.finished_success.emit(result)
