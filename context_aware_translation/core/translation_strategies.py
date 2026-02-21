from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from context_aware_translation.core.context_manager import TranslationContextManager
    from context_aware_translation.core.progress import ProgressCallback
    from context_aware_translation.storage.book_db import TermRecord


class SourceLanguageDetector(Protocol):
    """
    Protocol for detecting source language from text.
    """

    async def detect(self, text: str, cancel_check: Callable[[], bool] | None = None) -> str:
        """
        Detect the source language for the provided text.
        """
        ...


class GlossaryTranslationStrategy(Protocol):
    """
    Protocol for translating glossary terms with context.
    """

    async def translate(
        self,
        to_translate: list[dict[str, str]],
        translated_names: dict[str, str],
        source_language: str,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, str]:
        """
        Translate glossary terms with already translated names as context.
        """
        ...


class ChunkTranslationStrategy(Protocol):
    """
    Protocol for translating text chunks with term context.
    """

    async def translate(
        self,
        chunks: list[str],
        terms: list[tuple[str, str, str]],
        source_language: str,
        cancel_check: Callable[[], bool] | None = None,
    ) -> list[str]:
        """
        Translate chunks into target language with glossary terms.
        """
        ...


class DescriptionSummarizer(Protocol):
    """
    Protocol for summarizing term descriptions.
    """

    async def summarize(self, descriptions: list[str], cancel_check: Callable[[], bool] | None = None) -> str:
        """
        Summarize a batch of descriptions.
        """
        ...


class MangaPageTranslationStrategy(Protocol):
    """Protocol for translating manga pages using vision LLM with glossary terms."""

    async def translate(
        self,
        page_images: list[tuple[bytes, str]],
        terms: list[tuple[str, str, str]],
        source_language: str,
    ) -> list[str]: ...


class ImageFetcher(Protocol):
    """Protocol for fetching source images by source_id.

    Keeps the core layer decoupled from DocumentRepository.
    """

    def fetch_source_image(self, source_id: int) -> tuple[bytes, str]:
        """Return (image_bytes, mime_type) for a source.

        Raises ValueError if source not found or has no image.
        """
        ...

    def list_page_source_ids(self, document_id: int) -> list[int]:
        """Return source_ids with non-empty OCR text, ordered by sequence_number.

        Must match the filtering in MangaDocument.get_text() + add_text()
        skipping so that positional zip with chunks is correct.
        """
        ...


class DocumentTypeHandler(Protocol):
    """Protocol for document-type-specific dispatch points.

    Handlers implement the three methods that vary by document type:
    add_text, translate_chunks, and get_translated_lines.
    """

    def add_text(
        self,
        text: str,
        max_token_size_per_chunk: int,
        document_id: int,
        manager: TranslationContextManager,
    ) -> int:
        """Add text for this document type, returning the last chunk_id."""
        ...

    async def translate_chunks(
        self,
        document_ids: list[int],
        manager: TranslationContextManager,
        force: bool = False,
        skip_context: bool = False,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        """Translate chunks belonging to the given document IDs."""
        ...

    def get_translated_lines(
        self,
        document_id: int,
        manager: TranslationContextManager,
    ) -> list[str]:
        """Return translated text as a list of lines for a document."""
        ...


class TermReviewer(Protocol):
    """
    Protocol for reviewing term batches.
    """

    async def review_batch(
        self,
        terms: list[TermRecord],
        source_language: str,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, list[str]]:
        """
        Review terms and classify them into keep/ignore.
        """
        ...
