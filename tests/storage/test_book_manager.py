"""Integration tests for BookManager with profile-based config system."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from context_aware_translation.config import Config
from context_aware_translation.storage.book import BookStatus
from context_aware_translation.storage.book_manager import BookManager

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def library_root(tmp_path: Path) -> Path:
    """Create a temporary library root."""
    return tmp_path / "library"


@pytest.fixture
def book_manager(library_root: Path) -> BookManager:
    """Create a BookManager with temporary storage."""
    manager = BookManager(library_root)
    yield manager
    manager.close()


@pytest.fixture
def sample_config() -> dict[str, Any]:
    """Create a sample config dictionary for testing."""
    base_settings = {
        "api_key": "test-api-key",
        "base_url": "https://api.test.com/v1",
        "model": "test-model",
        "temperature": 0.5,
    }
    return {
        "translation_target_language": "zh-CN",
        "llm_concurrency": 20,
        "extractor_config": base_settings.copy(),
        "summarizor_config": base_settings.copy(),
        "translator_config": base_settings.copy(),
        "glossary_config": base_settings.copy(),
        "review_config": base_settings.copy(),
    }


@pytest.fixture
def book_manager_with_profile(library_root: Path, sample_config: dict[str, Any]) -> BookManager:
    """Create a BookManager with a default profile already set up."""
    manager = BookManager(library_root)
    manager.create_profile(
        name="Default Profile",
        config=sample_config,
        description="Default test profile",
    )
    yield manager
    manager.close()


# ============================================================================
# Test Profile Creation
# ============================================================================


class TestProfileCreation:
    """Tests for creating profiles."""

    def test_create_profile_with_all_fields(self, book_manager: BookManager, sample_config: dict[str, Any]) -> None:
        """Test creating a profile with all fields."""
        profile = book_manager.create_profile(
            name="Test Profile",
            config=sample_config,
            description="A test profile",
            is_default=True,
        )

        assert profile.name == "Test Profile"
        assert profile.config == sample_config
        assert profile.description == "A test profile"
        assert profile.is_default is True
        assert profile.profile_id.startswith("test-profile-")

    def test_create_profile_minimal(self, book_manager: BookManager, sample_config: dict[str, Any]) -> None:
        """Test creating a profile with minimal fields."""
        profile = book_manager.create_profile(
            name="Minimal Profile",
            config=sample_config,
        )

        assert profile.name == "Minimal Profile"
        assert profile.config == sample_config
        assert profile.description is None
        # First profile becomes default automatically
        assert profile.is_default is True

    def test_first_profile_becomes_default(self, book_manager: BookManager, sample_config: dict[str, Any]) -> None:
        """Test that first profile automatically becomes default."""
        profile = book_manager.create_profile(
            name="First Profile",
            config=sample_config,
            is_default=False,  # Explicitly set to False
        )

        # Should still become default as it's the first one
        assert profile.is_default is True

        # Verify via get_default_profile
        default = book_manager.get_default_profile()
        assert default is not None
        assert default.profile_id == profile.profile_id

    def test_second_profile_not_default(self, book_manager: BookManager, sample_config: dict[str, Any]) -> None:
        """Test that second profile is not default unless specified."""
        profile1 = book_manager.create_profile(name="First", config=sample_config)
        profile2 = book_manager.create_profile(name="Second", config=sample_config)

        assert profile1.is_default is True
        assert profile2.is_default is False

    def test_profile_id_uniqueness(self, book_manager: BookManager, sample_config: dict[str, Any]) -> None:
        """Test that creating profiles with same name generates unique IDs."""
        # Note: Name must be unique, but this tests ID generation
        profile1 = book_manager.create_profile(name="Profile One", config=sample_config)
        profile2 = book_manager.create_profile(name="Profile Two", config=sample_config)

        assert profile1.profile_id != profile2.profile_id


# ============================================================================
# Test Profile Retrieval
# ============================================================================


class TestProfileRetrieval:
    """Tests for retrieving profiles."""

    def test_get_profile(self, book_manager: BookManager, sample_config: dict[str, Any]) -> None:
        """Test get_profile returns correct profile."""
        created = book_manager.create_profile(name="Test Profile", config=sample_config)

        retrieved = book_manager.get_profile(created.profile_id)
        assert retrieved is not None
        assert retrieved.profile_id == created.profile_id
        assert retrieved.name == "Test Profile"
        assert retrieved.config == sample_config

    def test_get_profile_nonexistent(self, book_manager: BookManager) -> None:
        """Test get_profile returns None for nonexistent ID."""
        result = book_manager.get_profile("nonexistent-id")
        assert result is None

    def test_get_default_profile(self, book_manager: BookManager, sample_config: dict[str, Any]) -> None:
        """Test get_default_profile returns the default."""
        profile = book_manager.create_profile(name="Default", config=sample_config)

        default = book_manager.get_default_profile()
        assert default is not None
        assert default.profile_id == profile.profile_id

    def test_get_default_profile_none(self, book_manager: BookManager) -> None:
        """Test get_default_profile returns None when no profiles exist."""
        default = book_manager.get_default_profile()
        assert default is None

    def test_list_profiles(self, book_manager: BookManager, sample_config: dict[str, Any]) -> None:
        """Test list_profiles returns all profiles."""
        book_manager.create_profile(name="Alpha", config=sample_config)
        book_manager.create_profile(name="Beta", config=sample_config)
        book_manager.create_profile(name="Gamma", config=sample_config)

        profiles = book_manager.list_profiles()
        assert len(profiles) == 3
        names = [p.name for p in profiles]
        # Should be ordered by name
        assert names == ["Alpha", "Beta", "Gamma"]


# ============================================================================
# Test Profile Updates
# ============================================================================


class TestProfileUpdates:
    """Tests for updating profiles."""

    def test_update_profile_name(self, book_manager: BookManager, sample_config: dict[str, Any]) -> None:
        """Test updating profile name."""
        profile = book_manager.create_profile(name="Original", config=sample_config)

        updated = book_manager.update_profile(profile.profile_id, name="Updated Name")
        assert updated is not None
        assert updated.name == "Updated Name"

    def test_update_profile_config(self, book_manager: BookManager, sample_config: dict[str, Any]) -> None:
        """Test updating profile config."""
        profile = book_manager.create_profile(name="Test", config=sample_config)

        new_config = {**sample_config, "translation_target_language": "ja"}
        updated = book_manager.update_profile(profile.profile_id, config=new_config)

        assert updated is not None
        assert updated.config["translation_target_language"] == "ja"

    def test_set_default_profile(self, book_manager: BookManager, sample_config: dict[str, Any]) -> None:
        """Test setting a different profile as default."""
        profile1 = book_manager.create_profile(name="First", config=sample_config)
        profile2 = book_manager.create_profile(name="Second", config=sample_config)

        # profile1 is default initially
        assert book_manager.get_default_profile().profile_id == profile1.profile_id

        # Set profile2 as default
        book_manager.set_default_profile(profile2.profile_id)

        default = book_manager.get_default_profile()
        assert default.profile_id == profile2.profile_id

        # Verify profile1 is no longer default
        profile1_updated = book_manager.get_profile(profile1.profile_id)
        assert profile1_updated.is_default is False


# ============================================================================
# Test Profile Deletion
# ============================================================================


class TestProfileDeletion:
    """Tests for deleting profiles."""

    def test_delete_profile(self, book_manager: BookManager, sample_config: dict[str, Any]) -> None:
        """Test deleting an unused profile."""
        profile = book_manager.create_profile(name="To Delete", config=sample_config)

        success = book_manager.delete_profile(profile.profile_id)
        assert success is True

        # Verify it's gone
        retrieved = book_manager.get_profile(profile.profile_id)
        assert retrieved is None

    def test_delete_profile_nonexistent(self, book_manager: BookManager) -> None:
        """Test deleting nonexistent profile returns False."""
        success = book_manager.delete_profile("nonexistent-id")
        assert success is False

    def test_delete_profile_in_use_raises(self, book_manager_with_profile: BookManager) -> None:
        """Test deleting a profile in use raises ValueError."""
        profile = book_manager_with_profile.get_default_profile()

        # Create a book using this profile
        book_manager_with_profile.create_book(name="Test Book")

        # Try to delete the profile
        with pytest.raises(ValueError, match="book.*using"):
            book_manager_with_profile.delete_profile(profile.profile_id)


# ============================================================================
# Test Book Creation with Profiles
# ============================================================================


class TestBookCreationWithProfiles:
    """Tests for creating books with the profile-based system."""

    def test_create_book_requires_profile(self, book_manager: BookManager) -> None:
        """Test that creating a book without any profiles raises error."""
        with pytest.raises(ValueError, match="Create a profile before"):
            book_manager.create_book(name="Test Book")

    def test_create_book_uses_default_profile(self, book_manager_with_profile: BookManager, library_root: Path) -> None:
        """Test that creating a book without specifying profile uses default."""
        default_profile = book_manager_with_profile.get_default_profile()

        book = book_manager_with_profile.create_book(name="Test Book")

        assert book.profile_id == default_profile.profile_id
        assert book.name == "Test Book"
        assert book.status == BookStatus.ACTIVE

        # Verify folder structure
        book_path = library_root / "books" / book.book_id
        assert book_path.exists()
        assert (book_path / "logs").exists()

    def test_create_book_with_specific_profile(
        self, book_manager_with_profile: BookManager, sample_config: dict[str, Any]
    ) -> None:
        """Test creating a book with a specific profile."""
        # Create another profile
        other_profile = book_manager_with_profile.create_profile(
            name="Other Profile",
            config={**sample_config, "translation_target_language": "ja"},
        )

        book = book_manager_with_profile.create_book(
            name="Japanese Book",
            profile_id=other_profile.profile_id,
        )

        assert book.profile_id == other_profile.profile_id

    def test_create_book_with_custom_config(
        self, book_manager_with_profile: BookManager, sample_config: dict[str, Any]
    ) -> None:
        """Test creating a book with custom config (no profile)."""
        custom_config = {**sample_config, "translation_target_language": "ko"}

        book = book_manager_with_profile.create_book(
            name="Custom Book",
            custom_config=custom_config,
        )

        # Book should have no profile_id
        assert book.profile_id is None

        # Custom config should be retrievable
        config = book_manager_with_profile.get_book_config(book.book_id)
        assert config is not None
        assert config["translation_target_language"] == "ko"

    def test_create_book_custom_config_ignores_profile_id(
        self, book_manager_with_profile: BookManager, sample_config: dict[str, Any]
    ) -> None:
        """Test that custom_config takes precedence over profile_id."""
        default_profile = book_manager_with_profile.get_default_profile()
        custom_config = {**sample_config, "translation_target_language": "fr"}

        # Provide both custom_config and profile_id
        book = book_manager_with_profile.create_book(
            name="Custom Book",
            profile_id=default_profile.profile_id,
            custom_config=custom_config,
        )

        # custom_config should win, so profile_id should be None
        assert book.profile_id is None

    def test_create_book_invalid_profile_raises(self, book_manager_with_profile: BookManager) -> None:
        """Test creating a book with invalid profile_id raises error."""
        with pytest.raises(ValueError, match="Profile not found"):
            book_manager_with_profile.create_book(
                name="Test Book",
                profile_id="nonexistent-profile-id",
            )

    def test_book_id_format(self, book_manager_with_profile: BookManager) -> None:
        """Test that book_id is correctly slugified with UUID."""
        book = book_manager_with_profile.create_book(name="My Special Book!!!")

        assert book.book_id.startswith("my-special-book-")
        uuid_part = book.book_id.split("-")[-1]
        assert len(uuid_part) == 8
        assert all(c in "0123456789abcdef" for c in uuid_part)


# ============================================================================
# Test Book Retrieval
# ============================================================================


class TestBookRetrieval:
    """Tests for retrieving books."""

    def test_get_book(self, book_manager_with_profile: BookManager) -> None:
        """Test get_book returns correct book."""
        book = book_manager_with_profile.create_book(name="Test Book", description="A description")

        retrieved = book_manager_with_profile.get_book(book.book_id)
        assert retrieved is not None
        assert retrieved.book_id == book.book_id
        assert retrieved.name == "Test Book"
        assert retrieved.description == "A description"

    def test_get_book_nonexistent(self, book_manager_with_profile: BookManager) -> None:
        """Test get_book returns None for nonexistent ID."""
        result = book_manager_with_profile.get_book("nonexistent-id")
        assert result is None

    def test_list_books(self, book_manager_with_profile: BookManager) -> None:
        """Test list_books returns all books."""
        book1 = book_manager_with_profile.create_book(name="Book 1")
        book2 = book_manager_with_profile.create_book(name="Book 2")
        book3 = book_manager_with_profile.create_book(name="Book 3")

        books = book_manager_with_profile.list_books()
        assert len(books) == 3

        book_ids = {b.book_id for b in books}
        assert book1.book_id in book_ids
        assert book2.book_id in book_ids
        assert book3.book_id in book_ids

    def test_list_books_with_status_filter(self, book_manager_with_profile: BookManager) -> None:
        """Test list_books with status filter."""
        book1 = book_manager_with_profile.create_book(name="Active Book")
        book2 = book_manager_with_profile.create_book(name="To Archive")

        # Archive book2
        book_manager_with_profile.update_book(book2.book_id, status=BookStatus.ARCHIVED)

        active_books = book_manager_with_profile.list_books(status=BookStatus.ACTIVE)
        assert len(active_books) == 1
        assert active_books[0].book_id == book1.book_id


# ============================================================================
# Test Book Deletion
# ============================================================================


class TestBookDeletion:
    """Tests for deleting books."""

    def test_soft_delete(self, book_manager_with_profile: BookManager, library_root: Path) -> None:
        """Test soft delete sets status to DELETED."""
        book = book_manager_with_profile.create_book(name="To Delete")
        book_path = library_root / "books" / book.book_id

        success = book_manager_with_profile.delete_book(book.book_id, permanent=False)
        assert success is True

        # Folder should still exist
        assert book_path.exists()

        # Book status should be DELETED
        retrieved = book_manager_with_profile.get_book(book.book_id)
        assert retrieved is not None
        assert retrieved.status == BookStatus.DELETED

    def test_permanent_delete(self, book_manager_with_profile: BookManager, library_root: Path) -> None:
        """Test permanent delete removes folder and registry entry."""
        book = book_manager_with_profile.create_book(name="To Delete")
        book_path = library_root / "books" / book.book_id

        assert book_path.exists()

        success = book_manager_with_profile.delete_book(book.book_id, permanent=True)
        assert success is True

        # Folder should be removed
        assert not book_path.exists()

        # Book should not be retrievable
        retrieved = book_manager_with_profile.get_book(book.book_id)
        assert retrieved is None


# ============================================================================
# Test Book Updates
# ============================================================================


class TestBookUpdates:
    """Tests for updating books."""

    def test_update_name_and_description(self, book_manager_with_profile: BookManager) -> None:
        """Test updating name and description."""
        book = book_manager_with_profile.create_book(
            name="Original",
            description="Original description",
        )

        updated = book_manager_with_profile.update_book(
            book.book_id,
            name="Updated",
            description="Updated description",
        )

        assert updated is not None
        assert updated.name == "Updated"
        assert updated.description == "Updated description"

    def test_update_profile_id(self, book_manager_with_profile: BookManager, sample_config: dict[str, Any]) -> None:
        """Test changing a book's profile."""
        other_profile = book_manager_with_profile.create_profile(
            name="Other",
            config={**sample_config, "translation_target_language": "ja"},
        )

        book = book_manager_with_profile.create_book(name="Test Book")
        original_profile = book.profile_id

        updated = book_manager_with_profile.update_book(
            book.book_id,
            profile_id=other_profile.profile_id,
        )

        assert updated.profile_id == other_profile.profile_id
        assert updated.profile_id != original_profile

    def test_set_book_custom_config(
        self, book_manager_with_profile: BookManager, sample_config: dict[str, Any]
    ) -> None:
        """Test converting a book from profile mode to custom config mode."""
        book = book_manager_with_profile.create_book(name="Test Book")
        assert book.profile_id is not None

        custom_config = {**sample_config, "translation_target_language": "de"}
        book_manager_with_profile.set_book_custom_config(book.book_id, custom_config)

        # Book should now have no profile_id
        updated = book_manager_with_profile.get_book(book.book_id)
        assert updated.profile_id is None

        # Custom config should be retrievable
        config = book_manager_with_profile.get_book_config(book.book_id)
        assert config["translation_target_language"] == "de"


