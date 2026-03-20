from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from context_aware_translation.storage.sqlite_locking import get_sqlite_file_lock

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_CANCEL_REQUESTED = "cancel_requested"
STATUS_CANCELLING = "cancelling"
STATUS_CANCELLED = "cancelled"
STATUS_COMPLETED = "completed"
STATUS_COMPLETED_WITH_ERRORS = "completed_with_errors"
STATUS_FAILED = "failed"

TERMINAL_TASK_STATUSES = {
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_COMPLETED_WITH_ERRORS,
    STATUS_FAILED,
}

PHASE_PREPARE = "prepare"
PHASE_TRANSLATION_SUBMIT = "translation_submit"
PHASE_TRANSLATION_POLL = "translation_poll"
PHASE_TRANSLATION_VALIDATE = "translation_validate"
PHASE_TRANSLATION_FALLBACK = "translation_fallback"
PHASE_POLISH_SUBMIT = "polish_submit"
PHASE_POLISH_POLL = "polish_poll"
PHASE_POLISH_VALIDATE = "polish_validate"
PHASE_POLISH_FALLBACK = "polish_fallback"
PHASE_APPLY = "apply"
PHASE_DONE = "done"

CREATE_TRANSLATION_BATCH_TASKS = """
CREATE TABLE IF NOT EXISTS translation_batch_tasks (
    task_id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL,
    status TEXT NOT NULL,
    phase TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    document_ids_json TEXT,
    force INTEGER NOT NULL,
    total_items INTEGER NOT NULL,
    completed_items INTEGER NOT NULL,
    failed_items INTEGER NOT NULL,
    cancel_requested INTEGER NOT NULL,
    translation_batch_name TEXT,
    polish_batch_name TEXT,
    last_error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""

CREATE_TRANSLATION_BATCH_TASKS_BOOK_INDEX = """
CREATE INDEX IF NOT EXISTS idx_translation_batch_tasks_book_updated
ON translation_batch_tasks(book_id, updated_at DESC);
"""

CREATE_TRANSLATION_BATCH_TASKS_STATUS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_translation_batch_tasks_status
ON translation_batch_tasks(status);
"""

_UNSET = object()

_ALLOWED_UPDATE_COLUMNS = frozenset(
    {
        "status",
        "phase",
        "payload_json",
        "total_items",
        "completed_items",
        "failed_items",
        "cancel_requested",
        "translation_batch_name",
        "polish_batch_name",
        "last_error",
        "updated_at",
    }
)


@dataclass(frozen=True)
class TranslationBatchTaskRecord:
    task_id: str
    book_id: str
    status: str
    phase: str
    payload_json: str
    document_ids_json: str | None
    force: bool
    total_items: int
    completed_items: int
    failed_items: int
    cancel_requested: bool
    translation_batch_name: str | None
    polish_batch_name: str | None
    last_error: str | None
    created_at: float
    updated_at: float


class TranslationBatchTaskStore:
    """SQLite-backed store for persistent batch translation tasks."""

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
            cur.execute(CREATE_TRANSLATION_BATCH_TASKS)
            existing_cols = {row[1] for row in cur.execute("PRAGMA table_info(translation_batch_tasks)").fetchall()}
            if "skip_context" in existing_cols:
                cur.execute("ALTER TABLE translation_batch_tasks DROP COLUMN skip_context")
            cur.execute(CREATE_TRANSLATION_BATCH_TASKS_BOOK_INDEX)
            cur.execute(CREATE_TRANSLATION_BATCH_TASKS_STATUS_INDEX)
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def create_task(
        self,
        *,
        book_id: str,
        payload_json: str = "{}",
        document_ids_json: str | None = None,
        force: bool = False,
    ) -> TranslationBatchTaskRecord:
        now = time.time()
        task_id = uuid.uuid4().hex
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO translation_batch_tasks(
                    task_id,
                    book_id,
                    status,
                    phase,
                    payload_json,
                    document_ids_json,
                    force,
                    total_items,
                    completed_items,
                    failed_items,
                    cancel_requested,
                    translation_batch_name,
                    polish_batch_name,
                    last_error,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?)
                """,
                (
                    task_id,
                    book_id,
                    STATUS_QUEUED,
                    PHASE_PREPARE,
                    payload_json,
                    document_ids_json,
                    int(force),
                    0,
                    0,
                    0,
                    0,
                    now,
                    now,
                ),
            )
            self.conn.commit()
        record = self.get(task_id)
        if record is None:
            raise RuntimeError(f"Failed to load created translation batch task: {task_id}")
        return record

    def get(self, task_id: str) -> TranslationBatchTaskRecord | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM translation_batch_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            return self._row_to_record(row) if row is not None else None

    def list_tasks(self, book_id: str, *, limit: int = 50) -> list[TranslationBatchTaskRecord]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT *
                FROM translation_batch_tasks
                WHERE book_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (book_id, max(1, int(limit))),
            ).fetchall()
            return [self._row_to_record(row) for row in rows]

    def update(
        self,
        task_id: str,
        *,
        status: str | object = _UNSET,
        phase: str | object = _UNSET,
        payload_json: str | object = _UNSET,
        total_items: int | object = _UNSET,
        completed_items: int | object = _UNSET,
        failed_items: int | object = _UNSET,
        cancel_requested: bool | object = _UNSET,
        translation_batch_name: str | None | object = _UNSET,
        polish_batch_name: str | None | object = _UNSET,
        last_error: str | None | object = _UNSET,
    ) -> TranslationBatchTaskRecord:
        updates: dict[str, Any] = {}
        if status is not _UNSET:
            updates["status"] = status
        if phase is not _UNSET:
            updates["phase"] = phase
        if payload_json is not _UNSET:
            updates["payload_json"] = payload_json
        if total_items is not _UNSET:
            updates["total_items"] = int(total_items)  # type: ignore[arg-type]
        if completed_items is not _UNSET:
            updates["completed_items"] = int(completed_items)  # type: ignore[arg-type]
        if failed_items is not _UNSET:
            updates["failed_items"] = int(failed_items)  # type: ignore[arg-type]
        if cancel_requested is not _UNSET:
            updates["cancel_requested"] = int(bool(cancel_requested))
        if translation_batch_name is not _UNSET:
            updates["translation_batch_name"] = translation_batch_name
        if polish_batch_name is not _UNSET:
            updates["polish_batch_name"] = polish_batch_name
        if last_error is not _UNSET:
            updates["last_error"] = last_error
        if not updates:
            record = self.get(task_id)
            if record is None:
                raise KeyError(f"Translation batch task not found: {task_id}")
            return record

        updates["updated_at"] = time.time()
        for column in updates:
            if column not in _ALLOWED_UPDATE_COLUMNS:
                raise ValueError(f"Invalid update column: {column}")
        assignments = ", ".join(f"{column} = ?" for column in updates)
        values = list(updates.values()) + [task_id]
        with self._lock:
            cur = self.conn.execute(
                f"UPDATE translation_batch_tasks SET {assignments} WHERE task_id = ?",
                values,
            )
            self.conn.commit()
            if cur.rowcount == 0:
                raise KeyError(f"Translation batch task not found: {task_id}")

        record = self.get(task_id)
        if record is None:
            raise KeyError(f"Translation batch task not found: {task_id}")
        return record

    def mark_cancel_requested(self, task_id: str) -> TranslationBatchTaskRecord:
        return self.update(
            task_id,
            cancel_requested=True,
            status=STATUS_CANCEL_REQUESTED,
        )

    def delete(self, task_id: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM translation_batch_tasks WHERE task_id = ?", (task_id,))
            self.conn.commit()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> TranslationBatchTaskRecord:
        return TranslationBatchTaskRecord(
            task_id=str(row["task_id"]),
            book_id=str(row["book_id"]),
            status=str(row["status"]),
            phase=str(row["phase"]),
            payload_json=str(row["payload_json"]),
            document_ids_json=str(row["document_ids_json"]) if row["document_ids_json"] is not None else None,
            force=bool(row["force"]),
            total_items=int(row["total_items"]),
            completed_items=int(row["completed_items"]),
            failed_items=int(row["failed_items"]),
            cancel_requested=bool(row["cancel_requested"]),
            translation_batch_name=str(row["translation_batch_name"])
            if row["translation_batch_name"] is not None
            else None,
            polish_batch_name=str(row["polish_batch_name"]) if row["polish_batch_name"] is not None else None,
            last_error=str(row["last_error"]) if row["last_error"] is not None else None,
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )
