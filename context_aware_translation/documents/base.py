from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context_aware_translation.config import ImageReembeddingConfig, OCRConfig
    from context_aware_translation.core.progress import ProgressCallback
    from context_aware_translation.llm.client import LLMClient
    from context_aware_translation.storage.document_repository import DocumentRepository


class Document(ABC):
    """Base class for all document types. Operates on sources."""

    document_type: str  # Must be defined by subclasses
    supported_export_formats: tuple[str, ...]  # Must be defined by subclasses
    requires_ocr_config: bool = False  # Override in subclasses that need OCR config
    ocr_required_for_translation: bool = True  # If False, translation proceeds without OCR
    supports_preserve_structure: bool = False  # Override in subclasses that support it
    supports_multi_export: bool = True  # Override to False for types that cannot merge

    def __init__(self, repo: DocumentRepository, document_id: int):
        self.repo = repo
        self.document_id = document_id

    @classmethod
    @abstractmethod
    def can_import(cls, path: Path) -> bool:
        """Check if this document class can import the given path."""
        ...

    @classmethod
    @abstractmethod
    def do_import(
        cls,
        repo: DocumentRepository,
        path: Path,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, int]:
        """Import the path into the repository. Returns dict with 'imported' and 'skipped' counts."""
        ...

    @classmethod
    def _create_document_from_row(
        cls,
        row: dict,
        repo: DocumentRepository,
        ocr_config: OCRConfig | None = None,
    ) -> Document:
        """Create appropriate Document subclass from database row."""
        document_type = row["document_type"]
        document_id = row["document_id"]

        # Find matching document class from registry
        for doc_cls in get_document_classes():
            if doc_cls.document_type == document_type:
                # Check if class accepts ocr_config parameter
                # Type ignore needed because subclass constructors have different signatures
                if doc_cls.requires_ocr_config:
                    return doc_cls(repo, document_id, ocr_config)  # type: ignore[call-arg]
                else:
                    return doc_cls(repo, document_id)

        raise ValueError(f"Unknown document type: {document_type}")

    @classmethod
    def load(cls, repo: DocumentRepository, ocr_config: OCRConfig | None = None) -> Document | None:
        """Factory: Load THE document from DB. Returns None if no document exists.
        Dispatches to correct subclass based on document_type."""
        row = repo.get_document_row()
        if row is None:
            return None

        return cls._create_document_from_row(row, repo, ocr_config)

    @classmethod
    def load_by_id(
        cls,
        repo: DocumentRepository,
        document_id: int,
        ocr_config: OCRConfig | None = None,
    ) -> Document | None:
        """Load a specific document by ID."""
        row = repo.get_document_by_id(document_id)
        if not row:
            return None
        return cls._create_document_from_row(row, repo, ocr_config)

    @classmethod
    def load_all(
        cls,
        repo: DocumentRepository,
        ocr_config: OCRConfig | None = None,
    ) -> list[Document]:
        """Load all documents from database."""
        rows = repo.list_documents()
        return [cls._create_document_from_row(row, repo, ocr_config) for row in rows]

    @classmethod
    def load_by_ids(
        cls,
        repo: DocumentRepository,
        document_ids: list[int],
        ocr_config: OCRConfig | None = None,
    ) -> list[Document]:
        """Load specific documents by their IDs."""
        documents = []
        for doc_id in document_ids:
            doc = cls.load_by_id(repo, doc_id, ocr_config)
            if doc:
                documents.append(doc)
        return documents

    @abstractmethod
    def is_ocr_completed(self) -> bool:
        """Check if OCR is complete for this document.

        Returns True if:
        - Document doesn't need OCR (e.g., text documents)
        - All image sources have been OCR'd (is_ocr_completed=1)
        """
        ...

    @abstractmethod
    async def process_ocr(
        self,
        llm_client: LLMClient,
        source_ids: list[int] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> int:
        """OCR sources where is_ocr_completed=0 and source_type='image'. No-op for text.

        Args:
            llm_client: LLM client for OCR
            source_ids: Optional list of source IDs to process. If None, process all.
            cancel_check: Optional cooperative cancellation callback.

        Returns:
            Number of sources processed.
        """
        ...

    @abstractmethod
    def get_text(self) -> str:
        """Merge all sources' text (text_content for text, ocr_json for images)."""
        ...

    @abstractmethod
    def is_text_added(self) -> bool:
        """True if ALL sources have is_text_added=1."""
        ...

    @abstractmethod
    def mark_text_added(self) -> None:
        """Mark ALL sources as text added."""
        ...

    @abstractmethod
    async def set_text(
        self,
        lines: list[str],
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> int:
        """Distribute translated lines to sources. Returns lines consumed."""
        ...

    @abstractmethod
    async def reembed(
        self,
        image_reembedding_config: ImageReembeddingConfig,
        *,
        force: bool = False,
        source_ids: list[int] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> int:
        """Generate reembedded images for this document using the image generator backend.

        This is the new generation path — it creates reembedded images and persists them
        to the DB. It uses already-persisted images as a skip-already-done optimization
        unless force=True.

        Args:
            image_reembedding_config: Config for the image generator backend.
            force: If True, regenerate all items even if already cached in DB.
            source_ids: If provided, only process sources with these IDs. If None, process all sources.
            cancel_check: Optional cooperative cancellation callback.
            progress_callback: Optional callback for progress updates.

        Returns:
            Count of items newly generated (not counting cached hits).
        """
        ...

    @abstractmethod
    def can_export(self, export_format: str) -> bool:
        """Check if this document can be exported to the given format.

        Args:
            export_format: Export format (e.g., 'txt', 'epub', 'md')

        Returns:
            True if format is supported, False otherwise.
        """
        ...

    @classmethod
    @abstractmethod
    def export_merged(cls, documents: list[Document], export_format: str, output_path: Path) -> None:
        """Export multiple documents merged into a single file.

        Each document should have had set_text() called before this method.
        This method accesses each document's internal translated content.

        Args:
            documents: List of documents to merge
            export_format: Export format (e.g., 'txt', 'epub', 'md')
            output_path: Path to write the merged file

        Raises:
            ValueError: If format is not supported or no content to export
        """
        ...

    @abstractmethod
    def export_preserve_structure(self, output_folder: Path) -> None:
        """Export preserving original file structure.
        Raises NotImplementedError for PDF/ScannedBook."""
        ...


def get_document_classes() -> list[type[Document]]:
    """Return list of all document classes that can be imported.

    Returns classes that implement can_import() and do_import() methods.
    Uses late imports to avoid circular dependencies.
    """
    from context_aware_translation.documents.epub import EPUBDocument
    from context_aware_translation.documents.manga import MangaDocument
    from context_aware_translation.documents.pdf import PDFDocument
    from context_aware_translation.documents.scanned_book import ScannedBookDocument
    from context_aware_translation.documents.text import TextDocument

    return [TextDocument, PDFDocument, ScannedBookDocument, MangaDocument, EPUBDocument]


def is_ocr_required_for_type(document_type: str) -> bool:
    """Check if a document type requires OCR completion before translation.

    Args:
        document_type: The document type string (e.g., 'text', 'pdf', 'epub')

    Returns:
        True if OCR must complete before translation, False if translation
        can proceed without OCR (e.g. EPUB where text content is available).

    Raises:
        ValueError: If document type is unknown.
    """
    for cls in get_document_classes():
        if cls.document_type == document_type:
            return cls.ocr_required_for_translation
    raise ValueError(f"Unknown document type: {document_type}")


def can_build_glossary_without_prior_ocr_for_type(document_type: str) -> bool:
    """Check if glossary build for this document type can skip earlier OCR blockers.

    Args:
        document_type: The document type string (e.g., 'epub', 'text', 'pdf')

    Returns:
        True if glossary can be built without enforcing prior OCR stack ordering.

    Raises:
        ValueError: If document type is unknown.
    """
    for cls in get_document_classes():
        if cls.document_type == document_type:
            # Reuse existing class policy:
            # - OCR is not required for translation
            # - Document type still has OCR capabilities/config (e.g. EPUB image OCR)
            return (not cls.ocr_required_for_translation) and cls.requires_ocr_config
    raise ValueError(f"Unknown document type: {document_type}")


def get_supported_formats_for_type(document_type: str) -> tuple[str, ...]:
    """Return supported export formats for a given document type.

    Args:
        document_type: The document type string (e.g., 'text', 'pdf', 'scanned_book')

    Returns:
        Tuple of supported export format strings.

    Raises:
        ValueError: If document type is unknown.
    """
    for cls in get_document_classes():
        if cls.document_type == document_type:
            return cls.supported_export_formats
    raise ValueError(f"Unknown document type: {document_type}")


def supports_multi_export_for_type(document_type: str) -> bool:
    """Check if a document type supports merging multiple documents into one export.

    Args:
        document_type: The document type string (e.g., 'text', 'pdf', 'epub')

    Returns:
        True if multiple documents of this type can be merged into one export file.

    Raises:
        ValueError: If document type is unknown.
    """
    for cls in get_document_classes():
        if cls.document_type == document_type:
            return cls.supports_multi_export
    raise ValueError(f"Unknown document type: {document_type}")


def supports_preserve_structure_for_type(document_type: str) -> bool:
    """Check if a document type supports preserve structure export.

    Args:
        document_type: The document type string (e.g., 'text', 'pdf', 'scanned_book')

    Returns:
        True if the document type supports preserve structure export.

    Raises:
        ValueError: If document type is unknown.
    """
    for cls in get_document_classes():
        if cls.document_type == document_type:
            return cls.supports_preserve_structure
    raise ValueError(f"Unknown document type: {document_type}")
