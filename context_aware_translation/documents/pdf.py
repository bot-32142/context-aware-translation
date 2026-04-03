from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import tempfile
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pikepdf
import pypdfium2

from context_aware_translation.core.cancellation import OperationCancelledError, raise_if_cancelled
from context_aware_translation.core.progress import ProgressCallback, ProgressUpdate, WorkflowStep
from context_aware_translation.documents.base import Document
from context_aware_translation.documents.content.ocr_content import MergedOCRContent
from context_aware_translation.documents.content.ocr_items import ImageItem
from context_aware_translation.llm.image_generator import build_text_replacements, create_image_generator
from context_aware_translation.llm.ocr import ocr_images
from context_aware_translation.utils.image_utils import compress_image_for_ocr, detect_mime_type
from context_aware_translation.utils.pandoc_export import export_pandoc

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from context_aware_translation.config import ImageReembeddingConfig, OCRConfig
    from context_aware_translation.llm.client import LLMClient
    from context_aware_translation.storage.repositories.document_repository import DocumentRepository


def _rasterize_page_from_path(pdf_path: str, page_index: int, dpi: int) -> bytes:
    """Rasterize one PDF page from file path (for process-pool workers)."""
    pdf = pypdfium2.PdfDocument(pdf_path)
    page = pdf[page_index]
    scale = dpi / 72
    bitmap = page.render(scale=scale)
    pil_image = bitmap.to_pil()
    buffer = io.BytesIO()
    pil_image.save(buffer, format="PNG")
    pdf.close()
    return buffer.getvalue()


