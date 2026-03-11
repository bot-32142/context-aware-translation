"""Tests for batch_task_overlap_guard."""

import json
from pathlib import Path

import pytest

from context_aware_translation.adapters.qt.workers.batch_task_overlap_guard import has_any_batch_task_overlap
from context_aware_translation.storage.task_store import TaskStore


@pytest.fixture
def task_store(tmp_path: Path) -> TaskStore:
    store = TaskStore(tmp_path / "tasks.db")
    yield store
    store.close()


def _create_task(store: TaskStore, book_id: str, document_ids: list[int] | None = None) -> str:
    doc_json = json.dumps(document_ids) if document_ids is not None else None
    task = store.create(book_id=book_id, task_type="batch_translation", document_ids_json=doc_json)
    return task.task_id


def test_overlap_blocks_for_any_status(task_store: TaskStore):
    """Even completed/cancelled tasks reserve docs."""
    for status in ["queued", "running", "paused", "failed", "completed", "cancelled"]:
        task = task_store.create(book_id="book-1", task_type="batch_translation", document_ids_json=json.dumps([1]))
        task_store.update(task.task_id, status=status)

        assert has_any_batch_task_overlap(task_store, "book-1", [1]) is True
        # Clean up for next iteration
        task_store.delete(task.task_id)


def test_overlap_all_docs_semantics(task_store: TaskStore):
    """document_ids=None overlaps all."""
    _create_task(task_store, "book-1", None)
    assert has_any_batch_task_overlap(task_store, "book-1", [1]) is True
    assert has_any_batch_task_overlap(task_store, "book-1", [2]) is True
    assert has_any_batch_task_overlap(task_store, "book-1", None) is True


def test_exclude_task_ids_allows_self_run(task_store: TaskStore):
    """Selected task can run when excluding its own task_id."""
    task_id = _create_task(task_store, "book-1", [1])
    assert has_any_batch_task_overlap(task_store, "book-1", [1], exclude_task_ids={task_id}) is False
    assert has_any_batch_task_overlap(task_store, "book-1", [1]) is True


def test_delete_task_releases_reservation(task_store: TaskStore):
    """Reservation clears only after task row deletion."""
    task_id = _create_task(task_store, "book-1", [1])
    assert has_any_batch_task_overlap(task_store, "book-1", [1]) is True

    task_store.delete(task_id)

    assert has_any_batch_task_overlap(task_store, "book-1", [1]) is False


def test_no_overlap_with_disjoint_docs(task_store: TaskStore):
    _create_task(task_store, "book-1", [1])
    assert has_any_batch_task_overlap(task_store, "book-1", [2]) is False


def test_no_tasks_no_overlap(task_store: TaskStore):
    assert has_any_batch_task_overlap(task_store, "book-1", [1]) is False
