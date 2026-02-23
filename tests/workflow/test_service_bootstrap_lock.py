"""Tests for per-book bootstrap lock in WorkflowService."""

import asyncio
import threading
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_aware_translation.workflow.service import WorkflowService


@pytest.fixture(autouse=True)
def _reset_locks():
    """Reset bootstrap locks between tests."""
    with WorkflowService._bootstrap_registry_lock:
        WorkflowService._bootstrap_locks.clear()
    yield
    with WorkflowService._bootstrap_registry_lock:
        WorkflowService._bootstrap_locks.clear()


def _make_service(book_id: str = "book-1") -> WorkflowService:
    """Create a WorkflowService with mocked dependencies."""
    svc = object.__new__(WorkflowService)
    svc.config = MagicMock()
    svc.llm_client = MagicMock()
    svc.context_tree = MagicMock()
    svc.manager = MagicMock()
    svc.db = MagicMock()
    svc.document_repo = MagicMock()
    svc.book_id = book_id
    return svc


def test_prepare_prereqs_serialized_for_same_book():
    """Two threads on same book enter _prepare_llm_prerequisites, second waits for first."""
    svc1 = _make_service("book-1")
    svc2 = _make_service("book-1")

    order: list[str] = []
    lock = threading.Lock()

    async def slow_process_doc(_doc_ids, cancel_check=None):  # noqa: ARG001
        with lock:
            order.append("start")
        time.sleep(0.1)
        with lock:
            order.append("end")

    async def fast_process_doc(_doc_ids, cancel_check=None):  # noqa: ARG001
        with lock:
            order.append("start2")
        with lock:
            order.append("end2")

    svc1._process_document = slow_process_doc
    svc1._ensure_source_language = AsyncMock()
    svc2._process_document = fast_process_doc
    svc2._ensure_source_language = AsyncMock()

    def run_in_thread(svc):
        asyncio.run(svc._prepare_llm_prerequisites(None))

    t1 = threading.Thread(target=run_in_thread, args=(svc1,))
    t2 = threading.Thread(target=run_in_thread, args=(svc2,))
    t1.start()
    time.sleep(0.02)  # Ensure t1 starts first
    t2.start()
    t1.join()
    t2.join()

    # t1 should complete before t2 starts
    assert order.index("end") < order.index("start2")


def test_prepare_prereqs_not_serialized_for_different_books():
    """Different book IDs can preflight in parallel."""
    svc1 = _make_service("book-1")
    svc2 = _make_service("book-2")

    concurrent = threading.Event()
    reached_concurrent = [False]

    async def slow_process_doc_1(_doc_ids, cancel_check=None):  # noqa: ARG001
        concurrent.wait(timeout=2.0)

    async def slow_process_doc_2(_doc_ids, cancel_check=None):  # noqa: ARG001
        concurrent.set()
        reached_concurrent[0] = True

    svc1._process_document = slow_process_doc_1
    svc1._ensure_source_language = AsyncMock()
    svc2._process_document = slow_process_doc_2
    svc2._ensure_source_language = AsyncMock()

    def run_in_thread(svc):
        asyncio.run(svc._prepare_llm_prerequisites(None))

    t1 = threading.Thread(target=run_in_thread, args=(svc1,))
    t2 = threading.Thread(target=run_in_thread, args=(svc2,))
    t1.start()
    time.sleep(0.02)
    t2.start()
    t2.join(timeout=3.0)
    t1.join(timeout=3.0)

    assert reached_concurrent[0], "book-2 should have run concurrently with book-1"


def test_get_bootstrap_lock_returns_same_lock_for_same_book():
    lock1 = WorkflowService._get_bootstrap_lock("book-1")
    lock2 = WorkflowService._get_bootstrap_lock("book-1")
    assert lock1 is lock2


def test_get_bootstrap_lock_returns_different_locks_for_different_books():
    lock1 = WorkflowService._get_bootstrap_lock("book-1")
    lock2 = WorkflowService._get_bootstrap_lock("book-2")
    assert lock1 is not lock2


def test_get_bootstrap_lock_handles_none_book_id():
    lock = WorkflowService._get_bootstrap_lock(None)
    assert lock is not None
