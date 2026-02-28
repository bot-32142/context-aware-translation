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
            sources = workflow.document_repo.get_document_sources_needing_ocr(doc.document_id)
            if source_ids is not None:
                sources = [s for s in sources if s["source_id"] in source_ids]
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
    for document in documents:
        bootstrap_ops.check_cancel(cancel_check)
        if workflow.config.ocr_config is not None:
            if cancel_check is None:
                processed = await document.process_ocr(workflow.llm_client, source_ids)
            else:
                processed = await document.process_ocr(workflow.llm_client, source_ids, cancel_check=cancel_check)
            if processed > 0:
                current += processed
                total_processed += processed

                if progress_callback:
                    progress_callback(
                        ProgressUpdate(
                            step=WorkflowStep.OCR,
                            current=current,
                            total=total_sources,
                            message=f"OCR page {current}/{total_sources}",
                        )
                    )

    return total_processed
