from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_aware_translation.config import GlossaryTranslationConfig, ReviewConfig
from context_aware_translation.workflow.ops import glossary_ops


def _make_workflow() -> SimpleNamespace:
    manager = SimpleNamespace(
        extract_keyed_context=AsyncMock(),
        build_occurrence_mapping=AsyncMock(),
        get_term_keys_for_documents=MagicMock(return_value={"doc-term"}),
        review_terms=AsyncMock(),
        translate_terms=AsyncMock(),
    )
    config = SimpleNamespace(
        extractor_config=SimpleNamespace(concurrency=3),
        glossary_config=GlossaryTranslationConfig(model="glossary-model", api_key="key", base_url="https://example"),
        review_config=ReviewConfig(model="review-model", api_key="key", base_url="https://example"),
        llm_concurrency=4,
    )
    return SimpleNamespace(config=config, manager=manager)


@pytest.mark.asyncio
async def test_build_glossary_scopes_extraction_and_occurrence_to_selected_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = _make_workflow()
    monkeypatch.setattr(
        "context_aware_translation.workflow.ops.glossary_ops.bootstrap_ops.prepare_llm_prerequisites",
        AsyncMock(),
    )

    await glossary_ops.build_glossary(workflow, document_ids=[7])

    workflow.manager.extract_keyed_context.assert_awaited_once_with(
        concurrency=3,
        document_ids=[7],
        cancel_check=None,
        progress_callback=None,
    )
    workflow.manager.build_occurrence_mapping.assert_awaited_once_with(cancel_check=None, document_ids=[7])


@pytest.mark.asyncio
async def test_review_terms_scopes_pending_terms_to_selected_documents() -> None:
    workflow = _make_workflow()

    await glossary_ops.review_terms(workflow, document_ids=[7])

    workflow.manager.get_term_keys_for_documents.assert_called_once_with([7])
    workflow.manager.review_terms.assert_awaited_once_with(
        concurrency=workflow.config.review_config.concurrency,
        term_keys={"doc-term"},
        cancel_check=None,
        progress_callback=None,
    )


@pytest.mark.asyncio
async def test_translate_glossary_scopes_terms_to_selected_documents() -> None:
    workflow = _make_workflow()

    await glossary_ops.translate_glossary(workflow, document_ids=[7])

    workflow.manager.get_term_keys_for_documents.assert_called_once_with([7])
    workflow.manager.translate_terms.assert_awaited_once_with(
        translation_name_similarity_threshold=0.7,
        concurrency=workflow.config.glossary_config.concurrency or workflow.config.llm_concurrency,
        term_keys={"doc-term"},
        cancel_check=None,
        progress_callback=None,
    )