# ============================================================================
# Test Config.from_book()
# ============================================================================


class TestConfigFromBook:
    """Tests for Config.from_book() method."""

    def test_from_book_with_profile(
        self, book_manager_with_profile: BookManager, library_root: Path, sample_config: dict[str, Any]
    ) -> None:
        """Test Config.from_book() loads config from profile."""
        book = book_manager_with_profile.create_book(name="Test Book")

        config = Config.from_book(
            book=book,
            library_root=library_root,
            registry=book_manager_with_profile.registry,
        )

        # Verify target language from profile
        assert config.translation_target_language == sample_config["translation_target_language"]

        # Verify paths
        expected_book_path = library_root / "books" / book.book_id
        assert config.output_dir == expected_book_path
        assert config.sqlite_path == expected_book_path / "book.db"
        assert config.book_id == book.book_id

        # Verify LLM config (now stored in step configs)
        assert config.extractor_config.api_key == sample_config["extractor_config"]["api_key"]
        assert config.extractor_config.model == sample_config["extractor_config"]["model"]

    def test_from_book_with_custom_config(self, book_manager_with_profile: BookManager, library_root: Path) -> None:
        """Test Config.from_book() loads custom config."""
        base_settings = {
            "api_key": "custom-key",
            "base_url": "https://custom.api.com/v1",
            "model": "custom-model",
        }
        custom_config = {
            "translation_target_language": "ko",
            "llm_concurrency": 10,
            "extractor_config": base_settings.copy(),
            "summarizor_config": {**base_settings, "noise_filtering_threshold": 0.5},
            "translator_config": base_settings.copy(),
            "glossary_config": base_settings.copy(),
            "review_config": base_settings.copy(),
        }

        book = book_manager_with_profile.create_book(
            name="Custom Book",
            custom_config=custom_config,
        )

        config = Config.from_book(
            book=book,
            library_root=library_root,
            registry=book_manager_with_profile.registry,
        )

        assert config.translation_target_language == "ko"
        assert config.llm_concurrency == 10
        assert config.extractor_config.api_key == "custom-key"
        assert config.extractor_config.model == "custom-model"
        assert config.summarizor_config is not None
        assert config.summarizor_config.model == "custom-model"

    def test_from_book_profile_not_found_raises(
        self, book_manager_with_profile: BookManager, library_root: Path
    ) -> None:
        """Test Config.from_book() raises if profile not found."""
        book = book_manager_with_profile.create_book(name="Test Book")

        # Manually set an invalid profile_id
        book.profile_id = "nonexistent-profile-id"

        with pytest.raises(ValueError, match="Profile not found"):
            Config.from_book(
                book=book,
                library_root=library_root,
                registry=book_manager_with_profile.registry,
            )

    def test_from_book_no_custom_config_raises(
        self, book_manager_with_profile: BookManager, library_root: Path
    ) -> None:
        """Test Config.from_book() raises if no custom config and no profile."""
        book = book_manager_with_profile.create_book(name="Test Book")

        # Manually clear the profile_id without setting custom config
        book.profile_id = None

        with pytest.raises(ValueError, match="No custom config found"):
            Config.from_book(
                book=book,
                library_root=library_root,
                registry=book_manager_with_profile.registry,
            )


