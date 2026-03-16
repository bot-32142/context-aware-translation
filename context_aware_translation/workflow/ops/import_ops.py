from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from context_aware_translation.documents import base as document_base
from context_aware_translation.documents.base import Document
from context_aware_translation.workflow.ops import bootstrap_ops

if TYPE_CHECKING:
    from context_aware_translation.workflow.runtime import WorkflowContext


def resolve_imported_document_id(
    workflow: WorkflowContext,
    existing_document_ids: set[int],
    imported_count: int,
) -> int | None:
    """Resolve the newly created document_id after an import operation."""
    if imported_count <= 0:
        return None

    after_documents = workflow.document_repo.list_documents()
    new_ids = sorted(
        int(doc["document_id"]) for doc in after_documents if int(doc["document_id"]) not in existing_document_ids
    )
    if not new_ids:
        return None
    return new_ids[-1]


def resolve_import_class(
    _workflow: WorkflowContext,
    classes: list[type[Document]],
    path: Path,
    *,
    document_type: str | None,
    cancel_check: Callable[[], bool] | None = None,
) -> type[Document]:
    """Resolve target document class for import request."""
    if document_type:
        for cls in classes:
            bootstrap_ops.check_cancel(cancel_check)
            if cls.document_type != document_type:
                continue
            if cls.can_import(path):
                return cls
            raise ValueError(f"Path cannot be imported as {document_type}")
        raise ValueError(f"Unknown document type: {document_type}")

    matches = []
    for cls in classes:
        bootstrap_ops.check_cancel(cancel_check)
        if cls.can_import(path):
            matches.append(cls)
    if len(matches) > 1:
        names = [cls.__name__.replace("Document", "").lower() for cls in matches]
        raise ValueError(f"Path can be imported as: {', '.join(names)}. Please specify document_type.")
    if len(matches) == 0:
        raise ValueError("Cannot import path: no supported document type matches.")
    return matches[0]


def import_with_class(
    workflow: WorkflowContext,
    document_class: type[Document],
    path: Path,
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, int | None]:
    """Import a path with a resolved document class and return standardized result."""
    existing_document_ids = {int(doc["document_id"]) for doc in workflow.document_repo.list_documents()}
    bootstrap_ops.check_cancel(cancel_check)
    result = document_class.do_import(workflow.document_repo, path, cancel_check=cancel_check)
    document_id = resolve_imported_document_id(workflow, existing_document_ids, int(result["imported"]))
    return {
        "imported": int(result["imported"]),
        "skipped": int(result["skipped"]),
        "document_id": document_id,
    }


def import_path(
    workflow: WorkflowContext,
    *,
    path: Path,
    document_type: str | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, int | None]:
    """Import a file/folder path into the current book."""
    bootstrap_ops.check_cancel(cancel_check)
    if not path.exists():
        raise ValueError(f"Path does not exist: {path}")

    bootstrap_ops.check_cancel(cancel_check)
    if path.is_dir() and not any(path.iterdir()):
        raise ValueError(f"Cannot import empty folder: {path}")

    classes = document_base.get_document_classes()
    target_class = resolve_import_class(
        workflow,
        classes,
        path,
        document_type=document_type,
        cancel_check=cancel_check,
    )
    return import_with_class(workflow, target_class, path, cancel_check=cancel_check)
