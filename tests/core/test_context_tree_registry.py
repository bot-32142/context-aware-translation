"""Tests for ContextTreeRegistry."""

import threading
from unittest.mock import MagicMock

import pytest

from context_aware_translation.core.context_tree_registry import ContextTreeRegistry


@pytest.fixture(autouse=True)
def _reset_registry():
    ContextTreeRegistry._reset()
    yield
    ContextTreeRegistry._reset()


def _make_mock_tree():
    tree = MagicMock()
    tree.close = MagicMock()
    return tree


def test_acquire_creates_tree():
    tree = _make_mock_tree()
    builder = MagicMock(return_value=tree)
    result = ContextTreeRegistry.acquire("book-1", builder)
    assert result is tree
    builder.assert_called_once()


def test_acquire_returns_same_instance():
    tree = _make_mock_tree()
    builder = MagicMock(return_value=tree)
    t1 = ContextTreeRegistry.acquire("book-1", builder)
    t2 = ContextTreeRegistry.acquire("book-1", builder)
    assert t1 is t2
    builder.assert_called_once()  # Only built once


def test_release_decrements_refcount():
    tree = _make_mock_tree()
    ContextTreeRegistry.acquire("book-1", lambda: tree)
    ContextTreeRegistry.acquire("book-1", lambda: tree)
    ContextTreeRegistry.release("book-1")
    tree.close.assert_not_called()  # Still one ref


def test_release_closes_at_zero():
    tree = _make_mock_tree()
    ContextTreeRegistry.acquire("book-1", lambda: tree)
    ContextTreeRegistry.release("book-1")
    tree.close.assert_called_once()


def test_concurrent_acquire_same_book():
    tree = _make_mock_tree()
    call_count = 0

    def slow_builder():
        nonlocal call_count
        call_count += 1
        return tree

    results = [None, None]
    barrier = threading.Barrier(2)

    def worker(idx):
        barrier.wait()
        results[idx] = ContextTreeRegistry.acquire("book-1", slow_builder)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results[0] is results[1]
    # Builder called once (second thread finds existing entry)
    assert call_count == 1


def test_concurrent_acquire_different_books():
    trees = [_make_mock_tree(), _make_mock_tree()]
    results = [None, None]
    barrier = threading.Barrier(2)

    def worker(idx):
        barrier.wait()
        results[idx] = ContextTreeRegistry.acquire(f"book-{idx}", lambda i=idx: trees[i])

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results[0] is trees[0]
    assert results[1] is trees[1]


def test_release_unknown_book_id_is_safe(caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        ContextTreeRegistry.release("nonexistent")
    assert "unknown book_id" in caplog.text


def test_invalidate_skips_when_in_use(caplog):
    import logging

    tree = _make_mock_tree()
    ContextTreeRegistry.acquire("book-1", lambda: tree)
    with caplog.at_level(logging.WARNING):
        ContextTreeRegistry.invalidate("book-1")
    tree.close.assert_not_called()
    assert "ref_count" in caplog.text
