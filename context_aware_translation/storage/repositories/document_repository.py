"""Repository for document and source operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from context_aware_translation.documents.base import is_ocr_required_for_type

if TYPE_CHECKING:
    from context_aware_translation.storage.schema.book_db import SQLiteBookDB


class DocumentRepository:
    """Repository for document and source operations."""

    def __init__(self, db: SQLiteBookDB) -> None:
        """Initialize DocumentRepository with a database instance.

        Args:
            db: SQLiteBookDB instance to delegate operations to
        """
        self.db = db

    # =========================================================================
    # Document Methods
    # =========================================================================

    def get_document_row(self) -> dict | None:
        """Get THE document (at most 1 row). Returns dict or None."""
        return self.db.get_document_row()

    def list_documents(self) -> list[dict]:
        """Return all documents from database."""
        return self.db.list_documents()

    def get_document_by_id(self, document_id: int) -> dict | None:
        """Get specific document by ID."""
        return self.db.get_document_by_id(document_id)

    def get_chunk_count(self, document_id: int) -> int:
        """Get the count of chunks for a specific document.

        Args:
            document_id: The document ID to count chunks for

        Returns:
            Number of chunks for the document
        """
        return self.db.get_chunk_count(document_id)

    def insert_document(self, document_type: str, auto_commit: bool = True) -> int:
        """Insert a new document. Returns document_id."""
        return self.db.insert_document(document_type, auto_commit)

    def list_documents_pending_glossary(self) -> list[dict]:
        """Return documents that need glossary building.

        Wraps the DB query and filters out documents that have pending OCR
        when their document type requires OCR for translation. Document types
        where OCR is optional (e.g. EPUB) are allowed through regardless of
        image OCR status.
        """
        candidates = self.db.list_documents_pending_glossary()
        results = []
        for doc in candidates:
            if not is_ocr_required_for_type(doc["document_type"]):
                results.append(doc)
                continue
            # For OCR-required types, filter out those with pending OCR
            sources_needing_ocr = self.db.get_document_sources_needing_ocr(doc["document_id"])
            if not sources_needing_ocr:
                results.append(doc)

        return results

    def list_documents_pending_translation(self) -> list[dict]:
        """Return documents that need translation."""
        return self.db.list_documents_pending_translation()

    def list_documents_with_chunks(self) -> list[dict]:
        """Return documents that have chunks, with translation counts."""
        return self.db.list_documents_with_chunks()

    def list_documents_with_image_sources(self) -> list[dict]:
        """Return documents that have image sources (for OCR review)."""
        return self.db.list_documents_with_image_sources()

    def get_documents_with_status(self) -> list[dict]:
        """Return all documents with their processing status."""
        return self.db.get_documents_with_status()

    # =========================================================================
    # Document Source Methods
    # =========================================================================

    def insert_document_source(
        self,
        document_id: int,
        sequence_number: int,
        source_type: str,
        *,
        relative_path: str | None = None,
        text_content: str | None = None,
        binary_content: bytes | None = None,
        mime_type: str | None = None,
        ocr_json: str | None = None,
        is_ocr_completed: bool = False,
        is_text_added: bool = False,
        auto_commit: bool = True,
    ) -> int:
        """Insert a document source. Returns source_id."""
        return self.db.insert_document_source(
            document_id,
            sequence_number,
            source_type,
            relative_path=relative_path,
            text_content=text_content,
            binary_content=binary_content,
            mime_type=mime_type,
            ocr_json=ocr_json,
            is_ocr_completed=is_ocr_completed,
            is_text_added=is_text_added,
            auto_commit=auto_commit,
        )

    def get_document_sources(self, document_id: int) -> list[dict]:
        """Get all sources for a document, ordered by sequence_number."""
        return self.db.get_document_sources(document_id)

    def get_document_sources_without_binary(self, document_id: int) -> list[dict]:
        """Get source rows needed for text workflows without loading binary blobs."""
        return self.db.get_document_sources_without_binary(document_id)

    def get_document_sources_metadata(self, document_id: int) -> list[dict]:
        """Get source metadata (no binary_content/text_content) for a document."""
        return self.db.get_document_sources_metadata(document_id)

    def get_source_binary_content(self, source_id: int) -> bytes | None:
        """Get binary_content for a single source by ID."""
        return self.db.get_source_binary_content(source_id)

    def get_source_ocr_json(self, source_id: int) -> str | None:
        """Get ocr_json for a single source by ID."""
        return self.db.get_source_ocr_json(source_id)

    def source_exists_by_content(self, text_content: str) -> bool:
        """Check if a source with the same text_content already exists."""
        return self.db.source_exists_by_content(text_content)

    def source_exists_by_binary(self, binary_content: bytes) -> bool:
        """Check if a source with the same binary_content already exists."""
        return self.db.source_exists_by_binary(binary_content)

    def get_document_sources_needing_ocr(self, document_id: int) -> list[dict]:
        """Get sources where is_ocr_completed=0 and source_type='image'."""
        return self.db.get_document_sources_needing_ocr(document_id)

    # =========================================================================
    # Document Source Update Methods
    # =========================================================================

    def update_source_ocr(self, source_id: int, ocr_json: str, auto_commit: bool = True) -> None:
        """Update source's ocr_json field."""
        self.db.update_source_ocr(source_id, ocr_json, auto_commit)

    def update_source_ocr_completed(self, source_id: int, auto_commit: bool = True) -> None:
        """Mark source's is_ocr_completed=1."""
        self.db.update_source_ocr_completed(source_id, auto_commit)

    def update_source_text_added(self, source_id: int, auto_commit: bool = True) -> None:
        """Mark source's is_text_added=1."""
        self.db.update_source_text_added(source_id, auto_commit)

    def update_all_sources_text_added(self, document_id: int, auto_commit: bool = True) -> None:
        """Mark all sources for a document as is_text_added=1."""
        self.db.update_all_sources_text_added(document_id, auto_commit)

    def reset_source_ocr(self, source_id: int, auto_commit: bool = True) -> None:
        """Reset OCR flags for a source so it can be re-OCR'd.

        Clears ocr_json and resets is_ocr_completed and is_text_added to 0.
        Also deletes existing chunks for the document and resets is_text_added
        on all sources to ensure clean glossary rebuild.

        Used when user wants to re-run OCR on a specific page.
        """
        self.db.reset_source_ocr(source_id, auto_commit)

    def reset_document_stack(
        self,
        document_id: int,
    ) -> dict:
        """Stack-based document reset: book.db.

        Resets processing state for the target document and all documents
        added after it (by chunk_id ordering). Does NOT delete the documents
        themselves - they remain importable for re-processing.

        Ordering (critical):
          1. Capture cutoff chunk_id BEFORE any deletion
          2. Clean book.db: delete chunks >= cutoff, prune terms, reset is_text_added

        Args:
            document_id: The document to reset.

        Returns:
            Dict with cutoff, affected_document_ids, deleted_chunks, etc.
        """
        affected_doc_ids = self._stack_document_ids(document_id)
        if not affected_doc_ids:
            return {
                "document_exists": False,
                "cutoff": None,
                "affected_document_ids": [],
                "deleted_chunks": 0,
                "pruned_terms": 0,
                "deleted_terms": 0,
            }

        cutoff = self._min_chunk_id_for_documents(affected_doc_ids)

        if cutoff is not None:
            # Step 2: Clean book.db (chunks, terms, flags)
            result = self.db.reset_documents_from(cutoff)
        else:
            self.db.clear_source_language()
            result = {
                "affected_document_ids": affected_doc_ids,
                "deleted_chunks": 0,
                "pruned_terms": 0,
                "deleted_terms": 0,
            }

        result["document_exists"] = True
        result["cutoff"] = cutoff
        return result

    def delete_documents_stack(
        self,
        document_id: int,
    ) -> dict:
        """Stack-based document deletion: book.db + documents.

        Deletes the target document and all documents added after it,
        including their sources, chunks, and term data.

        Ordering (critical):
          1. Capture cutoff chunk_id BEFORE any deletion
          2. Clean book.db: delete chunks/terms, then delete sources and documents

        Args:
            document_id: The document to delete.

        Returns:
            Dict with cutoff, affected_document_ids, deleted_chunks,
            deleted_sources, deleted_documents, etc.
        """
        affected_doc_ids = self._stack_document_ids(document_id)

        if not affected_doc_ids:
            return {
                "document_exists": False,
                "cutoff": None,
                "affected_document_ids": [],
                "deleted_chunks": 0,
                "pruned_terms": 0,
                "deleted_terms": 0,
                "deleted_sources": 0,
                "deleted_documents": 0,
            }

        cutoff = self._min_chunk_id_for_documents(affected_doc_ids)

        # Step 2: Delete documents (handles chunk/term reset + source/doc deletion)
        result = self.db.delete_documents_from(document_id)
        result["document_exists"] = True
        result["cutoff"] = cutoff
        return result

    def _stack_document_ids(self, document_id: int) -> list[int]:
        rows = self.db.conn.execute(
            "SELECT document_id FROM document WHERE document_id >= ? ORDER BY document_id",
            (document_id,),
        ).fetchall()
        return [int(row["document_id"]) for row in rows]

    def _min_chunk_id_for_documents(self, document_ids: list[int]) -> int | None:
        if not document_ids:
            return None
        placeholders = ",".join("?" * len(document_ids))
        row = self.db.conn.execute(
            f"SELECT MIN(chunk_id) as min_id FROM chunks WHERE document_id IN ({placeholders})",
            document_ids,
        ).fetchone()
        if row is None or row["min_id"] is None:
            return None
        return int(row["min_id"])

    # =========================================================================
    # Image Reembedding Methods
    # =========================================================================

    def save_reembedded_image(self, document_id: int, element_idx: int, image_bytes: bytes, mime_type: str) -> None:
        """Persist a single reembedded image."""
        self.db.save_reembedded_image(document_id, element_idx, image_bytes, mime_type)

    def load_reembedded_images(self, document_id: int) -> dict[int, tuple[bytes, str]]:
        """Load all reembedded images for a document."""
        return self.db.load_reembedded_images(document_id)

    # =========================================================================
    # Transaction Methods
    # =========================================================================

    def begin(self) -> None:
        """Begin a transaction."""
        self.db.begin()

    def commit(self) -> None:
        """Commit the current transaction."""
        self.db.commit()

    def rollback(self) -> None:
        """Rollback the current transaction."""
        self.db.rollback()
