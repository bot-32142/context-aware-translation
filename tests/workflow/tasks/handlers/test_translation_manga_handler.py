from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

from context_aware_translation.storage.task_store import TaskRecord
from context_aware_translation.workflow.tasks.claims import (
    AllDocuments,
    ClaimMode,
    ResourceClaim,
    SomeDocuments,
)
from context_aware_translation.workflow.tasks.handlers.translation_manga import TranslationMangaHandler
from context_aware_translation.workflow.tasks.models import (
    STATUS_CANCEL_REQUESTED,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_COMPLETED_WITH_ERRORS,
    STATUS_FAILED,
    STATUS_PAUSED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    ActionSnapshot,
    TaskAction,
)


def _make_record(
    status: str = STATUS_QUEUED,
    document_ids_json: str | None = None,
    payload_json: str | None = None,
    task_id: str = "task-manga",
    book_id: str = "book-1",
    config_snapshot_json: str | None = None,
) -> TaskRecord:
    now = time.time()
    return TaskRecord(
        task_id=task_id,
        book_id=book_id,
        task_type="translation_manga",
        status=status,
        phase=None,
        document_ids_json=document_ids_json,
        payload_json=payload_json,
        config_snapshot_json=config_snapshot_json,
        cancel_requested=False,
        total_items=0,
        completed_items=0,
        failed_items=0,
        last_error=None,
        created_at=now,
        updated_at=now,
    )


def _make_snapshot(
    running_task_ids: frozenset[str] | None = None,
    active_claims: frozenset[ResourceClaim] | None = None,
) -> ActionSnapshot:
    return ActionSnapshot(
        running_task_ids=running_task_ids or frozenset(),
        active_claims=active_claims or frozenset(),
        now_monotonic=time.monotonic(),
        retry_after_by_book={},
    )


handler = TranslationMangaHandler()


def test_task_type():
    assert handler.task_type == "translation_manga"


def test_decode_payload_empty():
    record = _make_record(payload_json=None)
    assert handler.decode_payload(record) == {}


def test_decode_payload_valid():
    record = _make_record(payload_json='{"force": true}')
    payload = handler.decode_payload(record)
    assert payload["force"] is True


def test_scope_all_documents_when_no_ids():
    record = _make_record(document_ids_json=None)
    scope = handler.scope(record, {})
    assert isinstance(scope, AllDocuments)
    assert scope.book_id == "book-1"


def test_scope_some_documents_when_ids_provided():
    record = _make_record(document_ids_json=json.dumps([10, 20]))
    scope = handler.scope(record, {})
    assert isinstance(scope, SomeDocuments)
    assert scope.doc_ids == frozenset({10, 20})


def test_scope_all_documents_when_empty_list():
    record = _make_record(document_ids_json=json.dumps([]))
    scope = handler.scope(record, {})
    assert isinstance(scope, AllDocuments)


def test_scope_all_documents_on_invalid_json():
    record = _make_record(document_ids_json="not-json")
    scope = handler.scope(record, {})
    assert isinstance(scope, AllDocuments)


def test_claims_all_docs_when_scope_is_all():
    record = _make_record(document_ids_json=None)
    claims = handler.claims(record, {})
    assert ResourceClaim("doc", "book-1", "*") in claims
    assert ResourceClaim("glossary_state", "book-1", "*", ClaimMode.READ_SHARED) in claims


def test_claims_include_context_tree():
    """Manga translation claims context_tree, aligned with workflow.translate()."""
    record = _make_record(document_ids_json=None)
    claims = handler.claims(record, {})
    context_tree_claims = [c for c in claims if c.namespace == "context_tree"]
    assert context_tree_claims == [ResourceClaim("context_tree", "book-1", "*", ClaimMode.WRITE_COOPERATIVE)]


def test_claims_specific_docs_when_scope_is_some():
    record = _make_record(document_ids_json=json.dumps([5, 6]))
    claims = handler.claims(record, {})
    assert ResourceClaim("doc", "book-1", "5") in claims
    assert ResourceClaim("doc", "book-1", "6") in claims
    assert ResourceClaim("doc", "book-1", "*") not in claims


# --- can() tests ---


def test_can_run_queued():
    record = _make_record(status=STATUS_QUEUED)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert result.allowed


def test_can_run_paused():
    record = _make_record(status=STATUS_PAUSED)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert result.allowed


def test_can_run_cancelled():
    record = _make_record(status=STATUS_CANCELLED)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert result.allowed


def test_can_run_failed():
    record = _make_record(status=STATUS_FAILED)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert result.allowed


def test_can_run_completed_with_errors():
    record = _make_record(status=STATUS_COMPLETED_WITH_ERRORS)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert result.allowed


def test_cannot_run_already_running():
    record = _make_record(status=STATUS_RUNNING)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert not result.allowed


def test_cannot_run_completed():
    record = _make_record(status=STATUS_COMPLETED)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert not result.allowed


