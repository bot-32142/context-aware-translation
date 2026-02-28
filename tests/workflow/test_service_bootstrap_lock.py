"""Tests for per-book bootstrap lock in bootstrap_ops."""

import asyncio
import threading
import time
from unittest.mock import MagicMock

import pytest

from context_aware_translation.workflow.runtime import WorkflowContext
from context_aware_translation.workflow.services import bootstrap_ops


@pytest.fixture(autouse=True)
def _reset_locks():
    """Reset bootstrap locks between tests."""
    with bootstrap_ops.BOOTSTRAP_REGISTRY_LOCK:
        bootstrap_ops.BOOTSTRAP_LOCKS.clear()
    yield
    with bootstrap_ops.BOOTSTRAP_REGISTRY_LOCK:
        bootstrap_ops.BOOTSTRAP_LOCKS.clear()


def _make_context(book_id: str = "book-1") -> WorkflowContext:
    """Create a WorkflowContext with mocked dependencies."""
    return WorkflowContext(
        config=MagicMock(),
        llm_client=MagicMock(),
        context_tree=MagicMock(),
        manager=MagicMock(),
        db=MagicMock(),
        document_repo=MagicMock(),
        book_id=book_id,
    )


def test_prepare_prereqs_serialized_for_same_book():
    """Two threads on same book enter prepare_llm_prerequisites, second waits for first."""
    ctx1 = _make_context("book-1")
    ctx2 = _make_context("book-1")

    order: list[str] = []
    lock = threading.Lock()

    async def fake_process_document(workflow, _doc_ids, cancel_check=None):  # noqa: ARG001
        if workflow is ctx1:
            with lock:
                order.append("start")
            time.sleep(0.1)
            with lock:
                order.append("end")
            return
        with lock:
            order.append("start2")
        with lock:
            order.append("end2")

    async def fake_ensure_source_language(_workflow, cancel_check=None):  # noqa: ARG001
        return None

    def run_in_thread(ctx):
        asyncio.run(bootstrap_ops.prepare_llm_prerequisites(ctx, None))

    with (
        pytest.MonkeyPatch.context() as mp,
    ):
        mp.setattr(bootstrap_ops, "process_document", fake_process_document)
        mp.setattr(bootstrap_ops, "ensure_source_language", fake_ensure_source_language)
        t1 = threading.Thread(target=run_in_thread, args=(ctx1,))
        t2 = threading.Thread(target=run_in_thread, args=(ctx2,))
        t1.start()
        time.sleep(0.02)  # Ensure t1 starts first
        t2.start()
        t1.join()
        t2.join()

    # t1 should complete before t2 starts
    assert order.index("end") < order.index("start2")


def test_prepare_prereqs_not_serialized_for_different_books():
    """Different book IDs can preflight in parallel."""
    ctx1 = _make_context("book-1")
    ctx2 = _make_context("book-2")

    concurrent = threading.Event()
    reached_concurrent = [False]

    async def fake_process_document(workflow, _doc_ids, cancel_check=None):  # noqa: ARG001
        if workflow is ctx1:
            concurrent.wait(timeout=2.0)
            return
        concurrent.set()
        reached_concurrent[0] = True

    async def fake_ensure_source_language(_workflow, cancel_check=None):  # noqa: ARG001
        return None

    def run_in_thread(ctx):
        asyncio.run(bootstrap_ops.prepare_llm_prerequisites(ctx, None))

    with (
        pytest.MonkeyPatch.context() as mp,
    ):
        mp.setattr(bootstrap_ops, "process_document", fake_process_document)
        mp.setattr(bootstrap_ops, "ensure_source_language", fake_ensure_source_language)
        t1 = threading.Thread(target=run_in_thread, args=(ctx1,))
        t2 = threading.Thread(target=run_in_thread, args=(ctx2,))
        t1.start()
        time.sleep(0.02)
        t2.start()
        t2.join(timeout=3.0)
        t1.join(timeout=3.0)

    assert reached_concurrent[0], "book-2 should have run concurrently with book-1"


def test_get_bootstrap_lock_returns_same_lock_for_same_book():
    lock1 = bootstrap_ops.get_bootstrap_lock("book-1")
    lock2 = bootstrap_ops.get_bootstrap_lock("book-1")
    assert lock1 is lock2


def test_get_bootstrap_lock_returns_different_locks_for_different_books():
    lock1 = bootstrap_ops.get_bootstrap_lock("book-1")
    lock2 = bootstrap_ops.get_bootstrap_lock("book-2")
    assert lock1 is not lock2


def test_get_bootstrap_lock_handles_none_book_id():
    lock = bootstrap_ops.get_bootstrap_lock(None)
    assert lock is not None
