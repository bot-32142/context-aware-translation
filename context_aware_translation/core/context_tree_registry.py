"""Ref-counted singleton ContextTree instances per book."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from context_aware_translation.core.context_tree import ContextTree

logger = logging.getLogger(__name__)


class ContextTreeRegistry:
    """Ref-counted singleton ContextTree instances per book.

    Uses per-book locks so construction of book A doesn't block book B.
    Double-checked locking: check _entries under global lock, if miss,
    acquire per-book lock, re-check, then call builder_func().
    """

    _lock = threading.Lock()
    _book_locks: dict[str, threading.Lock] = {}
    _entries: dict[str, tuple[ContextTree, int]] = {}  # book_id -> (tree, ref_count)

    @classmethod
    def acquire(cls, book_id: str, builder_func: Callable[[], ContextTree]) -> ContextTree:
        """Get or create a ContextTree for the book. Increments ref count."""
        with cls._lock:
            entry = cls._entries.get(book_id)
            if entry is not None:
                tree, count = entry
                cls._entries[book_id] = (tree, count + 1)
                return tree
            # Get or create per-book lock
            if book_id not in cls._book_locks:
                cls._book_locks[book_id] = threading.Lock()
            book_lock = cls._book_locks[book_id]

        # Acquire per-book lock (outside global lock to avoid blocking other books)
        with book_lock:
            # Double-check under global lock
            with cls._lock:
                entry = cls._entries.get(book_id)
                if entry is not None:
                    tree, count = entry
                    cls._entries[book_id] = (tree, count + 1)
                    return tree

            # Build the tree (may be slow - LLM calls in _resume_summarization)
            tree = builder_func()

            with cls._lock:
                # Another thread may have raced and inserted between our check and build
                entry = cls._entries.get(book_id)
                if entry is not None:
                    # Discard our tree, use the existing one
                    tree.close()
                    existing_tree, count = entry
                    cls._entries[book_id] = (existing_tree, count + 1)
                    return existing_tree
                cls._entries[book_id] = (tree, 1)
                return tree

    @classmethod
    def release(cls, book_id: str) -> None:
        """Decrement ref count. Close tree when it reaches 0."""
        with cls._lock:
            entry = cls._entries.get(book_id)
            if entry is None:
                logger.warning("ContextTreeRegistry.release called for unknown book_id: %s", book_id)
                return
            tree, count = entry
            if count <= 1:
                del cls._entries[book_id]
                cls._book_locks.pop(book_id, None)
            else:
                cls._entries[book_id] = (tree, count - 1)
                return
        # Close outside lock to avoid holding it during I/O
        tree.close()

    @classmethod
    def invalidate(cls, book_id: str) -> None:
        """Force-close and remove a cached tree (e.g., on config change).
        Only acts if ref_count == 0. Logs warning if tree is still in use."""
        with cls._lock:
            entry = cls._entries.get(book_id)
            if entry is None:
                return
            tree, count = entry
            if count > 0:
                logger.warning(
                    "ContextTreeRegistry.invalidate called for book %s with ref_count=%d; skipping",
                    book_id,
                    count,
                )
                return
            del cls._entries[book_id]
            cls._book_locks.pop(book_id, None)
        tree.close()

    @classmethod
    def _reset(cls) -> None:
        """Reset all state. For testing only."""
        with cls._lock:
            for tree, _ in cls._entries.values():
                tree.close()
            cls._entries.clear()
            cls._book_locks.clear()
