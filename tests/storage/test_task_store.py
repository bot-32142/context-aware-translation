from __future__ import annotations

import threading
import time

import pytest

from context_aware_translation.storage.repositories.task_store import TaskRecord, TaskStore


def test_create_returns_valid_record(tmp_path):
    db_path = tmp_path / "tasks.db"
    store = TaskStore(db_path)
    try:
        record = store.create(book_id="book-1", task_type="translation")
    finally:
        store.close()

    assert isinstance(record, TaskRecord)
    assert record.status == "queued"
    assert record.book_id == "book-1"
    assert record.task_type == "translation"
    assert record.cancel_requested is False
    assert record.total_items == 0
    assert record.completed_items == 0
    assert record.failed_items == 0
    assert record.phase is None
    assert record.last_error is None
    assert record.task_id != ""


def test_get_returns_none_for_missing(tmp_path):
    db_path = tmp_path / "tasks.db"
    store = TaskStore(db_path)
    try:
        result = store.get("nonexistent-id")
    finally:
        store.close()

    assert result is None


def test_get_returns_correct_record_after_create(tmp_path):
    db_path = tmp_path / "tasks.db"
    store = TaskStore(db_path)
    try:
        created = store.create(
            book_id="book-2",
            task_type="glossary",
            document_ids_json="[1,2,3]",
            payload_json='{"key":"val"}',
            status="queued",
            phase="prepare",
        )
        fetched = store.get(created.task_id)
    finally:
        store.close()

    assert fetched is not None
    assert fetched.task_id == created.task_id
    assert fetched.book_id == "book-2"
    assert fetched.task_type == "glossary"
    assert fetched.document_ids_json == "[1,2,3]"
    assert fetched.payload_json == '{"key":"val"}'
    assert fetched.phase == "prepare"


def test_task_store_instances_share_file_lock_for_writes(tmp_path):
    db_path = tmp_path / "tasks.db"
    first_store = TaskStore(db_path)
    second_store = TaskStore(db_path)
    finished = threading.Event()
    errors: list[Exception] = []

    def create_from_second_store() -> None:
        try:
            second_store.create(book_id="book-2", task_type="translation")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            finished.set()

    lock_acquired = False
    try:
        first_store._lock.acquire()
        lock_acquired = True
        worker = threading.Thread(target=create_from_second_store)
        worker.start()
        time.sleep(0.2)
        assert not finished.is_set()
        first_store._lock.release()
        lock_acquired = False
        worker.join(2)
    finally:
        if lock_acquired:
            first_store._lock.release()
        first_store.close()
        second_store.close()

    assert errors == []
    assert finished.is_set()


def test_update_changes_fields_and_bumps_updated_at(tmp_path):
    db_path = tmp_path / "tasks.db"
    store = TaskStore(db_path)
    try:
        created = store.create(book_id="book-3", task_type="translation")
        before_updated_at = created.updated_at
        time.sleep(0.01)
        updated = store.update(
            created.task_id,
            status="running",
            phase="translate",
            total_items=10,
            completed_items=3,
            failed_items=1,
            last_error="some error",
        )
    finally:
        store.close()

    assert updated.status == "running"
    assert updated.phase == "translate"
    assert updated.total_items == 10
    assert updated.completed_items == 3
    assert updated.failed_items == 1
    assert updated.last_error == "some error"
    assert updated.updated_at > before_updated_at


def test_update_raises_key_error_for_missing(tmp_path):
    db_path = tmp_path / "tasks.db"
    store = TaskStore(db_path)
    try:
        with pytest.raises(KeyError):
            store.update("nonexistent-id", status="running")
    finally:
        store.close()


def test_list_tasks_returns_all_when_no_filters(tmp_path):
    db_path = tmp_path / "tasks.db"
    store = TaskStore(db_path)
    try:
        for i in range(5):
            store.create(book_id=f"book-{i}", task_type="translation")
        results = store.list_tasks()
    finally:
        store.close()

    assert len(results) == 5


def test_list_tasks_filters_by_book_id(tmp_path):
    db_path = tmp_path / "tasks.db"
    store = TaskStore(db_path)
    try:
        store.create(book_id="book-a", task_type="translation")
        store.create(book_id="book-a", task_type="glossary")
        store.create(book_id="book-b", task_type="translation")
        results = store.list_tasks(book_id="book-a")
    finally:
        store.close()

    assert len(results) == 2
    assert all(r.book_id == "book-a" for r in results)


