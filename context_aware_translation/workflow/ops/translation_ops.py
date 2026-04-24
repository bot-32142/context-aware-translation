from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from context_aware_translation.core.progress import ProgressCallback, ProgressUpdate, WorkflowStep
from context_aware_translation.workflow.ops import bootstrap_ops

if TYPE_CHECKING:
    from context_aware_translation.workflow.runtime import WorkflowContext


def update_chunk_records(workflow: WorkflowContext, chunk_records: list) -> None:
    """Persist translated chunk records via the context manager."""
    workflow.manager._state_update([], chunk_records)


def build_doc_type_by_id(workflow: WorkflowContext, document_ids: list[int] | None) -> dict[int, str]:
    """Build document_id -> document_type mapping for selected translation targets."""
    all_docs = workflow.document_repo.list_documents()
    if document_ids is None:
        return {int(doc["document_id"]): str(doc["document_type"]) for doc in all_docs}
    id_set = {int(doc_id) for doc_id in document_ids}
    return {int(doc["document_id"]): str(doc["document_type"]) for doc in all_docs if int(doc["document_id"]) in id_set}


async def translate(
    workflow: WorkflowContext,
    *,
    document_ids: list[int] | None = None,
    source_ids: list[int] | None = None,
    progress_callback: ProgressCallback | None = None,
    force: bool = False,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    """Translate documents using the glossary context."""
    translator_config = workflow.config.translator_config
    assert translator_config is not None

    preflight_document_ids = bootstrap_ops.resolve_preflight_document_ids(workflow, document_ids)
    await bootstrap_ops.prepare_llm_prerequisites(workflow, preflight_document_ids, cancel_check=cancel_check)

    bootstrap_ops.check_cancel(cancel_check)
    workflow.manager.build_context_tree(
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    )

    bootstrap_ops.check_cancel(cancel_check)
    doc_type_by_id = build_doc_type_by_id(workflow, document_ids)
    source_ids_by_document: dict[int, list[int]] | None = None
    if source_ids is not None:
        if len(doc_type_by_id) != 1:
            raise ValueError("source_ids filtering requires exactly one selected document.")
        only_doc_id, only_doc_type = next(iter(doc_type_by_id.items()))
        if only_doc_type != "manga":
            raise ValueError("source_ids filtering is only supported for manga translation.")
        source_ids_by_document = {int(only_doc_id): [int(source_id) for source_id in source_ids]}
    max_tokens_per_call = int(getattr(translator_config, "max_tokens_per_llm_call", 2000) or 2000)
    if max_tokens_per_call <= 0:
        max_tokens_per_call = 2000

    await workflow.manager.translate_chunks(
        doc_type_by_id=doc_type_by_id,
        source_ids_by_document=source_ids_by_document,
        concurrency=translator_config.concurrency,
        batch_size=0,
        max_tokens_per_batch=max_tokens_per_call,
        force=force,
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    )


async def retranslate_chunk(
    workflow: WorkflowContext,
    *,
    chunk_id: int,
    document_id: int,
    progress_callback: ProgressCallback | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> str:
    """Retranslate a single chunk by ID using the LLM."""
    translator_config = workflow.config.translator_config
    assert translator_config is not None

    preflight_document_ids = bootstrap_ops.resolve_preflight_document_ids(workflow, [document_id])
    await bootstrap_ops.prepare_llm_prerequisites(workflow, preflight_document_ids, cancel_check=cancel_check)

    bootstrap_ops.check_cancel(cancel_check)
    workflow.manager.build_context_tree(
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    )

    bootstrap_ops.check_cancel(cancel_check)

    chunk = workflow.db.get_chunk_by_id(chunk_id)
    if chunk is None:
        raise ValueError(f"Chunk {chunk_id} not found")

    source_language = workflow.db.get_source_language()
    if not source_language:
        raise ValueError("Source language not found in the database")

    all_terms = [term for term in workflow.manager.term_repo.list_keyed_context() if not term.ignored]
    await workflow.manager.build_local_chunk_summaries_for_batches(
        [[chunk]],
        source_language=source_language,
        concurrency=1,
        cancel_check=cancel_check,
    )

    request = workflow.manager.build_batch_request_payload(
        [chunk],
        all_terms,
        source_language=source_language,
    )
    batch_texts = request.texts
    batch_terms = request.terms
    local_context = request.local_context

    bootstrap_ops.check_cancel(cancel_check)
    if progress_callback is not None:
        progress_callback(
            ProgressUpdate(
                step=WorkflowStep.TRANSLATE_CHUNKS,
                current=0,
                total=1,
                message="Translating batch 0/1",
            )
        )

    translated_texts = await workflow.manager.chunk_translator.translate(
        batch_texts,
        batch_terms,
        source_language,
        cancel_check=cancel_check,
        local_context=local_context,
    )

    new_translation: str = translated_texts[0]
    chunk.translation = new_translation
    chunk.is_translated = True

    workflow.manager._state_update([], [chunk])
    if progress_callback is not None:
        progress_callback(
            ProgressUpdate(
                step=WorkflowStep.TRANSLATE_CHUNKS,
                current=1,
                total=1,
                message="Translating batch 1/1",
            )
        )
    return new_translation
