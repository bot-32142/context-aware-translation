from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from context_aware_translation.core.progress import ProgressCallback

if TYPE_CHECKING:
    from context_aware_translation.workflow.service import WorkflowService


async def build_glossary(
    workflow: WorkflowService,
    *,
    document_ids: list[int] | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    """Build glossary: extract terms and build occurrence mapping."""
    extractor_config = workflow.config.extractor_config
    assert extractor_config is not None

    await workflow._prepare_llm_prerequisites(document_ids, cancel_check=cancel_check)

    workflow._check_cancel(cancel_check)
    await workflow.manager.extract_keyed_context(
        concurrency=extractor_config.concurrency,
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    )
    await workflow.manager.build_occurrence_mapping(cancel_check=cancel_check)


async def translate_glossary(
    workflow: WorkflowService,
    *,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> None:
    """Translate glossary terms using glossary-table-only prerequisites."""
    glossary_config = workflow.config.glossary_config
    assert glossary_config is not None

    try:
        workflow._check_cancel(cancel_check)
        await workflow.manager.translate_terms(
            translation_name_similarity_threshold=0.7,
            concurrency=glossary_config.concurrency or workflow.config.llm_concurrency,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )
    except ValueError as exc:
        if not workflow._is_missing_source_language_error(exc):
            raise
        await workflow._ensure_glossary_source_language(cancel_check=cancel_check)
        workflow._check_cancel(cancel_check)
        await workflow.manager.translate_terms(
            translation_name_similarity_threshold=0.7,
            concurrency=glossary_config.concurrency or workflow.config.llm_concurrency,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )


async def review_terms(
    workflow: WorkflowService,
    *,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> None:
    """Review unreviewed terms using glossary-table-only prerequisites."""
    review_config = workflow.config.review_config
    if review_config is None:
        raise ValueError("Review config not set. Please configure review settings.")

    try:
        workflow._check_cancel(cancel_check)
        await workflow.manager.review_terms(
            concurrency=review_config.concurrency,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )
    except ValueError as exc:
        if not workflow._is_missing_source_language_error(exc):
            raise
        await workflow._ensure_glossary_source_language(cancel_check=cancel_check)
        workflow._check_cancel(cancel_check)
        await workflow.manager.review_terms(
            concurrency=review_config.concurrency,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )
