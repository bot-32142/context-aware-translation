from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from context_aware_translation.core.progress import ProgressCallback
from context_aware_translation.workflow.ops import bootstrap_ops

if TYPE_CHECKING:
    from context_aware_translation.workflow.runtime import WorkflowContext


async def build_glossary(
    workflow: WorkflowContext,
    *,
    document_ids: list[int] | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    """Build glossary: extract terms and build occurrence mapping."""
    extractor_config = workflow.config.extractor_config
    assert extractor_config is not None

    await bootstrap_ops.prepare_llm_prerequisites(workflow, document_ids, cancel_check=cancel_check)

    bootstrap_ops.check_cancel(cancel_check)
    await workflow.manager.extract_keyed_context(
        concurrency=extractor_config.concurrency,
        document_ids=document_ids,
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    )
    await workflow.manager.build_occurrence_mapping(cancel_check=cancel_check, document_ids=document_ids)


async def translate_glossary(
    workflow: WorkflowContext,
    *,
    document_ids: list[int] | None = None,
    term_keys: set[str] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> None:
    """Translate glossary terms using glossary-table-only prerequisites."""
    glossary_config = workflow.config.glossary_config
    assert glossary_config is not None
    scoped_term_keys = (
        set(term_keys)
        if term_keys is not None
        else workflow.manager.get_term_keys_for_documents(document_ids)
        if document_ids is not None
        else None
    )

    try:
        bootstrap_ops.check_cancel(cancel_check)
        await workflow.manager.translate_terms(
            translation_name_similarity_threshold=0.7,
            concurrency=glossary_config.concurrency or workflow.config.llm_concurrency,
            term_keys=scoped_term_keys,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )
    except ValueError as exc:
        if not bootstrap_ops.is_missing_source_language_error(exc):
            raise
        await bootstrap_ops.ensure_glossary_source_language(workflow, cancel_check=cancel_check)
        bootstrap_ops.check_cancel(cancel_check)
        await workflow.manager.translate_terms(
            translation_name_similarity_threshold=0.7,
            concurrency=glossary_config.concurrency or workflow.config.llm_concurrency,
            term_keys=scoped_term_keys,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )


async def review_terms(
    workflow: WorkflowContext,
    *,
    document_ids: list[int] | None = None,
    term_keys: set[str] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> None:
    """Review unreviewed terms using glossary-table-only prerequisites."""
    review_config = workflow.config.review_config
    if review_config is None:
        raise ValueError("Review config not set. Please configure review settings.")
    scoped_term_keys = (
        set(term_keys)
        if term_keys is not None
        else workflow.manager.get_term_keys_for_documents(document_ids)
        if document_ids is not None
        else None
    )

    try:
        bootstrap_ops.check_cancel(cancel_check)
        await workflow.manager.review_terms(
            concurrency=review_config.concurrency,
            term_keys=scoped_term_keys,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )
    except ValueError as exc:
        if not bootstrap_ops.is_missing_source_language_error(exc):
            raise
        await bootstrap_ops.ensure_glossary_source_language(workflow, cancel_check=cancel_check)
        bootstrap_ops.check_cancel(cancel_check)
        await workflow.manager.review_terms(
            concurrency=review_config.concurrency,
            term_keys=scoped_term_keys,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )
