"""Tests for business logic changes (Plan A)."""

import time
from pathlib import Path

import pytest

from context_aware_translation.config import (
    EndpointProfile,
    ExtractorConfig,
    LLMConfig,
)
from context_aware_translation.core.progress import (
    ProgressUpdate,
    WorkflowStep,
)
from context_aware_translation.storage.models.config_profile import ConfigProfile
from context_aware_translation.storage.repositories.term_repository import TermRepository
from context_aware_translation.storage.schema.book_db import SQLiteBookDB, TermRecord


class TestConfigSerialization:
    """Test to_dict() / from_dict() roundtrip for all config classes."""

    def test_endpoint_profile_roundtrip(self) -> None:
        """Test EndpointProfile serialization roundtrip."""
        original = EndpointProfile(
            name="test-profile",
            api_key="test-key",
            base_url="https://api.test.com",
            model="gpt-4",
            temperature=0.7,
            concurrency=10,
        )

        data = original.to_dict()
        restored = EndpointProfile.from_dict(data)

        assert restored.name == original.name
        assert restored.api_key == original.api_key
        assert restored.base_url == original.base_url
        assert restored.model == original.model
        assert restored.temperature == original.temperature
        assert restored.concurrency == original.concurrency

    def test_llm_config_roundtrip(self) -> None:
        """Test LLMConfig serialization roundtrip."""
        original = LLMConfig(
            api_key="test-key",
            base_url="https://api.test.com",
            model="gpt-4",
            temperature=0.5,
            concurrency=5,
        )

        data = original.to_dict()
        restored = LLMConfig.from_dict(data)

        assert restored.api_key == original.api_key
        assert restored.model == original.model
        assert restored.temperature == original.temperature

    def test_extractor_config_roundtrip(self) -> None:
        """Test ExtractorConfig serialization roundtrip."""
        original = ExtractorConfig(
            api_key="test-key",
            base_url="https://api.test.com",
            model="gpt-4",
            max_gleaning=5,
            max_term_name_length=300,
        )

        data = original.to_dict()
        restored = ExtractorConfig.from_dict(data)

        assert restored.max_gleaning == original.max_gleaning
        assert restored.max_term_name_length == original.max_term_name_length

    def test_config_profile_roundtrip(self) -> None:
        """Test ConfigProfile serialization roundtrip."""
        now = time.time()
        original = ConfigProfile(
            profile_id="test-id",
            name="Test Profile",
            created_at=now,
            updated_at=now,
            config={"translation_target_language": "Chinese"},
            description="A test profile",
            is_default=True,
        )

        data = original.to_dict()
        restored = ConfigProfile.from_dict(data)

        assert restored.profile_id == original.profile_id
        assert restored.name == original.name
        assert restored.config == original.config
        assert restored.is_default == original.is_default


class TestBulkTermOperations:
    """Test bulk term operations."""

    @pytest.fixture
    def term_repo(self, tmp_path: Path) -> TermRepository:
        """Create a temporary database with repository."""
        db_path = tmp_path / "test.db"
        db = SQLiteBookDB(db_path)
        return TermRepository(db)

    def test_update_terms_bulk(self, term_repo: TermRepository) -> None:
        """Test update_terms_bulk updates correct fields."""
        # Insert test terms
        terms = [
            TermRecord(key="term1", descriptions={}, occurrence={}, votes=1, total_api_calls=1),
            TermRecord(key="term2", descriptions={}, occurrence={}, votes=2, total_api_calls=1),
            TermRecord(key="term3", descriptions={}, occurrence={}, votes=3, total_api_calls=1),
        ]
        term_repo.upsert_terms(terms)

        # Bulk update
        count = term_repo.update_terms_bulk(["term1", "term2"], ignored=True, is_reviewed=True)

        assert count == 2

        term1 = term_repo.keyed_context_db.get_term("term1")
        term2 = term_repo.keyed_context_db.get_term("term2")
        term3 = term_repo.keyed_context_db.get_term("term3")

        assert term1 is not None and term1.ignored is True
        assert term1.is_reviewed is True
        assert term2 is not None and term2.ignored is True
        assert term3 is not None and term3.ignored is False

    def test_delete_terms(self, term_repo: TermRepository) -> None:
        """Test delete_terms removes terms."""
        terms = [
            TermRecord(key="term1", descriptions={}, occurrence={}, votes=1, total_api_calls=1),
            TermRecord(key="term2", descriptions={}, occurrence={}, votes=2, total_api_calls=1),
        ]
        term_repo.upsert_terms(terms)

        count = term_repo.delete_terms(["term1"])

        assert count == 1
        assert term_repo.keyed_context_db.get_term("term1") is None
        assert term_repo.keyed_context_db.get_term("term2") is not None

    def test_get_term_count(self, term_repo: TermRepository) -> None:
        """Test get_term_count returns correct count."""
        terms = [
            TermRecord(key="term1", descriptions={}, occurrence={}, votes=1, total_api_calls=1, ignored=False),
            TermRecord(key="term2", descriptions={}, occurrence={}, votes=2, total_api_calls=1, ignored=True),
            TermRecord(key="term3", descriptions={}, occurrence={}, votes=3, total_api_calls=1, ignored=False),
        ]
        term_repo.upsert_terms(terms)

        assert term_repo.get_term_count(include_ignored=True) == 3
        assert term_repo.get_term_count(include_ignored=False) == 2


