from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from context_aware_translation.core.cancellation import raise_if_cancelled
from context_aware_translation.core.progress import ProgressCallback
from context_aware_translation.documents.base import Document
from context_aware_translation.utils.compression_marker import decode_compressed_lines
from context_aware_translation.utils.file_utils import classify_file, scan_folder

if TYPE_CHECKING:
    from context_aware_translation.config import ImageReembeddingConfig
    from context_aware_translation.llm.client import LLMClient
    from context_aware_translation.storage.repositories.document_repository import DocumentRepository


class TextDocument(Document):
    """Document for text files. Operates on sources with source_type='text'."""

    document_type = "text"
    supported_export_formats: tuple[str, ...] = ("txt",)
    requires_ocr_config = False
    ocr_required_for_translation = False
    supports_preserve_structure = True

    def __init__(self, repo: DocumentRepository, document_id: int):
        super().__init__(repo, document_id)
        self._translated_lines: list[str] | None = None

    @classmethod
    def can_import(cls, path: Path) -> bool:
        """Detect if path can be imported as TextDocument.

        Returns True if:
        - path is a single .txt or .md file
        - path is a folder containing only .txt or .md files

        Returns False otherwise.
        """
        path = Path(path)

        if not path.exists():
            return False

        if path.is_file():
            # Single file - check if it's text
            file_type = classify_file(path)
            return file_type == "text"
        elif path.is_dir():
            # Folder - check all files are text
            files = scan_folder(path)
            if not files:
                return False
            return all(classify_file(f) == "text" for f in files)

        return False

    @classmethod
    def do_import(
        cls,
        repo: DocumentRepository,
        path: Path,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, int]:
        """Import text file(s) into repository with transaction handling.

        Creates a document with document_type="text" and inserts sources
        for each text file in alphabetical order. Skips files that already exist.

        Args:
            repo: DocumentRepository instance
            path: Path to single text file or folder of text files

        Returns:
            Dict with "imported" and "skipped" counts.

        Raises:
            Exception: Re-raises any exception after rollback
        """
        path = Path(path)
        raise_if_cancelled(cancel_check)

        files_to_import = [path] if path.is_file() else scan_folder(path)

        imported = 0
        skipped = 0

        # Check which files already exist
        files_to_actually_import = []
        for file_path in files_to_import:
            raise_if_cancelled(cancel_check)
            text_content = file_path.read_text(encoding="utf-8")
            raise_if_cancelled(cancel_check)
            if repo.source_exists_by_content(text_content):
                skipped += 1
            else:
                files_to_actually_import.append((file_path, text_content))

        if not files_to_actually_import:
            return {"imported": 0, "skipped": skipped}

        repo.begin()
        try:
            raise_if_cancelled(cancel_check)
            document_id = repo.insert_document("text", auto_commit=False)

            for seq, (file_path, text_content) in enumerate(files_to_actually_import):
                raise_if_cancelled(cancel_check)
                repo.insert_document_source(
                    document_id,
                    seq,
                    "text",
                    relative_path=file_path.name,
                    text_content=text_content,
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
        """Text documents don't need OCR - always returns True."""
        return True

    async def process_ocr(
        self,
        llm_client: LLMClient,
        source_ids: list[int] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        on_item_processed: Callable[[], None] | None = None,
    ) -> int:
        """No-op for text documents - they don't need OCR."""
        _ = (llm_client, source_ids, on_item_processed)
        raise_if_cancelled(cancel_check)
        return 0

    def get_text(self) -> str:
        """Merge all sources' text_content in sequence order."""
        sources = self.repo.get_document_sources(self.document_id)
        sources_sorted = sorted(sources, key=lambda s: s["sequence_number"])
        texts = [s["text_content"] for s in sources_sorted if s["text_content"]]
        return "\n".join(texts)

    def is_text_added(self) -> bool:
        """True if ALL sources have is_text_added=1."""
        sources = self.repo.get_document_sources(self.document_id)
        if not sources:
            return True  # No sources means nothing to add
        return all(s["is_text_added"] == 1 for s in sources)

    def mark_text_added(self) -> None:
        """Mark ALL sources as text added."""
        self.repo.update_all_sources_text_added(self.document_id)

    async def set_text(
        self,
        lines: list[str],
        cancel_check: Callable[[], bool] | None = None,  # noqa: ARG002
        progress_callback: ProgressCallback | None = None,  # noqa: ARG002
    ) -> int:
        """Store translated lines for export. Returns lines consumed.

        Note: progress_callback is ignored for text documents (no images to reembed).
        """
        self._translated_lines = lines
        return len(lines)

    async def reembed(
        self,
        image_reembedding_config: ImageReembeddingConfig,  # noqa: ARG002
        *,
        force: bool = False,  # noqa: ARG002
        source_ids: list[int] | None = None,  # noqa: ARG002
        cancel_check: Callable[[], bool] | None = None,  # noqa: ARG002
        progress_callback: ProgressCallback | None = None,  # noqa: ARG002
    ) -> int:
        """No-op for text documents — they have no images to reembed."""
        return 0

    def can_export(self, export_format: str) -> bool:
        """Check if this document can be exported to the given format."""
        return export_format.lower() in self.supported_export_formats

    @classmethod
    def export_merged(
        cls,
        documents: list[Document],
        export_format: str,
        output_path: Path,
        *,
        use_original_images: bool = False,
    ) -> None:
        """Export multiple text documents merged into a single file."""
        _ = use_original_images
        if not documents:
            raise ValueError("No documents to export")

        # Validate format
        if export_format.lower() != "txt":
            raise ValueError(
                f"Text documents only support 'txt' export format. Requested format '{export_format}' is not supported."
            )

        # Merge all documents' translated lines
        merged_lines = []
        for doc in documents:
            if not isinstance(doc, TextDocument):
                raise ValueError("All documents must be TextDocument instances")
            if doc._translated_lines is None:
                raise ValueError(f"Document {doc.document_id} has no translated text. Call set_text() first.")
            merged_lines.extend(decode_compressed_lines(doc._translated_lines))
            merged_lines.append("")  # Add blank line between documents

        # Remove trailing blank line
        if merged_lines and merged_lines[-1] == "":
            merged_lines.pop()

        # Write to file
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(merged_lines), encoding="utf-8")

    def export_preserve_structure(self, output_folder: Path) -> None:
        """Export each source file to its original relative path."""
        if self._translated_lines is None:
            raise ValueError("No translated text to export. Call set_text() first.")

        output_folder = Path(output_folder)
        sources = self.repo.get_document_sources(self.document_id)
        sources_sorted = sorted(sources, key=lambda s: s["sequence_number"])

        def count_lines(text: str) -> int:
            return text.count("\n") + (1 if text and not text.endswith("\n") else 0)

        line_start = 0

        for source in sources_sorted:
            relative_path = source.get("relative_path")

            text_content = source.get("text_content") or ""
            line_count = count_lines(text_content)

            if relative_path and line_count > 0:
                # Extract the lines for this source
                source_lines = self._translated_lines[line_start : line_start + line_count]
                source_text = "\n".join(decode_compressed_lines(source_lines))

                # Write to output folder preserving relative path
                output_path = output_folder / relative_path
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(source_text, encoding="utf-8")

            line_start += line_count
