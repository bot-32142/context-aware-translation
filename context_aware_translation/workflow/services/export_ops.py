from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from context_aware_translation.core.progress import ProgressCallback, ProgressUpdate, WorkflowStep
from context_aware_translation.documents.base import Document

if TYPE_CHECKING:
    from context_aware_translation.workflow.service import WorkflowService


def get_lines_with_original_fallback(workflow: WorkflowService, document: Document) -> list[str]:
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
    workflow: WorkflowService,
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
        return workflow._get_lines_with_original_fallback(document)


async def materialize_document_translation_state(
    workflow: WorkflowService,
    document: Document,
    *,
    allow_original_fallback: bool = False,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> None:
    """Apply translated lines to a document so it is ready for export or reembedding."""
    all_lines = workflow._resolve_export_lines(
        document,
        allow_original_fallback=allow_original_fallback,
    )
    if document.document_type == "epub":
        from context_aware_translation.documents.epub import EPUBDocument

        if isinstance(document, EPUBDocument):
            document.set_translation_target_language(workflow.config.translation_target_language)

    await document.set_text(
        all_lines,
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    )
    workflow._check_cancel(cancel_check)


async def apply_export_text(
    workflow: WorkflowService,
    document: Document,
    *,
    allow_original_fallback: bool,
    cancel_check: Callable[[], bool] | None,
    progress_callback: ProgressCallback | None,
) -> None:
    """Apply export text lines to a document, with fallback semantics."""
    await workflow.materialize_document_translation_state(
        document,
        allow_original_fallback=allow_original_fallback,
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    )


async def export(
    workflow: WorkflowService,
    *,
    file_path: Path,
    export_format: str | None = None,
    document_ids: list[int] | None = None,
    allow_original_fallback: bool = False,
    progress_callback: ProgressCallback | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    """Export translated content to file."""
    workflow._check_cancel(cancel_check)
    documents = workflow._load_documents(document_ids)
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

    total_docs = len(documents)
    for idx, doc in enumerate(documents):
        workflow._check_cancel(cancel_check)
        if progress_callback:
            progress_callback(
                ProgressUpdate(
                    step=WorkflowStep.EXPORT,
                    current=idx + 1,
                    total=total_docs,
                    message=f"Exporting document {idx + 1}/{total_docs}",
                )
            )
        await workflow._apply_export_text(
            doc,
            allow_original_fallback=allow_original_fallback,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )

    workflow._check_cancel(cancel_check)
    doc_class = type(documents[0])
    doc_class.export_merged(documents, export_format, file_path)


async def export_preserve_structure(
    workflow: WorkflowService,
    *,
    output_folder: Path,
    document_ids: list[int] | None = None,
    allow_original_fallback: bool = False,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> None:
    """Export while preserving original document structure."""
    workflow._check_cancel(cancel_check)
    documents = workflow._load_documents(document_ids)
    if not documents:
        raise ValueError("No documents to export")

    for document in documents:
        if not document.supports_preserve_structure:
            raise NotImplementedError(f"{type(document).__name__} documents do not support structure-preserving export")

    for document in documents:
        workflow._check_cancel(cancel_check)
        await workflow._apply_export_text(
            document,
            allow_original_fallback=allow_original_fallback,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )
        document.export_preserve_structure(output_folder / str(document.document_id))