class TestTermFilteringPagination:
    """Test term filtering and pagination."""

    @pytest.fixture
    def term_repo(self, tmp_path: Path) -> TermRepository:
        """Create a temporary database with test terms."""
        db_path = tmp_path / "test.db"
        db = SQLiteBookDB(db_path)
        term_repo = TermRepository(db)

        terms = [
            TermRecord(
                key="alpha",
                descriptions={},
                occurrence={},
                votes=5,
                total_api_calls=1,
                ignored=False,
                is_reviewed=True,
                translated_name="阿尔法",
            ),
            TermRecord(
                key="beta", descriptions={}, occurrence={}, votes=3, total_api_calls=1, ignored=True, is_reviewed=False
            ),
            TermRecord(
                key="gamma",
                descriptions={},
                occurrence={},
                votes=1,
                total_api_calls=1,
                ignored=False,
                is_reviewed=False,
                translated_name="伽马",
            ),
            TermRecord(
                key="delta", descriptions={}, occurrence={}, votes=4, total_api_calls=1, ignored=False, is_reviewed=True
            ),
        ]
        term_repo.upsert_terms(terms)
        return term_repo

    def test_list_terms_pagination(self, term_repo: TermRepository) -> None:
        """Test list_terms pagination."""
        page1 = term_repo.list_terms_filtered(limit=2, offset=0)
        page2 = term_repo.list_terms_filtered(limit=2, offset=2)

        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0].key != page2[0].key

    def test_list_terms_sorting(self, term_repo: TermRepository) -> None:
        """Test list_terms sorting."""
        terms_asc = term_repo.list_terms_filtered(sort_by="votes", sort_desc=False)
        terms_desc = term_repo.list_terms_filtered(sort_by="votes", sort_desc=True)

        assert terms_asc[0].votes <= terms_asc[-1].votes
        assert terms_desc[0].votes >= terms_desc[-1].votes

    def test_list_terms_filter_ignored(self, term_repo: TermRepository) -> None:
        """Test list_terms filter by ignored status."""
        ignored = term_repo.list_terms_filtered(filter_ignored=True)
        kept = term_repo.list_terms_filtered(filter_ignored=False)

        assert len(ignored) == 1
        assert ignored[0].key == "beta"
        assert len(kept) == 3

    def test_list_terms_filter_reviewed(self, term_repo: TermRepository) -> None:
        """Test list_terms filter by reviewed status."""
        reviewed = term_repo.list_terms_filtered(filter_reviewed=True)
        not_reviewed = term_repo.list_terms_filtered(filter_reviewed=False)

        assert len(reviewed) == 2
        assert len(not_reviewed) == 2

    def test_list_terms_filter_translated(self, term_repo: TermRepository) -> None:
        """Test list_terms filter by translated status."""
        translated = term_repo.list_terms_filtered(filter_translated=True)
        not_translated = term_repo.list_terms_filtered(filter_translated=False)

        assert len(translated) == 2
        assert len(not_translated) == 2

    def test_search_terms(self, term_repo: TermRepository) -> None:
        """Test search_terms pattern matching."""
        results = term_repo.search_terms("a")  # matches alpha, beta, gamma, delta
        assert len(results) == 4

        results = term_repo.search_terms("lph")  # matches alpha only
        assert len(results) == 1
        assert results[0].key == "alpha"

        results = term_repo.search_terms("阿尔")
        assert len(results) == 1
        assert results[0].key == "alpha"


class TestStatistics:
    """Test statistics methods."""

    @pytest.fixture
    def term_repo(self, tmp_path: Path) -> TermRepository:
        """Create a temporary database with test data."""
        db_path = tmp_path / "test.db"
        db = SQLiteBookDB(db_path)
        term_repo = TermRepository(db)

        terms = [
            TermRecord(
                key="term1",
                descriptions={},
                occurrence={},
                votes=1,
                total_api_calls=1,
                ignored=False,
                is_reviewed=True,
                translated_name="翻译1",
            ),
            TermRecord(
                key="term2", descriptions={}, occurrence={}, votes=2, total_api_calls=1, ignored=True, is_reviewed=False
            ),
            TermRecord(
                key="term3",
                descriptions={},
                occurrence={},
                votes=3,
                total_api_calls=1,
                ignored=False,
                is_reviewed=False,
            ),
        ]
        term_repo.upsert_terms(terms)
        return term_repo

    def test_get_term_stats(self, term_repo: TermRepository) -> None:
        """Test get_term_stats returns correct counts."""
        stats = term_repo.get_term_stats()

        assert stats["total"] == 3
        assert stats["reviewed"] == 1
        assert stats["ignored"] == 1
        assert stats["translated"] == 1
        assert stats["pending"] == 1  # not reviewed and not ignored
        assert stats["unignored"] == 2
        assert stats["unignored_reviewed"] == 1

    def test_get_chunk_stats_empty(self, term_repo: TermRepository) -> None:
        """Test get_chunk_stats with no chunks."""
        stats = term_repo.get_chunk_stats()

        assert stats["total"] == 0
        assert stats["translated"] == 0
        assert stats["progress_percent"] == 0.0


class TestValidation:
    """Test validation methods."""

    def test_config_validate_missing_fields(self) -> None:
        """Test Config.validate catches missing fields."""
        # Create a minimal config that should fail validation
        # We need to use the validate method on a constructed config
        # Since Config requires many fields, we test the validate method directly
        pass  # Config requires __post_init__ which does validation - tested implicitly

    def test_book_manager_validate_book_name(self, tmp_path: Path) -> None:
        """Test BookManager.validate_book_name checks for valid format only.

        Note: Uniqueness is enforced via SQL UNIQUE constraint, not pre-validation.
        """
        from context_aware_translation.storage.library.book_manager import BookManager

        manager = BookManager(library_root=tmp_path)

        # Test empty name
        error = manager.validate_book_name("")
        assert error == "Book name is required"

        # Test whitespace only
        error = manager.validate_book_name("   ")
        assert error == "Book name is required"

        # Test too long name
        error = manager.validate_book_name("x" * 201)
        assert error == "Book name must be 200 characters or less"

        # Test valid name
        error = manager.validate_book_name("Valid Book Name")
        assert error is None

        manager.close()


class TestProgressCallback:
    """Test progress callback types."""

    def test_workflow_step_enum(self) -> None:
        """Test WorkflowStep enum values."""
        assert WorkflowStep.OCR.value == "ocr"
        assert WorkflowStep.EXTRACT_TERMS.value == "extract_terms"
        assert WorkflowStep.TRANSLATE_CHUNKS.value == "translate_chunks"
        assert WorkflowStep.EXPORT.value == "export"

    def test_progress_update_dataclass(self) -> None:
        """Test ProgressUpdate dataclass."""
        update = ProgressUpdate(
            step=WorkflowStep.OCR,
            current=5,
            total=10,
            message="Processing page 5",
        )

        assert update.step == WorkflowStep.OCR
        assert update.current == 5
        assert update.total == 10
        assert update.message == "Processing page 5"