# ============================================================================
# Test get_book_config()
# ============================================================================


class TestGetBookConfig:
    """Tests for BookManager.get_book_config()."""

    def test_get_config_from_profile(
        self, book_manager_with_profile: BookManager, sample_config: dict[str, Any]
    ) -> None:
        """Test get_book_config returns profile config."""
        book = book_manager_with_profile.create_book(name="Test Book")

        config = book_manager_with_profile.get_book_config(book.book_id)
        assert config is not None
        assert config["translation_target_language"] == sample_config["translation_target_language"]

    def test_get_config_from_custom(
        self, book_manager_with_profile: BookManager, sample_config: dict[str, Any]
    ) -> None:
        """Test get_book_config returns custom config."""
        custom_config = {**sample_config, "translation_target_language": "ru"}

        book = book_manager_with_profile.create_book(
            name="Custom Book",
            custom_config=custom_config,
        )

        config = book_manager_with_profile.get_book_config(book.book_id)
        assert config is not None
        assert config["translation_target_language"] == "ru"

    def test_get_config_nonexistent_book(self, book_manager_with_profile: BookManager) -> None:
        """Test get_book_config returns None for nonexistent book."""
        config = book_manager_with_profile.get_book_config("nonexistent-id")
        assert config is None


# ============================================================================
# Test Path Helpers
# ============================================================================


