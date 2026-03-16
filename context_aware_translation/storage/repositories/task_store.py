from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_UNSET = object()

_ALLOWED_UPDATE_COLUMNS = frozenset(
    {
        "status",
        "phase",
        "document_ids_json",
        "payload_json",
        "config_snapshot_json",
        "cancel_requested",
        "total_items",
        "completed_items",
        "failed_items",
        "last_error",
        "updated_at",
    }
)

_CREATE_TASKS_TABLE = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL,
    phase TEXT,
    document_ids_json TEXT,
    payload_json TEXT,
    config_snapshot_json TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    total_items INTEGER NOT NULL DEFAULT 0,
    completed_items INTEGER NOT NULL DEFAULT 0,
    failed_items INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""

_CREATE_IDX_BOOK_TYPE = """
CREATE INDEX IF NOT EXISTS idx_tasks_book_type ON tasks(book_id, task_type, updated_at DESC);
"""

_CREATE_IDX_BOOK_UPDATED = """
CREATE INDEX IF NOT EXISTS idx_tasks_book_updated ON tasks(book_id, updated_at DESC);
"""

_CREATE_IDX_UPDATED = """
CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at DESC);
"""

_CREATE_IDX_STATUS = """
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
"""


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    book_id: str
    task_type: str
    status: str
    phase: str | None
    document_ids_json: str | None
    payload_json: str | None
    config_snapshot_json: str | None
    cancel_requested: bool
    total_items: int
    completed_items: int
    failed_items: int
    last_error: str | None
    created_at: float
    updated_at: float


class TaskStore:
    """SQLite-backed unified store for all task types."""

    def __init__(self, sqlite_path: Path) -> None:
        self.db_path = Path(sqlite_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._configure_connection()
        self._init_schema()

    def _configure_connection(self) -> None:
        with self._lock:
            self.conn.execute("PRAGMA journal_mode = WAL;")
            self.conn.execute("PRAGMA synchronous = FULL;")

    def _init_schema(self) -> None:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(_CREATE_TASKS_TABLE)
            cur.execute(_CREATE_IDX_BOOK_TYPE)
            cur.execute(_CREATE_IDX_BOOK_UPDATED)
            cur.execute(_CREATE_IDX_UPDATED)
            cur.execute(_CREATE_IDX_STATUS)
            # Migration: add config_snapshot_json if missing (existing databases)
            existing_cols = {row[1] for row in cur.execute("PRAGMA table_info(tasks)").fetchall()}
            if "config_snapshot_json" not in existing_cols:
                cur.execute("ALTER TABLE tasks ADD COLUMN config_snapshot_json TEXT")
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def create(
        self,
        *,
        book_id: str,
        task_type: str,
        document_ids_json: str | None = None,
        payload_json: str | None = None,
        config_snapshot_json: str | None = None,
        status: str = "queued",
        phase: str | None = None,
    ) -> TaskRecord:
        now = time.time()
        task_id = uuid.uuid4().hex
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO tasks(
                    task_id,
                    book_id,
                    task_type,
                    status,
                    phase,
                    document_ids_json,
                    payload_json,
                    config_snapshot_json,
                    cancel_requested,
                    total_items,
                    completed_items,
                    failed_items,
                    last_error,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    book_id,
                    task_type,
                    status,
                    phase,
                    document_ids_json,
                    payload_json,
                    config_snapshot_json,
                    0,
                    0,
                    0,
                    0,
                    None,
                    now,
                    now,
                ),
            )
            self.conn.commit()
        record = self.get(task_id)
        if record is None:
            raise RuntimeError(f"Failed to load created task: {task_id}")
        return record

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            return self._row_to_record(row) if row is not None else None

    def update(self, task_id: str, **kwargs: Any) -> TaskRecord:
        updates: dict[str, Any] = {}
        for key, value in kwargs.items():
            if key not in _ALLOWED_UPDATE_COLUMNS:
                raise ValueError(f"Invalid update column: {key}")
            if key == "cancel_requested":
                updates[key] = int(bool(value))
            elif key in ("total_items", "completed_items", "failed_items"):
                updates[key] = int(value)
            else:
                updates[key] = value

        if not updates:
            record = self.get(task_id)
            if record is None:
                raise KeyError(f"Task not found: {task_id}")
            return record

        updates["updated_at"] = time.time()
        # SAFETY: column names are validated against _ALLOWED_UPDATE_COLUMNS above.
        assignments = ", ".join(f"{column} = ?" for column in updates)
        values = list(updates.values()) + [task_id]
        with self._lock:
            cur = self.conn.execute(
                f"UPDATE tasks SET {assignments} WHERE task_id = ?",
                values,
            )
            self.conn.commit()
            if cur.rowcount == 0:
                raise KeyError(f"Task not found: {task_id}")
            row = self.conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"Task not found: {task_id}")
        return self._row_to_record(row)

    def list_tasks(
        self,
        book_id: str | None = None,
        task_type: str | None = None,
        limit: int | None = None,
        exclude_statuses: frozenset[str] | None = None,
        include_payload: bool = True,
        include_config_snapshot: bool = True,
    ) -> list[TaskRecord]:
        where_clauses: list[str] = []
        params: list[Any] = []

        if book_id is not None:
            where_clauses.append("book_id = ?")
            params.append(book_id)
        if task_type is not None:
            where_clauses.append("task_type = ?")
            params.append(task_type)
        if exclude_statuses:
            placeholders = ", ".join("?" for _ in exclude_statuses)
            where_clauses.append(f"status NOT IN ({placeholders})")
            params.extend(sorted(exclude_statuses))

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        limit_sql = f"LIMIT {int(limit)}" if limit is not None else ""

        payload_col = "payload_json" if include_payload else "NULL AS payload_json"
        snapshot_col = "config_snapshot_json" if include_config_snapshot else "NULL AS config_snapshot_json"
        query = (
            "SELECT task_id, book_id, task_type, status, phase, document_ids_json, "
            f"{payload_col}, {snapshot_col}, "
            "cancel_requested, total_items, completed_items, failed_items, last_error, created_at, updated_at "
            f"FROM tasks {where_sql} ORDER BY updated_at DESC {limit_sql}"
        )
        with self._lock:
            rows = self.conn.execute(query, params).fetchall()
            return [self._row_to_record(row) for row in rows]

    def delete(self, task_id: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            self.conn.commit()

    def mark_cancel_requested(self, task_id: str) -> TaskRecord:
        return self.update(
            task_id,
            cancel_requested=True,
            status="cancel_requested",
        )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            task_id=str(row["task_id"]),
            book_id=str(row["book_id"]),
            task_type=str(row["task_type"]),
            status=str(row["status"]),
            phase=str(row["phase"]) if row["phase"] is not None else None,
            document_ids_json=str(row["document_ids_json"]) if row["document_ids_json"] is not None else None,
            payload_json=str(row["payload_json"]) if row["payload_json"] is not None else None,
            config_snapshot_json=str(row["config_snapshot_json"]) if row["config_snapshot_json"] is not None else None,
            cancel_requested=bool(row["cancel_requested"]),
            total_items=int(row["total_items"]),
            completed_items=int(row["completed_items"]),
            failed_items=int(row["failed_items"]),
            last_error=str(row["last_error"]) if row["last_error"] is not None else None,
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )
