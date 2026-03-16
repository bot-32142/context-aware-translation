from __future__ import annotations

import contextlib
import sqlite3
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context_aware_translation.core.context_tree import SummaryNode

CREATE_CONTEXT_TREE_NODES = """
CREATE TABLE IF NOT EXISTS context_tree_nodes (
    term TEXT NOT NULL,
    start_idx INTEGER NOT NULL,
    layer INTEGER NOT NULL,
    content TEXT NOT NULL,
    end_idx INTEGER NOT NULL,
    token_size INTEGER NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (term, start_idx, layer)
);
"""

CREATE_CONTEXT_TREE_METADATA = """
CREATE TABLE IF NOT EXISTS context_tree_metadata (
    term TEXT PRIMARY KEY,
    max_seen_index INTEGER NOT NULL DEFAULT -1,
    updated_at REAL NOT NULL
);
"""

CREATE_CONTEXT_TREE_INDEX_TERM_START = """
CREATE INDEX IF NOT EXISTS idx_context_tree_term_start ON context_tree_nodes(term, start_idx);
"""

CREATE_CONTEXT_TREE_INDEX_TERM_LAYER = """
CREATE INDEX IF NOT EXISTS idx_context_tree_term_layer ON context_tree_nodes(term, layer);
"""


class ContextTreeDB:
    """
    SQLite-backed storage for context tree nodes and metadata.
    """

    def __init__(self, sqlite_path: Path) -> None:
        self.db_path = Path(sqlite_path)
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Set check_same_thread=False to allow connection from multiple threads
        # WAL mode + proper locking ensures thread safety
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()  # Reentrant lock for thread safety
        self._configure_connection()
        self._init_schema()

    def _configure_connection(self) -> None:
        with self._lock:
            self.conn.execute("PRAGMA foreign_keys = ON;")
            self.conn.execute("PRAGMA journal_mode = WAL;")
            self.conn.execute("PRAGMA synchronous = FULL;")

    def _init_schema(self) -> None:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(CREATE_CONTEXT_TREE_NODES)
            cur.execute(CREATE_CONTEXT_TREE_METADATA)
            cur.execute(CREATE_CONTEXT_TREE_INDEX_TERM_START)
            cur.execute(CREATE_CONTEXT_TREE_INDEX_TERM_LAYER)
            self.conn.commit()
            self._checkpoint()

    def _checkpoint(self) -> None:
        """
        Force WAL checkpoint to ensure data is written to the main database file.

        This ensures that subsequent reads (even from other connections or after
        copying the DB file) see the committed data immediately.
        """
        # Note: _checkpoint is called from within locked methods, so no need to lock here
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")

    def begin(self) -> None:
        with self._lock:
            self.conn.execute("BEGIN;")

    def commit(self) -> None:
        with self._lock:
            self.conn.commit()
            self._checkpoint()

    def rollback(self) -> None:
        with self._lock:
            self.conn.rollback()

    def persist_node(self, term: str, node: SummaryNode) -> None:
        """Persist a node to the database immediately."""
        with self._lock:
            now = time.time()
            self.conn.execute(
                """
                INSERT INTO context_tree_nodes(term, start_idx, layer, content, end_idx, token_size, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(term, start_idx, layer) DO NOTHING
                """,
                (term, node.start, node.layer, node.content, node.end, node.token_size, now),
            )
            self.conn.commit()
            self._checkpoint()

    def persist_max_index(self, term: str, max_index: int) -> None:
        """Persist max_seen_index atomically, ensuring it only increases."""
        with self._lock:
            now = time.time()
            self.conn.execute(
                """
                INSERT INTO context_tree_metadata(term, max_seen_index, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(term) DO UPDATE SET
                    max_seen_index = MAX(max_seen_index, excluded.max_seen_index),
                    updated_at = excluded.updated_at
                """,
                (term, max_index, now),
            )
            self.conn.commit()
            self._checkpoint()

    def load_max_seen_indices(self) -> dict[str, int]:
        """Load max_seen_index for all terms."""
        with self._lock:
            rows = self.conn.execute("SELECT term, max_seen_index FROM context_tree_metadata").fetchall()
            return {row["term"]: row["max_seen_index"] for row in rows}

    def load_all_nodes(self) -> list[tuple[str, str, int, int, int, int]]:
        """
        Load all nodes from database.

        Returns:
            List of tuples: (term, content, layer, start_idx, end_idx, token_size)
        """
        with self._lock:
            rows = self.conn.execute(
                "SELECT term, start_idx, layer, content, end_idx, token_size FROM context_tree_nodes ORDER BY term, layer, start_idx"
            ).fetchall()

            nodes = []
            for row in rows:
                nodes.append(
                    (row["term"], row["content"], row["layer"], row["start_idx"], row["end_idx"], row["token_size"])
                )

            return nodes

    def delete_nodes_from_index(self, cutoff_index: int) -> int:
        """Delete all context tree nodes at or after the cutoff index.

        Also deletes higher-layer summary nodes that span the cutoff boundary
        (start_idx < cutoff but end_idx > cutoff), since they incorporate
        data from now-deleted chunks.

        Args:
            cutoff_index: The chunk_id cutoff. All nodes with start_idx >= cutoff
                or end_idx > cutoff will be deleted.

        Returns:
            Total number of deleted rows (approximate due to overlap between queries).
        """
        with self._lock:
            cur1 = self.conn.execute(
                "DELETE FROM context_tree_nodes WHERE start_idx >= ?",
                (cutoff_index,),
            )
            cur2 = self.conn.execute(
                "DELETE FROM context_tree_nodes WHERE end_idx > ?",
                (cutoff_index,),
            )
            total = cur1.rowcount + cur2.rowcount
            self.conn.commit()
            self._checkpoint()
            return total

    def rollback_metadata_to_index(self, cutoff_index: int) -> None:
        """Roll back max_seen_index for all terms to before the cutoff.

        Caps max_seen_index at cutoff_index - 1 for any term that has
        seen beyond the cutoff. Then removes metadata entries for terms
        that have no remaining nodes (orphan cleanup).

        Args:
            cutoff_index: The chunk_id cutoff.
        """
        with self._lock:
            now = time.time()
            self.conn.execute(
                """UPDATE context_tree_metadata
                   SET max_seen_index = ? - 1, updated_at = ?
                   WHERE max_seen_index >= ?""",
                (cutoff_index, now, cutoff_index),
            )
            self.conn.execute(
                """DELETE FROM context_tree_metadata
                   WHERE term NOT IN (
                       SELECT DISTINCT term FROM context_tree_nodes
                   )"""
            )
            self.conn.commit()
            self._checkpoint()

    def delete_all(self) -> None:
        """Delete all context tree nodes and metadata. Full reset."""
        with self._lock:
            self.conn.execute("DELETE FROM context_tree_nodes")
            self.conn.execute("DELETE FROM context_tree_metadata")
            self.conn.commit()
            self._checkpoint()

    def close(self) -> None:
        """Close the SQLite connection."""
        with self._lock:
            with contextlib.suppress(Exception):
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            self.conn.close()