class TestPathHelpers:
    """Tests for path helper methods."""

    def test_get_book_path(self, book_manager_with_profile: BookManager, library_root: Path) -> None:
        """Test get_book_path()."""
        book = book_manager_with_profile.create_book(name="Test Book")
        path = book_manager_with_profile.get_book_path(book.book_id)

        expected = library_root / "books" / book.book_id
        assert path == expected

    def test_get_book_db_path(self, book_manager_with_profile: BookManager, library_root: Path) -> None:
        """Test get_book_db_path()."""
        book = book_manager_with_profile.create_book(name="Test Book")
        path = book_manager_with_profile.get_book_db_path(book.book_id)

        expected = library_root / "books" / book.book_id / "book.db"
        assert path == expected

    def test_get_book_context_tree_path(self, book_manager_with_profile: BookManager, library_root: Path) -> None:
        """Test get_book_context_tree_path()."""
        book = book_manager_with_profile.create_book(name="Test Book")
        path = book_manager_with_profile.get_book_context_tree_path(book.book_id)

        expected = library_root / "books" / book.book_id / "context_tree.db"
        assert path == expected


# ============================================================================
# Test Isolation
# ============================================================================


class TestIsolation:
    """Tests for book isolation."""

    def test_separate_folders(self, book_manager_with_profile: BookManager, library_root: Path) -> None:
        """Test that books have separate folders."""
        book1 = book_manager_with_profile.create_book(name="Book 1")
        book2 = book_manager_with_profile.create_book(name="Book 2")

        path1 = library_root / "books" / book1.book_id
        path2 = library_root / "books" / book2.book_id

        assert path1 != path2
        assert path1.exists()
        assert path2.exists()

    def test_delete_one_does_not_affect_other(self, book_manager_with_profile: BookManager, library_root: Path) -> None:
        """Test that deleting one book doesn't affect the other."""
        book1 = book_manager_with_profile.create_book(name="Book 1")
        book2 = book_manager_with_profile.create_book(name="Book 2")

        path1 = library_root / "books" / book1.book_id
        path2 = library_root / "books" / book2.book_id

        # Permanently delete book1
        book_manager_with_profile.delete_book(book1.book_id, permanent=True)

        # book1 folder should be gone
        assert not path1.exists()

        # book2 should still exist
        assert path2.exists()
        retrieved = book_manager_with_profile.get_book(book2.book_id)
        assert retrieved is not None