def test_cannot_run_cancel_requested():
    record = _make_record(status=STATUS_CANCEL_REQUESTED)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert not result.allowed


def test_can_cancel_running():
    record = _make_record(status=STATUS_RUNNING)
    result = handler.can(TaskAction.CANCEL, record, {}, _make_snapshot())
    assert result.allowed


def test_cannot_cancel_completed():
    record = _make_record(status=STATUS_COMPLETED)
    result = handler.can(TaskAction.CANCEL, record, {}, _make_snapshot())
    assert not result.allowed


def test_can_delete_queued():
    record = _make_record(status=STATUS_QUEUED)
    result = handler.can(TaskAction.DELETE, record, {}, _make_snapshot())
    assert result.allowed


def test_cannot_delete_running():
    record = _make_record(status=STATUS_RUNNING)
    result = handler.can(TaskAction.DELETE, record, {}, _make_snapshot())
    assert not result.allowed


def test_cannot_delete_cancel_requested():
    record = _make_record(status=STATUS_CANCEL_REQUESTED)
    result = handler.can(TaskAction.DELETE, record, {}, _make_snapshot())
    assert not result.allowed


# --- can_autorun() tests ---


def test_can_autorun_always_returns_not_allowed():
    """Manga translation never autoruns — requires explicit initiation."""
    record = _make_record(status=STATUS_QUEUED)
    result = handler.can_autorun(record, {}, _make_snapshot())
    assert not result.allowed


def test_can_autorun_not_allowed_even_paused_no_conflicts():
    record = _make_record(status=STATUS_PAUSED)
    result = handler.can_autorun(record, {}, _make_snapshot())
    assert not result.allowed


# --- validate_submit() tests ---


def _make_submit_deps(tmp_path, documents, has_manga_config=True):
    """Build a WorkerDeps mock for validate_submit tests."""
    from context_aware_translation.config import MangaTranslatorConfig

    deps = MagicMock()
    deps.book_manager.get_book.return_value = MagicMock()
    deps.book_manager.library_root = tmp_path
    deps.book_manager.registry = MagicMock()
    deps.book_manager.get_book_db_path.return_value = tmp_path / "book.db"

    fake_config = MagicMock()
    fake_config.manga_translator_config = MangaTranslatorConfig(api_key="k", base_url="u") if has_manga_config else None

    fake_db = MagicMock()
    fake_repo = MagicMock()
    fake_repo.list_documents.return_value = documents

    return deps, fake_config, fake_db, fake_repo


_HANDLER_MOD = "context_aware_translation.workflow.tasks.handlers.translation_manga"


def test_validate_submit_rejects_missing_manga_config(tmp_path):
    deps = MagicMock()
    deps.book_manager.get_book.return_value = MagicMock()
    deps.book_manager.library_root = tmp_path
    deps.book_manager.registry = MagicMock()

    fake_config = MagicMock()
    fake_config.manga_translator_config = None

    with patch(f"{_HANDLER_MOD}.config_module.Config") as mock_config_cls:
        mock_config_cls.from_book.return_value = fake_config
        result = handler.validate_submit("book-1", {}, deps)

    assert not result.allowed
    assert "manga_translator_config" in result.reason


def test_validate_submit_rejects_non_manga_documents(tmp_path):
    docs = [
        {"document_id": 1, "document_type": "text"},
        {"document_id": 2, "document_type": "manga"},
    ]
    deps, fake_config, fake_db, fake_repo = _make_submit_deps(tmp_path, docs)

    with (
        patch(f"{_HANDLER_MOD}.config_module.Config") as mock_config_cls,
        patch(f"{_HANDLER_MOD}.book_db.SQLiteBookDB", return_value=fake_db),
        patch(f"{_HANDLER_MOD}.document_repository.DocumentRepository", return_value=fake_repo),
    ):
        mock_config_cls.from_book.return_value = fake_config
        result = handler.validate_submit("book-1", {}, deps)

    assert not result.allowed
    assert "manga type" in result.reason


def test_validate_submit_allows_all_manga_documents(tmp_path):
    docs = [{"document_id": 1, "document_type": "manga"}, {"document_id": 2, "document_type": "manga"}]
    deps, fake_config, fake_db, fake_repo = _make_submit_deps(tmp_path, docs)

    with (
        patch(f"{_HANDLER_MOD}.config_module.Config") as mock_config_cls,
        patch(f"{_HANDLER_MOD}.book_db.SQLiteBookDB", return_value=fake_db),
        patch(f"{_HANDLER_MOD}.document_repository.DocumentRepository", return_value=fake_repo),
    ):
        mock_config_cls.from_book.return_value = fake_config
        result = handler.validate_submit("book-1", {}, deps)

    assert result.allowed


