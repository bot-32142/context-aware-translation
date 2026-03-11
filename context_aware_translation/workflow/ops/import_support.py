from __future__ import annotations

import inspect
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from context_aware_translation.core.cancellation import raise_if_cancelled
from context_aware_translation.documents.base import get_document_classes
from context_aware_translation.storage.repositories.document_repository import DocumentRepository


def deduplicate_paths(paths: list[Path]) -> list[Path]:
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
    normalized = deduplicate_paths([Path(p) for p in path]) if isinstance(path, list) else [Path(path)]
    if not normalized:
        raise ValueError("No files selected for import.")
    return normalized


def link_or_copy_file(source: Path, target: Path) -> None:
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


def compute_common_parent(paths: list[Path]) -> Path | None:
    """Return common parent directory for selected files when available."""
    parent_strings = [str(path.parent) for path in paths]
    try:
        common = os.path.commonpath(parent_strings)
    except ValueError:
        return None
    return Path(common)


def relative_stage_path(source: Path, common_parent: Path | None, index: int) -> Path:
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
        common_parent = compute_common_parent(normalized)

        for index, source in enumerate(normalized):
            rel_path = relative_stage_path(source, common_parent, index)
            target = staged_root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            candidate = target
            suffix = 1
            while candidate.exists():
                candidate = target.with_name(f"{target.stem}_{suffix}{target.suffix}")
                suffix += 1
            link_or_copy_file(source, candidate)

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


@contextmanager
def resolve_import_path(paths: list[Path]) -> Iterator[Path]:
    """Yield a direct path or staged folder for multi-file import."""
    normalized = normalize_import_paths(paths)
    if len(normalized) == 1:
        yield normalized[0]
        return
    with stage_selected_files_as_folder(normalized) as staged_root:
        yield staged_root


def resolve_imported_document_id(
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


def import_via_repository(
    repo: DocumentRepository,
    *,
    paths: list[Path],
    document_type: str | None = None,
    cancel_check: Any = None,
    progress_callback: Any = None,
) -> dict[str, int | None]:
    """Import one file, folder, or staged multi-file folder through document classes."""
    normalized = normalize_import_paths(paths)
    existing_document_ids = {int(doc["document_id"]) for doc in repo.list_documents()}

    with resolve_import_path(normalized) as import_path:
        raise_if_cancelled(cancel_check)
        if not import_path.exists():
            raise ValueError(f"Path does not exist: {import_path}")
        raise_if_cancelled(cancel_check)
        if import_path.is_dir() and not any(import_path.iterdir()):
            raise ValueError(f"Cannot import empty folder: {import_path}")

        classes = get_document_classes()
        matches: list[type] = []
        if document_type:
            for cls in classes:
                raise_if_cancelled(cancel_check)
                if cls.document_type != document_type:
                    continue
                if not cls.can_import(import_path):
                    raise ValueError(f"Path cannot be imported as {document_type}")
                matches = [cls]
                break
            if not matches:
                raise ValueError(f"Unknown document type: {document_type}")
        else:
            for cls in classes:
                raise_if_cancelled(cancel_check)
                if cls.can_import(import_path):
                    matches.append(cls)
            if len(matches) > 1:
                names = [cls.__name__.replace("Document", "").lower() for cls in matches]
                raise ValueError(f"Path can be imported as: {', '.join(names)}. Please specify document_type.")
            if not matches:
                raise ValueError("Cannot import path: no supported document type matches.")

        document_class = matches[0]
        import_method = getattr(document_class, "do_import", None)
        if not callable(import_method):
            raise ValueError(f"Document type {document_class.__name__} does not support import.")
        kwargs: dict[str, Any] = {"cancel_check": cancel_check}
        try:
            has_progress_callback = "progress_callback" in inspect.signature(import_method).parameters
        except (TypeError, ValueError):
            has_progress_callback = False
        if has_progress_callback:
            kwargs["progress_callback"] = progress_callback
        result = import_method(repo, import_path, **kwargs)
        document_id = resolve_imported_document_id(repo, existing_document_ids, int(result["imported"]))
        return {
            "imported": int(result["imported"]),
            "skipped": int(result["skipped"]),
            "document_id": document_id,
        }