# ============================================================================
# Test Edge Cases
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_multiple_managers_same_library(self, library_root: Path, sample_config: dict[str, Any]) -> None:
        """Test that multiple managers can work with the same library."""
        manager1 = BookManager(library_root)
        manager1.create_profile(name="Test Profile", config=sample_config)
        book = manager1.create_book(name="Shared Book")
        manager1.close()

        # Second manager should see the profile and book
        manager2 = BookManager(library_root)
        profiles = manager2.list_profiles()
        assert len(profiles) == 1

        retrieved = manager2.get_book(book.book_id)
        assert retrieved is not None
        assert retrieved.name == "Shared Book"
        manager2.close()

    def test_profile_with_step_configs(
        self, book_manager: BookManager, sample_config: dict[str, Any], library_root: Path
    ) -> None:
        """Test profile with full step configs."""
        # Merge base settings with step-specific overrides (each step config must be complete)
        full_config = {
            **sample_config,
            "extractor_config": {
                **sample_config["extractor_config"],
                "max_gleaning": 5,
                "model": "extractor-model",
            },
            "translator_config": {
                **sample_config["translator_config"],
                "chunk_size": 2000,
                "model": "translator-model",
            },
        }

        book_manager.create_profile(name="Full Config", config=full_config)
        book = book_manager.create_book(name="Test Book")

        config = Config.from_book(
            book=book,
            library_root=library_root,
            registry=book_manager.registry,
        )

        assert config.extractor_config is not None
        assert config.extractor_config.max_gleaning == 5
        assert config.translator_config is not None
        assert config.translator_config.chunk_size == 2000