class PDFDocument(Document):
    """Document for PDF files. Operates on sources with source_type='image' (one per page)."""

    document_type = "pdf"
    supported_export_formats: tuple[str, ...] = ("epub", "md", "txt")
    requires_ocr_config = True
    supports_preserve_structure = False

    # DPI settings for PDF page extraction.
    # Storage: Original embedded images at full resolution when possible.
    #          Vector pages are rasterized at DEFAULT_VECTOR_DPI.
    #          Mixed pages use max(DEFAULT_VECTOR_DPI, estimated_image_dpi).
    # OCR: Compressed to ocr_config.ocr_dpi before sending to LLM for speed.
    DEFAULT_VECTOR_DPI = 150  # Base DPI for vector/mixed pages
    MAX_IMPORT_WORKERS = 4
    MIN_PARALLEL_RASTER_JOBS = 24

    def __init__(self, repo: DocumentRepository, document_id: int, ocr_config: OCRConfig | None = None):
        super().__init__(repo, document_id)
        self._merged_content: MergedOCRContent | None = None
        self._ocr_config = ocr_config

    @classmethod
    def _estimate_image_dpi(
        cls, image_width: int, image_height: int, page_width_pts: float, page_height_pts: float
    ) -> int:
        """Estimate the effective DPI of an embedded image.

        Uses a conservative estimate assuming the image fills the page.
        This may over-estimate DPI but will never under-estimate (safe for quality).

        Args:
            image_width: Image width in pixels
            image_height: Image height in pixels
            page_width_pts: Page width in points (1/72 inch)
            page_height_pts: Page height in points (1/72 inch)

        Returns:
            Estimated effective DPI
        """
        if page_width_pts <= 0 or page_height_pts <= 0:
            return cls.DEFAULT_VECTOR_DPI

        # Estimate DPI assuming image fills page (conservative)
        dpi_x = (image_width / page_width_pts) * 72
        dpi_y = (image_height / page_height_pts) * 72
        return max(int(dpi_x), int(dpi_y), cls.DEFAULT_VECTOR_DPI)

    @classmethod
    def _get_embedded_images_info(cls, pdf: pikepdf.Pdf, page_index: int) -> list[dict[str, Any]]:
        """Get information about embedded images on a page using pikepdf.

        Args:
            pdf: pikepdf.Pdf object
            page_index: Zero-based page index

        Returns:
            List of dicts with 'xref', 'width', 'height' for each image
        """
        images_info: list[dict[str, Any]] = []
        try:
            page = pdf.pages[page_index]
            if "/Resources" not in page or "/XObject" not in page["/Resources"]:
                return images_info

            xobjects = page["/Resources"]["/XObject"]
            for name in list(xobjects.keys()):
                xobj = xobjects[name]
                if xobj.get("/Subtype") == "/Image":
                    try:
                        pdfimage = pikepdf.PdfImage(xobj)  # type: ignore[arg-type]
                        images_info.append(
                            {
                                "name": str(name),
                                "width": pdfimage.width,
                                "height": pdfimage.height,
                                "obj": xobj,
                            }
                        )
                    except Exception:
                        pass
        except Exception:
            pass
        return images_info

    @classmethod
    def _extract_image_bytes(cls, pdfimage: pikepdf.PdfImage) -> tuple[bytes, str] | None:
        """Extract image bytes from a pikepdf PdfImage.

        Args:
            pdfimage: pikepdf.PdfImage object

        Returns:
            Tuple of (image_bytes, extension) or None if extraction fails
        """
        try:
            # Try to extract raw image data
            pil_image = pdfimage.as_pil_image()
            if pil_image.mode in ("CMYK", "LAB", "P"):
                pil_image = pil_image.convert("RGB")
            buffer = io.BytesIO()
            pil_image.save(buffer, format="PNG")
            return (buffer.getvalue(), "png")
        except Exception:
            return None

    @classmethod
    def _rasterize_page_from_bytes(cls, pdf_bytes: bytes, page_index: int, dpi: int) -> bytes:
        """Rasterize a PDF page from bytes at the specified DPI using pypdfium2.

        Args:
            pdf_bytes: PDF file bytes
            page_index: Zero-based page index
            dpi: Target DPI for rasterization

        Returns:
            PNG image bytes
        """
        pdf = pypdfium2.PdfDocument(pdf_bytes)
        page = pdf[page_index]
        scale = dpi / 72  # Convert DPI to scale factor
        bitmap = page.render(scale=scale)
        pil_image = bitmap.to_pil()
        buffer = io.BytesIO()
        pil_image.save(buffer, format="PNG")
        pdf.close()
        return buffer.getvalue()

    @classmethod
    def _extract_page_image_for_storage(
        cls,
        pdf_bytes: bytes,
        pikepdf_doc: pikepdf.Pdf,
        page_index: int,
        page_width_pts: float,
        page_height_pts: float,
        vector_dpi: int,
    ) -> tuple[bytes, str]:
        """Extract image from a PDF page for storage.

        For scanned pages (single full-page embedded image): extracts original at full resolution.
        For vector pages (no embedded images): rasterizes at vector_dpi.
        For mixed pages: rasterizes at max(vector_dpi, estimated_image_dpi).

        Args:
            pdf_bytes: PDF file bytes (for pypdfium2 rasterization)
            pikepdf_doc: pikepdf.Pdf object (for image extraction)
            page_index: Zero-based page index
            page_width_pts: Page width in points
            page_height_pts: Page height in points
            vector_dpi: Base DPI for rasterizing vector/mixed pages

        Returns:
            Tuple of (image_bytes, mime_type)
        """
        images_info = cls._get_embedded_images_info(pikepdf_doc, page_index)

        # Pure vector page (no images) - rasterize at vector_dpi
        if len(images_info) == 0:
            image_bytes = cls._rasterize_page_from_bytes(pdf_bytes, page_index, vector_dpi)
            return (image_bytes, "image/png")

        # Try to extract original embedded image for scanned pages (single full-page image)
        if len(images_info) == 1:
            img_info = images_info[0]
            img_width = img_info["width"]
            img_height = img_info["height"]

            # Check if image covers most of page (scanned page)
            page_aspect = page_width_pts / page_height_pts if page_height_pts > 0 else 1
            img_aspect = img_width / img_height if img_height > 0 else 1

            if abs(page_aspect - img_aspect) < 0.1:
                try:
                    pdfimage = pikepdf.PdfImage(img_info["obj"])
                    result = cls._extract_image_bytes(pdfimage)
                    if result is not None:
                        image_bytes, _ = result
                        return (image_bytes, "image/png")
                except Exception:
                    pass  # Fall through to rasterization

        # Mixed page (text + images) - rasterize at max(vector_dpi, estimated_image_dpi)
        max_estimated_dpi = vector_dpi
        for img_info in images_info:
            estimated_dpi = cls._estimate_image_dpi(
                img_info["width"], img_info["height"], page_width_pts, page_height_pts
            )
            max_estimated_dpi = max(max_estimated_dpi, estimated_dpi)

        image_bytes = cls._rasterize_page_from_bytes(pdf_bytes, page_index, max_estimated_dpi)
        return (image_bytes, "image/png")

    @classmethod
    def _build_page_extraction_plan(
        cls,
        pikepdf_doc: pikepdf.Pdf,
        page_index: int,
        page_width_pts: float,
        page_height_pts: float,
        vector_dpi: int,
    ) -> tuple[bytes | None, int | None]:
        """Plan extraction for one page.

        Returns either:
        - (embedded_image_bytes, None) when direct image extraction is possible
        - (None, rasterize_dpi) when the page should be rasterized
        """
        images_info = cls._get_embedded_images_info(pikepdf_doc, page_index)

        # Pure vector page (no images) - rasterize at vector_dpi.
        if len(images_info) == 0:
            return (None, vector_dpi)

        # Scanned-like page (single full-page image) - keep original image quality if possible.
        if len(images_info) == 1:
            img_info = images_info[0]
            img_width = img_info["width"]
            img_height = img_info["height"]
            page_aspect = page_width_pts / page_height_pts if page_height_pts > 0 else 1
            img_aspect = img_width / img_height if img_height > 0 else 1

            if abs(page_aspect - img_aspect) < 0.1:
                try:
                    pdfimage = pikepdf.PdfImage(img_info["obj"])
                    extracted = cls._extract_image_bytes(pdfimage)
                    if extracted is not None:
                        image_bytes, _ = extracted
                        return (image_bytes, None)
                except Exception:
                    pass

        # Mixed page - rasterize at max(vector_dpi, estimated embedded image dpi).
        max_estimated_dpi = vector_dpi
        for img_info in images_info:
            estimated_dpi = cls._estimate_image_dpi(
                img_info["width"], img_info["height"], page_width_pts, page_height_pts
            )
            max_estimated_dpi = max(max_estimated_dpi, estimated_dpi)

        return (None, max_estimated_dpi)

    @classmethod
    def _rasterize_jobs_parallel(
        cls,
        pdf_path: Path,
        pdf_bytes: bytes,
        jobs: list[tuple[int, int]],
        cancel_check: Callable[[], bool] | None = None,
    ) -> list[tuple[int, bytes]]:
        """Rasterize page jobs in parallel when beneficial; fallback to sequential when needed."""
        if not jobs:
            return []

        if len(jobs) < cls.MIN_PARALLEL_RASTER_JOBS:
            sequential_results: list[tuple[int, bytes]] = []
            for page_index, dpi in jobs:
                raise_if_cancelled(cancel_check)
                sequential_results.append((page_index, cls._rasterize_page_from_bytes(pdf_bytes, page_index, dpi)))
            return sequential_results

        cpu_count = os.cpu_count() or 1
        max_workers = max(1, min(len(jobs), cls.MAX_IMPORT_WORKERS, cpu_count))
        results: list[tuple[int, bytes]] = []

        if max_workers == 1:
            for page_index, dpi in jobs:
                raise_if_cancelled(cancel_check)
                results.append((page_index, cls._rasterize_page_from_bytes(pdf_bytes, page_index, dpi)))
            return results

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_page: dict[Any, int] = {
                executor.submit(_rasterize_page_from_path, str(pdf_path), page_index, dpi): page_index
                for page_index, dpi in jobs
            }
            try:
                for future in as_completed(future_to_page):
                    raise_if_cancelled(cancel_check)
                    page_index = future_to_page[future]
                    image_bytes = future.result()
                    results.append((page_index, image_bytes))
            except Exception:
                for pending in future_to_page:
                    pending.cancel()
                raise_if_cancelled(cancel_check)
                logger.warning("Parallel PDF rasterization failed; retrying sequentially.", exc_info=True)
                fallback_results: list[tuple[int, bytes]] = []
                for page_index, dpi in jobs:
                    raise_if_cancelled(cancel_check)
                    fallback_results.append((page_index, cls._rasterize_page_from_bytes(pdf_bytes, page_index, dpi)))
                return fallback_results

        return results

    @classmethod
    def can_import(cls, path: Path) -> bool:
        """Detect if path can be imported as PDFDocument.

        Returns True only if path is a single .pdf file.
        Folders are not supported for PDF imports.

        Args:
            path: Path to check for PDF import compatibility.

        Returns:
            True if path is a single .pdf file, False otherwise.
        """
        if not path.exists():
            return False

        return path.is_file() and path.suffix.lower() == ".pdf"

    @classmethod
    def do_import(
        cls,
        repo: DocumentRepository,
        path: Path,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, int]:
        """Import PDF file into repository with page extraction.

        Uses smart extraction:
        - Scanned pages (single full-page image): extracts original at full resolution
        - Vector pages (text/graphics only): rasterizes at DEFAULT_VECTOR_DPI

        Images are stored at original resolution. They are compressed on-the-fly during
        OCR processing for faster LLM calls.

        Manages transactions internally (begin/commit/rollback).
        Skips PDFs that have already been imported (checks first page content).

        Args:
            repo: DocumentRepository for database operations.
            path: Path to PDF file to import.

        Returns:
            Dict with "imported" and "skipped" counts.

        Raises:
            Exception: If import fails, transaction is rolled back and exception re-raised.
        """
        vector_dpi = cls.DEFAULT_VECTOR_DPI

        raise_if_cancelled(cancel_check)
        pdf_bytes = path.read_bytes()
        raise_if_cancelled(cancel_check)

        # Use pypdfium2 for page dimensions
        pdfium_doc = pypdfium2.PdfDocument(pdf_bytes)

        # Use pikepdf for image extraction
        pikepdf_doc = pikepdf.open(io.BytesIO(pdf_bytes))

        total_pages = len(pdfium_doc)
        processed_pages = 0
        pages: list[tuple[bytes, str] | None] = [None] * total_pages
        rasterize_jobs: list[tuple[int, int]] = []

        def emit_progress() -> None:
            if not progress_callback or total_pages == 0:
                return
            progress_callback(
                ProgressUpdate(
                    step=WorkflowStep.EXPORT,
                    current=processed_pages,
                    total=total_pages,
                    message=f"Importing PDF pages ({processed_pages}/{total_pages})",
                )
            )

        emit_progress()
        try:
            for page_idx in range(total_pages):
                raise_if_cancelled(cancel_check)
                page = pdfium_doc[page_idx]
                page_width_pts, page_height_pts = page.get_size()

                extracted_image, rasterize_dpi = cls._build_page_extraction_plan(
                    pikepdf_doc,
                    page_idx,
                    page_width_pts,
                    page_height_pts,
                    vector_dpi,
                )
                if extracted_image is not None:
                    pages[page_idx] = (extracted_image, "image/png")
                    processed_pages += 1
                    emit_progress()
                else:
                    assert rasterize_dpi is not None
                    rasterize_jobs.append((page_idx, rasterize_dpi))
                raise_if_cancelled(cancel_check)
        finally:
            pdfium_doc.close()
            pikepdf_doc.close()

        for page_idx, image_bytes in cls._rasterize_jobs_parallel(
            path, pdf_bytes, rasterize_jobs, cancel_check=cancel_check
        ):
            pages[page_idx] = (image_bytes, "image/png")
            processed_pages += 1
            emit_progress()
            raise_if_cancelled(cancel_check)

        if any(page is None for page in pages):
            raise RuntimeError("PDF import failed: one or more pages were not extracted.")
        resolved_pages = [page for page in pages if page is not None]

        # Check if this PDF was already imported by checking first page
        if resolved_pages and repo.source_exists_by_binary(resolved_pages[0][0]):
            return {"imported": 0, "skipped": 1}

        repo.begin()
        try:
            raise_if_cancelled(cancel_check)
            document_id = repo.insert_document("pdf", auto_commit=False)

            for seq, (image_bytes, mime_type) in enumerate(resolved_pages):
                raise_if_cancelled(cancel_check)
                repo.insert_document_source(
                    document_id,
                    seq,
                    "image",
                    binary_content=image_bytes,
                    mime_type=mime_type,
                    auto_commit=False,
                )

            raise_if_cancelled(cancel_check)
            repo.commit()
        except Exception:
            repo.rollback()
            raise

        return {"imported": 1, "skipped": 0}

    def is_ocr_completed(self) -> bool:
        """Check if all image sources have been OCR'd."""
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
        # Compress high-res stored images to configured ocr_dpi for faster LLM processing
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

    def _get_merged_content(self) -> MergedOCRContent:
        sources = self.repo.get_document_sources(self.document_id)
        sources_sorted = sorted(sources, key=lambda s: s["sequence_number"])

        # Collect raw JSON and image bytes for each source
        # Images are stored at high resolution for quality output
        pages = []
        for source in sources_sorted:
            if source.get("ocr_json"):
                raw_json = json.loads(source["ocr_json"])
                image_bytes = source.get("binary_content")
                pages.append((raw_json, image_bytes))

        return MergedOCRContent.from_raw_ocr(pages)

    def get_text(self) -> str:
        """Merge all sources' OCR results into one, then extract text."""
        merged = self._get_merged_content()
        texts = merged.get_texts()
        return "\n".join(texts)

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
        """Export multiple PDF documents merged into a single file."""
        if not documents:
            raise ValueError("No documents to export")

        # Validate format
        if export_format.lower() not in ("epub", "md", "txt"):
            raise ValueError(
                f"PDF documents only support 'epub', 'md', and 'txt' export formats. "
                f"Requested format '{export_format}' is not supported."
            )

        # Use a single temp directory for all images so they persist until pandoc runs
        with tempfile.TemporaryDirectory() as tmpdirname:
            # Merge all documents' markdown content
            merged_parts = []
            ocr_config = None

            for doc in documents:
                if not isinstance(doc, PDFDocument):
                    raise ValueError("All documents must be PDFDocument instances")
                if doc._merged_content is None:
                    raise ValueError(f"Document {doc.document_id} has no translated content. Call set_text() first.")

                # Get OCR config from first document if available
                if ocr_config is None and doc._ocr_config is not None:
                    ocr_config = doc._ocr_config

                # Extract markdown from each document
                # CoverItem outputs YAML frontmatter with cover-image for pandoc
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
            else:
                export_pandoc(merged_markdown, output_path, fmt, "md")

    def export_preserve_structure(self, output_folder: Path) -> None:
        """Not supported for PDF documents."""
        raise NotImplementedError("PDF documents do not support structure-preserving export")
