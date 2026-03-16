from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, final

from context_aware_translation.config import (
    GlossaryTranslationConfig,
    LLMConfig,
    MangaTranslatorConfig,
    ReviewConfig,
    SummarizorConfig,
    TranslatorConfig,
)
from context_aware_translation.llm.client import LLMClient
from context_aware_translation.llm.glossary_translator import translate_glossary
from context_aware_translation.llm.language_detector import detect_source_language
from context_aware_translation.llm.manga_translator import translate_manga_pages
from context_aware_translation.llm.reviewer import review_batch
from context_aware_translation.llm.summarizor import summarize_descriptions
from context_aware_translation.llm.translator import translate_chunk

if TYPE_CHECKING:
    from context_aware_translation.storage.schema.book_db import TermRecord


@final
class LLMSourceLanguageDetector:
    """
    Source language detector backed by LLM language detection.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        extractor_config: LLMConfig,
        sample_size: int = 1000,
    ) -> None:
        self.llm_client: LLMClient = llm_client
        self.extractor_config: LLMConfig = extractor_config
        self.sample_size: int = sample_size

    async def detect(self, text: str, cancel_check: Callable[[], bool] | None = None) -> str:
        return await detect_source_language(
            text,
            self.llm_client,
            self.extractor_config,
            self.sample_size,
            cancel_check=cancel_check,
        )


@final
class LLMGlossaryTranslator:
    """
    Glossary translation strategy backed by LLM translation.
    """

    def __init__(
        self,
        glossary_config: GlossaryTranslationConfig,
        translation_target_language: str,
        llm_client: LLMClient,
    ) -> None:
        self.glossary_config: GlossaryTranslationConfig = glossary_config
        self.translation_target_language: str = translation_target_language
        self.llm_client: LLMClient = llm_client

    async def translate(
        self,
        to_translate: list[dict[str, str]],
        translated_names: dict[str, str],
        source_language: str,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, str]:
        return await translate_glossary(
            to_translate,
            translated_names,
            self.glossary_config,
            self.translation_target_language,
            source_language,
            self.llm_client,
            cancel_check=cancel_check,
        )


@final
class LLMChunkTranslator:
    """
    Chunk translation strategy backed by LLM translation.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        translator_config: TranslatorConfig,
        target_language: str,
    ) -> None:
        self.llm_client: LLMClient = llm_client
        self.translator_config: TranslatorConfig = translator_config
        self.target_language: str = target_language

    async def translate(
        self,
        chunks: list[str],
        terms: list[tuple[str, str, str]],
        source_language: str,
        cancel_check: Callable[[], bool] | None = None,
    ) -> list[str]:
        return await translate_chunk(
            chunks,
            terms,
            self.llm_client,
            self.translator_config,
            source_language,
            self.target_language,
            cancel_check=cancel_check,
        )


@final
class LLMDescriptionSummarizer:
    """
    Description summarizer backed by LLM summarization.
    """

    def __init__(
        self,
        summarizor_config: SummarizorConfig,
        llm_client: LLMClient,
    ) -> None:
        self.summarizor_config: SummarizorConfig = summarizor_config
        self.llm_client: LLMClient = llm_client

    async def summarize(self, descriptions: list[str], cancel_check: Callable[[], bool] | None = None) -> str:
        return await summarize_descriptions(
            descriptions,
            self.summarizor_config,
            self.llm_client,
            cancel_check=cancel_check,
        )


@final
class LLMTermReviewer:
    """
    Term reviewer backed by LLM review.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        review_config: ReviewConfig,
    ) -> None:
        self.llm_client: LLMClient = llm_client
        self.review_config: ReviewConfig = review_config

    async def review_batch(
        self,
        terms: list[TermRecord],
        source_language: str,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, list[str]]:
        return await review_batch(
            terms,
            self.llm_client,
            self.review_config,
            source_language,
            cancel_check=cancel_check,
        )


@final
class LLMMangaPageTranslator:
    """Manga page translation strategy backed by vision LLM."""

    def __init__(
        self,
        llm_client: LLMClient,
        manga_config: MangaTranslatorConfig,
        target_language: str,
    ) -> None:
        self.llm_client = llm_client
        self.manga_config = manga_config
        self.target_language = target_language

    async def translate(
        self,
        page_images: list[tuple[bytes, str]],
        terms: list[tuple[str, str, str]],
        source_language: str,
        extracted_texts: list[str] | None = None,
    ) -> list[str]:
        return await translate_manga_pages(
            page_images,
            terms,
            self.llm_client,
            self.manga_config,
            source_language,
            self.target_language,
            extracted_texts=extracted_texts,
        )
