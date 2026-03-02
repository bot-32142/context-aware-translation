from __future__ import annotations

import contextlib
import json
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class TermRecord:
    key: str
    descriptions: dict
    occurrence: dict
    votes: int
    total_api_calls: int
    new_translation: str | None = None
    translated_name: str | None = None
    ignored: bool = False
    is_reviewed: bool = False
    created_at: float | None = None
    updated_at: float | None = None


@dataclass
class ChunkRecord:
    """Base chunk record for general storage operations."""

    chunk_id: int
    hash: str
    text: str
    document_id: int | None = None
    created_at: float | None = None
    is_extracted: bool = False
    is_summarized: bool = False


@dataclass
class TranslationChunkRecord(ChunkRecord):
    """Chunk record with translation-specific fields."""

    is_occurrence_mapped: bool = False
    is_translated: bool = False
    translation: str | None = None
    normalized_text: str = ""


CREATE_META = """
CREATE TABLE IF NOT EXISTS meta (
    schema_version INTEGER NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    source_language TEXT,
    last_noise_filtered_at REAL
);
"""

CREATE_TERMS = """
CREATE TABLE IF NOT EXISTS terms (
    key TEXT PRIMARY KEY,
    descriptions_json TEXT NOT NULL,
    occurrence_json TEXT NOT NULL,
    votes INTEGER NOT NULL,
    total_api_calls INTEGER NOT NULL,
    new_translation TEXT,
    translated_name TEXT,
    ignored INTEGER NOT NULL DEFAULT 0,
    is_reviewed INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""

CREATE_CHUNKS = """
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id INTEGER PRIMARY KEY,
    hash TEXT UNIQUE NOT NULL,
    text TEXT,
    normalized_text TEXT,
    document_id INTEGER REFERENCES document(document_id),
    created_at REAL NOT NULL,
    is_extracted INTEGER NOT NULL DEFAULT 0,
    is_summarized INTEGER NOT NULL DEFAULT 0,
    is_occurrence_mapped INTEGER NOT NULL DEFAULT 0,
    is_translated INTEGER NOT NULL DEFAULT 0,
    translation TEXT
);
"""

CREATE_DOCUMENT = """
CREATE TABLE IF NOT EXISTS document (
    document_id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_type TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""

CREATE_DOCUMENT_SOURCES = """
CREATE TABLE IF NOT EXISTS document_sources (
    source_id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES document(document_id) ON DELETE CASCADE,
    sequence_number INTEGER NOT NULL,
    relative_path TEXT,
    source_type TEXT NOT NULL,
    text_content TEXT,
    binary_content BLOB,
    mime_type TEXT,
    ocr_json TEXT,
    is_ocr_completed INTEGER NOT NULL DEFAULT 0,
    is_text_added INTEGER NOT NULL DEFAULT 0,
    reembedded_images_json TEXT
);
"""


class SQLiteBookDB:
    """
    SQLite-backed term store that owns term, chunk, and link tables.
    """

    def __init__(self, sqlite_path: Path) -> None:
        self.db_path = Path(sqlite_path)
        self.schema_version = 2
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._configure_connection()
        self._init_schema()

    def _configure_connection(self) -> None:
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.execute("PRAGMA journal_mode = WAL;")
        self.conn.execute("PRAGMA synchronous = FULL;")

    def _migrate_schema(self, from_version: int) -> None:
        cur = self.conn.cursor()
        if from_version < 2:
            cur.execute("ALTER TABLE chunks ADD COLUMN normalized_text TEXT")
            from context_aware_translation.utils.cjk_normalize import normalize_for_matching

            rows = cur.execute("SELECT chunk_id, text FROM chunks WHERE text IS NOT NULL").fetchall()
            for row in rows:
                cur.execute(
                    "UPDATE chunks SET normalized_text = ? WHERE chunk_id = ?",
                    (normalize_for_matching(row["text"]), row["chunk_id"]),
                )
        cur.execute(
            "UPDATE meta SET schema_version = ?, updated_at = ?",
            (self.schema_version, time.time()),
        )
        self.conn.commit()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute(CREATE_META)
        cur.execute(CREATE_TERMS)
        cur.execute(CREATE_CHUNKS)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id);")
        cur.execute(CREATE_DOCUMENT)
        cur.execute(CREATE_DOCUMENT_SOURCES)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_document_sources_document_id ON document_sources(document_id);")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_document_sources_metadata "
            "ON document_sources("
            "document_id, sequence_number, source_id, "
            "source_type, mime_type, is_ocr_completed, is_text_added, "
            "relative_path);"
        )
        self.conn.commit()

        meta = cur.execute("SELECT schema_version FROM meta").fetchone()
        now = time.time()
        if meta is None:
            cur.execute(
                "INSERT INTO meta(schema_version, created_at, updated_at) VALUES (?, ?, ?)",
                (self.schema_version, now, now),
            )
            self.conn.commit()
        else:
            version = meta["schema_version"]
            if version < self.schema_version:
                self._migrate_schema(version)
            elif version > self.schema_version:
                raise RuntimeError(f"Database schema version {version} is newer than supported {self.schema_version}")

    def refresh(self) -> None:
        """End any implicit read transaction so the next query sees fresh data.

        Python's sqlite3 with default isolation_level="" holds implicit
        transactions open, which freezes the WAL snapshot.  Rolling back
        releases that snapshot so a subsequent SELECT picks up commits
        from other connections.
        """
        self.conn.rollback()

    def begin(self) -> None:
        self.conn.execute("BEGIN;")

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def upsert_terms(self, terms: Iterable[TermRecord], auto_commit: bool = True) -> None:
        now = time.time()
        cur = self.conn.cursor()
        for term in terms:
            descriptions_json = json.dumps(term.descriptions or {}, ensure_ascii=False)
            occurrence_json = json.dumps(term.occurrence or {}, ensure_ascii=False)
            cur.execute(
                """
                INSERT INTO terms(
                    key, descriptions_json, occurrence_json,
                    votes, total_api_calls, new_translation, translated_name,
                    ignored, is_reviewed, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    descriptions_json=excluded.descriptions_json,
                    occurrence_json=excluded.occurrence_json,
                    votes=excluded.votes,
                    total_api_calls=excluded.total_api_calls,
                    new_translation=excluded.new_translation,
                    translated_name=excluded.translated_name,
                    ignored=excluded.ignored,
                    is_reviewed=excluded.is_reviewed,
                    updated_at=excluded.updated_at
                """,
                (
                    term.key,
                    descriptions_json,
                    occurrence_json,
                    term.votes,
                    term.total_api_calls,
                    term.new_translation,
                    term.translated_name,
                    1 if term.ignored else 0,
                    1 if term.is_reviewed else 0,
                    term.created_at or now,
                    term.updated_at or now,
                ),
            )
        if auto_commit:
            self.conn.commit()

    def get_term(self, key: str) -> TermRecord | None:
        row = self.conn.execute("SELECT * FROM terms WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        return self._row_to_term(row)

    def list_terms(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
        sort_by: str = "key",
        sort_desc: bool = False,
        filter_ignored: bool | None = None,
        filter_reviewed: bool | None = None,
        filter_translated: bool | None = None,
    ) -> list[TermRecord]:
        """List terms with pagination, sorting, and filtering.

        Args:
            limit: Maximum number of terms to return (None for all)
            offset: Number of terms to skip
            sort_by: Field to sort by. Valid values: key, votes, translated_name,
                updated_at, created_at, ignored, is_reviewed, occurrence_count.
                Invalid values
                silently default to "key".
            sort_desc: Sort in descending order
            filter_ignored: None=all, True=only ignored, False=only kept
            filter_reviewed: None=all, True=only reviewed, False=only not reviewed
            filter_translated: True=has translation, False=no translation, None=all

        Returns:
            List of TermRecord instances
        """
        # Validate sort_by to prevent SQL injection
        sort_expressions = {
            "key": "key",
            "votes": "votes",
            "translated_name": "translated_name",
            "updated_at": "updated_at",
            "created_at": "created_at",
            "ignored": "ignored",
            "is_reviewed": "is_reviewed",
            # Number of chunk keys where this term occurs.
            "occurrence_count": "(SELECT COUNT(*) FROM json_each(occurrence_json))",
        }
        if sort_by not in sort_expressions:
            sort_by = "key"
        order_expr = sort_expressions[sort_by]

        conditions = []
        params: list[Any] = []

        if filter_ignored is not None:
            conditions.append("ignored = ?")
            params.append(1 if filter_ignored else 0)
        if filter_reviewed is not None:
            conditions.append("is_reviewed = ?")
            params.append(1 if filter_reviewed else 0)
        if filter_translated is True:
            conditions.append("translated_name IS NOT NULL AND translated_name != ''")
        elif filter_translated is False:
            conditions.append("(translated_name IS NULL OR translated_name = '')")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        order_dir = "DESC" if sort_desc else "ASC"
        limit_clause = f"LIMIT {limit} OFFSET {offset}" if limit is not None else ""

        sql = f"""
            SELECT * FROM terms
            {where_clause}
            ORDER BY {order_expr} {order_dir}, key ASC
            {limit_clause}
        """
        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_term(r) for r in rows]

    def search_terms(self, pattern: str, limit: int = 100) -> list[TermRecord]:
        """Search terms by source key or translated name pattern.

        Args:
            pattern: Search pattern (will match anywhere in key or translated name)
            limit: Maximum number of results

        Returns:
            List of matching TermRecord instances
        """
        sql = """
            SELECT * FROM terms
            WHERE key LIKE ? OR translated_name LIKE ?
            ORDER BY key
            LIMIT ?
        """
        like_pattern = f"%{pattern}%"
        rows = self.conn.execute(sql, (like_pattern, like_pattern, limit)).fetchall()
        return [self._row_to_term(r) for r in rows]

    def get_terms_pending_review(self) -> list[TermRecord]:
        """Get all terms that have not been reviewed (is_reviewed = 0)."""
        rows = self.conn.execute("SELECT * FROM terms WHERE is_reviewed = 0").fetchall()
        return [self._row_to_term(r) for r in rows]

    def get_terms_to_translate(self) -> list[TermRecord]:
        """Get all terms where translated_name is None."""
        rows = self.conn.execute("SELECT * FROM terms WHERE translated_name IS NULL").fetchall()
        return [self._row_to_term(r) for r in rows]

    def update_terms_bulk(
        self,
        keys: list[str],
        *,
        ignored: bool | None = None,
        is_reviewed: bool | None = None,
        translated_name: str | None = None,
    ) -> int:
        """
        Update multiple terms in a single transaction.
        Returns count of updated terms.
        Only updates fields that are not None.
        """
        if not keys:
            return 0

        updates = []
        params: list[Any] = []
        if ignored is not None:
            updates.append("ignored = ?")
            params.append(1 if ignored else 0)
        if is_reviewed is not None:
            updates.append("is_reviewed = ?")
            params.append(1 if is_reviewed else 0)
        if translated_name is not None:
            updates.append("translated_name = ?")
            params.append(translated_name)

        if not updates:
            return 0

        updates.append("updated_at = ?")
        params.append(time.time())

        placeholders = ",".join("?" * len(keys))
        sql = f"""
            UPDATE terms
            SET {", ".join(updates)}
            WHERE key IN ({placeholders})
        """
        cursor = self.conn.execute(sql, params + keys)
        self.conn.commit()
        return cursor.rowcount

    def delete_terms(self, keys: list[str]) -> int:
        """Delete terms by keys. Returns count of deleted terms."""
        if not keys:
            return 0
        placeholders = ",".join("?" * len(keys))
        cursor = self.conn.execute(
            f"DELETE FROM terms WHERE key IN ({placeholders})",
            keys,
        )
        self.conn.commit()
        return cursor.rowcount

    def get_term_count(self, include_ignored: bool = True) -> int:
        """Get total term count without loading all terms."""
        if include_ignored:
            row = self.conn.execute("SELECT COUNT(*) FROM terms").fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) FROM terms WHERE ignored = 0").fetchone()
        return row[0] if row else 0

    def get_term_stats(self) -> dict[str, int]:
        """Get term statistics without loading all terms.

        Returns:
            Dictionary with keys: total, reviewed, ignored, translated, pending,
            unignored, unignored_reviewed
        """
        row = self.conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN is_reviewed = 1 THEN 1 ELSE 0 END) as reviewed,
                SUM(CASE WHEN ignored = 1 THEN 1 ELSE 0 END) as ignored,
                SUM(CASE WHEN translated_name IS NOT NULL AND translated_name != '' THEN 1 ELSE 0 END) as translated,
                SUM(CASE WHEN is_reviewed = 0 AND ignored = 0 THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN ignored = 0 THEN 1 ELSE 0 END) as unignored,
                SUM(CASE WHEN ignored = 0 AND is_reviewed = 1 THEN 1 ELSE 0 END) as unignored_reviewed
            FROM terms
        """).fetchone()

        if row is None:
            return {
                "total": 0,
                "reviewed": 0,
                "ignored": 0,
                "translated": 0,
                "pending": 0,
                "unignored": 0,
                "unignored_reviewed": 0,
            }

        return {
            "total": row[0] or 0,
            "reviewed": row[1] or 0,
            "ignored": row[2] or 0,
            "translated": row[3] or 0,
            "pending": row[4] or 0,
            "unignored": row[5] or 0,
            "unignored_reviewed": row[6] or 0,
        }

    def get_chunk_stats(self) -> dict[str, int | float]:
        """Get chunk/translation statistics.

        Returns:
            Dictionary with keys: total, translated, extracted, progress_percent
        """
        row = self.conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN is_translated = 1 THEN 1 ELSE 0 END) as translated,
                SUM(CASE WHEN is_extracted = 1 THEN 1 ELSE 0 END) as extracted
            FROM chunks
        """).fetchone()

        if row is None:
            return {"total": 0, "translated": 0, "extracted": 0, "progress_percent": 0.0}

        total = row[0] or 0
        translated = row[1] or 0
        extracted = row[2] or 0
        progress_percent = round(translated / total * 100, 1) if total > 0 else 0.0

        return {
            "total": total,
            "translated": translated,
            "extracted": extracted,
            "progress_percent": progress_percent,
        }

    def get_translation(self, name: str) -> str | None:
        """Get translation for a term by its key."""
        row = self.conn.execute("SELECT translated_name FROM terms WHERE key = ?", (name,)).fetchone()
        if row:
            translated_name: str | None = row["translated_name"]
            return translated_name
        return None

    def upsert_chunks(self, chunks: Iterable[ChunkRecord], auto_commit: bool = True) -> list[int]:
        """
        Insert chunk metadata; skip duplicates by hash. Returns list of chunk_ids
        that were newly inserted or already present.

        Thread-safety: When called through StorageManager.apply_batch(), the
        StorageManager's lock ensures thread-safety. If called directly, ensure proper
        transaction isolation or external synchronization.
        """
        cur = self.conn.cursor()
        seen_hashes: set[str] = set()
        inserted: list[int] = []

        for chunk in chunks:
            if chunk.hash in seen_hashes:
                continue
            seen_hashes.add(chunk.hash)

            existing = cur.execute("SELECT chunk_id FROM chunks WHERE hash = ?", (chunk.hash,)).fetchone()

            if existing:
                chunk_id = existing["chunk_id"]
                is_translated = getattr(chunk, "is_translated", False)
                is_occurrence_mapped = getattr(chunk, "is_occurrence_mapped", False)
                translation = getattr(chunk, "translation", None)
                cur.execute(
                    """
                    UPDATE chunks
                    SET is_extracted = ?, is_summarized = ?, is_occurrence_mapped = ?, is_translated = ?, translation = ?
                    WHERE chunk_id = ?
                    """,
                    (
                        1 if chunk.is_extracted else 0,
                        1 if chunk.is_summarized else 0,
                        1 if is_occurrence_mapped else 0,
                        1 if is_translated else 0,
                        translation,
                        chunk_id,
                    ),
                )
                inserted.append(chunk_id)
            else:
                now = chunk.created_at or time.time()
                is_translated = getattr(chunk, "is_translated", False)
                is_occurrence_mapped = getattr(chunk, "is_occurrence_mapped", False)
                translation = getattr(chunk, "translation", None)
                document_id = getattr(chunk, "document_id", None)
                normalized_text = getattr(chunk, "normalized_text", None)
                if normalized_text is None and chunk.text:
                    from context_aware_translation.utils.cjk_normalize import normalize_for_matching

                    normalized_text = normalize_for_matching(chunk.text)
                cur.execute(
                    """
                    INSERT INTO chunks(chunk_id, hash, text, normalized_text, document_id, created_at, is_extracted, is_summarized, is_occurrence_mapped, is_translated, translation)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.chunk_id,
                        chunk.hash,
                        chunk.text,
                        normalized_text,
                        document_id,
                        now,
                        1 if chunk.is_extracted else 0,
                        1 if chunk.is_summarized else 0,
                        1 if is_occurrence_mapped else 0,
                        1 if is_translated else 0,
                        translation,
                    ),
                )
                inserted.append(chunk.chunk_id)

        if auto_commit:
            self.conn.commit()
        return inserted

    def chunk_exists_by_hash(self, chunk_hash: str) -> int | None:
        """
        Check if a chunk exists by hash.

        Args:
            chunk_hash: The hash of the chunk to check

        Returns:
            The chunk_id if found, None otherwise
        """
        row = self.conn.execute("SELECT chunk_id FROM chunks WHERE hash = ?", (chunk_hash,)).fetchone()
        if row:
            chunk_id: int = row["chunk_id"]
            return chunk_id
        return None

    def get_max_chunk_id(self) -> int:
        """
        Get the maximum chunk_id from the chunks table.

        Returns:
            The maximum chunk_id, or -1 if no chunks exist
        """
        row = self.conn.execute("SELECT MAX(chunk_id) as max_id FROM chunks").fetchone()
        if row and row["max_id"] is not None:
            max_id: int = row["max_id"]
            return max_id
        return -1

    def get_chunk_count(self, document_id: int) -> int:
        """
        Get the count of chunks for a specific document.

        Args:
            document_id: The document ID to count chunks for

        Returns:
            Number of chunks for the document
        """
        row = self.conn.execute(
            "SELECT COUNT(*) as count FROM chunks WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        if row:
            count: int = row["count"]
            return count
        return 0

    def get_chunk_by_id(self, chunk_id: int) -> TranslationChunkRecord | None:
        """Get a single chunk by its chunk_id.

        Returns None if no chunk with that ID exists.
        """
        row = self.conn.execute("SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_translation_chunk(row)

    def get_chunks_to_extract(self) -> list[TranslationChunkRecord]:
        """Get all chunks where is_extracted = 0."""
        rows = self.conn.execute("SELECT * FROM chunks WHERE is_extracted = 0").fetchall()
        return [self._row_to_translation_chunk(r) for r in rows]

    def get_chunks_to_map_occurrence(self) -> list[TranslationChunkRecord]:
        """Get all chunks where is_occurrence_mapped = 0."""
        rows = self.conn.execute("SELECT * FROM chunks WHERE is_occurrence_mapped = 0").fetchall()
        return [self._row_to_translation_chunk(r) for r in rows]

    def get_chunks_to_translate(
        self, document_ids: list[int] | None = None, force: bool = False
    ) -> list[TranslationChunkRecord]:
        """Get chunks to translate, optionally filtered by document_ids.

        Args:
            document_ids: Specific document IDs to filter, or None for all.
            force: If True, return all chunks (including already translated).
                If False (default), only return untranslated chunks.
        """
        if document_ids is not None:
            if not document_ids:
                return []
            placeholders = ",".join("?" * len(document_ids))
            translated_filter = "" if force else " AND is_translated = 0"
            rows = self.conn.execute(
                f"SELECT * FROM chunks WHERE document_id IN ({placeholders}){translated_filter}",
                document_ids,
            ).fetchall()
        else:
            where = "WHERE is_translated = 0" if not force else ""
            rows = self.conn.execute(f"SELECT * FROM chunks {where}").fetchall()
        return [self._row_to_translation_chunk(r) for r in rows]

    def list_chunks(
        self, document_id: int | None = None, document_ids: list[int] | None = None
    ) -> list[TranslationChunkRecord]:
        """List all chunk records, optionally filtered by document_id(s)."""
        if document_ids is not None:
            if not document_ids:
                return []
            placeholders = ",".join("?" * len(document_ids))
            rows = self.conn.execute(
                f"SELECT * FROM chunks WHERE document_id IN ({placeholders})", document_ids
            ).fetchall()
        elif document_id is not None:
            rows = self.conn.execute("SELECT * FROM chunks WHERE document_id = ?", (document_id,)).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM chunks").fetchall()
        return [self._row_to_translation_chunk(r) for r in rows]

    def list_chunks_grouped_by_document(self) -> dict[int, list[TranslationChunkRecord]]:
        """List all chunks grouped by document_id for batch export."""
        rows = self.conn.execute("SELECT * FROM chunks ORDER BY document_id, chunk_id").fetchall()
        result: dict[int, list[TranslationChunkRecord]] = {}
        for row in rows:
            chunk = self._row_to_translation_chunk(row)
            doc_id = chunk.document_id
            if doc_id is not None:
                if doc_id not in result:
                    result[doc_id] = []
                result[doc_id].append(chunk)
        return result

    def set_source_language(self, source_language: str) -> None:
        """Set the source language in the meta table."""
        cur = self.conn.cursor()
        cur.execute("UPDATE meta SET source_language = ?", (source_language,))
        self.conn.commit()

    def get_source_language(self) -> str | None:
        """Get the source language from the meta table."""
        row = self.conn.execute("SELECT source_language FROM meta").fetchone()
        if row is None:
            return None
        # row["source_language"] can be None or empty string, both are valid
        source_lang = row["source_language"]
        return source_lang if source_lang is not None else None

    def get_last_noise_filtered_at(self) -> float | None:
        """Get the last_noise_filtered_at checkpoint from the meta table."""
        row = self.conn.execute("SELECT last_noise_filtered_at FROM meta").fetchone()
        if row is None:
            return None
        last_noise_filtered_at: float | None = row["last_noise_filtered_at"]
        return last_noise_filtered_at

    def set_last_noise_filtered_at(self, timestamp: float) -> None:
        """Set the last_noise_filtered_at checkpoint in the meta table."""
        cur = self.conn.cursor()
        cur.execute("UPDATE meta SET last_noise_filtered_at = ?", (timestamp,))
        self.conn.commit()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        self.conn.close()

    def _row_to_term(self, row: sqlite3.Row) -> TermRecord:
        # sqlite3.Row doesn't support .get(), use dict() conversion or check keys
        row_dict = dict(row)
        return TermRecord(
            key=row["key"],
            descriptions=json.loads(row["descriptions_json"]),
            occurrence=json.loads(row["occurrence_json"]),
            votes=row["votes"],
            total_api_calls=row["total_api_calls"],
            new_translation=row_dict.get("new_translation"),
            translated_name=row_dict.get("translated_name"),
            ignored=bool(row["ignored"]),
            is_reviewed=bool(row_dict.get("is_reviewed", 0)),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_translation_chunk(self, row: sqlite3.Row) -> TranslationChunkRecord:
        row_dict = dict(row)
        return TranslationChunkRecord(
            chunk_id=row["chunk_id"],
            hash=row["hash"],
            text=row["text"],
            document_id=row_dict.get("document_id"),
            created_at=row_dict.get("created_at"),
            is_extracted=bool(row["is_extracted"]),
            is_summarized=bool(row["is_summarized"]),
            is_occurrence_mapped=bool(row_dict.get("is_occurrence_mapped", 0)),
            is_translated=bool(row_dict.get("is_translated", 0)),
            translation=row_dict.get("translation"),
            normalized_text=row_dict.get("normalized_text") or "",
        )

    # Document table CRUD methods

    def get_document_row(self) -> dict | None:
        """Get THE document (at most 1 row). Returns dict or None."""
        row = self.conn.execute("SELECT * FROM document").fetchone()
        if row is None:
            return None
        return dict(row)

    def list_documents(self) -> list[dict]:
        """Return all documents from database."""
        rows = self.conn.execute("SELECT * FROM document").fetchall()
        return [dict(row) for row in rows]

    def get_document_by_id(self, document_id: int) -> dict | None:
        """Get specific document by ID."""
        row = self.conn.execute("SELECT * FROM document WHERE document_id = ?", (document_id,)).fetchone()
        return dict(row) if row else None

    def list_documents_pending_glossary(self) -> list[dict]:
        """Return documents that have pending glossary work.

        A document has pending glossary work if ANY of:
        - It has sources with is_text_added=0 that are ready (OCR complete or not image)
          This covers fresh imports and re-OCR scenarios.
        - It has chunks with is_extracted = 0 (terms not yet extracted)
        - It has chunks with is_occurrence_mapped = 0 (occurrence mapping not done)

        Note: This query does NOT filter by OCR completion status.
        The application layer (DocumentRepository) handles OCR-readiness
        filtering based on document type.

        This handles:
        - Fresh imports (sources with is_text_added=0)
        - Re-OCR scenarios (sources reset to is_text_added=0)
        - App crash during extraction (chunks with is_extracted=0)
        - App crash during mapping (chunks with is_occurrence_mapped=0)
        """
        rows = self.conn.execute(
            """
            SELECT d.*
            FROM document d
            WHERE (
                EXISTS (
                    SELECT 1 FROM document_sources ds
                    WHERE ds.document_id = d.document_id
                    AND ds.is_text_added = 0
                    AND (ds.source_type != 'image' OR ds.is_ocr_completed = 1)
                )
                OR EXISTS (
                    SELECT 1 FROM chunks c
                    WHERE c.document_id = d.document_id
                    AND (c.is_extracted = 0 OR c.is_occurrence_mapped = 0)
                )
            )
            """,
        ).fetchall()
        return [dict(row) for row in rows]

    def list_documents_pending_translation(self) -> list[dict]:
        """Return documents that need translation.

        A document needs translation if:
        - It has chunks with is_translated = 0 (chunks not yet translated)

        Note: If chunks exist, build_glossary was already run, which checked OCR completion.
        """
        rows = self.conn.execute(
            """
            SELECT DISTINCT d.*
            FROM document d
            INNER JOIN chunks c ON d.document_id = c.document_id
            WHERE c.is_translated = 0
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def list_documents_with_chunks(self) -> list[dict]:
        """Return documents that have chunks, with translation counts."""
        rows = self.conn.execute(
            """
            SELECT d.*,
                COUNT(c.chunk_id) as total_chunks,
                SUM(CASE WHEN c.is_translated = 1 THEN 1 ELSE 0 END) as chunks_translated
            FROM document d
            INNER JOIN chunks c ON d.document_id = c.document_id
            GROUP BY d.document_id
            ORDER BY d.document_id
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def get_documents_with_status(self) -> list[dict]:
        """Return all documents with their processing status.

        Returns list of dicts with:
        - document_id, document_type, created_at
        - total_sources: Total number of sources
        - ocr_completed: Number of sources with OCR completed
        - ocr_pending: Number of sources needing OCR (image sources with is_ocr_completed=0)
        - total_chunks: Total number of chunks
        - chunks_extracted: Number of chunks with is_extracted=1
        - chunks_mapped: Number of chunks with is_occurrence_mapped=1
        - chunks_translated: Number of chunks with is_translated=1
        """
        rows = self.conn.execute(
            """
            SELECT
                d.document_id,
                d.document_type,
                d.created_at,
                COALESCE(src.total_sources, 0) as total_sources,
                COALESCE(src.ocr_completed, 0) as ocr_completed,
                COALESCE(src.ocr_pending, 0) as ocr_pending,
                COALESCE(ch.total_chunks, 0) as total_chunks,
                COALESCE(ch.chunks_extracted, 0) as chunks_extracted,
                COALESCE(ch.chunks_mapped, 0) as chunks_mapped,
                COALESCE(ch.chunks_translated, 0) as chunks_translated
            FROM document d
            LEFT JOIN (
                SELECT
                    document_id,
                    COUNT(*) as total_sources,
                    SUM(CASE WHEN is_ocr_completed = 1 THEN 1 ELSE 0 END) as ocr_completed,
                    SUM(CASE WHEN source_type = 'image' AND is_ocr_completed = 0 THEN 1 ELSE 0 END) as ocr_pending
                FROM document_sources
                GROUP BY document_id
            ) src ON d.document_id = src.document_id
            LEFT JOIN (
                SELECT
                    document_id,
                    COUNT(*) as total_chunks,
                    SUM(CASE WHEN is_extracted = 1 THEN 1 ELSE 0 END) as chunks_extracted,
                    SUM(CASE WHEN is_occurrence_mapped = 1 THEN 1 ELSE 0 END) as chunks_mapped,
                    SUM(CASE WHEN is_translated = 1 THEN 1 ELSE 0 END) as chunks_translated
                FROM chunks
                GROUP BY document_id
            ) ch ON d.document_id = ch.document_id
            ORDER BY d.document_id
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def insert_document(self, document_type: str, auto_commit: bool = True) -> int:
        """Insert a new document. Returns document_id."""
        now = time.time()
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO document(document_type, created_at) VALUES (?, ?)",
            (document_type, now),
        )
        document_id: int = cur.lastrowid  # type: ignore[assignment]
        if auto_commit:
            self.conn.commit()
        return document_id

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
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO document_sources(
                document_id, sequence_number, relative_path, source_type,
                text_content, binary_content, mime_type, ocr_json,
                is_ocr_completed, is_text_added
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                sequence_number,
                relative_path,
                source_type,
                text_content,
                binary_content,
                mime_type,
                ocr_json,
                1 if is_ocr_completed else 0,
                1 if is_text_added else 0,
            ),
        )
        source_id: int = cur.lastrowid  # type: ignore[assignment]
        if auto_commit:
            self.conn.commit()
        return source_id

    def get_document_sources(self, document_id: int) -> list[dict]:
        """Get all sources for a document, ordered by sequence_number."""
        rows = self.conn.execute(
            "SELECT * FROM document_sources WHERE document_id = ? ORDER BY sequence_number",
            (document_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_document_sources_metadata(self, document_id: int) -> list[dict]:
        """Get lightweight source metadata fully covered by idx_document_sources_metadata.

        SQLite reads only from the covering index and never touches the main
        table, avoiding overflow-page traversal for rows with large
        binary_content / text_content blobs.

        Use get_source_binary_content() and get_source_ocr_json() to fetch
        heavy columns on demand by primary-key lookup.
        """
        rows = self.conn.execute(
            """
            SELECT source_id, document_id, sequence_number, relative_path,
                   source_type, mime_type, is_ocr_completed, is_text_added
            FROM document_sources
            WHERE document_id = ?
            ORDER BY sequence_number
            """,
            (document_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_source_binary_content(self, source_id: int) -> bytes | None:
        """Get binary_content for a single source by ID."""
        row = self.conn.execute(
            "SELECT binary_content FROM document_sources WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        if row is None:
            return None
        content = row["binary_content"]
        return bytes(content) if content is not None else None

    def get_source_ocr_json(self, source_id: int) -> str | None:
        """Get ocr_json for a single source by ID."""
        row = self.conn.execute(
            "SELECT ocr_json FROM document_sources WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        if row is None:
            return None
        value = row["ocr_json"]
        return str(value) if value is not None else None

    def source_exists_by_content(self, text_content: str) -> bool:
        """Check if a source with the same text_content already exists."""
        row = self.conn.execute(
            "SELECT 1 FROM document_sources WHERE text_content = ? LIMIT 1",
            (text_content,),
        ).fetchone()
        return row is not None

    def source_exists_by_binary(self, binary_content: bytes) -> bool:
        """Check if a source with the same binary_content already exists."""
        row = self.conn.execute(
            "SELECT 1 FROM document_sources WHERE binary_content = ? LIMIT 1",
            (binary_content,),
        ).fetchone()
        return row is not None

    def get_document_sources_needing_ocr(self, document_id: int) -> list[dict]:
        """Get sources where is_ocr_completed=0 and source_type='image'."""
        rows = self.conn.execute(
            """
            SELECT * FROM document_sources
            WHERE document_id = ? AND is_ocr_completed = 0 AND source_type = 'image'
            ORDER BY sequence_number
            """,
            (document_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_documents_with_image_sources(self) -> list[dict]:
        """Return documents that have image sources (need OCR review)."""
        rows = self.conn.execute(
            """
            SELECT DISTINCT d.*
            FROM document d
            INNER JOIN document_sources ds ON d.document_id = ds.document_id
            WHERE ds.source_type = 'image'
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def update_source_ocr(self, source_id: int, ocr_json: str, auto_commit: bool = True) -> None:
        """Update source's ocr_json field."""
        self.conn.execute(
            "UPDATE document_sources SET ocr_json = ? WHERE source_id = ?",
            (ocr_json, source_id),
        )
        if auto_commit:
            self.conn.commit()

    def update_source_ocr_completed(self, source_id: int, auto_commit: bool = True) -> None:
        """Mark source's is_ocr_completed=1."""
        self.conn.execute(
            "UPDATE document_sources SET is_ocr_completed = 1 WHERE source_id = ?",
            (source_id,),
        )
        if auto_commit:
            self.conn.commit()

    def update_source_text_added(self, source_id: int, auto_commit: bool = True) -> None:
        """Mark source's is_text_added=1."""
        self.conn.execute(
            "UPDATE document_sources SET is_text_added = 1 WHERE source_id = ?",
            (source_id,),
        )
        if auto_commit:
            self.conn.commit()

    def reset_source_ocr(self, source_id: int, auto_commit: bool = True) -> None:
        """Reset OCR flags for a source so it can be re-OCR'd.

        Clears ocr_json and resets is_ocr_completed and is_text_added to 0.
        Also deletes existing chunks for the document to avoid mixing stale
        and fresh data when glossary is rebuilt.

        Used when user wants to re-run OCR on a specific page.
        """
        # Get the document_id for this source
        row = self.conn.execute(
            "SELECT document_id FROM document_sources WHERE source_id = ?",
            (source_id,),
        ).fetchone()

        # Reset OCR flags on the source
        self.conn.execute(
            """
            UPDATE document_sources
            SET is_ocr_completed = 0, is_text_added = 0, ocr_json = NULL
            WHERE source_id = ?
            """,
            (source_id,),
        )

        # Delete existing chunks for the document to ensure clean rebuild
        if row is not None:
            document_id = row["document_id"]
            self.conn.execute(
                "DELETE FROM chunks WHERE document_id = ?",
                (document_id,),
            )
            # Reset is_text_added for all sources in the document
            # since chunks are deleted, text needs to be re-added
            self.conn.execute(
                "UPDATE document_sources SET is_text_added = 0 WHERE document_id = ?",
                (document_id,),
            )

        if auto_commit:
            self.conn.commit()

    def get_min_chunk_id_for_document(self, document_id: int) -> int | None:
        """Get the minimum chunk_id for a document.

        Returns None if no chunks exist for the document.
        """
        row = self.conn.execute(
            "SELECT MIN(chunk_id) as min_id FROM chunks WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        if row and row["min_id"] is not None:
            return int(row["min_id"])
        return None

    def get_document_ids_from_chunk_id(self, cutoff_chunk_id: int) -> list[int]:
        """Get all document_ids that have chunks at or after the cutoff.

        Returns list of document_ids affected by a stack-based reset.
        """
        rows = self.conn.execute(
            "SELECT DISTINCT document_id FROM chunks WHERE chunk_id >= ? AND document_id IS NOT NULL",
            (cutoff_chunk_id,),
        ).fetchall()
        return [row["document_id"] for row in rows]

    def reset_documents_from(self, cutoff_chunk_id: int, auto_commit: bool = True) -> dict:
        """Stack-based document reset: delete all data from cutoff_chunk_id onward.

        Deletes chunks >= cutoff, prunes term descriptions/occurrences,
        deletes terms with no remaining descriptions, and resets
        is_text_added for affected documents.

        Args:
            cutoff_chunk_id: All chunks with chunk_id >= this value will be deleted.
            auto_commit: Whether to commit the transaction.

        Returns:
            Dict with affected_document_ids, deleted_chunks, pruned_terms, deleted_terms.
        """
        # Step 1: Get affected document_ids before deletion
        affected_doc_ids = self.get_document_ids_from_chunk_id(cutoff_chunk_id)

        # Step 2: Delete chunks
        cur = self.conn.execute(
            "DELETE FROM chunks WHERE chunk_id >= ?",
            (cutoff_chunk_id,),
        )
        deleted_chunks = cur.rowcount

        # Step 3: Prune term descriptions and occurrences
        # list_terms() returns list[TermRecord] dataclass instances
        def _safe_int_key(k: str) -> int | None:
            try:
                return int(k)
            except ValueError:
                return None

        pruned_count = 0
        deleted_count = 0
        for term in self.list_terms():
            # term.descriptions and term.occurrence are already parsed dicts
            # Keys are chunk_id strings
            new_descriptions = {
                k: v for k, v in term.descriptions.items() if _safe_int_key(k) is None or int(k) < cutoff_chunk_id
            }
            new_occurrence = {
                k: v for k, v in term.occurrence.items() if _safe_int_key(k) is None or int(k) < cutoff_chunk_id
            }
            if not new_descriptions:
                # Term has no remaining descriptions -- delete it entirely
                self.conn.execute("DELETE FROM terms WHERE key = ?", (term.key,))
                deleted_count += 1
            else:
                self.conn.execute(
                    "UPDATE terms SET descriptions_json = ?, occurrence_json = ?, updated_at = ? WHERE key = ?",
                    (
                        json.dumps(new_descriptions, ensure_ascii=False),
                        json.dumps(new_occurrence),
                        time.time(),
                        term.key,
                    ),
                )
                pruned_count += 1

        # Step 4: Reset source flags for affected documents
        if affected_doc_ids:
            placeholders = ",".join("?" * len(affected_doc_ids))
            self.conn.execute(
                f"UPDATE document_sources SET is_text_added = 0 WHERE document_id IN ({placeholders})",
                affected_doc_ids,
            )

        # Step 5: Commit
        if auto_commit:
            self.conn.commit()

        return {
            "affected_document_ids": affected_doc_ids,
            "deleted_chunks": deleted_chunks,
            "pruned_terms": pruned_count,
            "deleted_terms": deleted_count,
        }

    def delete_documents_from(self, document_id: int, auto_commit: bool = True) -> dict:
        """Stack-based document deletion.

        Deletes the target document and all documents with higher document_id.
        First resets chunks/terms/flags via reset_documents_from(), then deletes
        document sources and document rows for affected documents.

        Args:
            document_id: The document to delete. All documents with equal or higher
                document_id are also deleted (stack model).
            auto_commit: Whether to commit the transaction.

        Returns:
            Dict with affected_document_ids, deleted_chunks, pruned_terms,
            deleted_terms, deleted_sources, deleted_documents.
        """
        # Get all document_ids >= target
        affected_doc_ids = [
            row["document_id"]
            for row in self.conn.execute(
                "SELECT document_id FROM document WHERE document_id >= ? ORDER BY document_id",
                (document_id,),
            ).fetchall()
        ]

        if not affected_doc_ids:
            return {
                "affected_document_ids": [],
                "deleted_chunks": 0,
                "pruned_terms": 0,
                "deleted_terms": 0,
                "deleted_sources": 0,
                "deleted_documents": 0,
            }

        # Find min chunk_id across all affected documents (for stack-based reset)
        placeholders = ",".join("?" * len(affected_doc_ids))
        row = self.conn.execute(
            f"SELECT MIN(chunk_id) as min_id FROM chunks WHERE document_id IN ({placeholders})",
            affected_doc_ids,
        ).fetchone()
        cutoff = int(row["min_id"]) if row and row["min_id"] is not None else None

        # Reset chunks and terms if any chunks exist
        reset_result = {"deleted_chunks": 0, "pruned_terms": 0, "deleted_terms": 0}
        if cutoff is not None:
            reset_result = self.reset_documents_from(cutoff, auto_commit=False)

        # Delete document sources
        cur_sources = self.conn.execute(
            f"DELETE FROM document_sources WHERE document_id IN ({placeholders})",
            affected_doc_ids,
        )
        deleted_sources = cur_sources.rowcount

        # Delete documents
        cur_docs = self.conn.execute(
            f"DELETE FROM document WHERE document_id IN ({placeholders})",
            affected_doc_ids,
        )
        deleted_documents = cur_docs.rowcount

        if auto_commit:
            self.conn.commit()

        return {
            "affected_document_ids": affected_doc_ids,
            "deleted_chunks": reset_result["deleted_chunks"],
            "pruned_terms": reset_result["pruned_terms"],
            "deleted_terms": reset_result["deleted_terms"],
            "deleted_sources": deleted_sources,
            "deleted_documents": deleted_documents,
        }

    def update_all_sources_text_added(self, document_id: int, auto_commit: bool = True) -> None:
        """Mark all sources for a document as is_text_added=1."""
        self.conn.execute(
            "UPDATE document_sources SET is_text_added = 1 WHERE document_id = ?",
            (document_id,),
        )
        if auto_commit:
            self.conn.commit()

    def save_reembedded_image(self, document_id: int, element_idx: int, image_bytes: bytes, mime_type: str) -> None:
        """Persist a single reembedded image using atomic JSON update."""
        import base64

        b64_data = base64.b64encode(image_bytes).decode("utf-8")
        value_json = json.dumps({"bytes": b64_data, "mime": mime_type})

        self.conn.execute(
            """
            UPDATE document_sources
            SET reembedded_images_json = json_set(
                COALESCE(reembedded_images_json, '{}'),
                '$.' || ?,
                json(?)
            )
            WHERE document_id = ?
            """,
            (str(element_idx), value_json, document_id),
        )
        self.conn.commit()

    def load_reembedded_images(self, document_id: int) -> dict[int, tuple[bytes, str]]:
        """
        Load all reembedded images for a document.

        Returns:
            Dictionary mapping element_idx to (image_bytes, mime_type) tuples
        """
        import base64

        row = self.conn.execute(
            "SELECT reembedded_images_json FROM document_sources WHERE document_id = ?",
            (document_id,),
        ).fetchone()

        if row is None or not row["reembedded_images_json"]:
            return {}
        images_json = json.loads(row["reembedded_images_json"])

        result: dict[int, tuple[bytes, str]] = {}

        for idx_str, value in images_json.items():
            element_idx = int(idx_str)
            b64_data = value["bytes"]
            mime_type = value["mime"]
            image_bytes = base64.b64decode(b64_data)
            result[element_idx] = (image_bytes, mime_type)

        return result