def test_list_tasks_filters_by_task_type(tmp_path):
    db_path = tmp_path / "tasks.db"
    store = TaskStore(db_path)
    try:
        store.create(book_id="book-c", task_type="translation")
        store.create(book_id="book-c", task_type="glossary")
        store.create(book_id="book-d", task_type="translation")
        results = store.list_tasks(task_type="translation")
    finally:
        store.close()

    assert len(results) == 2
    assert all(r.task_type == "translation" for r in results)


def test_list_tasks_limit_caps_results(tmp_path):
    db_path = tmp_path / "tasks.db"
    store = TaskStore(db_path)
    try:
        for _i in range(10):
            store.create(book_id="book-e", task_type="translation")
        results = store.list_tasks(limit=3)
    finally:
        store.close()

    assert len(results) == 3


def test_delete_removes_task(tmp_path):
    db_path = tmp_path / "tasks.db"
    store = TaskStore(db_path)
    try:
        created = store.create(book_id="book-f", task_type="translation")
        assert store.get(created.task_id) is not None
        store.delete(created.task_id)
        result = store.get(created.task_id)
    finally:
        store.close()

    assert result is None


def test_mark_cancel_requested_sets_both_fields(tmp_path):
    db_path = tmp_path / "tasks.db"
    store = TaskStore(db_path)
    try:
        created = store.create(book_id="book-g", task_type="translation")
        cancelled = store.mark_cancel_requested(created.task_id)
    finally:
        store.close()

    assert cancelled.cancel_requested is True
    assert cancelled.status == "cancel_requested"


def test_multiple_creates_generate_unique_task_ids(tmp_path):
    db_path = tmp_path / "tasks.db"
    store = TaskStore(db_path)
    try:
        records = [store.create(book_id="book-h", task_type="translation") for _ in range(10)]
    finally:
        store.close()

    task_ids = [r.task_id for r in records]
    assert len(set(task_ids)) == 10


# ---------------------------------------------------------------------------
# config_snapshot_json round-trip
# ---------------------------------------------------------------------------


def test_config_snapshot_json_round_trips_through_create_and_get(tmp_path):
    """config_snapshot_json written via create() must be returned verbatim by get()."""
    import json

    snapshot = json.dumps({"snapshot_version": 1, "config": {"key": "value"}})
    db_path = tmp_path / "tasks.db"
    store = TaskStore(db_path)
    try:
        created = store.create(
            book_id="book-snap",
            task_type="translation",
            config_snapshot_json=snapshot,
        )
        fetched = store.get(created.task_id)
    finally:
        store.close()

    assert created.config_snapshot_json == snapshot
    assert fetched is not None
    assert fetched.config_snapshot_json == snapshot


def test_config_snapshot_json_defaults_to_none(tmp_path):
    """config_snapshot_json is None when not supplied."""
    db_path = tmp_path / "tasks.db"
    store = TaskStore(db_path)
    try:
        created = store.create(book_id="book-no-snap", task_type="translation")
        fetched = store.get(created.task_id)
    finally:
        store.close()

    assert created.config_snapshot_json is None
    assert fetched is not None
    assert fetched.config_snapshot_json is None


def test_config_snapshot_json_migration_adds_column(tmp_path):
    """Opening an older DB without config_snapshot_json column should migrate it via ALTER TABLE."""
    import sqlite3

    db_path = tmp_path / "old_tasks.db"

    # Create a DB without config_snapshot_json (simulating an older schema)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY,
            book_id TEXT NOT NULL,
            task_type TEXT NOT NULL,
            status TEXT NOT NULL,
            phase TEXT,
            document_ids_json TEXT,
            payload_json TEXT,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            total_items INTEGER NOT NULL DEFAULT 0,
            completed_items INTEGER NOT NULL DEFAULT 0,
            failed_items INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
    """)
    conn.commit()
    conn.close()

    # Opening TaskStore should migrate the column without error
    store = TaskStore(db_path)
    try:
        record = store.create(book_id="book-migrated", task_type="translation")
    finally:
        store.close()

    assert record.config_snapshot_json is None

    # Verify the column now exists
    conn2 = sqlite3.connect(db_path)
    cols = {row[1] for row in conn2.execute("PRAGMA table_info(tasks)").fetchall()}
    conn2.close()
    assert "config_snapshot_json" in cols
