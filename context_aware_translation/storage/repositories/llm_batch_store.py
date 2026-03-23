from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from context_aware_translation.storage.sqlite_locking import get_sqlite_file_lock

STATUS_SUBMITTED = "submitted"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

CREATE_LLM_BATCH_REQUESTS = """
CREATE TABLE IF NOT EXISTS llm_batch_requests (
    request_hash TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    status TEXT NOT NULL,
    batch_name TEXT,
    response_text TEXT,
    error_text TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""

CREATE_LLM_BATCH_STATUS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_llm_batch_requests_status
ON llm_batch_requests(status);
"""


@dataclass(frozen=True)
class LLMBatchRecord:
    request_hash: str
    provider: str
    status: str
    batch_name: str | None
    response_text: str | None
    error_text: str | None
    created_at: float
    updated_at: float


class LLMBatchStore:
    """SQLite store for resumable LLM batch requests."""

    def __init__(self, sqlite_path: Path) -> None:
        self.db_path = Path(sqlite_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = get_sqlite_file_lock(self.db_path)
        self._configure_connection()
        self._init_schema()

    def _configure_connection(self) -> None:
        with self._lock:
            self.conn.execute("PRAGMA journal_mode = WAL;")
            self.conn.execute("PRAGMA synchronous = FULL;")

    def _init_schema(self) -> None:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(CREATE_LLM_BATCH_REQUESTS)
            cur.execute(CREATE_LLM_BATCH_STATUS_INDEX)
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def get(self, request_hash: str) -> LLMBatchRecord | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM llm_batch_requests WHERE request_hash = ?",
                (request_hash,),
            ).fetchone()
            return self._row_to_record(row) if row is not None else None

    def _upsert(
        self,
        request_hash: str,
        provider: str,
        status: str,
        *,
        batch_name: str | None = None,
        response_text: str | None = None,
        error_text: str | None = None,
    ) -> None:
        now = time.time()
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO llm_batch_requests(
                    request_hash, provider, status, batch_name, response_text, error_text, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_hash) DO UPDATE SET
                    provider = excluded.provider,
                    status = excluded.status,
                    batch_name = COALESCE(excluded.batch_name, llm_batch_requests.batch_name),
                    response_text = excluded.response_text,
                    error_text = excluded.error_text,
                    updated_at = excluded.updated_at
                """,
                (request_hash, provider, status, batch_name, response_text, error_text, now, now),
            )
            self.conn.commit()

    def upsert_submitted(self, request_hash: str, provider: str, batch_name: str) -> None:
        self._upsert(request_hash, provider, STATUS_SUBMITTED, batch_name=batch_name)

    def upsert_completed(
        self,
        request_hash: str,
        provider: str,
        response_text: str,
        *,
        batch_name: str | None = None,
    ) -> None:
        self._upsert(request_hash, provider, STATUS_COMPLETED, batch_name=batch_name, response_text=response_text)

    def upsert_failed(
        self,
        request_hash: str,
        provider: str,
        error_text: str,
        *,
        batch_name: str | None = None,
    ) -> None:
        self._upsert(request_hash, provider, STATUS_FAILED, batch_name=batch_name, error_text=error_text)

    def get_completed_response(self, request_hash: str) -> str | None:
        """Return cached completed response without deleting it."""
        with self._lock:
            row = self.conn.execute(
                """
                SELECT response_text
                FROM llm_batch_requests
                WHERE request_hash = ? AND status = ? AND response_text IS NOT NULL
                """,
                (request_hash, STATUS_COMPLETED),
            ).fetchone()
            if row is None:
                return None
            return str(row["response_text"])

    def delete(self, request_hash: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM llm_batch_requests WHERE request_hash = ?", (request_hash,))
            self.conn.commit()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> LLMBatchRecord:
        return LLMBatchRecord(
            request_hash=str(row["request_hash"]),
            provider=str(row["provider"]),
            status=str(row["status"]),
            batch_name=str(row["batch_name"]) if row["batch_name"] is not None else None,
            response_text=str(row["response_text"]) if row["response_text"] is not None else None,
            error_text=str(row["error_text"]) if row["error_text"] is not None else None,
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )
