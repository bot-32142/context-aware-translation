"""BookManager for managing books and config profiles with folder structure."""

from __future__ import annotations

import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir

from context_aware_translation.config import ensure_valid_persisted_config_payload
from context_aware_translation.storage.book import Book, BookStatus
from context_aware_translation.storage.config_profile import ConfigProfile
from context_aware_translation.storage.endpoint_profile import EndpointProfile
from context_aware_translation.storage.registry_db import RegistryDB

# Platform-specific data directory:
# macOS:   ~/Library/Application Support/ContextAwareTranslation
# Windows: C:\Users\<User>\AppData\Roaming\ContextAwareTranslation
# Linux:   ~/.local/share/ContextAwareTranslation
DEFAULT_LIBRARY_ROOT = Path(user_data_dir("ContextAwareTranslation", appauthor=False))

class BookManager:
    """
    Manages books and config profiles with folder structure and registry.

    Folder structure:
    <library_root>/
      registry.db                    # Global book registry and config profiles
      books/
        <book_id>/
          book.db                    # Terms, chunks, documents
          context_tree.db            # Context tree
          logs/                      # Book-specific logs
    """

    def __init__(self, library_root: Path | None = None):
        """
        Initialize BookManager.

        Args:
            library_root: Root directory for the library. Defaults to platform-specific data dir.
        """
        self.library_root = library_root or DEFAULT_LIBRARY_ROOT
        self._ensure_structure()
        registry_path = self.library_root / "registry.db"
        self.registry = RegistryDB(registry_path)

    def _ensure_structure(self) -> None:
        """Create library_root and books/ directory if needed."""
        self.library_root.mkdir(parents=True, exist_ok=True)
        (self.library_root / "books").mkdir(exist_ok=True)

    def _generate_id(self, name: str) -> str:
        """
        Generate an ID from name.

        Slugifies name and appends 8-character UUID hex.
        Example: "My Book" -> "my-book-a1b2c3d4"

        Args:
            name: Name to slugify

        Returns:
            Generated ID
        """
        # Slugify: lowercase, replace spaces/special chars with hyphens
        slug = re.sub(r"[^\w\s-]", "", name.lower())
        slug = re.sub(r"[-\s]+", "-", slug).strip("-")

        # Append short UUID
        short_uuid = uuid.uuid4().hex[:8]
        return f"{slug}-{short_uuid}"

    def _endpoint_profile_ref_exists(self, profile_ref: str) -> bool:
        """Return True if endpoint profile reference matches a profile ID."""
        return self.registry.get_endpoint_profile(profile_ref) is not None

    # =========================================================================
    # Profile Management
    # =========================================================================

    def create_profile(
        self,
        name: str,
        config: dict[str, Any],
        description: str | None = None,
        is_default: bool = False,
    ) -> ConfigProfile:
        """
        Create a new config profile.

        Args:
            name: Profile name (must be unique)
            config: Configuration dictionary including translation_target_language
            description: Optional description
            is_default: Whether this profile should be the default

        Returns:
            Created ConfigProfile instance

        Raises:
            sqlite3.IntegrityError: If name already exists
        """
        ensure_valid_persisted_config_payload(
            config,
            endpoint_profile_exists=self._endpoint_profile_ref_exists,
        )
        profile_id = self._generate_id(name)
        now = time.time()

        profile = ConfigProfile(
            profile_id=profile_id,
            name=name,
            created_at=now,
            updated_at=now,
            config=config,
            description=description,
            is_default=is_default,
        )

        self.registry.insert_profile(profile)
        return profile

    def get_profile(self, profile_id: str) -> ConfigProfile | None:
        """
        Get a profile by ID.

        Args:
            profile_id: Profile identifier

        Returns:
            ConfigProfile instance if found, None otherwise
        """
        return self.registry.get_profile(profile_id)

    def get_default_profile(self) -> ConfigProfile | None:
        """
        Get the default profile.

        Returns:
            Default ConfigProfile instance if one exists, None otherwise
        """
        return self.registry.get_default_profile()

    def list_profiles(self) -> list[ConfigProfile]:
        """
        List all profiles.

        Returns:
            List of ConfigProfile instances ordered by name
        """
        return self.registry.list_profiles()

    def update_profile(self, profile_id: str, **updates: Any) -> ConfigProfile | None:
        """
        Update profile fields.

        Args:
            profile_id: ID of profile to update
            **updates: Field names and values to update (name, description, config, is_default)

        Returns:
            Updated ConfigProfile instance if found, None otherwise
        """
        if "config" in updates and updates["config"] is not None:
            ensure_valid_persisted_config_payload(
                updates["config"],
                endpoint_profile_exists=self._endpoint_profile_ref_exists,
            )
        return self.registry.update_profile(profile_id, **updates)

    def delete_profile(self, profile_id: str) -> bool:
        """
        Delete a profile.

        Args:
            profile_id: ID of profile to delete

        Returns:
            True if deleted, False if not found

        Raises:
            ValueError: If profile is in use by any books
        """
        return self.registry.delete_profile(profile_id)

    def set_default_profile(self, profile_id: str) -> None:
        """
        Set a profile as the default.

        Args:
            profile_id: ID of profile to set as default

        Raises:
            ValueError: If profile doesn't exist
        """
        self.registry.set_default_profile(profile_id)

    # =========================================================================
    # System Default Seeding
    # =========================================================================

    def seed_system_defaults(self) -> None:
        """Seed system-default endpoint and config profiles for first-time users.

        Only seeds if both endpoint_profiles and config_profiles tables are empty.
        Creates three endpoint profiles (Gemini Pro, Gemini Flash, DeepSeek) and one
        config profile following recommended practices from the README.
        """
        if self.registry.has_any_endpoint_profile() or self.registry.has_any_profile():
            return

        now = time.time()

        # --- Endpoint Profiles ---
        gemini = EndpointProfile(
            profile_id="system-default-gemini-pro",
            name="system-default-gemini-pro",
            created_at=now,
            updated_at=now,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            model="gemini-2.5-pro",
            temperature=0.0,
            kwargs={"reasoning_effort": "low"},
        )
        self.registry.insert_endpoint_profile(gemini)

        gemini_flash = EndpointProfile(
            profile_id="system-default-gemini-flash",
            name="system-default-gemini-flash",
            created_at=now,
            updated_at=now,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            model="gemini-3-flash-preview",
            temperature=0.0,
        )
        self.registry.insert_endpoint_profile(gemini_flash)

        deepseek = EndpointProfile(
            profile_id="system-default-deepseek",
            name="system-default-deepseek",
            created_at=now,
            updated_at=now,
            base_url="https://api.deepseek.com",
            model="deepseek-chat",
            temperature=0.0,
        )
        self.registry.insert_endpoint_profile(deepseek)

        # --- Config Profile (follows README best practices) ---
        # DeepSeek for extraction/summarization (low-cost caching model)
        # Gemini for translation (high-quality translation model)
        default_config = ConfigProfile(
            profile_id="system-default-profile",
            name="system-default-profile",
            created_at=now,
            updated_at=now,
            config={
                "translation_target_language": "简体中文",
                "extractor_config": {"endpoint_profile": "system-default-deepseek"},
                "summarizor_config": {"endpoint_profile": "system-default-deepseek"},
                "glossary_config": {"endpoint_profile": "system-default-gemini-flash"},
                "translator_config": {"endpoint_profile": "system-default-gemini-pro"},
                "review_config": {"endpoint_profile": "system-default-gemini-flash"},
                "ocr_config": {"endpoint_profile": "system-default-gemini-flash"},
                "manga_translator_config": {"endpoint_profile": "system-default-gemini-pro"},
            },
        )
        self.registry.insert_profile(default_config)

    # =========================================================================
    # Endpoint Profile Management
    # =========================================================================

    def create_endpoint_profile(
        self,
        name: str,
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        temperature: float = 0.0,
        kwargs: dict[str, Any] | None = None,
        timeout: int = 60,
        max_retries: int = 3,
        concurrency: int = 5,
        description: str | None = None,
        is_default: bool = False,
        token_limit: int | None = None,
        input_token_limit: int | None = None,
        output_token_limit: int | None = None,
    ) -> EndpointProfile:
        """
        Create a new endpoint profile.

        Args:
            name: Profile name (must be unique)
            api_key: API key (optional, can use environment variable)
            base_url: Base URL for the API endpoint
            model: Model identifier
            temperature: Temperature for generation (0.0-1.0)
            timeout: Request timeout in seconds
            max_retries: Maximum number of retries
            concurrency: Maximum concurrent requests
            description: Optional description
            is_default: Whether this profile should be the default
            token_limit: Maximum total token usage limit (None = unlimited)
            input_token_limit: Maximum input token usage limit (None = unlimited)
            output_token_limit: Maximum output token usage limit (None = unlimited)

        Returns:
            Created EndpointProfile instance

        Raises:
            sqlite3.IntegrityError: If name already exists
        """
        profile_id = self._generate_id(name)
        now = time.time()

        profile = EndpointProfile(
            profile_id=profile_id,
            name=name,
            created_at=now,
            updated_at=now,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            kwargs=kwargs or {},
            timeout=timeout,
            max_retries=max_retries,
            concurrency=concurrency,
            description=description,
            is_default=is_default,
            token_limit=token_limit,
            input_token_limit=input_token_limit,
            output_token_limit=output_token_limit,
        )

        self.registry.insert_endpoint_profile(profile)
        return profile

    def get_endpoint_profile(self, profile_id: str) -> EndpointProfile | None:
        """
        Get an endpoint profile by ID.

        Args:
            profile_id: Profile identifier

        Returns:
            EndpointProfile instance if found, None otherwise
        """
        return self.registry.get_endpoint_profile(profile_id)

    def get_default_endpoint_profile(self) -> EndpointProfile | None:
        """
        Get the default endpoint profile.

        Returns:
            Default EndpointProfile instance if one exists, None otherwise
        """
        return self.registry.get_default_endpoint_profile()

    def list_endpoint_profiles(self) -> list[EndpointProfile]:
        """
        List all endpoint profiles.

        Returns:
            List of EndpointProfile instances ordered by name
        """
        return self.registry.list_endpoint_profiles()

    def update_endpoint_profile(self, profile_id: str, **updates: Any) -> EndpointProfile | None:
        """
        Update endpoint profile fields.

        Args:
            profile_id: ID of endpoint profile to update
            **updates: Field names and values to update (name, description, api_key, base_url,
                      model, temperature, timeout, max_retries, concurrency, is_default)

        Returns:
            Updated EndpointProfile instance if found, None otherwise
        """
        return self.registry.update_endpoint_profile(profile_id, **updates)

    def delete_endpoint_profile(self, profile_id: str) -> bool:
        """
        Delete an endpoint profile.

        Args:
            profile_id: ID of endpoint profile to delete

        Returns:
            True if deleted, False if not found
        """
        return self.registry.delete_endpoint_profile(profile_id)

    def set_default_endpoint_profile(self, profile_id: str) -> None:
        """
        Set an endpoint profile as the default.

        Args:
            profile_id: ID of endpoint profile to set as default

        Raises:
            ValueError: If profile doesn't exist
        """
        self.registry.set_default_endpoint_profile(profile_id)

    # =========================================================================
    # Book Management
    # =========================================================================

    def create_book(
        self,
        name: str,
        description: str | None = None,
        profile_id: str | None = None,
        custom_config: dict[str, Any] | None = None,
    ) -> Book:
        """
        Create a new book with folder structure.

        A book can either use a profile (shared config) or have custom config.
        These are mutually exclusive - if custom_config is provided, profile_id
        is ignored and the book will have its own config stored in book_config table.

        Args:
            name: Book name
            description: Optional description
            profile_id: Profile ID to use (if None and no custom_config, uses default profile)
            custom_config: Custom configuration dictionary (mutually exclusive with profile_id)

        Returns:
            Created Book instance

        Raises:
            ValueError: If no profiles exist (must create a profile first)
            ValueError: If specified profile_id doesn't exist
            Exception: If creation fails (triggers rollback)
        """
        # Enforce: at least one profile must exist
        if not self.registry.has_any_profile():
            raise ValueError("Create a profile before importing books")

        # Determine config source
        if custom_config is not None:
            ensure_valid_persisted_config_payload(
                custom_config,
                endpoint_profile_exists=self._endpoint_profile_ref_exists,
            )
            # Custom config mode: profile_id stays None
            actual_profile_id = None
        else:
            # Profile mode: use specified or default
            if profile_id is not None:
                # Verify profile exists
                profile = self.registry.get_profile(profile_id)
                if profile is None:
                    raise ValueError(f"Profile not found: {profile_id}")
                actual_profile_id = profile_id
            else:
                # Use default profile
                default_profile = self.registry.get_default_profile()
                if default_profile is None:
                    raise ValueError("No default profile found")
                actual_profile_id = default_profile.profile_id

        book_id = self._generate_id(name)
        now = time.time()

        book = Book(
            book_id=book_id,
            name=name,
            created_at=now,
            updated_at=now,
            description=description,
            status=BookStatus.ACTIVE,
            profile_id=actual_profile_id,
        )

        # Create folder structure
        book_path = self.get_book_path(book_id)
        try:
            book_path.mkdir(parents=True, exist_ok=False)
            (book_path / "logs").mkdir(exist_ok=True)

            # Insert book into registry
            self.registry.insert_book(book)

            # Store custom config if provided
            if custom_config is not None:
                self.registry.set_book_config(book_id, custom_config)

        except Exception as e:
            # Rollback: remove folder if it was created
            if book_path.exists():
                shutil.rmtree(book_path)
            raise e

        return book

    def get_book(self, book_id: str) -> Book | None:
        """
        Get book from registry.

        Args:
            book_id: Book identifier

        Returns:
            Book instance if found, None otherwise
        """
        return self.registry.get_book(book_id)

    def list_books(self, status: BookStatus | None = None) -> list[Book]:
        """
        List books with optional status filter.

        Args:
            status: Optional status filter

        Returns:
            List of Book instances
        """
        return self.registry.list_books(status=status)

    def delete_book(self, book_id: str, permanent: bool = False) -> bool:
        """
        Delete a book.

        Args:
            book_id: Book identifier
            permanent: If True, remove folder and registry entry; if False, soft delete

        Returns:
            True if deleted, False if not found
        """
        success = self.registry.delete_book(book_id, permanent=permanent)

        if success and permanent:
            # Remove folder
            book_path = self.get_book_path(book_id)
            if book_path.exists():
                shutil.rmtree(book_path)

        return success

    def update_book(self, book_id: str, **updates: Any) -> Book | None:
        """
        Update book metadata.

        Args:
            book_id: Book identifier
            **updates: Fields to update (name, description, source_language, profile_id, status)

        Returns:
            Updated Book instance if found, None otherwise
        """
        return self.registry.update_book(book_id, **updates)

    def set_book_custom_config(self, book_id: str, config: dict[str, Any]) -> None:
        """
        Set custom configuration for a book.

        This converts a book from profile mode to custom config mode.
        The book's profile_id will be set to None.

        Args:
            book_id: Book identifier
            config: Configuration dictionary

        Raises:
            ValueError: If book not found
        """
        ensure_valid_persisted_config_payload(
            config,
            endpoint_profile_exists=self._endpoint_profile_ref_exists,
        )

        book = self.registry.get_book(book_id)
        if book is None:
            raise ValueError(f"Book not found: {book_id}")

        # Clear profile_id and store custom config
        self.registry.update_book(book_id, profile_id=None)
        self.registry.set_book_config(book_id, config)

    def get_book_config(self, book_id: str) -> dict[str, Any] | None:
        """
        Get the effective configuration for a book.

        Returns config from profile if book uses a profile,
        or from book_config table if book has custom config.

        Args:
            book_id: Book identifier

        Returns:
            Configuration dictionary if found, None if book not found
        """
        book = self.registry.get_book(book_id)
        if book is None:
            return None

        if book.profile_id is not None:
            # Profile mode
            profile = self.registry.get_profile(book.profile_id)
            if profile is None:
                return None
            return profile.config
        else:
            # Custom config mode
            return self.registry.get_book_config(book_id)

    def get_config_snapshot_json(self, book_id: str) -> str:
        """
        Capture and serialize the current config for book_id as a JSON envelope string.

        Raises:
            ValueError: If the book is not found or has no valid config.
        """
        import json

        from context_aware_translation.config import Config

        book = self.registry.get_book(book_id)
        if book is None:
            raise ValueError(f"Book not found: {book_id}")

        config = Config.from_book(book, self.library_root, self.registry)
        from context_aware_translation.config import CONFIG_SNAPSHOT_VERSION

        envelope = {
            "snapshot_version": CONFIG_SNAPSHOT_VERSION,
            "config": config.to_dict(),
        }
        return json.dumps(envelope, ensure_ascii=False)

    def get_book_path(self, book_id: str) -> Path:
        """
        Get path to book folder.

        Args:
            book_id: Book identifier

        Returns:
            Path to book folder
        """
        return self.library_root / "books" / book_id

    def get_book_db_path(self, book_id: str) -> Path:
        """
        Get path to book.db.

        Args:
            book_id: Book identifier

        Returns:
            Path to book.db
        """
        return self.get_book_path(book_id) / "book.db"

    def get_book_context_tree_path(self, book_id: str) -> Path:
        """
        Get path to context_tree.db.

        Args:
            book_id: Book identifier

        Returns:
            Path to context_tree.db
        """
        return self.get_book_path(book_id) / "context_tree.db"

    def validate_book_name(self, name: str) -> str | None:
        """
        Validate book name format only.

        Note: Uniqueness is enforced via SQL UNIQUE constraint.
        UI should catch IntegrityError and show user-friendly message.

        Args:
            name: Name to validate

        Returns:
            Error message if invalid, None if valid
        """
        if not name or not name.strip():
            return "Book name is required"

        if len(name) > 200:
            return "Book name must be 200 characters or less"

        return None

    def get_book_progress(self, book_id: str) -> dict[str, int | float] | None:
        """
        Get translation progress for a book.

        Args:
            book_id: Book identifier

        Returns:
            Dictionary with keys: documents, chunks, translated_chunks, progress_percent
            Returns None if book not found or has no database yet.
        """
        book = self.get_book(book_id)
        if book is None:
            return None

        book_db_path = self.get_book_db_path(book_id)
        if not book_db_path.exists():
            return None

        from context_aware_translation.storage.book_db import SQLiteBookDB
        from context_aware_translation.storage.document_repository import DocumentRepository
        from context_aware_translation.storage.term_repository import TermRepository

        db = None
        try:
            db = SQLiteBookDB(book_db_path)
            term_repo = TermRepository(db)
            doc_repo = DocumentRepository(db)

            # Get document count
            documents = doc_repo.list_documents()
            doc_count = len(documents)

            # Get chunk stats
            chunk_stats = term_repo.get_chunk_stats()

            return {
                "documents": doc_count,
                "chunks": chunk_stats["total"],
                "translated_chunks": chunk_stats["translated"],
                "progress_percent": chunk_stats["progress_percent"],
            }
        except Exception:
            return None
        finally:
            if db is not None:
                db.close()

    def reset_endpoint_tokens(self, profile_id: str) -> EndpointProfile | None:
        """Reset token usage counter for an endpoint profile."""
        return self.registry.reset_endpoint_tokens(profile_id)

    def close(self) -> None:
        """Close registry connection."""
        self.registry.close()
