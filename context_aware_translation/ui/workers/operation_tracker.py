"""Per-document operation tracking across all worker types."""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


class DocumentOperationTracker:
    """Tracks per-document operations across all worker types.

    Thread-safe. All methods are classmethods using a shared lock.
    """

    _lock = threading.Lock()
    _next_op_id: int = 0
    _active_ops: dict[str, dict[int, list[int] | None]] = {}
    # book_id -> {op_id -> document_ids (None = all docs)}

    @classmethod
    def try_start_operation(cls, book_id: str, document_ids: list[int] | None) -> int | None:
        """Atomically check overlap and register operation.

        Returns op_id if started, None if blocked by overlap.
        document_ids=None means "all documents" which overlaps with everything.
        """
        with cls._lock:
            active = cls._active_ops.get(book_id, {})
            if cls._overlaps(active, document_ids):
                return None
            op_id = cls._next_op_id
            cls._next_op_id += 1
            cls._active_ops.setdefault(book_id, {})[op_id] = document_ids
            return op_id

    @classmethod
    def finish_operation(cls, book_id: str, op_id: int) -> None:
        """Remove a completed operation. Safe to call multiple times (idempotent)."""
        with cls._lock:
            book_ops = cls._active_ops.get(book_id)
            if book_ops is None:
                return
            book_ops.pop(op_id, None)
            if not book_ops:
                cls._active_ops.pop(book_id, None)

    @classmethod
    def has_document_overlap(cls, book_id: str, document_ids: list[int] | None) -> bool:
        """Check if proposed document_ids overlap with any active operation."""
        with cls._lock:
            active = cls._active_ops.get(book_id, {})
            return cls._overlaps(active, document_ids)

    @classmethod
    def is_any_active_for_book(cls, book_id: str) -> bool:
        """Check if any operation is active for the book."""
        with cls._lock:
            return bool(cls._active_ops.get(book_id))

    @classmethod
    def get_active_document_ids(cls, book_id: str) -> set[int] | None:
        """Return union of all active doc IDs. None if any op covers 'all docs'."""
        with cls._lock:
            active = cls._active_ops.get(book_id, {})
            if not active:
                return set()
            result: set[int] = set()
            for doc_ids in active.values():
                if doc_ids is None:
                    return None  # At least one op covers all docs
                result.update(doc_ids)
            return result

    @staticmethod
    def _overlaps(active: dict[int, list[int] | None], proposed: list[int] | None) -> bool:
        """Check if proposed document_ids overlap with any active operation."""
        if not active:
            return False
        for existing_ids in active.values():
            if existing_ids is None or proposed is None:
                # None means "all docs" - always overlaps
                return True
            if set(existing_ids) & set(proposed):
                return True
        return False

    @classmethod
    def _reset(cls) -> None:
        """Reset all state. For testing only."""
        with cls._lock:
            cls._active_ops.clear()
            cls._next_op_id = 0
