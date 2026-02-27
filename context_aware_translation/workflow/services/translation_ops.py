from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from context_aware_translation.core.progress import ProgressCallback

if TYPE_CHECKING:
    from context_aware_translation.workflow.service import WorkflowService


def update_chunk_records(workflow: WorkflowService, chunk_records: list) -> None:
    """Persist translated chunk records via the context manager."""
    workflow.manager._state_update([], chunk_records)


def build_doc_type_by_id(workflow: WorkflowService, document_ids: list[int] | None) -> dict[int, str]:
    """Build document_id -> document_type mapping for selected translation targets."""
    all_docs = workflow.document_repo.list_documents()
    if document_ids is None:
        return {int(doc["document_id"]): str(doc["document_type"]) for doc in all_docs}
    id_set = {int(doc_id) for doc_id in document_ids}
    return {int(doc["document_id"]): str(doc["document_type"]) for doc in all_docs if int(doc["document_id"]) in id_set}


async def translate(
    workflow: WorkflowService,
    *,
    document_ids: list[int] | None = None,
    progress_callback: ProgressCallback | None = None,
    force: bool = False,
    skip_context: bool = False,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    """Translate documents using the glossary context."""
    translator_config = workflow.config.translator_config
    assert translator_config is not None

    preflight_document_ids = workflow._resolve_preflight_document_ids(document_ids)
    await workflow._prepare_llm_prerequisites(preflight_document_ids, cancel_check=cancel_check)

    if not skip_context:
        workflow._check_cancel(cancel_check)
        workflow.manager.build_context_tree(cancel_check=cancel_check)

    workflow._check_cancel(cancel_check)
    doc_type_by_id = workflow._build_doc_type_by_id(document_ids)

    await workflow.manager.translate_chunks(
        doc_type_by_id=doc_type_by_id,
        concurrency=translator_config.concurrency,
        batch_size=translator_config.num_of_chunks_per_llm_call,
        force=force,
        skip_context=skip_context,
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    )


async def retranslate_chunk(
    workflow: WorkflowService,
    *,
    chunk_id: int,
    document_id: int,
    skip_context: bool = False,
    cancel_check: Callable[[], bool] | None = None,
) -> str:
    """Retranslate a single chunk by ID using the LLM."""
    translator_config = workflow.config.translator_config
    assert translator_config is not None

    preflight_document_ids = workflow._resolve_preflight_document_ids([document_id])
    await workflow._prepare_llm_prerequisites(preflight_document_ids, cancel_check=cancel_check)

    if not skip_context:
        workflow._check_cancel(cancel_check)
        workflow.manager.build_context_tree(cancel_check=cancel_check)

    workflow._check_cancel(cancel_check)

    chunk = workflow.db.get_chunk_by_id(chunk_id)
    if chunk is None:
        raise ValueError(f"Chunk {chunk_id} not found")

    source_language = workflow.db.get_source_language()
    if not source_language:
        raise ValueError("Source language not found in the database")

    all_terms = [term for term in workflow.manager.term_repo.list_keyed_context() if not term.ignored]
    _, batch_terms = workflow.manager.build_batch_request_payload(
        [chunk],
        all_terms,
        skip_context=skip_context,
    )

    workflow._check_cancel(cancel_check)

    translated_texts = await workflow.manager.chunk_translator.translate(
        [chunk.text], batch_terms, source_language, cancel_check=cancel_check
    )

    new_translation: str = translated_texts[0]
    chunk.translation = new_translation
    chunk.is_translated = True

    workflow.manager._state_update([], [chunk])
    return new_translation
