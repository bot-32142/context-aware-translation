from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

from context_aware_translation.config import (
    Config,
    ExtractorConfig,
    GlossaryTranslationConfig,
    ImageReembeddingConfig,
    MangaTranslatorConfig,
    OCRConfig,
    ReviewConfig,
    SummarizorConfig,
    TranslatorBatchConfig,
    TranslatorConfig,
)
from context_aware_translation.storage.repositories.task_store import TaskRecord
from context_aware_translation.workflow.tasks.handlers.translate_and_export import TranslateAndExportHandler
from context_aware_translation.workflow.tasks.models import (
    STATUS_CANCELLED,
    STATUS_CANCELLING,
    STATUS_QUEUED,
    STATUS_RUNNING,
)


def _make_record(
    *,
    status: str = STATUS_QUEUED,
    document_ids: list[int] | None = None,
    payload: dict | None = None,
    task_id: str = "task-one-shot",
    book_id: str = "book-1",
    phase: str | None = None,
    config_snapshot_json: str | None = None,
) -> TaskRecord:
    now = time.time()
    return TaskRecord(
        task_id=task_id,
        book_id=book_id,
        task_type="translate_and_export",
        status=status,
        phase=phase,
        document_ids_json=json.dumps(document_ids if document_ids is not None else [4]),
        payload_json=json.dumps(
            payload
            if payload is not None
            else {
                "format_id": "txt",
                "output_path": "/tmp/out.txt",
                "use_batch": False,
                "use_reembedding": False,
                "enable_polish": True,
                "options": {},
            }
        ),
        config_snapshot_json=config_snapshot_json,
        cancel_requested=False,
        total_items=0,
        completed_items=0,
        failed_items=0,
        last_error=None,
        created_at=now,
        updated_at=now,
    )


def _make_config() -> Config:
    shared = {"api_key": "key", "base_url": "https://example.invalid/v1", "model": "demo-model"}
    return Config(
        translation_target_language="English",
        extractor_config=ExtractorConfig(**shared),
        summarizor_config=SummarizorConfig(**shared),
        glossary_config=GlossaryTranslationConfig(**shared),
        translator_config=TranslatorConfig(**shared),
        translator_batch_config=TranslatorBatchConfig(
            provider="gemini_ai_studio",
            api_key="key",
            model="batch-model",
        ),
        review_config=ReviewConfig(**shared),
        ocr_config=OCRConfig(**shared),
        image_reembedding_config=ImageReembeddingConfig(**shared),
        manga_translator_config=MangaTranslatorConfig(**shared),
    )


def _make_deps(tmp_path, *, document_type: str = "text", touched: bool = False):
    deps = MagicMock()
    deps.book_manager.get_book.return_value = MagicMock()
    deps.book_manager.get_book_db_path.return_value = tmp_path / "book.db"
    deps.book_manager.library_root = tmp_path
    deps.book_manager.registry = MagicMock()
    deps.task_store.list_tasks.return_value = []

    fake_db = MagicMock()
    fake_repo = MagicMock()
    fake_repo.get_document_by_id.return_value = {"document_id": 4, "document_type": document_type}
    fake_repo.get_document_sources_metadata.return_value = []
    fake_repo.get_chunk_count.return_value = 1 if touched else 0
    fake_repo.load_reembedded_images.return_value = {}
    return deps, fake_db, fake_repo


handler = TranslateAndExportHandler()


def test_validate_submit_rejects_touched_document(tmp_path):
    deps, fake_db, fake_repo = _make_deps(tmp_path, touched=True)
    params = {"document_ids": [4], "format_id": "txt", "output_path": "/tmp/out.txt", "options": {}}
    with (
        patch(
            "context_aware_translation.workflow.tasks.translate_and_export_support.config_module.Config.from_book",
            return_value=_make_config(),
        ),
        patch(
            "context_aware_translation.workflow.tasks.translate_and_export_support.book_db.SQLiteBookDB",
            return_value=fake_db,
        ),
        patch(
            "context_aware_translation.workflow.tasks.translate_and_export_support.document_repository.DocumentRepository",
            return_value=fake_repo,
        ),
    ):
        result = handler.validate_submit("book-1", params, deps)

    assert not result.allowed
    assert result.code == "document_touched"


def test_validate_submit_rejects_batch_for_manga(tmp_path):
    deps, fake_db, fake_repo = _make_deps(tmp_path, document_type="manga")
    params = {"document_ids": [4], "format_id": "cbz", "output_path": "/tmp/out.cbz", "use_batch": True, "options": {}}
    with (
        patch(
            "context_aware_translation.workflow.tasks.translate_and_export_support.config_module.Config.from_book",
            return_value=_make_config(),
        ),
        patch(
            "context_aware_translation.workflow.tasks.translate_and_export_support.book_db.SQLiteBookDB",
            return_value=fake_db,
        ),
        patch(
            "context_aware_translation.workflow.tasks.translate_and_export_support.document_repository.DocumentRepository",
            return_value=fake_repo,
        ),
    ):
        result = handler.validate_submit("book-1", params, deps)

    assert not result.allowed
    assert "non-manga" in (result.reason or "").lower()


