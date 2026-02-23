from context_aware_translation.storage.translation_batch_task_store import (
    PHASE_TRANSLATION_POLL,
    STATUS_CANCEL_REQUESTED,
    STATUS_RUNNING,
    TranslationBatchTaskStore,
)


def test_translation_batch_task_store_create_and_list(tmp_path):
    db_path = tmp_path / "task_store.db"
    store = TranslationBatchTaskStore(db_path)
    try:
        created = store.create_task(
            book_id="book-1",
            payload_json='{"items":[]}',
            document_ids_json="[1,2]",
            force=True,
            skip_context=False,
        )
        fetched = store.get(created.task_id)
        listed = store.list_tasks("book-1")
    finally:
        store.close()

    assert fetched is not None
    assert fetched.task_id == created.task_id
    assert fetched.force is True
    assert fetched.skip_context is False
    assert listed and listed[0].task_id == created.task_id


def test_translation_batch_task_store_update_and_cancel(tmp_path):
    db_path = tmp_path / "task_store.db"
    store = TranslationBatchTaskStore(db_path)
    try:
        created = store.create_task(book_id="book-2")
        updated = store.update(
            created.task_id,
            status=STATUS_RUNNING,
            phase=PHASE_TRANSLATION_POLL,
            total_items=10,
            completed_items=3,
            failed_items=1,
            translation_batch_name="batch/jobs/1",
            payload_json='{"items":[{"index":0}]}',
            last_error="none",
        )
        cancelled = store.mark_cancel_requested(created.task_id)
    finally:
        store.close()

    assert updated.status == STATUS_RUNNING
    assert updated.phase == PHASE_TRANSLATION_POLL
    assert updated.total_items == 10
    assert updated.completed_items == 3
    assert updated.failed_items == 1
    assert updated.translation_batch_name == "batch/jobs/1"
    assert cancelled.status == STATUS_CANCEL_REQUESTED
    assert cancelled.cancel_requested is True


def test_translation_batch_task_store_delete(tmp_path):
    db_path = tmp_path / "task_store.db"
    store = TranslationBatchTaskStore(db_path)
    try:
        created = store.create_task(book_id="book-3")
        assert store.get(created.task_id) is not None
        store.delete(created.task_id)
        deleted = store.get(created.task_id)
    finally:
        store.close()

    assert deleted is None