class TestConfigPersistenceValidation:
    """Tests for config validation before persistence."""

    def test_create_profile_rejects_incomplete_config(self, book_manager: BookManager) -> None:
        incomplete_config = {"translation_target_language": "zh-CN"}

        with pytest.raises(ValueError, match="Invalid config payload"):
            book_manager.create_profile(name="Invalid Profile", config=incomplete_config)

    def test_update_profile_rejects_invalid_config(
        self, book_manager: BookManager, sample_config: dict[str, Any]
    ) -> None:
        profile = book_manager.create_profile(name="Valid Profile", config=sample_config)

        with pytest.raises(ValueError, match="Invalid config payload"):
            book_manager.update_profile(profile.profile_id, config={"translation_target_language": "zh-CN"})

    def test_set_book_custom_config_rejects_incomplete_config(
        self,
        book_manager_with_profile: BookManager,
    ) -> None:
        book = book_manager_with_profile.create_book(name="Config Validation Book")

        with pytest.raises(ValueError, match="Invalid config payload"):
            book_manager_with_profile.set_book_custom_config(book.book_id, {"translation_target_language": "zh-CN"})

    def test_profile_config_can_reference_registry_endpoint_profile_kwargs(
        self,
        book_manager: BookManager,
        library_root: Path,
    ) -> None:
        """kwargs from registry endpoint profiles are persisted and flow through to Config."""
        custom_kwargs = {"extra_body": {"google": {"thinking_config": {"thinking_level": "MINIMAL"}}}}
        endpoint = book_manager.create_endpoint_profile(
            name="kwargs-endpoint",
            api_key="ep-key",
            base_url="https://ep.example.com/v1",
            model="ep-model",
            kwargs=custom_kwargs,
        )

        # Verify kwargs are persisted in the registry
        retrieved = book_manager.get_endpoint_profile(endpoint.profile_id)
        assert retrieved is not None
        assert retrieved.kwargs == custom_kwargs

        # Verify kwargs flow through Config.from_book
        profile_config = {
            "translation_target_language": "zh-CN",
            "extractor_config": {"endpoint_profile": endpoint.profile_id},
            "summarizor_config": {"endpoint_profile": endpoint.profile_id},
            "translator_config": {"endpoint_profile": endpoint.profile_id},
            "glossary_config": {"endpoint_profile": endpoint.profile_id},
            "review_config": {"endpoint_profile": endpoint.profile_id},
        }
        book_manager.create_profile(name="Profile With Kwargs", config=profile_config)
        book = book_manager.create_book(name="Book With Kwargs")

        cfg = Config.from_book(book=book, library_root=library_root, registry=book_manager.registry)
        assert cfg.extractor_config is not None
        assert cfg.extractor_config.kwargs == custom_kwargs
        assert cfg.glossary_config is not None
        assert cfg.glossary_config.kwargs == custom_kwargs

    def test_endpoint_profile_kwargs_updated(
        self,
        book_manager: BookManager,
    ) -> None:
        """kwargs can be updated on an existing endpoint profile."""
        endpoint = book_manager.create_endpoint_profile(
            name="update-kwargs-ep",
            api_key="ep-key",
            base_url="https://ep.example.com/v1",
            model="ep-model",
            kwargs={"old_key": "old_value"},
        )

        new_kwargs = {"reasoning_effort": "low", "extra_body": {"test": True}}
        updated = book_manager.update_endpoint_profile(endpoint.profile_id, kwargs=new_kwargs)
        assert updated is not None
        assert updated.kwargs == new_kwargs

        # Verify it's persisted after re-read
        retrieved = book_manager.get_endpoint_profile(endpoint.profile_id)
        assert retrieved is not None
        assert retrieved.kwargs == new_kwargs

    def test_endpoint_profile_kwargs_default_empty(
        self,
        book_manager: BookManager,
    ) -> None:
        """Endpoint profiles created without kwargs default to empty dict."""
        endpoint = book_manager.create_endpoint_profile(
            name="no-kwargs-ep",
            api_key="ep-key",
            base_url="https://ep.example.com/v1",
            model="ep-model",
        )

        retrieved = book_manager.get_endpoint_profile(endpoint.profile_id)
        assert retrieved is not None
        assert retrieved.kwargs == {}

    def test_seed_system_defaults_on_empty_db(
        self,
        library_root: Path,
    ) -> None:
        """Test that seed_system_defaults creates default endpoints and config profile."""
        manager = BookManager(library_root)
        try:
            manager.seed_system_defaults()

            # Should have 3 endpoint profiles
            endpoints = manager.list_endpoint_profiles()
            assert len(endpoints) == 3
            names = {ep.name for ep in endpoints}
            assert names == {"system-default-gemini-pro", "system-default-gemini-flash", "system-default-deepseek"}

            # Check Gemini endpoint
            gemini = manager.get_endpoint_profile("system-default-gemini-pro")
            assert gemini is not None
            assert gemini.base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"
            assert gemini.model == "gemini-2.5-pro"
            assert gemini.is_default is True  # first inserted becomes default

            # Check Gemini Flash endpoint
            gemini_flash = manager.get_endpoint_profile("system-default-gemini-flash")
            assert gemini_flash is not None
            assert gemini_flash.base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"
            assert gemini_flash.model == "gemini-3-flash-preview"

            # Check DeepSeek endpoint
            deepseek = manager.get_endpoint_profile("system-default-deepseek")
            assert deepseek is not None
            assert deepseek.base_url == "https://api.deepseek.com"
            assert deepseek.model == "deepseek-chat"

            # Should have 1 config profile
            profiles = manager.list_profiles()
            assert len(profiles) == 1
            profile = profiles[0]
            assert profile.name == "system-default-profile"
            assert profile.is_default is True
            config = profile.config
            assert config["translation_target_language"] == "简体中文"
            assert config["extractor_config"]["endpoint_profile"] == "system-default-deepseek"
            assert config["summarizor_config"]["endpoint_profile"] == "system-default-deepseek"
            assert config["glossary_config"]["endpoint_profile"] == "system-default-gemini-flash"
            assert config["translator_config"]["endpoint_profile"] == "system-default-gemini-pro"
            assert config["review_config"]["endpoint_profile"] == "system-default-gemini-flash"
            assert config["ocr_config"]["endpoint_profile"] == "system-default-gemini-flash"
        finally:
            manager.close()

    def test_seed_system_defaults_skipped_when_endpoints_exist(
        self,
        book_manager: BookManager,
    ) -> None:
        """Test that seeding is skipped if endpoint profiles already exist."""
        book_manager.create_endpoint_profile(
            name="user-endpoint",
            api_key="key",
            base_url="https://example.com",
            model="model",
        )

        book_manager.seed_system_defaults()

        # Should only have the user-created endpoint, no system defaults
        endpoints = book_manager.list_endpoint_profiles()
        assert len(endpoints) == 1
        assert endpoints[0].name == "user-endpoint"

    def test_seed_system_defaults_skipped_when_profiles_exist(
        self,
        book_manager: BookManager,
        sample_config: dict[str, Any],
    ) -> None:
        """Test that seeding is skipped if config profiles already exist."""
        book_manager.create_profile(name="user-profile", config=sample_config)

        book_manager.seed_system_defaults()

        # Should only have the user-created profile, no system defaults
        profiles = book_manager.list_profiles()
        assert len(profiles) == 1
        assert profiles[0].name == "user-profile"

    def test_seed_system_defaults_idempotent(
        self,
        library_root: Path,
    ) -> None:
        """Test that calling seed_system_defaults twice is safe."""
        manager = BookManager(library_root)
        try:
            manager.seed_system_defaults()
            manager.seed_system_defaults()  # second call should be a no-op

            assert len(manager.list_endpoint_profiles()) == 3
            assert len(manager.list_profiles()) == 1
        finally:
            manager.close()

    def test_profile_config_can_reference_registry_endpoint_profile_by_id(
        self,
        book_manager: BookManager,
        library_root: Path,
    ) -> None:
        endpoint = book_manager.create_endpoint_profile(
            name="shared-endpoint",
            api_key="ep-key",
            base_url="https://ep.example.com/v1",
            model="ep-model",
        )

        profile_config = {
            "translation_target_language": "zh-CN",
            "extractor_config": {"endpoint_profile": endpoint.profile_id},
            "summarizor_config": {"endpoint_profile": endpoint.profile_id},
            "translator_config": {"endpoint_profile": endpoint.profile_id},
            "glossary_config": {"endpoint_profile": endpoint.profile_id},
            "review_config": {"endpoint_profile": endpoint.profile_id},
        }

        book_manager.create_profile(name="Profile With Endpoint ID Ref", config=profile_config)
        book = book_manager.create_book(name="Book With Endpoint ID Ref")

        cfg = Config.from_book(book=book, library_root=library_root, registry=book_manager.registry)
        assert cfg.extractor_config is not None
        assert cfg.extractor_config.api_key == "ep-key"
        assert cfg.extractor_config.base_url == "https://ep.example.com/v1"
        assert cfg.extractor_config.model == "ep-model"
