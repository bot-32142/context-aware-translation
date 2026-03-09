from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from context_aware_translation.core.cancellation import OperationCancelledError, raise_if_cancelled
from context_aware_translation.core.progress import ProgressCallback, ProgressUpdate, WorkflowStep
from context_aware_translation.documents.base import Document
from context_aware_translation.documents.content.ocr_content import MergedOCRContent
from context_aware_translation.llm.ocr import ocr_images
from context_aware_translation.utils.file_utils import classify_file, get_mime_type, scan_folder
from context_aware_translation.utils.image_utils import (
    compress_image_for_ocr,
    detect_mime_type,
    validate_image_bytes,
)
from context_aware_translation.utils.pandoc_export import export_pandoc

if TYPE_CHECKING:
    from context_aware_translation.config import ImageReembeddingConfig, OCRConfig
    from context_aware_translation.llm.client import LLMClient
    from context_aware_translation.storage.document_repository import DocumentRepository


class ScannedBookDocument(Document):
    """Document for scanned books (image folders). Operates on sources with source_type='image'."""

    document_type = "scanned_book"
    supported_export_formats: tuple[str, ...] = ("epub", "md")
    requires_ocr_config = True
    supports_preserve_structure = False

    def __init__(self, repo: DocumentRepository, document_id: int, ocr_config: OCRConfig | None = None):
        super().__init__(repo, document_id)
        self._merged_content: MergedOCRContent | None = None
        self._ocr_config = ocr_config

    @classmethod
    def can_import(cls, path: Path) -> bool:
        """Detect if path can be imported as ScannedBookDocument.

        Returns True if:
        - path is a single non-PDF image file
        - path is a folder containing only non-PDF image files

        Returns False otherwise (including for PDF files).
        """
        if not path.exists():
            return False

        if path.is_file():
            # Single file - check if it's a non-PDF image
            if path.suffix.lower() == ".pdf":
                return False  # PDFs handled by PDFDocument
            file_type = classify_file(path)
            return file_type == "image"
        elif path.is_dir():
            # Folder - check all files are non-PDF images
            files = scan_folder(path)
            if not files:
                return False
            # Reject if any file is PDF or not an image
            return all(f.suffix.lower() != ".pdf" and classify_file(f) == "image" for f in files)

        return False

    @classmethod
    def do_import(
        cls,
        repo: DocumentRepository,
        path: Path,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, int]:
        """Import scanned book from path (single image or folder of images).

        Creates document with document_type="scanned_book" and inserts each image
        as a source with source_type="image", storing binary_content and mime_type.
        Files are processed in alphabetical order. Skips files that already exist.

        Args:
            repo: DocumentRepository for database operations
            path: Path to single image file or folder of images

        Returns:
            Dict with "imported" and "skipped" counts.

        Raises:
            Exception: If import fails (transaction will be rolled back)
        """
        raise_if_cancelled(cancel_check)
        files = [path] if path.is_file() else scan_folder(path)

        imported = 0
        skipped = 0

        # Check which files already exist
        files_to_actually_import = []
        for file_path in files:
            raise_if_cancelled(cancel_check)
            binary_content = file_path.read_bytes()
            raise_if_cancelled(cancel_check)
            validate_image_bytes(binary_content, source_name=str(file_path))
            if repo.source_exists_by_binary(binary_content):
                skipped += 1
            else:
                mime_type = get_mime_type(file_path)
                if mime_type is None:
                    mime_type = "application/octet-stream"
                files_to_actually_import.append((file_path, binary_content, mime_type))

        if not files_to_actually_import:
            return {"imported": 0, "skipped": skipped}

        repo.begin()
        try:
            raise_if_cancelled(cancel_check)
            document_id = repo.insert_document("scanned_book", auto_commit=False)

            for seq, (_file_path, binary_content, mime_type) in enumerate(files_to_actually_import):
                raise_if_cancelled(cancel_check)
                repo.insert_document_source(
                    document_id,
                    seq,
                    "image",
                    binary_content=binary_content,
                    mime_type=mime_type,
                    auto_commit=False,
                )
                imported += 1

            raise_if_cancelled(cancel_check)
            repo.commit()
        except Exception:
            repo.rollback()
            raise

        return {"imported": imported, "skipped": skipped}

    def is_ocr_completed(self) -> bool:
        """Check if all sources have been OCR'd."""
        sources_needing_ocr = self.repo.get_document_sources_needing_ocr(self.document_id)
        return len(sources_needing_ocr) == 0

    async def process_ocr(
        self,
        llm_client: LLMClient,
        source_ids: list[int] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        on_item_processed: Callable[[], None] | None = None,
    ) -> int:
        raise_if_cancelled(cancel_check)
        if self._ocr_config is None:
            raise ValueError("ocr_config is required for process_ocr")
        if source_ids is None:
            sources = self.repo.get_document_sources_needing_ocr(self.document_id)
        else:
            source_ids_set = frozenset(source_ids)
            sources = [
                source
                for source in self.repo.get_document_sources(self.document_id)
                if source["source_type"] == "image" and source["source_id"] in source_ids_set
            ]

        if not sources:
            return 0

        # Collect all images upfront for batch processing
        # Compress high-res images to configured ocr_dpi for faster LLM processing
        image_data = [
            (
                compress_image_for_ocr(s["binary_content"], self._ocr_config.ocr_dpi),
                s.get("mime_type", "image/png"),
                f"page_{s['sequence_number']}",
            )
            for s in sources
        ]

        # Define callback for incremental persistence of OCR results
        def persist_result(index: int, ocr_pages: list[dict[str, Any]]) -> None:
            raise_if_cancelled(cancel_check)
            self.repo.update_source_ocr(sources[index]["source_id"], json.dumps(ocr_pages))
            self.repo.update_source_ocr_completed(sources[index]["source_id"])
            if on_item_processed is not None:
                on_item_processed()
            raise_if_cancelled(cancel_check)

        # Process all images concurrently in one call with incremental persistence
        if cancel_check is None:
            await ocr_images(
                image_data,
                llm_client,
                self._ocr_config,
                on_result=persist_result,
            )
        else:
            await ocr_images(
                image_data,
                llm_client,
                self._ocr_config,
                on_result=persist_result,
                cancel_check=cancel_check,
            )

        raise_if_cancelled(cancel_check)
        return len(sources)

    def get_text(self) -> str:
        """Merge all sources' OCR results into one, then extract text."""
        merged = self._get_merged_content()
        texts = merged.get_texts()
        return "\n".join(texts)

    def _get_merged_content(self) -> MergedOCRContent:
        sources = self.repo.get_document_sources(self.document_id)
        sources_sorted = sorted(sources, key=lambda s: s["sequence_number"])

        pages_data = [(json.loads(s["ocr_json"]), s.get("binary_content")) for s in sources_sorted if s.get("ocr_json")]

        return MergedOCRContent.from_raw_ocr(pages_data)

    def is_text_added(self) -> bool:
        """True if ALL sources have is_text_added=1."""
        sources = self.repo.get_document_sources(self.document_id)
        if not sources:
            return True
        return all(s["is_text_added"] == 1 for s in sources)

    def mark_text_added(self) -> None:
        """Mark ALL sources as text added."""
        self.repo.update_all_sources_text_added(self.document_id)

    async def set_text(
        self,
        lines: list[str],
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,  # noqa: ARG002
    ) -> int:
        """Distribute translated lines to merged OCR content. Returns lines consumed.

        Loads any previously-generated reembedded images from DB so that export still
        applies them.
        """
        merged = self._get_merged_content()
        line_count = merged.set_texts(lines)
        self._merged_content = merged

        # Load cached reembedded images from DB so export applies them
        from context_aware_translation.documents.content.ocr_items import ImageItem

        existing = self.repo.load_reembedded_images(self.document_id)
        for idx, elem in enumerate(self._merged_content.elements):
            if isinstance(elem, ImageItem) and idx in existing:
                elem.reembedded_image_bytes = existing[idx][0]

        return line_count

    async def reembed(
        self,
        image_reembedding_config: ImageReembeddingConfig,
        *,
        force: bool = False,
        source_ids: list[int] | None = None,  # noqa: ARG002
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> int:
        """Generate reembedded images for all ImageItems with translated text.

        Uses existing DB cache to skip already-done items unless force=True.
        Returns count of items newly generated.
        """
        import asyncio

        from context_aware_translation.documents.content.ocr_items import ImageItem
        from context_aware_translation.llm.image_generator import (
            build_text_replacements,
            create_image_generator,
        )

        if self._merged_content is None:
            return 0

        generator = create_image_generator(image_reembedding_config)

        # Load existing to skip already-processed items (unless force=True)
        existing = self.repo.load_reembedded_images(self.document_id) if not force else {}

        items_to_process: list[tuple[int, ImageItem]] = []
        for idx, elem in enumerate(self._merged_content.elements):
            if isinstance(elem, ImageItem) and elem.needs_reembedding() and idx not in existing:
                items_to_process.append((idx, elem))

        if not items_to_process:
            return 0

        total = len(items_to_process)
        completed = 0
        progress_lock = asyncio.Lock()
        semaphore = asyncio.Semaphore(image_reembedding_config.concurrency)

        async def process_item(idx: int, item: ImageItem) -> None:
            nonlocal completed
            async with semaphore:
                raise_if_cancelled(cancel_check)
                translated = item.get_embedded_translation()
                if translated is None or item.image_bytes is None:
                    return

                text_replacements = build_text_replacements(item.embedded_text or "", translated)
                mime_type = detect_mime_type(item.image_bytes)

                new_bytes = await generator.edit_image(
                    image_bytes=item.image_bytes,
                    mime_type=mime_type,
                    text_replacements=text_replacements,
                    cancel_check=cancel_check,
                )
                raise_if_cancelled(cancel_check)

                item.reembedded_image_bytes = new_bytes
                self.repo.save_reembedded_image(self.document_id, idx, new_bytes, "image/png")

                async with progress_lock:
                    completed += 1
                    if progress_callback:
                        progress_callback(
                            ProgressUpdate(
                                step=WorkflowStep.REEMBED,
                                current=completed,
                                total=total,
                                message=f"Reembedding image {completed}/{total}",
                            )
                        )

        results = await asyncio.gather(
            *[process_item(idx, item) for idx, item in items_to_process],
            return_exceptions=True,
        )

        for (_idx, _), result in zip(items_to_process, results, strict=True):
            if isinstance(result, OperationCancelledError):
                raise result
            if isinstance(result, Exception):
                raise RuntimeError(f"Failed to reembed image at index {_idx}: {result}. Please try again or skip it.")

        return completed

    def can_export(self, export_format: str) -> bool:
        """Check if this document can be exported to the given format."""
        return export_format.lower() in self.supported_export_formats

    @classmethod
    def export_merged(cls, documents: list[Document], export_format: str, output_path: Path) -> None:
        """Export multiple scanned book documents merged into a single file."""
        if not documents:
            raise ValueError("No documents to export")

        # Validate format
        if export_format.lower() not in ("epub", "md"):
            raise ValueError(
                f"Scanned book documents only support 'epub' and 'md' export formats. "
                f"Requested format '{export_format}' is not supported."
            )

        # Use a single temp directory for all images so they persist until pandoc runs
        with tempfile.TemporaryDirectory() as tmpdirname:
            # Merge all documents' markdown content
            merged_parts = []
            ocr_config = None

            for doc in documents:
                if not isinstance(doc, ScannedBookDocument):
                    raise ValueError("All documents must be ScannedBookDocument instances")
                if doc._merged_content is None:
                    raise ValueError(f"Document {doc.document_id} has no translated content. Call set_text() first.")

                # Get OCR config from first document if available
                if ocr_config is None and doc._ocr_config is not None:
                    ocr_config = doc._ocr_config

                # Extract markdown from each document
                strip_artifacts = ocr_config.strip_llm_artifacts if ocr_config else True
                markdown = doc._merged_content.to_markdown(Path(tmpdirname), strip_llm_artifacts=strip_artifacts)
                merged_parts.append(markdown)

            # Combine all markdown with separators
            merged_markdown = "\n\n".join(merged_parts)

            # Export using pandoc (inside temp dir context so images still exist)
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            fmt = export_format.lower()
            if fmt == "md":
                output_path.write_text(merged_markdown, encoding="utf-8")
            elif fmt == "epub":
                export_pandoc(merged_markdown, output_path, fmt, "md")

    def export_preserve_structure(self, output_folder: Path) -> None:
        """Not supported for scanned book documents."""
        raise NotImplementedError("Scanned book documents do not support structure-preserving export")
