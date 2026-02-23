"""Tests for DocumentOperationTracker."""

import threading

import pytest

from context_aware_translation.ui.workers.operation_tracker import DocumentOperationTracker


@pytest.fixture(autouse=True)
def _reset_tracker():
    DocumentOperationTracker._reset()
    yield
    DocumentOperationTracker._reset()


def test_try_start_finish_lifecycle():
    op_id = DocumentOperationTracker.try_start_operation("book-1", [1])
    assert op_id is not None
    DocumentOperationTracker.finish_operation("book-1", op_id)
    assert not DocumentOperationTracker.is_any_active_for_book("book-1")


def test_overlap_none_vs_specific():
    op_id = DocumentOperationTracker.try_start_operation("book-1", None)
    assert op_id is not None
    blocked = DocumentOperationTracker.try_start_operation("book-1", [1])
    assert blocked is None
    DocumentOperationTracker.finish_operation("book-1", op_id)


def test_overlap_specific_vs_none():
    op_id = DocumentOperationTracker.try_start_operation("book-1", [1])
    assert op_id is not None
    blocked = DocumentOperationTracker.try_start_operation("book-1", None)
    assert blocked is None
    DocumentOperationTracker.finish_operation("book-1", op_id)


def test_overlap_disjoint():
    op1 = DocumentOperationTracker.try_start_operation("book-1", [1])
    op2 = DocumentOperationTracker.try_start_operation("book-1", [2])
    assert op1 is not None
    assert op2 is not None
    DocumentOperationTracker.finish_operation("book-1", op1)
    DocumentOperationTracker.finish_operation("book-1", op2)


def test_overlap_same_doc():
    op1 = DocumentOperationTracker.try_start_operation("book-1", [1])
    assert op1 is not None
    op2 = DocumentOperationTracker.try_start_operation("book-1", [1])
    assert op2 is None


def test_no_overlap_empty():
    assert not DocumentOperationTracker.has_document_overlap("book-1", [1])


def test_finish_idempotent():
    op_id = DocumentOperationTracker.try_start_operation("book-1", [1])
    assert op_id is not None
    DocumentOperationTracker.finish_operation("book-1", op_id)
    DocumentOperationTracker.finish_operation("book-1", op_id)  # No error


def test_try_start_atomic_same_doc():
    """Two concurrent starts for same doc, exactly one succeeds."""
    results = [None, None]
    barrier = threading.Barrier(2)

    def worker(idx):
        barrier.wait()
        results[idx] = DocumentOperationTracker.try_start_operation("book-1", [1])

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    successes = [r for r in results if r is not None]
    assert len(successes) == 1


def test_thread_safety():
    """20 threads try_start/finish without errors."""
    errors = []
    barrier = threading.Barrier(20)

    def worker(idx):
        try:
            barrier.wait()
            op_id = DocumentOperationTracker.try_start_operation("book-1", [idx])
            if op_id is not None:
                DocumentOperationTracker.finish_operation("book-1", op_id)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors


def test_is_any_active_for_book():
    assert not DocumentOperationTracker.is_any_active_for_book("book-1")
    op_id = DocumentOperationTracker.try_start_operation("book-1", [1])
    assert DocumentOperationTracker.is_any_active_for_book("book-1")
    DocumentOperationTracker.finish_operation("book-1", op_id)
    assert not DocumentOperationTracker.is_any_active_for_book("book-1")


def test_get_active_document_ids():
    op1 = DocumentOperationTracker.try_start_operation("book-1", [1, 2])
    op2 = DocumentOperationTracker.try_start_operation("book-1", [3])
    ids = DocumentOperationTracker.get_active_document_ids("book-1")
    assert ids == {1, 2, 3}
    DocumentOperationTracker.finish_operation("book-1", op1)
    DocumentOperationTracker.finish_operation("book-1", op2)


def test_get_active_document_ids_returns_none_for_all_docs():
    op_id = DocumentOperationTracker.try_start_operation("book-1", None)
    ids = DocumentOperationTracker.get_active_document_ids("book-1")
    assert ids is None
    DocumentOperationTracker.finish_operation("book-1", op_id)


def test_get_active_document_ids_empty():
    ids = DocumentOperationTracker.get_active_document_ids("book-1")
    assert ids == set()
