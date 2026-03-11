from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from context_aware_translation.core.models import KeyedContext, Term
from context_aware_translation.storage.schema.book_db import (
    ChunkRecord,
    SQLiteBookDB,
    TermRecord,
    TranslationChunkRecord,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass
class BatchUpdate:
    keyed_context: Sequence[Term]
    chunk_records: Sequence[ChunkRecord]


class StorageManager(Protocol):
    def apply_batch(self, update: BatchUpdate) -> None: ...

    def close(self) -> None: ...

    def chunk_exists_by_hash(self, chunk_hash: str) -> int | None: ...

    def get_keyed_context(self, key: str) -> KeyedContext | None: ...

    def list_keyed_context(self) -> Sequence[KeyedContext]: ...

    def get_next_chunk_id(self) -> int: ...

    def get_chunks_to_extract(self) -> Sequence[ChunkRecord]: ...

    def list_chunks(self, document_id: int | None = None) -> Sequence[ChunkRecord]: ...

    def list_chunks_grouped_by_document(self) -> dict[int, Sequence[ChunkRecord]]: ...

    def get_source_language(self) -> str | None: ...


class TermRepository:
    """
    Coordinates SQLite updates.
    """

    def __init__(
        self,
        db: SQLiteBookDB,
    ) -> None:
        self.keyed_context_db = db
        self._lock = threading.Lock()
        self._closed = False
        self._in_transaction = False

    def _record_to_term(self, record: TermRecord) -> Term:
        """Convert TermRecord to Term."""
        return Term(
            key=record.key,
            descriptions=record.descriptions,
            occurrence=record.occurrence,
            votes=record.votes,
            total_api_calls=record.total_api_calls,
            new_translation=record.new_translation,
            translated_name=record.translated_name,
            ignored=record.ignored,
        )

    def term_from_record(self, record: TermRecord) -> Term:
        """Convert TermRecord to Term for external callers."""
        return self._record_to_term(record)

    def _term_to_record(self, term: Term, existing_record: TermRecord | None = None) -> TermRecord:
        """Convert Term to TermRecord, preserving existing fields when incoming values are empty."""
        now = time.time()

        if existing_record is not None:
            preserve_counters = (
                term.votes == 0 and term.total_api_calls == 0 and not term.descriptions and not term.occurrence
            )
            return TermRecord(
                key=term.key,
                descriptions=term.descriptions if term.descriptions else existing_record.descriptions,
                occurrence=term.occurrence if term.occurrence else existing_record.occurrence,
                votes=existing_record.votes if preserve_counters else term.votes,
                total_api_calls=existing_record.total_api_calls if preserve_counters else term.total_api_calls,
                new_translation=term.new_translation
                if term.new_translation is not None
                else existing_record.new_translation,
                translated_name=term.translated_name
                if term.translated_name is not None
                else existing_record.translated_name,
                ignored=term.ignored,
                is_reviewed=existing_record.is_reviewed,
                created_at=existing_record.created_at,
                updated_at=now,
            )

        return TermRecord(
            key=term.key,
            descriptions=term.descriptions,
            occurrence=term.occurrence,
            votes=term.votes,
            total_api_calls=term.total_api_calls,
            new_translation=term.new_translation,
            translated_name=term.translated_name,
            ignored=term.ignored,
            is_reviewed=False,
            created_at=now,
            updated_at=now,
        )

    def apply_batch(self, update: BatchUpdate) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("StorageManager is closed and cannot accept new operations")

            owns_transaction = not self._in_transaction
            if owns_transaction:
                self.keyed_context_db.begin()
                self._in_transaction = True

            try:
                if update.chunk_records:
                    self.keyed_context_db.upsert_chunks(update.chunk_records, auto_commit=False)
                if update.keyed_context:
                    keyed_contexts = []
                    for keyed_context in update.keyed_context:
                        existing = self.keyed_context_db.get_term(keyed_context.key)
                        keyed_contexts.append(self._term_to_record(keyed_context, existing))
                    self.keyed_context_db.upsert_terms(keyed_contexts, auto_commit=False)
                if owns_transaction:
                    self.keyed_context_db.commit()
                    self._in_transaction = False
            except Exception:
                if owns_transaction:
                    self.keyed_context_db.rollback()
                    self._in_transaction = False
                raise

    def close(self) -> None:
        """
        Mark storage manager as closed.

        This method blocks until all in-progress apply_batch() operations complete,
        then prevents new operations from starting. Should only be called during
        application shutdown.

        Note: DB lifecycle is now owned by Translator - do NOT close DB here.
        """
        with self._lock:
            self._closed = True

    def chunk_exists_by_hash(self, chunk_hash: str) -> int | None:
        """
        Check if a chunk exists by hash.

        Args:
            chunk_hash: The hash of the chunk to check

        Returns:
            The chunk_id if found, None otherwise
        """
        return self.keyed_context_db.chunk_exists_by_hash(chunk_hash)

    def get_keyed_context(self, key: str) -> KeyedContext | None:
        """
        Get a keyed context by its key.

        Args:
            key: The key of the context

        Returns:
            The KeyedContext if found, None otherwise
        """
        record = self.keyed_context_db.get_term(key)
        if record is None:
            return None
        return self._record_to_term(record)

    def list_keyed_context(self) -> list[Term]:
        """
        List all keyed context in the database.

        Returns:
            List of all Term objects (which implement KeyedContext)
        """
        records = self.keyed_context_db.list_terms()
        return [self._record_to_term(record) for record in records]

    def get_terms_pending_review(self) -> list[TermRecord]:
        return self.keyed_context_db.get_terms_pending_review()

    def upsert_terms(self, terms: list[TermRecord]) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("StorageManager is closed")
            self.keyed_context_db.upsert_terms(terms)

    def get_terms_to_translate(self) -> list[Term]:
        """
        Get all terms where translated_name is None.

        Returns:
            List of Term objects that need translation
        """
        records = self.keyed_context_db.get_terms_to_translate()
        return [self._record_to_term(record) for record in records]

    def get_next_chunk_id(self) -> int:
        """
        Get the next available chunk_id.

        Returns:
            The next chunk_id to use (max existing chunk_id + 1, or 0 if no chunks exist)
        """
        return self.keyed_context_db.get_max_chunk_id() + 1

    def get_chunks_to_extract(self) -> list[TranslationChunkRecord]:
        """
        Get all chunks that need to be extracted.

        Returns:
            List of ChunkRecord objects where is_extracted = False
        """
        return self.keyed_context_db.get_chunks_to_extract()

    def list_chunks(
        self, document_id: int | None = None, document_ids: list[int] | None = None
    ) -> list[TranslationChunkRecord]:
        """
        List all chunk records in the database, optionally filtered by document_id(s).

        Args:
            document_id: If provided, only return chunks for this document.
            document_ids: If provided, only return chunks for these documents.
                         If both None, return all chunks.

        Returns:
            List of all ChunkRecord objects
        """
        return self.keyed_context_db.list_chunks(document_id=document_id, document_ids=document_ids)

    def list_chunks_grouped_by_document(self) -> dict[int, list[TranslationChunkRecord]]:
        """
        List all chunks grouped by document_id for batch export.

        Returns:
            Dictionary mapping document_id to list of chunks for that document
        """
        return self.keyed_context_db.list_chunks_grouped_by_document()

    def get_chunks_to_map_occurrence(self) -> list[TranslationChunkRecord]:
        """
        Get all chunks that need occurrence mapping.

        Returns:
            List of ChunkRecord objects where is_occurrence_mapped = False
        """
        return self.keyed_context_db.get_chunks_to_map_occurrence()

    def get_chunks_to_translate(
        self, document_ids: list[int] | None = None, force: bool = False
    ) -> list[TranslationChunkRecord]:
        """
        Get chunks that need translation.

        Args:
            document_ids: Specific document IDs to filter, or None for all
            force: If True, return all chunks including already translated

        Returns:
            List of TranslationChunkRecord objects
        """
        return self.keyed_context_db.get_chunks_to_translate(document_ids, force=force)

    def set_source_language(self, source_language: str) -> None:
        """Set the source language in the meta table."""
        self.keyed_context_db.set_source_language(source_language)

    def get_source_language(self) -> str | None:
        """Get the source language from the meta table."""
        return self.keyed_context_db.get_source_language()

    def get_last_noise_filtered_at(self) -> float | None:
        """Get the last_noise_filtered_at checkpoint from the meta table."""
        return self.keyed_context_db.get_last_noise_filtered_at()

    def set_last_noise_filtered_at(self, timestamp: float) -> None:
        """Set the last_noise_filtered_at checkpoint in the meta table."""
        self.keyed_context_db.set_last_noise_filtered_at(timestamp)

    def list_term_records(self) -> list[TermRecord]:
        return self.keyed_context_db.list_terms()

    def update_terms_bulk(
        self,
        term_keys: list[str],
        ignored: bool | None = None,
        is_reviewed: bool | None = None,
        translated_name: str | None = None,
    ) -> int:
        """Bulk update multiple terms."""
        with self._lock:
            if self._closed:
                raise RuntimeError("StorageManager is closed")
            return self.keyed_context_db.update_terms_bulk(
                term_keys, ignored=ignored, is_reviewed=is_reviewed, translated_name=translated_name
            )

    def delete_terms(self, term_keys: list[str]) -> int:
        """Delete multiple terms by key."""
        with self._lock:
            if self._closed:
                raise RuntimeError("StorageManager is closed")
            return self.keyed_context_db.delete_terms(term_keys)

    def get_term_count(self, include_ignored: bool = True) -> int:
        """Get total term count."""
        return self.keyed_context_db.get_term_count(include_ignored)

    def list_terms_filtered(
        self,
        limit: int | None = None,
        offset: int = 0,
        sort_by: str = "key",
        sort_desc: bool = False,
        filter_ignored: bool | None = None,
        filter_reviewed: bool | None = None,
        filter_translated: bool | None = None,
    ) -> list[TermRecord]:
        """List terms with pagination and filtering."""
        return self.keyed_context_db.list_terms(
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_desc=sort_desc,
            filter_ignored=filter_ignored,
            filter_reviewed=filter_reviewed,
            filter_translated=filter_translated,
        )

    def search_terms(self, pattern: str, limit: int = 100) -> list[TermRecord]:
        """Search terms by pattern."""
        return self.keyed_context_db.search_terms(pattern, limit)

    def get_term_stats(self) -> dict[str, int]:
        """Get term statistics."""
        return self.keyed_context_db.get_term_stats()

    def get_chunk_stats(self) -> dict[str, Any]:
        """Get chunk statistics."""
        return self.keyed_context_db.get_chunk_stats()
