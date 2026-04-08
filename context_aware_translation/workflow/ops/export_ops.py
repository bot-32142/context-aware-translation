from __future__ import annotations

import shutil
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from context_aware_translation.core.progress import ProgressCallback, ProgressUpdate, WorkflowStep
from context_aware_translation.documents.base import Document, supports_original_image_export_for_type
from context_aware_translation.documents.epub import EPUBDocument
from context_aware_translation.workflow.ops import bootstrap_ops

if TYPE_CHECKING:
    from context_aware_translation.workflow.runtime import WorkflowContext


def get_lines_with_original_fallback(workflow: WorkflowContext, document: Document) -> list[str]:
    """Return export lines with per-chunk fallback for untranslated chunks."""
    chunks = sorted(workflow.db.list_chunks(document_id=document.document_id), key=lambda chunk: chunk.chunk_id)
    if not chunks:
        if document.document_type == "manga":
            return []
        return document.get_text().split("\n")

    if document.document_type == "manga":
        return [chunk.translation if chunk.is_translated and chunk.translation is not None else "" for chunk in chunks]

    merged_chunks = [
        chunk.translation if chunk.is_translated and chunk.translation is not None else chunk.text for chunk in chunks
    ]
    return "".join(merged_chunks).split("\n")


def resolve_export_lines(
    workflow: WorkflowContext,
    document: Document,
    *,
    allow_original_fallback: bool,
) -> list[str]:
    """Resolve text lines to apply to a document during export."""
    try:
        return workflow.manager.get_translated_lines(document.document_id, document.document_type)
    except ValueError:
        if not allow_original_fallback:
            raise
        return get_lines_with_original_fallback(workflow, document)


async def materialize_document_translation_state(
    workflow: WorkflowContext,
    document: Document,
    *,
    allow_original_fallback: bool = False,
    epub_force_horizontal_ltr: bool = False,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> None:
    """Apply translated lines to a document so it is ready for export or reembedding."""
    all_lines = resolve_export_lines(
        workflow,
        document,
        allow_original_fallback=allow_original_fallback,
    )
    if document.document_type == "epub" and isinstance(document, EPUBDocument):
        document.set_translation_target_language(workflow.config.translation_target_language)
        document.set_export_layout_preferences(force_horizontal_ltr=epub_force_horizontal_ltr)

    await document.set_text(
        all_lines,
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    )
    bootstrap_ops.check_cancel(cancel_check)


async def apply_export_text(
    workflow: WorkflowContext,
    document: Document,
    *,
    allow_original_fallback: bool,
    epub_force_horizontal_ltr: bool,
    cancel_check: Callable[[], bool] | None,
    progress_callback: ProgressCallback | None,
) -> None:
    """Apply export text lines to a document, with fallback semantics."""
    await materialize_document_translation_state(
        workflow,
        document,
        allow_original_fallback=allow_original_fallback,
        epub_force_horizontal_ltr=epub_force_horizontal_ltr,
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    )


async def export(
    workflow: WorkflowContext,
    *,
    file_path: Path,
    export_format: str | None = None,
    document_ids: list[int] | None = None,
    allow_original_fallback: bool = False,
    use_original_images: bool = False,
    epub_force_horizontal_ltr: bool = False,
    progress_callback: ProgressCallback | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    """Export translated content to file."""
    bootstrap_ops.check_cancel(cancel_check)
    documents = bootstrap_ops.load_documents(workflow, document_ids)
    if not documents:
        raise ValueError("No documents to export")

    doc_types = {d.document_type for d in documents}
    if len(doc_types) > 1:
        raise ValueError(f"Cannot export mixed document types: {doc_types}. All documents must be the same type.")

    if export_format is None:
        ext = file_path.suffix.lower()
        export_format = ext[1:] if ext else "txt"

    if not documents[0].can_export(export_format):
        supported = ", ".join(documents[0].supported_export_formats)
        raise ValueError(f"Format '{export_format}' not supported. Supported: {supported}")
    if use_original_images and not supports_original_image_export_for_type(documents[0].document_type):
        raise ValueError("Original-image export is not supported for this document type.")

    total_docs = len(documents)
    for idx, doc in enumerate(documents):
        bootstrap_ops.check_cancel(cancel_check)
        if progress_callback:
            progress_callback(
                ProgressUpdate(
                    step=WorkflowStep.EXPORT,
                    current=idx + 1,
                    total=total_docs,
                    message=f"Exporting document {idx + 1}/{total_docs}",
                )
            )
        await apply_export_text(
            workflow,
            doc,
            allow_original_fallback=allow_original_fallback,
            epub_force_horizontal_ltr=epub_force_horizontal_ltr,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )

    bootstrap_ops.check_cancel(cancel_check)
    doc_class = type(documents[0])
    staged_root, staged_file = _prepare_staged_file(file_path)
    try:
        doc_class.export_merged(documents, export_format, staged_file, use_original_images=use_original_images)
        bootstrap_ops.check_cancel(cancel_check)
        _promote_staged_path(staged_file, file_path)
    finally:
        _cleanup_staged_path(staged_root)


async def export_preserve_structure(
    workflow: WorkflowContext,
    *,
    output_folder: Path,
    document_ids: list[int] | None = None,
    allow_original_fallback: bool = False,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> None:
    """Export while preserving original document structure."""
    bootstrap_ops.check_cancel(cancel_check)
    documents = bootstrap_ops.load_documents(workflow, document_ids)
    if not documents:
        raise ValueError("No documents to export")

    for document in documents:
        if not document.supports_preserve_structure:
            raise NotImplementedError(f"{type(document).__name__} documents do not support structure-preserving export")

    staged_output = _prepare_staged_directory(output_folder)
    try:
        for document in documents:
            bootstrap_ops.check_cancel(cancel_check)
            await apply_export_text(
                workflow,
                document,
                allow_original_fallback=allow_original_fallback,
                epub_force_horizontal_ltr=False,
                cancel_check=cancel_check,
                progress_callback=progress_callback,
            )
            document.export_preserve_structure(staged_output / str(document.document_id))
        bootstrap_ops.check_cancel(cancel_check)
        _promote_staged_path(staged_output, output_folder)
    finally:
        _cleanup_staged_path(staged_output)


def _prepare_staged_file(final_path: Path) -> tuple[Path, Path]:
    final_parent = final_path.parent
    final_parent.mkdir(parents=True, exist_ok=True)
    staged_root = Path(tempfile.mkdtemp(prefix=f".{final_path.stem or 'export'}-", dir=final_parent))
    return staged_root, staged_root / final_path.name


def _prepare_staged_directory(final_path: Path) -> Path:
    final_parent = final_path.parent
    final_parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f".{final_path.name or 'export'}-", dir=final_parent))


def _promote_staged_path(staged_path: Path, final_path: Path) -> None:
    backup_path: Path | None = None
    if final_path.exists():
        backup_path = final_path.with_name(f"{final_path.name}.bak-{uuid.uuid4().hex}")
        final_path.replace(backup_path)
    try:
        staged_path.replace(final_path)
    except Exception:
        if backup_path is not None and backup_path.exists() and not final_path.exists():
            backup_path.replace(final_path)
        raise
    if backup_path is not None:
        _cleanup_staged_path(backup_path)


def _cleanup_staged_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        return
    path.unlink(missing_ok=True)
