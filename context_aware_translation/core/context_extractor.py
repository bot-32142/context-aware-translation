from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Protocol

from context_aware_translation.config import ExtractorConfig
from context_aware_translation.core.models import KeyedContext, Term
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.llm.extractor import extract_terms as llm_extract_terms
from context_aware_translation.storage.schema.book_db import ChunkRecord

logger = logging.getLogger(__name__)


class ContextExtractor(Protocol):
    """
    Protocol for extracting context from text chunks.
    """

    async def extract_keyed_context(
        self,
        chunk_record: ChunkRecord,
        source_language: str,
    ) -> Sequence[KeyedContext]:
        """
        Extract keyed context from a chunk record.

        Args:
            chunk_record: The chunk record to extract keyed context from
            source_language: The source language of the text

        Returns:
            Sequence of KeyedContext objects extracted from the chunk record
        """
        ...


class TermExtractor:
    """
    Implementation of ContextExtractor that extracts Term objects using LLM.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        extractor_config: ExtractorConfig,
    ):
        self.llm_client = llm_client
        self.extractor_config = extractor_config

    async def extract_keyed_context(
        self,
        chunk_record: ChunkRecord,
        source_language: str,
    ) -> Sequence[Term]:
        """
        Extract terms from a chunk record using LLM.

        Args:
            chunk_record: The chunk record to extract terms from
            source_language: The source language of the text

        Returns:
            List of Term objects extracted from the chunk
        """
        terms = await llm_extract_terms(chunk_record, self.llm_client, self.extractor_config, source_language)
        return terms
