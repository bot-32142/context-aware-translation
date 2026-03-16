from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from context_aware_translation.storage.repositories.task_store import TaskRecord
from context_aware_translation.workflow.tasks.handlers.glossary_translation import GlossaryTranslationHandler


def _make_record(
    status: str = "queued",
    task_id: str = "task-translate",
    book_id: str = "book-1",
) -> TaskRecord:
    now = time.time()
    return TaskRecord(
        task_id=task_id,
        book_id=book_id,
        task_type="glossary_translation",
        status=status,
        phase=None,
        document_ids_json=None,
        payload_json=None,
        config_snapshot_json=None,
        cancel_requested=False,
        total_items=0,
        completed_items=0,
        failed_items=0,
        last_error=None,
        created_at=now,
        updated_at=now,
    )


handler = GlossaryTranslationHandler()


def test_validate_submit_denied_when_only_ignored_terms(tmp_path):
    deps = MagicMock()
    deps.book_manager.get_book.return_value = MagicMock()
    deps.book_manager.get_book_db_path.return_value = tmp_path / "book.db"

    ignored_term = MagicMock()
    ignored_term.ignored = True

    fake_db = MagicMock()
    fake_term_repo = MagicMock()
    fake_term_repo.get_terms_to_translate.return_value = [ignored_term]

    with (
        patch("context_aware_translation.storage.schema.book_db.SQLiteBookDB", return_value=fake_db),
        patch(
            "context_aware_translation.storage.repositories.term_repository.TermRepository", return_value=fake_term_repo
        ),
    ):
        decision = handler.validate_submit("book-1", {}, deps)

    assert not decision.allowed
    assert decision.code == "no_untranslated_terms"


def test_validate_submit_allowed_when_non_ignored_term_exists(tmp_path):
    deps = MagicMock()
    deps.book_manager.get_book.return_value = MagicMock()
    deps.book_manager.get_book_db_path.return_value = tmp_path / "book.db"

    pending_term = MagicMock()
    pending_term.ignored = False

    fake_db = MagicMock()
    fake_term_repo = MagicMock()
    fake_term_repo.get_terms_to_translate.return_value = [pending_term]

    with (
        patch("context_aware_translation.storage.schema.book_db.SQLiteBookDB", return_value=fake_db),
        patch(
            "context_aware_translation.storage.repositories.term_repository.TermRepository", return_value=fake_term_repo
        ),
    ):
        decision = handler.validate_submit("book-1", {}, deps)

    assert decision.allowed


def test_validate_submit_allowed_when_empty_translation_exists(tmp_path):
    deps = MagicMock()
    deps.book_manager.get_book.return_value = MagicMock()
    deps.book_manager.get_book_db_path.return_value = tmp_path / "book.db"

    pending_term = MagicMock()
    pending_term.ignored = False
    pending_term.translated_name = ""

    fake_db = MagicMock()
    fake_term_repo = MagicMock()
    fake_term_repo.get_terms_to_translate.return_value = [pending_term]

    with (
        patch("context_aware_translation.storage.schema.book_db.SQLiteBookDB", return_value=fake_db),
        patch(
            "context_aware_translation.storage.repositories.term_repository.TermRepository", return_value=fake_term_repo
        ),
    ):
        decision = handler.validate_submit("book-1", {}, deps)

    assert decision.allowed


def test_validate_run_denied_when_only_ignored_terms(tmp_path):
    deps = MagicMock()
    deps.book_manager.get_book.return_value = MagicMock()
    deps.book_manager.get_book_db_path.return_value = tmp_path / "book.db"
    record = _make_record()

    ignored_term = MagicMock()
    ignored_term.ignored = True

    fake_db = MagicMock()
    fake_term_repo = MagicMock()
    fake_term_repo.get_terms_to_translate.return_value = [ignored_term]

    with (
        patch("context_aware_translation.storage.schema.book_db.SQLiteBookDB", return_value=fake_db),
        patch(
            "context_aware_translation.storage.repositories.term_repository.TermRepository", return_value=fake_term_repo
        ),
    ):
        decision = handler.validate_run(record, {}, deps)

    assert not decision.allowed
    assert decision.code == "no_untranslated_terms"


def test_validate_run_allowed_when_non_ignored_term_exists(tmp_path):
    deps = MagicMock()
    deps.book_manager.get_book.return_value = MagicMock()
    deps.book_manager.get_book_db_path.return_value = tmp_path / "book.db"
    record = _make_record()

    pending_term = MagicMock()
    pending_term.ignored = False

    fake_db = MagicMock()
    fake_term_repo = MagicMock()
    fake_term_repo.get_terms_to_translate.return_value = [pending_term]

    with (
        patch("context_aware_translation.storage.schema.book_db.SQLiteBookDB", return_value=fake_db),
        patch(
            "context_aware_translation.storage.repositories.term_repository.TermRepository", return_value=fake_term_repo
        ),
    ):
        decision = handler.validate_run(record, {}, deps)

    assert decision.allowed


def test_validate_run_allowed_when_empty_translation_exists(tmp_path):
    deps = MagicMock()
    deps.book_manager.get_book.return_value = MagicMock()
    deps.book_manager.get_book_db_path.return_value = tmp_path / "book.db"
    record = _make_record()

    pending_term = MagicMock()
    pending_term.ignored = False
    pending_term.translated_name = ""

    fake_db = MagicMock()
    fake_term_repo = MagicMock()
    fake_term_repo.get_terms_to_translate.return_value = [pending_term]

    with (
        patch("context_aware_translation.storage.schema.book_db.SQLiteBookDB", return_value=fake_db),
        patch(
            "context_aware_translation.storage.repositories.term_repository.TermRepository", return_value=fake_term_repo
        ),
    ):
        decision = handler.validate_run(record, {}, deps)

    assert decision.allowed
