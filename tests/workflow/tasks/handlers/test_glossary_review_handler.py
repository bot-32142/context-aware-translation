from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from context_aware_translation.storage.repositories.task_store import TaskRecord
from context_aware_translation.workflow.tasks.claims import (
    ClaimMode,
    NoDocuments,
    ResourceClaim,
)
from context_aware_translation.workflow.tasks.handlers.glossary_review import GlossaryReviewHandler
from context_aware_translation.workflow.tasks.models import (
    STATUS_CANCEL_REQUESTED,
    STATUS_CANCELLED,
    STATUS_CANCELLING,
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
    task_id: str = "task-review",
    book_id: str = "book-1",
    payload_json: str | None = None,
    config_snapshot_json: str | None = None,
) -> TaskRecord:
    now = time.time()
    return TaskRecord(
        task_id=task_id,
        book_id=book_id,
        task_type="glossary_review",
        status=status,
        phase=None,
        document_ids_json=None,
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


handler = GlossaryReviewHandler()


# --- task_type ---


def test_task_type():
    assert handler.task_type == "glossary_review"


# --- decode_payload ---


def test_decode_payload_empty():
    record = _make_record(payload_json=None)
    assert handler.decode_payload(record) == {}


def test_decode_payload_valid():
    record = _make_record(payload_json='{"key": "value"}')
    payload = handler.decode_payload(record)
    assert payload["key"] == "value"


# --- scope ---


def test_scope_returns_no_documents():
    record = _make_record()
    scope = handler.scope(record, {})
    assert isinstance(scope, NoDocuments)
    assert scope.book_id == "book-1"


# --- claims ---


def test_claims_returns_glossary_state_write_exclusive():
    record = _make_record()
    claims = handler.claims(record, {})
    expected = ResourceClaim("glossary_state", "book-1", "*", ClaimMode.WRITE_EXCLUSIVE)
    assert expected in claims
    assert len(claims) == 1


# --- can() RUN ---


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


def test_cannot_run_running():
    record = _make_record(status=STATUS_RUNNING)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert not result.allowed
    assert "running" in result.reason.lower()


def test_cannot_run_completed():
    record = _make_record(status=STATUS_COMPLETED)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert not result.allowed


def test_cannot_run_cancel_requested():
    record = _make_record(status=STATUS_CANCEL_REQUESTED)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert not result.allowed


def test_cannot_run_cancelling():
    record = _make_record(status=STATUS_CANCELLING)
    result = handler.can(TaskAction.RUN, record, {}, _make_snapshot())
    assert not result.allowed


# --- can() CANCEL ---


def test_can_cancel_running():
    record = _make_record(status=STATUS_RUNNING)
    result = handler.can(TaskAction.CANCEL, record, {}, _make_snapshot())
    assert result.allowed


def test_can_cancel_queued():
    record = _make_record(status=STATUS_QUEUED)
    result = handler.can(TaskAction.CANCEL, record, {}, _make_snapshot())
    assert result.allowed


def test_cannot_cancel_completed():
    record = _make_record(status=STATUS_COMPLETED)
    result = handler.can(TaskAction.CANCEL, record, {}, _make_snapshot())
    assert not result.allowed


def test_cannot_cancel_failed():
    record = _make_record(status=STATUS_FAILED)
    result = handler.can(TaskAction.CANCEL, record, {}, _make_snapshot())
    assert not result.allowed


# --- can() DELETE ---


def test_can_delete_queued():
    record = _make_record(status=STATUS_QUEUED)
    result = handler.can(TaskAction.DELETE, record, {}, _make_snapshot())
    assert result.allowed


def test_can_delete_completed():
    record = _make_record(status=STATUS_COMPLETED)
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


def test_cannot_delete_cancelling():
    record = _make_record(status=STATUS_CANCELLING)
    result = handler.can(TaskAction.DELETE, record, {}, _make_snapshot())
    assert not result.allowed


# --- can_autorun() ---


def test_can_autorun_queued_no_conflicts():
    record = _make_record(status=STATUS_QUEUED)
    result = handler.can_autorun(record, {}, _make_snapshot())
    assert result.allowed


def test_can_autorun_paused_no_conflicts():
    record = _make_record(status=STATUS_PAUSED)
    result = handler.can_autorun(record, {}, _make_snapshot())
    assert result.allowed


def test_cannot_autorun_running():
    record = _make_record(status=STATUS_RUNNING)
    result = handler.can_autorun(record, {}, _make_snapshot())
    assert not result.allowed


def test_cannot_autorun_completed():
    record = _make_record(status=STATUS_COMPLETED)
    result = handler.can_autorun(record, {}, _make_snapshot())
    assert not result.allowed


def test_cannot_autorun_already_in_running_set():
    record = _make_record(status=STATUS_QUEUED, task_id="task-review")
    result = handler.can_autorun(record, {}, _make_snapshot(running_task_ids=frozenset({"task-review"})))
    assert not result.allowed


def test_cannot_autorun_with_claim_conflict():
    record = _make_record(status=STATUS_QUEUED, book_id="book-1")
    active_claim = ResourceClaim("glossary_state", "book-1", "*", ClaimMode.WRITE_EXCLUSIVE)
    result = handler.can_autorun(record, {}, _make_snapshot(active_claims=frozenset({active_claim})))
    assert not result.allowed


# --- validate_submit() ---


def test_validate_submit_denied_when_book_not_found():
    deps = MagicMock()
    deps.book_manager.get_book.return_value = None
    result = handler.validate_submit("book-1", {}, deps)
    assert not result.allowed
    assert "book-1" in result.reason


def test_validate_submit_denied_when_no_review_config(tmp_path):
    deps = MagicMock()
    fake_book = MagicMock()
    deps.book_manager.get_book.return_value = fake_book
    deps.book_manager.library_root = tmp_path
    deps.book_manager.registry = MagicMock()

    fake_config = MagicMock()
    fake_config.review_config = None

    with patch(
        "context_aware_translation.config.Config.from_book",
        return_value=fake_config,
    ):
        result = handler.validate_submit("book-1", {}, deps)

    assert not result.allowed
    assert result.code == "no_review_config"


def test_validate_submit_denied_when_no_pending_review_terms(tmp_path):
    deps = MagicMock()
    fake_book = MagicMock()
    deps.book_manager.get_book.return_value = fake_book
    deps.book_manager.library_root = tmp_path
    deps.book_manager.registry = MagicMock()
    deps.book_manager.get_book_db_path.return_value = tmp_path / "book.db"

    fake_config = MagicMock()
    fake_config.review_config = MagicMock()

    fake_db = MagicMock()
    fake_term_repo = MagicMock()
    fake_term_repo.get_terms_pending_review.return_value = []

    with (
        patch(
            "context_aware_translation.config.Config.from_book",
            return_value=fake_config,
        ),
        patch(
            "context_aware_translation.storage.schema.book_db.SQLiteBookDB",
            return_value=fake_db,
        ),
        patch(
            "context_aware_translation.storage.repositories.term_repository.TermRepository",
            return_value=fake_term_repo,
        ),
    ):
        result = handler.validate_submit("book-1", {}, deps)

    assert not result.allowed
    assert result.code == "no_pending_terms"


def test_validate_submit_allowed_when_pending_terms_exist(tmp_path):
    deps = MagicMock()
    fake_book = MagicMock()
    deps.book_manager.get_book.return_value = fake_book
    deps.book_manager.library_root = tmp_path
    deps.book_manager.registry = MagicMock()
    deps.book_manager.get_book_db_path.return_value = tmp_path / "book.db"

    fake_config = MagicMock()
    fake_config.review_config = MagicMock()

    fake_db = MagicMock()
    fake_term_repo = MagicMock()
    fake_term_repo.get_terms_pending_review.return_value = [MagicMock()]

    with (
        patch(
            "context_aware_translation.config.Config.from_book",
            return_value=fake_config,
        ),
        patch(
            "context_aware_translation.storage.schema.book_db.SQLiteBookDB",
            return_value=fake_db,
        ),
        patch(
            "context_aware_translation.storage.repositories.term_repository.TermRepository",
            return_value=fake_term_repo,
        ),
    ):
        result = handler.validate_submit("book-1", {}, deps)

    assert result.allowed


# --- validate_run() ---


def test_validate_run_denied_when_book_not_found():
    record = _make_record()
    deps = MagicMock()
    deps.book_manager.get_book.return_value = None
    result = handler.validate_run(record, {}, deps)
    assert not result.allowed


def test_validate_run_denied_when_no_review_config(tmp_path):
    record = _make_record()
    deps = MagicMock()
    fake_book = MagicMock()
    deps.book_manager.get_book.return_value = fake_book
    deps.book_manager.library_root = tmp_path
    deps.book_manager.registry = MagicMock()

    fake_config = MagicMock()
    fake_config.review_config = None

    with patch(
        "context_aware_translation.config.Config.from_book",
        return_value=fake_config,
    ):
        result = handler.validate_run(record, {}, deps)

    assert not result.allowed
    assert result.code == "no_review_config"


def test_validate_run_allowed_when_pending_terms_exist(tmp_path):
    record = _make_record()
    deps = MagicMock()
    fake_book = MagicMock()
    deps.book_manager.get_book.return_value = fake_book
    deps.book_manager.library_root = tmp_path
    deps.book_manager.registry = MagicMock()
    deps.book_manager.get_book_db_path.return_value = tmp_path / "book.db"

    fake_config = MagicMock()
    fake_config.review_config = MagicMock()

    fake_db = MagicMock()
    fake_term_repo = MagicMock()
    fake_term_repo.get_terms_pending_review.return_value = [MagicMock()]

    with (
        patch(
            "context_aware_translation.config.Config.from_book",
            return_value=fake_config,
        ),
        patch(
            "context_aware_translation.storage.schema.book_db.SQLiteBookDB",
            return_value=fake_db,
        ),
        patch(
            "context_aware_translation.storage.repositories.term_repository.TermRepository",
            return_value=fake_term_repo,
        ),
    ):
        result = handler.validate_run(record, {}, deps)

    assert result.allowed


# --- build_worker() ---


def test_build_worker_run_returns_glossary_review_task_worker():
    from context_aware_translation.adapters.qt.workers.glossary_review_task_worker import GlossaryReviewTaskWorker

    deps = MagicMock()
    record = _make_record(status=STATUS_QUEUED)
    payload = handler.decode_payload(record)
    worker = handler.build_worker(TaskAction.RUN, record, payload, deps)
    assert isinstance(worker, GlossaryReviewTaskWorker)


def test_build_worker_cancel_returns_glossary_review_task_worker():
    from context_aware_translation.adapters.qt.workers.glossary_review_task_worker import GlossaryReviewTaskWorker

    deps = MagicMock()
    record = _make_record(status=STATUS_RUNNING)
    payload = handler.decode_payload(record)
    worker = handler.build_worker(TaskAction.CANCEL, record, payload, deps)
    assert isinstance(worker, GlossaryReviewTaskWorker)


def test_build_worker_run_uses_config_snapshot_when_present():
    from context_aware_translation.adapters.qt.workers.glossary_review_task_worker import GlossaryReviewTaskWorker

    deps = MagicMock()
    record = _make_record(status=STATUS_QUEUED, config_snapshot_json='{"snapshot": true}')
    payload = handler.decode_payload(record)
    worker = handler.build_worker(TaskAction.RUN, record, payload, deps)
    assert isinstance(worker, GlossaryReviewTaskWorker)
    assert worker._config_snapshot_json == '{"snapshot": true}'


def test_build_worker_unsupported_action_raises():
    import pytest

    deps = MagicMock()
    record = _make_record()
    with pytest.raises(ValueError, match="Unsupported action"):
        handler.build_worker(TaskAction.DELETE, record, {}, deps)


# --- cancel_dispatch_policy ---


def test_cancel_dispatch_policy_local_terminalize():
    from context_aware_translation.workflow.tasks.handlers.base import CancelDispatchPolicy

    record = _make_record()
    policy = handler.cancel_dispatch_policy(record, {})
    assert policy == CancelDispatchPolicy.LOCAL_TERMINALIZE


# --- pre_delete ---


def test_pre_delete_returns_empty_list():
    record = _make_record()
    result = handler.pre_delete(record, {}, MagicMock())
    assert result == []