def test_validate_submit_with_selected_manga_doc_ids(tmp_path):
    docs = [
        {"document_id": 1, "document_type": "manga"},
        {"document_id": 2, "document_type": "text"},  # not selected
    ]
    deps, fake_config, fake_db, fake_repo = _make_submit_deps(tmp_path, docs)

    with (
        patch(f"{_HANDLER_MOD}.config_module.Config") as mock_config_cls,
        patch(f"{_HANDLER_MOD}.book_db.SQLiteBookDB", return_value=fake_db),
        patch(f"{_HANDLER_MOD}.document_repository.DocumentRepository", return_value=fake_repo),
    ):
        mock_config_cls.from_book.return_value = fake_config
        result = handler.validate_submit("book-1", {"document_ids": [1]}, deps)

    assert result.allowed


def test_validate_submit_rejects_book_not_found():
    deps = MagicMock()
    deps.book_manager.get_book.return_value = None
    result = handler.validate_submit("missing-book", {}, deps)
    assert not result.allowed
    assert "not found" in result.reason.lower()


# --- validate_run() tests ---


def test_validate_run_rejects_missing_manga_config(tmp_path):
    deps = MagicMock()
    deps.book_manager.get_book.return_value = MagicMock()
    deps.book_manager.library_root = tmp_path
    deps.book_manager.registry = MagicMock()

    fake_config = MagicMock()
    fake_config.manga_translator_config = None

    record = _make_record(status=STATUS_QUEUED)

    with patch(f"{_HANDLER_MOD}.config_module.Config") as mock_config_cls:
        mock_config_cls.from_book.return_value = fake_config
        result = handler.validate_run(record, {}, deps)

    assert not result.allowed
    assert "manga_translator_config" in result.reason


def test_validate_run_rejects_non_manga_documents(tmp_path):
    docs = [{"document_id": 1, "document_type": "pdf"}]
    deps, fake_config, fake_db, fake_repo = _make_submit_deps(tmp_path, docs)

    record = _make_record(status=STATUS_QUEUED)

    with (
        patch(f"{_HANDLER_MOD}.config_module.Config") as mock_config_cls,
        patch(f"{_HANDLER_MOD}.book_db.SQLiteBookDB", return_value=fake_db),
        patch(f"{_HANDLER_MOD}.document_repository.DocumentRepository", return_value=fake_repo),
    ):
        mock_config_cls.from_book.return_value = fake_config
        result = handler.validate_run(record, {}, deps)

    assert not result.allowed


def test_validate_run_allows_manga_documents(tmp_path):
    docs = [{"document_id": 1, "document_type": "manga"}]
    deps, fake_config, fake_db, fake_repo = _make_submit_deps(tmp_path, docs)

    record = _make_record(status=STATUS_QUEUED)

    with (
        patch(f"{_HANDLER_MOD}.config_module.Config") as mock_config_cls,
        patch(f"{_HANDLER_MOD}.book_db.SQLiteBookDB", return_value=fake_db),
        patch(f"{_HANDLER_MOD}.document_repository.DocumentRepository", return_value=fake_repo),
    ):
        mock_config_cls.from_book.return_value = fake_config
        result = handler.validate_run(record, {}, deps)

    assert result.allowed


# --- build_worker() tests ---


def test_build_worker_run_returns_translation_manga_task_worker():
    from context_aware_translation.ui.workers.translation_manga_task_worker import TranslationMangaTaskWorker

    deps = MagicMock()
    record = _make_record(status=STATUS_QUEUED, document_ids_json=json.dumps([1, 2]))
    payload = handler.decode_payload(record)
    worker = handler.build_worker(TaskAction.RUN, record, payload, deps)
    assert isinstance(worker, TranslationMangaTaskWorker)


def test_build_worker_run_wires_document_ids():
    deps = MagicMock()
    record = _make_record(status=STATUS_QUEUED, document_ids_json=json.dumps([10, 20]))
    payload = handler.decode_payload(record)
    worker = handler.build_worker(TaskAction.RUN, record, payload, deps)
    assert worker._document_ids == [10, 20]


def test_build_worker_run_passes_config_snapshot():
    from context_aware_translation.ui.workers.translation_manga_task_worker import TranslationMangaTaskWorker

    snapshot = json.dumps({"snapshot_version": 1, "config": {"key": "val"}})
    deps = MagicMock()
    record = _make_record(status=STATUS_QUEUED, config_snapshot_json=snapshot)
    payload = handler.decode_payload(record)
    worker = handler.build_worker(TaskAction.RUN, record, payload, deps)

    assert isinstance(worker, TranslationMangaTaskWorker)
    assert worker._config_snapshot_json == snapshot


def test_build_worker_cancel_returns_translation_manga_task_worker():
    from context_aware_translation.ui.workers.translation_manga_task_worker import TranslationMangaTaskWorker

    deps = MagicMock()
    record = _make_record(status=STATUS_RUNNING)
    worker = handler.build_worker(TaskAction.CANCEL, record, {}, deps)
    assert isinstance(worker, TranslationMangaTaskWorker)


def test_pre_delete_returns_empty_list():
    record = _make_record()
    assert handler.pre_delete(record, {}, MagicMock()) == []
