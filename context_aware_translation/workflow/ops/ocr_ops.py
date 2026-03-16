from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from context_aware_translation.core.progress import ProgressCallback, ProgressUpdate, WorkflowStep
from context_aware_translation.workflow.ops import bootstrap_ops

if TYPE_CHECKING:
    from context_aware_translation.documents.base import Document
    from context_aware_translation.workflow.runtime import WorkflowContext


async def run_ocr(
    workflow: WorkflowContext,
    *,
    document_loader: Callable[..., list[Document]],
    progress_callback: ProgressCallback | None = None,
    source_ids: list[int] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> int:
    """Run OCR on documents that need it and return processed source count."""
    total_processed = 0
    bootstrap_ops.check_cancel(cancel_check)
    documents = document_loader(workflow.document_repo, workflow.config.ocr_config)

    if not documents:
        return 0

    # Count total sources needing OCR (filtered if source_ids provided)
    all_sources = []
    for doc in documents:
        if workflow.config.ocr_config is not None:
            if source_ids is not None:
                sources = [
                    source
                    for source in workflow.document_repo.get_document_sources_metadata(doc.document_id)
                    if source.get("source_type") == "image" and source["source_id"] in source_ids
                ]
            else:
                sources = workflow.document_repo.get_document_sources_needing_ocr(doc.document_id)
            all_sources.extend(sources)

    total_sources = len(all_sources)

    bootstrap_ops.check_cancel(cancel_check)
    if progress_callback and total_sources > 0:
        progress_callback(
            ProgressUpdate(
                step=WorkflowStep.OCR,
                current=0,
                total=total_sources,
                message="Starting OCR...",
            )
        )

    current = 0

    def emit_progress() -> None:
        if progress_callback:
            progress_callback(
                ProgressUpdate(
                    step=WorkflowStep.OCR,
                    current=current,
                    total=total_sources,
                    message=f"OCR page {current}/{total_sources}",
                )
            )

    def on_item_processed() -> None:
        nonlocal current
        current += 1
        if total_sources > 0:
            current = min(current, total_sources)
            emit_progress()

    for document in documents:
        bootstrap_ops.check_cancel(cancel_check)
        if workflow.config.ocr_config is not None:
            before = current
            try:
                if cancel_check is None:
                    processed = await document.process_ocr(
                        workflow.llm_client,
                        source_ids,
                        on_item_processed=on_item_processed,
                    )
                else:
                    processed = await document.process_ocr(
                        workflow.llm_client,
                        source_ids,
                        cancel_check=cancel_check,
                        on_item_processed=on_item_processed,
                    )
            except TypeError as exc:
                # Backward-compat for test doubles / legacy document classes that do not
                # yet accept on_item_processed.
                if "on_item_processed" not in str(exc):
                    raise
                if cancel_check is None:
                    processed = await document.process_ocr(workflow.llm_client, source_ids)
                else:
                    processed = await document.process_ocr(
                        workflow.llm_client,
                        source_ids,
                        cancel_check=cancel_check,
                    )
            if processed > 0:
                total_processed += processed
                accounted = current - before
                # Fallback for document types that do not emit item-level callbacks.
                if accounted < processed:
                    current += processed - accounted
                    if total_sources > 0:
                        current = min(current, total_sources)
                        emit_progress()

    return total_processed