def test_validate_run_rejects_stale_resume_guard(tmp_path):
    deps, fake_db, fake_repo = _make_deps(tmp_path)
    record = _make_record(
        status=STATUS_CANCELLED,
        payload={
            "format_id": "txt",
            "output_path": "/tmp/out.txt",
            "use_batch": False,
            "use_reembedding": False,
            "enable_polish": True,
            "options": {},
            "resume_guard": "before",
            "resume_guard_required": True,
        },
    )
    payload = handler.decode_payload(record)
    with (
        patch(
            "context_aware_translation.workflow.tasks.translate_and_export_support.config_module.Config.from_book",
            return_value=_make_config(),
        ),
        patch(
            "context_aware_translation.workflow.tasks.translate_and_export_support.book_db.SQLiteBookDB",
            return_value=fake_db,
        ),
        patch(
            "context_aware_translation.workflow.tasks.translate_and_export_support.document_repository.DocumentRepository",
            return_value=fake_repo,
        ),
        patch(
            "context_aware_translation.workflow.tasks.translate_and_export_support.compute_resume_guard",
            return_value="after",
        ),
    ):
        result = handler.validate_run(record, payload, deps)

    assert not result.allowed
    assert result.code == "stale_resume_state"


def test_validate_run_rejects_stale_resume_guard_after_rerun_queue_state(tmp_path):
    deps, fake_db, fake_repo = _make_deps(tmp_path)
    record = _make_record(
        status=STATUS_QUEUED,
        payload={
            "format_id": "txt",
            "output_path": "/tmp/out.txt",
            "use_batch": False,
            "use_reembedding": False,
            "enable_polish": True,
            "options": {},
            "resume_guard": "before",
            "resume_guard_required": True,
        },
    )
    payload = handler.decode_payload(record)
    with (
        patch(
            "context_aware_translation.workflow.tasks.translate_and_export_support.config_module.Config.from_book",
            return_value=_make_config(),
        ),
        patch(
            "context_aware_translation.workflow.tasks.translate_and_export_support.book_db.SQLiteBookDB",
            return_value=fake_db,
        ),
        patch(
            "context_aware_translation.workflow.tasks.translate_and_export_support.document_repository.DocumentRepository",
            return_value=fake_repo,
        ),
        patch(
            "context_aware_translation.workflow.tasks.translate_and_export_support.compute_resume_guard",
            return_value="after",
        ),
    ):
        result = handler.validate_run(record, payload, deps)

    assert not result.allowed
    assert result.code == "stale_resume_state"


def test_validate_run_does_not_enforce_resume_guard_for_cancelling_batch_cleanup(tmp_path):
    deps, fake_db, fake_repo = _make_deps(tmp_path)
    record = _make_record(
        status=STATUS_CANCELLING,
        phase="translation_poll",
        payload={
            "format_id": "txt",
            "output_path": "/tmp/out.txt",
            "use_batch": True,
            "use_reembedding": False,
            "enable_polish": True,
            "options": {},
            "resume_guard": "before",
        },
    )
    payload = handler.decode_payload(record)
    with (
        patch(
            "context_aware_translation.workflow.tasks.translate_and_export_support.config_module.Config.from_book",
            return_value=_make_config(),
        ),
        patch(
            "context_aware_translation.workflow.tasks.translate_and_export_support.book_db.SQLiteBookDB",
            return_value=fake_db,
        ),
        patch(
            "context_aware_translation.workflow.tasks.translate_and_export_support.document_repository.DocumentRepository",
            return_value=fake_repo,
        ),
        patch(
            "context_aware_translation.workflow.tasks.translate_and_export_support.compute_resume_guard",
            return_value="after",
        ),
    ):
        result = handler.validate_run(record, payload, deps)

    assert result.allowed is True


def test_cancel_dispatch_policy_requires_provider_confirmation_for_batch_phases():
    record = _make_record(phase="translation_poll")
    payload = {"use_batch": True}

    result = handler.cancel_dispatch_policy(record, payload)

    assert result.value == "require_remote_confirmation"


def test_can_autorun_allows_batch_cancelling_resume_in_remote_phase():
    snapshot = MagicMock(running_task_ids=frozenset(), active_claims=frozenset())
    record = _make_record(status=STATUS_CANCELLING, phase="translation_poll", payload={"use_batch": True})

    result = handler.can_autorun(record, handler.decode_payload(record), snapshot)

    assert result.allowed is True


def test_can_autorun_rejects_local_running_phase_even_when_batch_enabled():
    snapshot = MagicMock(running_task_ids=frozenset(), active_claims=frozenset())
    record = _make_record(status=STATUS_RUNNING, phase="extract_terms", payload={"use_batch": True})

    result = handler.can_autorun(record, handler.decode_payload(record), snapshot)

    assert result.allowed is False
