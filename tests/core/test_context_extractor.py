from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from context_aware_translation.config import Config
from context_aware_translation.core.context_extractor import TermExtractor
from context_aware_translation.core.models import Term
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.storage.schema.book_db import ChunkRecord


@pytest.mark.asyncio
async def test_term_extractor_extract_keyed_context(temp_config: Config):
    """Test TermExtractor extracts terms from chunk."""
    llm_client = MagicMock(spec=LLMClient)

    # Mock the extract_terms function in the context_extractor module where it's imported
    from context_aware_translation.core import context_extractor

    original_extract = context_extractor.llm_extract_terms

    async def mock_extract_terms(_chunk_record, _client, _config, _source_language):
        return [
            Term(
                key="term1",
                descriptions={"chunk1": "description1"},
                occurrence={},
                votes=1,
                total_api_calls=1,
            ),
            Term(
                key="term2",
                descriptions={"chunk1": "description2"},
                occurrence={},
                votes=1,
                total_api_calls=1,
            ),
        ]

    context_extractor.llm_extract_terms = mock_extract_terms

    try:
        extractor_instance = TermExtractor(llm_client, temp_config.extractor_config)
        chunk_record = ChunkRecord(chunk_id=1, hash="hash1", text="test text")

        result = await extractor_instance.extract_keyed_context(chunk_record, source_language="英语")

        assert len(result) == 2
        assert all(isinstance(term, Term) for term in result)
        assert result[0].key == "term1"
        assert result[1].key == "term2"
    finally:
        context_extractor.llm_extract_terms = original_extract


@pytest.mark.asyncio
async def test_term_extractor_empty_result(temp_config: Config):
    """Test TermExtractor returns empty list when no terms found."""
    llm_client = MagicMock(spec=LLMClient)

    from context_aware_translation.core import context_extractor

    original_extract = context_extractor.llm_extract_terms

    async def mock_extract_terms(_chunk_record, _client, _config, _source_language):
        return []

    context_extractor.llm_extract_terms = mock_extract_terms

    try:
        extractor_instance = TermExtractor(llm_client, temp_config.extractor_config)
        chunk_record = ChunkRecord(chunk_id=1, hash="hash1", text="test text")

        result = await extractor_instance.extract_keyed_context(chunk_record, source_language="英语")

        assert result == []
    finally:
        context_extractor.llm_extract_terms = original_extract


@pytest.mark.asyncio
async def test_term_extractor_passes_parameters(temp_config: Config):
    """Test that TermExtractor passes correct parameters to extract_terms."""
    llm_client = MagicMock(spec=LLMClient)

    from context_aware_translation.core import context_extractor

    original_extract = context_extractor.llm_extract_terms

    call_args_list = []

    async def mock_extract_terms(chunk_record, client, config, source_language):
        call_args_list.append((chunk_record, client, config, source_language))
        return []

    context_extractor.llm_extract_terms = mock_extract_terms

    try:
        extractor_instance = TermExtractor(llm_client, temp_config.extractor_config)
        chunk_record = ChunkRecord(chunk_id=1, hash="hash1", text="test text")

        await extractor_instance.extract_keyed_context(chunk_record, source_language="英语")

        assert len(call_args_list) == 1
        assert call_args_list[0][0] == chunk_record
        assert call_args_list[0][1] == llm_client
        assert call_args_list[0][2] == temp_config.extractor_config
        assert call_args_list[0][3] == "英语"
    finally:
        context_extractor.llm_extract_terms = original_extract


@pytest.mark.asyncio
async def test_term_extractor_exception_propagation(temp_config: Config):
    """Test that exceptions from extract_terms are propagated."""
    llm_client = MagicMock(spec=LLMClient)

    from context_aware_translation.core import context_extractor

    original_extract = context_extractor.llm_extract_terms

    async def mock_extract_terms_raises(_chunk_record, _client, _config, _source_language):
        raise ValueError("Test error")

    context_extractor.llm_extract_terms = mock_extract_terms_raises

    try:
        extractor_instance = TermExtractor(llm_client, temp_config.extractor_config)
        chunk_record = ChunkRecord(chunk_id=1, hash="hash1", text="test text")

        # Exception should propagate
        with pytest.raises(ValueError, match="Test error"):
            await extractor_instance.extract_keyed_context(chunk_record, source_language="英语")
    finally:
        context_extractor.llm_extract_terms = original_extract


@pytest.mark.asyncio
async def test_term_extractor_none_result(temp_config: Config):
    """Test that TermExtractor handles None result from extract_terms."""
    # BUG: If extract_terms returns None instead of a list, this will fail
    llm_client = MagicMock(spec=LLMClient)

    from context_aware_translation.core import context_extractor

    original_extract = context_extractor.llm_extract_terms

    async def mock_extract_terms_none(_chunk_record, _client, _config, _source_language):
        return None  # BUG: Should return list, not None

    context_extractor.llm_extract_terms = mock_extract_terms_none

    try:
        extractor_instance = TermExtractor(llm_client, temp_config.extractor_config)
        chunk_record = ChunkRecord(chunk_id=1, hash="hash1", text="test text")

        # BUG: This will fail because None is not iterable
        with pytest.raises((TypeError, AttributeError)):
            result = await extractor_instance.extract_keyed_context(chunk_record, source_language="英语")
            # If it doesn't raise, iterating will fail
            list(result)
    finally:
        context_extractor.llm_extract_terms = original_extract
