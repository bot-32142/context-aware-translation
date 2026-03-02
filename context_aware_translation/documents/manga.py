from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from context_aware_translation.core.cancellation import OperationCancelledError, raise_if_cancelled
from context_aware_translation.core.progress import ProgressCallback, ProgressUpdate, WorkflowStep
from context_aware_translation.documents.base import Document
from context_aware_translation.documents.manga_alignment import get_sources_with_nonempty_ocr_text
from context_aware_translation.utils.file_utils import IMAGE_EXTENSIONS
from context_aware_translation.utils.image_utils import compress_image_for_ocr, validate_image_bytes

if TYPE_CHECKING:
    from context_aware_translation.config import ImageReembeddingConfig, OCRConfig
    from context_aware_translation.llm.client import LLMClient
    from context_aware_translation.storage.document_repository import DocumentRepository

logger = logging.getLogger(__name__)

# Mapping from MIME type to file extension for CBZ export
_MIME_TO_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}


def _mime_to_ext(mime_type: str) -> str:
    """Convert MIME type to file extension. Defaults to .png."""
    return _MIME_TO_EXT.get(mime_type, ".png")


class MangaDocument(Document):
    document_type = "manga"
    supported_export_formats: tuple[str, ...] = ("cbz",)
    requires_ocr_config = True
    supports_preserve_structure = False

    def __init__(self, repo: DocumentRepository, document_id: int, ocr_config: OCRConfig | None = None):
        super().__init__(repo, document_id)
        self._ocr_config = ocr_config
        self._page_translations: dict[int, str] = {}  # source_id -> translated_text
        self._reembedded_pages: dict[int, bytes] = {}  # source_id -> reembedded image bytes

    @classmethod
    def can_import(cls, path: Path) -> bool:
        """Detect if path can be imported as MangaDocument.

        Returns True if:
        - path is a .cbz file
        - path is a folder containing only image files

        Note: For folders, both MangaDocument and ScannedBookDocument can_import()
        will return True. The import system will ask the user to pick document_type.
        For .cbz files, only MangaDocument matches.
        """
        if path.is_file():
            return path.suffix.lower() == ".cbz"
        elif path.is_dir():
            from context_aware_translation.utils.file_utils import classify_file, scan_folder

            files = scan_folder(path)
            if not files:
                return False
            return all(f.suffix.lower() != ".pdf" and classify_file(f) == "image" for f in files)
        return False

    @classmethod
    def do_import(
        cls,
        repo: DocumentRepository,
        path: Path,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, int]:
        raise_if_cancelled(cancel_check)
        if path.is_dir():
            return cls._import_image_folder(repo, path, cancel_check=cancel_check)
        elif path.suffix.lower() == ".cbz":
            return cls._import_cbz(repo, path, cancel_check=cancel_check)
        raise ValueError(f"Unsupported manga format: {path.suffix}")

    @classmethod
    def _import_image_folder(
        cls,
        repo: DocumentRepository,
        path: Path,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, int]:
        """Import manga from a folder of images (same logic as ScannedBookDocument)."""
        from context_aware_translation.utils.file_utils import get_mime_type, scan_folder

        raise_if_cancelled(cancel_check)
        files = scan_folder(path)
        imported = 0
        skipped = 0

        files_to_import = []
        for file_path in files:
            raise_if_cancelled(cancel_check)
            binary_content = file_path.read_bytes()
            raise_if_cancelled(cancel_check)
            validate_image_bytes(binary_content, source_name=str(file_path))
            if repo.source_exists_by_binary(binary_content):
                skipped += 1
            else:
                mime_type = get_mime_type(file_path) or "application/octet-stream"
                files_to_import.append((file_path, binary_content, mime_type))

        if not files_to_import:
            return {"imported": 0, "skipped": skipped}

        repo.begin()
        try:
            raise_if_cancelled(cancel_check)
            document_id = repo.insert_document("manga", auto_commit=False)
            for seq, (_file_path, binary_content, mime_type) in enumerate(files_to_import):
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

    @classmethod
    def _import_cbz(
        cls,
        repo: DocumentRepository,
        path: Path,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, int]:
        import zipfile

        raise_if_cancelled(cancel_check)
        with zipfile.ZipFile(path, "r") as zf:
            image_entries = sorted(
                [
                    name
                    for name in zf.namelist()
                    if not name.startswith("__MACOSX")
                    and not name.endswith("/")
                    and Path(name).suffix.lower() in IMAGE_EXTENSIONS
                ]
            )

            if not image_entries:
                return {"imported": 0, "skipped": 0}

            imported = 0
            skipped = 0

            files_to_import = []
            for name in image_entries:
                raise_if_cancelled(cancel_check)
                binary_content = zf.read(name)
                raise_if_cancelled(cancel_check)
                validate_image_bytes(binary_content, source_name=name)
                if repo.source_exists_by_binary(binary_content):
                    skipped += 1
                else:
                    ext = Path(name).suffix.lower()
                    mime_map = {
                        ".png": "image/png",
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".gif": "image/gif",
                        ".webp": "image/webp",
                        ".bmp": "image/bmp",
                    }
                    mime_type = mime_map.get(ext, "image/png")
                    files_to_import.append((name, binary_content, mime_type))

            if not files_to_import:
                return {"imported": 0, "skipped": skipped}

            repo.begin()
            try:
                raise_if_cancelled(cancel_check)
                document_id = repo.insert_document("manga", auto_commit=False)
                for seq, (_name, binary_content, mime_type) in enumerate(files_to_import):
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
        sources = self.repo.get_document_sources_needing_ocr(self.document_id)
        return len(sources) == 0

    async def process_ocr(
        self,
        llm_client: LLMClient,
        source_ids: list[int] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        on_item_processed: Callable[[], None] | None = None,
    ) -> int:
        """OCR using simple manga text extraction (not structured OCR)."""
        raise_if_cancelled(cancel_check)
        if self._ocr_config is None:
            raise ValueError("ocr_config is required for process_ocr")

        ocr_config = self._ocr_config

        from context_aware_translation.llm.manga_ocr import ocr_manga_image

        sources = self.repo.get_document_sources_needing_ocr(self.document_id)
        if source_ids is not None:
            sources = [s for s in sources if s["source_id"] in source_ids]
        if not sources:
            return 0

        image_data = [
            (compress_image_for_ocr(s["binary_content"], ocr_config.ocr_dpi), s.get("mime_type", "image/png"))
            for s in sources
        ]

        semaphore = asyncio.Semaphore(ocr_config.concurrency)

        async def process_one(index: int, img_bytes: bytes, mime_type: str) -> None:
            raise_if_cancelled(cancel_check)
            async with semaphore:
                raise_if_cancelled(cancel_check)
                text = await ocr_manga_image(img_bytes, mime_type, llm_client, ocr_config)
                raise_if_cancelled(cancel_check)
                ocr_result = json.dumps({"text": text})
                self.repo.update_source_ocr(sources[index]["source_id"], ocr_result)
                self.repo.update_source_ocr_completed(sources[index]["source_id"])
                if on_item_processed is not None:
                    on_item_processed()
                raise_if_cancelled(cancel_check)

        await asyncio.gather(*[process_one(i, img, mime) for i, (img, mime) in enumerate(image_data)])
        raise_if_cancelled(cancel_check)
        return len(sources)

    def _get_sources_with_text(self) -> list[tuple[dict, str]]:
        """Return (source, text) pairs for pages with non-empty OCR text.

        Sorted by sequence_number.  This is the single source of truth for
        which pages are "non-blank" — used by get_text(), set_text(), and
        must match list_page_source_ids() / MangaDocumentHandler.add_text().
        """
        sources = self.repo.get_document_sources(self.document_id)
        return [(source, text) for _, source, text in get_sources_with_nonempty_ocr_text(sources)]

    def get_text(self) -> str:
        """Get concatenated plain text from all pages.

        Each page's text is separated by a newline. This matches the
        convention in MangaDocumentHandler.add_text() which splits by
        newline to recover per-page text.
        """
        texts = []
        for _source, page_text in self._get_sources_with_text():
            # Replace internal newlines with spaces so newlines in get_text()
            # output only appear as page separators
            texts.append(page_text.replace("\n", " "))
        return "\n".join(texts)

    def is_text_added(self) -> bool:
        sources = self.repo.get_document_sources(self.document_id)
        if not sources:
            return True
        return all(s["is_text_added"] == 1 for s in sources)

    def mark_text_added(self) -> None:
        self.repo.update_all_sources_text_added(self.document_id)

    async def set_text(
        self,
        lines: list[str],
        cancel_check: Callable[[], bool] | None = None,  # noqa: ARG002
        progress_callback: ProgressCallback | None = None,  # noqa: ARG002
    ) -> int:
        """Store translations for manga pages.

        For manga, 'lines' contains one block of translated text per page.
        Each element in lines corresponds to a source (page) in sequence order.
        Elements MAY contain internal newlines (multi-line dialogue).

        Loads any previously-generated reembedded images from DB so that export still
        applies them.
        """
        sources_with_text = self._get_sources_with_text()

        consumed = 0
        for source, _text in sources_with_text:
            if consumed >= len(lines):
                break
            self._page_translations[source["source_id"]] = lines[consumed]
            consumed += 1

        # Load cached reembedded images from DB so export applies them.
        sources = self.repo.get_document_sources(self.document_id)
        existing = self.repo.load_reembedded_images(self.document_id)
        for source_idx, source, _ocr_text in get_sources_with_nonempty_ocr_text(sources):
            cached = existing.get(source_idx)
            if cached is not None:
                self._reembedded_pages[source["source_id"]] = cached[0]

        return consumed

    async def reembed(
        self,
        image_reembedding_config: ImageReembeddingConfig,
        *,
        force: bool = False,
        source_ids: list[int] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> int:
        """Generate reembedded images for manga pages with translations.

        Uses existing DB cache to skip already-done items unless force=True.
        Returns count of pages newly generated.
        """
        from context_aware_translation.llm.image_generator import create_image_generator

        generator = create_image_generator(image_reembedding_config)
        semaphore = asyncio.Semaphore(image_reembedding_config.concurrency)

        sources = self.repo.get_document_sources(self.document_id)
        sources_sorted = sorted(sources, key=lambda s: s["sequence_number"])

        # Build mapping from source_id to positional index in the FULL list
        # (DB keys must be stable regardless of source_ids filtering)
        source_id_to_idx = {s["source_id"]: idx for idx, s in enumerate(sources_sorted)}

        if source_ids is not None:
            source_ids_set = frozenset(source_ids)
            sources_sorted = [s for s in sources_sorted if s["source_id"] in source_ids_set]

        # Load existing to skip already-processed items (unless force=True)
        existing = self.repo.load_reembedded_images(self.document_id) if not force else {}

        def _get_cached_reembed(source_id: int) -> tuple[bytes, str] | None:
            original_idx = source_id_to_idx[source_id]
            if original_idx in existing:
                return existing[original_idx]
            return None

        total = sum(
            1
            for source in sources_sorted
            if self._page_translations.get(source["source_id"], "").strip()
            and _get_cached_reembed(source["source_id"]) is None
        )
        if total == 0:
            return 0

        completed = 0
        progress_lock = asyncio.Lock()

        async def process_page(source: dict) -> None:
            nonlocal completed
            async with semaphore:
                raise_if_cancelled(cancel_check)
                source_id = source["source_id"]
                original_idx = source_id_to_idx[source_id]
                translated = self._page_translations.get(source_id, "")
                if not translated.strip():
                    return
                cached = _get_cached_reembed(source_id)
                if cached is not None:
                    # Already cached — populate in-memory but don't count as newly generated
                    self._reembedded_pages[source_id] = cached[0]
                    return
                image_bytes = source["binary_content"]
                mime_type = source.get("mime_type", "image/png")
                new_bytes = await generator.edit_image(image_bytes, mime_type, translated, cancel_check=cancel_check)
                raise_if_cancelled(cancel_check)
                self._reembedded_pages[source_id] = new_bytes
                self.repo.save_reembedded_image(self.document_id, original_idx, new_bytes, "image/png")

                async with progress_lock:
                    completed += 1
                    if progress_callback:
                        progress_callback(
                            ProgressUpdate(
                                step=WorkflowStep.REEMBED,
                                current=completed,
                                total=total,
                                message=f"Reembedding manga page {completed}/{total}",
                            )
                        )

        results = await asyncio.gather(
            *[process_page(s) for s in sources_sorted],
            return_exceptions=True,
        )
        for source, result in zip(sources_sorted, results, strict=True):
            if isinstance(result, OperationCancelledError):
                raise result
            if isinstance(result, Exception):
                raise RuntimeError(
                    f"Failed to reembed manga page (source {source['source_id']}): {type(result).__name__}: {result}"
                ) from result

        return completed

    def can_export(self, export_format: str) -> bool:
        return export_format.lower() in self.supported_export_formats

    @classmethod
    def export_merged(cls, documents: list[Document], export_format: str, output_path: Path) -> None:
        """Export manga documents. CBZ: zip of images. EPUB/MD: text with images."""
        fmt = export_format.lower()
        if fmt == "cbz":
            cls._export_cbz(documents, output_path)
        elif fmt in ("epub", "md"):
            cls._export_markdown_based(documents, export_format, output_path)
        else:
            raise ValueError(f"Unsupported format: {export_format}")

    @classmethod
    def _export_cbz(cls, documents: list[Document], output_path: Path) -> None:
        import zipfile

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_STORED) as zf:
            page_num = 0
            for doc in documents:
                if not isinstance(doc, MangaDocument):
                    raise ValueError("All documents must be MangaDocument instances")
                sources = doc.repo.get_document_sources(doc.document_id)
                sources_sorted = sorted(sources, key=lambda s: s["sequence_number"])
                for source in sources_sorted:
                    source_id = source["source_id"]
                    if source_id in doc._reembedded_pages:
                        img_bytes = doc._reembedded_pages[source_id]
                        ext = ".png"
                    else:
                        img_bytes = source["binary_content"]
                        ext = _mime_to_ext(source.get("mime_type", "image/png"))
                    zf.writestr(f"page_{page_num:04d}{ext}", img_bytes)
                    page_num += 1

    @classmethod
    def _export_markdown_based(cls, documents: list[Document], export_format: str, output_path: Path) -> None:
        """Export manga as markdown/epub: each page's translation as a text block."""
        import tempfile

        from context_aware_translation.utils.pandoc_export import export_pandoc

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            parts = []
            img_counter = 0
            for doc in documents:
                if not isinstance(doc, MangaDocument):
                    raise ValueError("All documents must be MangaDocument instances")
                sources = doc.repo.get_document_sources(doc.document_id)
                sources_sorted = sorted(sources, key=lambda s: s["sequence_number"])
                for source in sources_sorted:
                    source_id = source["source_id"]
                    if source_id in doc._reembedded_pages:
                        img_bytes = doc._reembedded_pages[source_id]
                        ext = ".png"
                    else:
                        img_bytes = source["binary_content"]
                        ext = _mime_to_ext(source.get("mime_type", "image/png"))

                    img_name = f"page_{img_counter:04d}{ext}"
                    img_path = Path(tmpdir) / img_name
                    img_path.write_bytes(img_bytes)

                    translation = doc._page_translations.get(source_id, "")
                    parts.append(f"![Page {img_counter + 1}]({img_path})\n\n{translation}")
                    img_counter += 1

            merged_markdown = "\n\n---\n\n".join(parts)

            fmt = export_format.lower()
            if fmt == "md":
                output_path.write_text(merged_markdown, encoding="utf-8")
            elif fmt == "epub":
                export_pandoc(merged_markdown, output_path, fmt, "md")

    def export_preserve_structure(self, output_folder: Path) -> None:
        raise NotImplementedError("Manga documents do not support structure-preserving export")
