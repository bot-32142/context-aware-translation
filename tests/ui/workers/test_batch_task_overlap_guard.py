"""Tests for batch_task_overlap_guard."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from context_aware_translation.storage.translation_batch_task_store import TranslationBatchTaskStore
from context_aware_translation.ui.workers.batch_task_overlap_guard import has_any_batch_task_overlap


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "translation_batch_tasks.db"


@pytest.fixture
def book_manager(tmp_path: Path) -> MagicMock:
    bm = MagicMock()
    bm.get_book_db_path.return_value = tmp_path / "book.db"
    return bm


def _create_task(store_path: Path, book_id: str, document_ids: list[int] | None = None) -> str:
    store = TranslationBatchTaskStore(store_path)
    try:
        doc_json = json.dumps(document_ids) if document_ids is not None else None
        task = store.create_task(book_id=book_id, document_ids_json=doc_json)
        return task.task_id
    finally:
        store.close()


def test_overlap_blocks_for_any_status(book_manager: MagicMock, store_path: Path):
    """Even completed/cancelled tasks reserve docs."""
    for status in ["queued", "running", "paused", "failed", "completed", "cancelled"]:
        store = TranslationBatchTaskStore(store_path)
        try:
            task = store.create_task(book_id="book-1", document_ids_json=json.dumps([1]))
            store.update(task.task_id, status=status)
        finally:
            store.close()

        assert has_any_batch_task_overlap(book_manager, "book-1", [1]) is True
        # Clean up for next iteration
        store = TranslationBatchTaskStore(store_path)
        try:
            store.delete_task(task.task_id)
        finally:
            store.close()


def test_overlap_all_docs_semantics(book_manager: MagicMock, store_path: Path):
    """document_ids=None overlaps all."""
    _create_task(store_path, "book-1", None)
    assert has_any_batch_task_overlap(book_manager, "book-1", [1]) is True
    assert has_any_batch_task_overlap(book_manager, "book-1", [2]) is True
    assert has_any_batch_task_overlap(book_manager, "book-1", None) is True


def test_exclude_task_ids_allows_self_run(book_manager: MagicMock, store_path: Path):
    """Selected task can run when excluding its own task_id."""
    task_id = _create_task(store_path, "book-1", [1])
    assert has_any_batch_task_overlap(book_manager, "book-1", [1], exclude_task_ids={task_id}) is False
    assert has_any_batch_task_overlap(book_manager, "book-1", [1]) is True


def test_delete_task_releases_reservation(book_manager: MagicMock, store_path: Path):
    """Reservation clears only after task row deletion."""
    task_id = _create_task(store_path, "book-1", [1])
    assert has_any_batch_task_overlap(book_manager, "book-1", [1]) is True

    store = TranslationBatchTaskStore(store_path)
    try:
        store.delete_task(task_id)
    finally:
        store.close()

    assert has_any_batch_task_overlap(book_manager, "book-1", [1]) is False


def test_no_overlap_with_disjoint_docs(book_manager: MagicMock, store_path: Path):
    _create_task(store_path, "book-1", [1])
    assert has_any_batch_task_overlap(book_manager, "book-1", [2]) is False


def test_no_tasks_no_overlap(book_manager: MagicMock, store_path: Path):  # noqa: ARG001
    assert has_any_batch_task_overlap(book_manager, "book-1", [1]) is False
