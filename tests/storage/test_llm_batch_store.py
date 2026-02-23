from pathlib import Path

from context_aware_translation.storage.llm_batch_store import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_SUBMITTED,
    LLMBatchStore,
)


def test_batch_store_upsert_submitted_and_get(tmp_path: Path) -> None:
    db_path = tmp_path / "batch_cache.db"
    store = LLMBatchStore(db_path)
    store.upsert_submitted("hash-1", "gemini_ai_studio", "batch/jobs/1")

    record = store.get("hash-1")
    assert record is not None
    assert record.status == STATUS_SUBMITTED
    assert record.provider == "gemini_ai_studio"
    assert record.batch_name == "batch/jobs/1"
    assert record.response_text is None
    assert record.error_text is None


def test_batch_store_get_completed_response_does_not_cleanup(tmp_path: Path) -> None:
    db_path = tmp_path / "batch_cache.db"
    store = LLMBatchStore(db_path)
    store.upsert_submitted("hash-2b", "gemini_ai_studio", "batch/jobs/2b")
    store.upsert_completed("hash-2b", "gemini_ai_studio", '{"ok":true}', batch_name="batch/jobs/2b")

    cached = store.get_completed_response("hash-2b")
    assert cached == '{"ok":true}'

    record = store.get("hash-2b")
    assert record is not None
    assert record.status == STATUS_COMPLETED


def test_batch_store_failed_then_resubmitted(tmp_path: Path) -> None:
    db_path = tmp_path / "batch_cache.db"
    store = LLMBatchStore(db_path)
    store.upsert_submitted("hash-3", "gemini_ai_studio", "batch/jobs/3")
    store.upsert_failed("hash-3", "gemini_ai_studio", "failed", batch_name="batch/jobs/3")

    failed = store.get("hash-3")
    assert failed is not None
    assert failed.status == STATUS_FAILED
    assert failed.error_text == "failed"

    store.upsert_submitted("hash-3", "gemini_ai_studio", "batch/jobs/4")
    resubmitted = store.get("hash-3")
    assert resubmitted is not None
    assert resubmitted.status == STATUS_SUBMITTED
    assert resubmitted.batch_name == "batch/jobs/4"
    assert resubmitted.error_text is None


def test_batch_store_persists_across_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "batch_cache.db"
    store = LLMBatchStore(db_path)
    store.upsert_submitted("hash-4", "gemini_ai_studio", "batch/jobs/4")
    store.close()

    reopened = LLMBatchStore(db_path)
    record = reopened.get("hash-4")
    assert record is not None
    assert record.status == STATUS_SUBMITTED
