from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from context_aware_translation.storage.book import Book, BookStatus
from context_aware_translation.storage.config_profile import ConfigProfile
from context_aware_translation.storage.endpoint_profile import EndpointProfile

CREATE_CONFIG_PROFILES_TABLE = """
CREATE TABLE IF NOT EXISTS config_profiles (
    profile_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    config_json TEXT NOT NULL,
    is_default INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""

CREATE_DEFAULT_PROFILE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_default_profile
ON config_profiles(is_default) WHERE is_default = 1;
"""

CREATE_ENDPOINT_PROFILES_TABLE = """
CREATE TABLE IF NOT EXISTS endpoint_profiles (
    profile_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    api_key TEXT,
    base_url TEXT,
    model TEXT,
    temperature REAL DEFAULT 0.7,
    kwargs TEXT DEFAULT '{}',
    enable_thinking INTEGER DEFAULT 1,
    timeout INTEGER DEFAULT 60,
    max_retries INTEGER DEFAULT 3,
    concurrency INTEGER DEFAULT 5,
    is_default INTEGER DEFAULT 0,
    token_limit INTEGER DEFAULT NULL,
    tokens_used INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""

CREATE_ENDPOINT_DEFAULT_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_endpoint_default
ON endpoint_profiles(is_default) WHERE is_default = 1;
"""

CREATE_BOOKS_TABLE = """
CREATE TABLE IF NOT EXISTS books (
    book_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    source_language TEXT,
    profile_id TEXT REFERENCES config_profiles(profile_id),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    status TEXT DEFAULT 'active'
);
"""

CREATE_BOOK_CONFIG_TABLE = """
CREATE TABLE IF NOT EXISTS book_config (
    book_id TEXT PRIMARY KEY REFERENCES books(book_id),
    config_json TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""

# Migration: Add unique index on books.name for existing databases
# (New databases get UNIQUE constraint in table definition)
CREATE_BOOKS_NAME_UNIQUE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_books_name ON books(name);
"""


class RegistryDB:
    """
    SQLite-backed registry for managing books (translation projects) and config profiles.

    Thread-safe database for CRUD operations on books, profiles, and their configurations.
    """

    def __init__(self, sqlite_path: Path) -> None:
        self.db_path = Path(sqlite_path)
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Set check_same_thread=False to allow connection from multiple threads
        # WAL mode + proper locking ensures thread safety
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()  # Reentrant lock for thread safety
        self._configure_connection()
        self._init_schema()

    def _configure_connection(self) -> None:
        with self._lock:
            self.conn.execute("PRAGMA foreign_keys = ON;")
            self.conn.execute("PRAGMA journal_mode = WAL;")
            self.conn.execute("PRAGMA synchronous = FULL;")

    def _init_schema(self) -> None:
        with self._lock:
            cur = self.conn.cursor()
            # Create tables in order (profiles first due to FK)
            cur.execute(CREATE_CONFIG_PROFILES_TABLE)
            cur.execute(CREATE_DEFAULT_PROFILE_INDEX)
            cur.execute(CREATE_ENDPOINT_PROFILES_TABLE)
            cur.execute(CREATE_ENDPOINT_DEFAULT_INDEX)
            cur.execute(CREATE_BOOKS_TABLE)
            cur.execute(CREATE_BOOK_CONFIG_TABLE)
            # Migration: ensure unique index on books.name for existing databases
            cur.execute(CREATE_BOOKS_NAME_UNIQUE_INDEX)
            # Migration: Add token tracking columns to endpoint_profiles
            with contextlib.suppress(sqlite3.OperationalError):
                cur.execute("ALTER TABLE endpoint_profiles ADD COLUMN token_limit INTEGER DEFAULT NULL")
            with contextlib.suppress(sqlite3.OperationalError):
                cur.execute("ALTER TABLE endpoint_profiles ADD COLUMN tokens_used INTEGER DEFAULT 0")
            with contextlib.suppress(sqlite3.OperationalError):
                cur.execute("ALTER TABLE endpoint_profiles ADD COLUMN input_token_limit INTEGER DEFAULT NULL")
            with contextlib.suppress(sqlite3.OperationalError):
                cur.execute("ALTER TABLE endpoint_profiles ADD COLUMN output_token_limit INTEGER DEFAULT NULL")
            with contextlib.suppress(sqlite3.OperationalError):
                cur.execute("ALTER TABLE endpoint_profiles ADD COLUMN input_tokens_used INTEGER DEFAULT 0")
            with contextlib.suppress(sqlite3.OperationalError):
                cur.execute("ALTER TABLE endpoint_profiles ADD COLUMN output_tokens_used INTEGER DEFAULT 0")
            with contextlib.suppress(sqlite3.OperationalError):
                cur.execute("ALTER TABLE endpoint_profiles ADD COLUMN cached_input_tokens_used INTEGER DEFAULT 0")
            with contextlib.suppress(sqlite3.OperationalError):
                cur.execute("ALTER TABLE endpoint_profiles ADD COLUMN uncached_input_tokens_used INTEGER DEFAULT 0")
            with contextlib.suppress(sqlite3.OperationalError):
                cur.execute("ALTER TABLE endpoint_profiles ADD COLUMN enable_thinking INTEGER DEFAULT 1")
            with contextlib.suppress(sqlite3.OperationalError):
                cur.execute("ALTER TABLE endpoint_profiles ADD COLUMN kwargs TEXT DEFAULT '{}'")
            self.conn.commit()
            self._checkpoint()

    def _checkpoint(self) -> None:
        """
        Force WAL checkpoint to ensure data is written to the main database file.

        This ensures that subsequent reads (even from other connections or after
        copying the DB file) see the committed data immediately.
        """
        # Note: _checkpoint is called from within locked methods, so no need to lock here
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")

    # =========================================================================
    # Profile CRUD Methods
    # =========================================================================

    def insert_profile(self, profile: ConfigProfile) -> None:
        """
        Insert a new profile into the registry.

        If this is the first profile and is_default is not set, it becomes the default.

        Args:
            profile: ConfigProfile instance to insert

        Raises:
            sqlite3.IntegrityError: If profile_id or name already exists
        """
        with self._lock:
            # If this is the first profile and no default is set, make it default
            if not self.has_any_profile() and not profile.is_default:
                profile.is_default = True

            self.conn.execute(
                """
                INSERT INTO config_profiles(profile_id, name, description, config_json, is_default, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.profile_id,
                    profile.name,
                    profile.description,
                    json.dumps(profile.config, ensure_ascii=False),
                    1 if profile.is_default else 0,
                    profile.created_at,
                    profile.updated_at,
                ),
            )
            self.conn.commit()
            self._checkpoint()

    def get_profile(self, profile_id: str) -> ConfigProfile | None:
        """
        Retrieve a profile by its ID.

        Args:
            profile_id: Unique identifier of the profile

        Returns:
            ConfigProfile instance if found, None otherwise
        """
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM config_profiles WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()

            if row is None:
                return None

            return self._row_to_profile(row)

    def get_default_profile(self) -> ConfigProfile | None:
        """
        Retrieve the default profile.

        Returns:
            ConfigProfile instance if a default exists, None otherwise
        """
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM config_profiles WHERE is_default = 1",
            ).fetchone()

            if row is None:
                return None

            return self._row_to_profile(row)

    def list_profiles(self) -> list[ConfigProfile]:
        """
        List all profiles.

        Returns:
            List of ConfigProfile instances ordered by name
        """
        with self._lock:
            rows = self.conn.execute("SELECT * FROM config_profiles ORDER BY name").fetchall()

            return [self._row_to_profile(row) for row in rows]

    def update_profile(self, profile_id: str, **updates: Any) -> ConfigProfile | None:
        """
        Update profile fields.

        Args:
            profile_id: ID of profile to update
            **updates: Field names and values to update (name, description, config, is_default)

        Returns:
            Updated ConfigProfile instance if found, None otherwise
        """
        with self._lock:
            # Check if profile exists
            existing = self.conn.execute(
                "SELECT 1 FROM config_profiles WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()

            if existing is None:
                return None

            # Build update query dynamically
            allowed_fields = {"name", "description", "config", "is_default"}
            update_fields = {k: v for k, v in updates.items() if k in allowed_fields}

            now = time.time()

            if update_fields:
                # Handle config serialization
                if "config" in update_fields:
                    update_fields["config_json"] = json.dumps(update_fields.pop("config"), ensure_ascii=False)

                # Handle is_default boolean to int
                if "is_default" in update_fields:
                    update_fields["is_default"] = 1 if update_fields["is_default"] else 0

                # Always update updated_at
                update_fields["updated_at"] = now

                set_clause = ", ".join(f"{field} = ?" for field in update_fields)
                values = list(update_fields.values())
                values.append(profile_id)

                self.conn.execute(
                    f"UPDATE config_profiles SET {set_clause} WHERE profile_id = ?",
                    values,
                )

                self.conn.commit()
                self._checkpoint()

            return self.get_profile(profile_id)

    def delete_profile(self, profile_id: str) -> bool:
        """
        Delete a profile.

        Args:
            profile_id: ID of profile to delete

        Returns:
            True if profile was deleted, False if not found

        Raises:
            ValueError: If profile is in use by any books
        """
        with self._lock:
            # Check if profile exists
            existing = self.conn.execute(
                "SELECT 1 FROM config_profiles WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()

            if existing is None:
                return False

            # Check if any books are using this profile
            books_using = self.conn.execute(
                "SELECT COUNT(*) FROM books WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()[0]

            if books_using > 0:
                raise ValueError(f"Cannot delete profile: {books_using} book(s) are using it")

            self.conn.execute(
                "DELETE FROM config_profiles WHERE profile_id = ?",
                (profile_id,),
            )
            self.conn.commit()
            self._checkpoint()
            return True

    def set_default_profile(self, profile_id: str) -> None:
        """
        Set a profile as the default.

        Args:
            profile_id: ID of profile to set as default

        Raises:
            ValueError: If profile doesn't exist
        """
        with self._lock:
            # Check if profile exists
            existing = self.conn.execute(
                "SELECT 1 FROM config_profiles WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()

            if existing is None:
                raise ValueError(f"Profile not found: {profile_id}")

            # Clear existing default
            self.conn.execute("UPDATE config_profiles SET is_default = 0 WHERE is_default = 1")

            # Set new default
            self.conn.execute(
                "UPDATE config_profiles SET is_default = 1, updated_at = ? WHERE profile_id = ?",
                (time.time(), profile_id),
            )
            self.conn.commit()
            self._checkpoint()

    def has_any_profile(self) -> bool:
        """
        Check if any profile exists.

        Returns:
            True if at least one profile exists, False otherwise
        """
        with self._lock:
            row = self.conn.execute("SELECT COUNT(*) FROM config_profiles").fetchone()
            return bool(row[0] > 0)

    def _row_to_profile(self, row: sqlite3.Row) -> ConfigProfile:
        """Convert a database row to a ConfigProfile instance."""
        return ConfigProfile(
            profile_id=row["profile_id"],
            name=row["name"],
            description=row["description"],
            config=json.loads(row["config_json"]),
            is_default=bool(row["is_default"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # =========================================================================
    # Endpoint Profile CRUD Methods
    # =========================================================================

    def insert_endpoint_profile(self, profile: EndpointProfile) -> None:
        """
        Insert a new endpoint profile into the registry.

        If this is the first endpoint profile and is_default is not set, it becomes the default.

        Args:
            profile: EndpointProfile instance to insert

        Raises:
            sqlite3.IntegrityError: If profile_id or name already exists
        """
        with self._lock:
            # If this is the first endpoint profile and no default is set, make it default
            if not self.has_any_endpoint_profile() and not profile.is_default:
                profile.is_default = True

            self.conn.execute(
                """
                INSERT INTO endpoint_profiles(profile_id, name, description, api_key, base_url, model,
                                             temperature, kwargs, timeout, max_retries, concurrency, is_default,
                                             token_limit, tokens_used,
                                             input_token_limit, output_token_limit,
                                             input_tokens_used, output_tokens_used,
                                             cached_input_tokens_used, uncached_input_tokens_used,
                                             created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.profile_id,
                    profile.name,
                    profile.description,
                    profile.api_key,
                    profile.base_url,
                    profile.model,
                    profile.temperature,
                    json.dumps(profile.kwargs or {}),
                    profile.timeout,
                    profile.max_retries,
                    profile.concurrency,
                    1 if profile.is_default else 0,
                    profile.token_limit,
                    profile.tokens_used,
                    profile.input_token_limit,
                    profile.output_token_limit,
                    profile.input_tokens_used,
                    profile.output_tokens_used,
                    profile.cached_input_tokens_used,
                    profile.uncached_input_tokens_used,
                    profile.created_at,
                    profile.updated_at,
                ),
            )
            self.conn.commit()
            self._checkpoint()

    def get_endpoint_profile(self, profile_id: str) -> EndpointProfile | None:
        """
        Retrieve an endpoint profile by its ID.

        Args:
            profile_id: Unique identifier of the endpoint profile

        Returns:
            EndpointProfile instance if found, None otherwise
        """
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM endpoint_profiles WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()

            if row is None:
                return None

            return self._row_to_endpoint_profile(row)

    def get_default_endpoint_profile(self) -> EndpointProfile | None:
        """
        Retrieve the default endpoint profile.

        Returns:
            EndpointProfile instance if a default exists, None otherwise
        """
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM endpoint_profiles WHERE is_default = 1",
            ).fetchone()

            if row is None:
                return None

            return self._row_to_endpoint_profile(row)

    def list_endpoint_profiles(self) -> list[EndpointProfile]:
        """
        List all endpoint profiles.

        Returns:
            List of EndpointProfile instances ordered by name
        """
        with self._lock:
            rows = self.conn.execute("SELECT * FROM endpoint_profiles ORDER BY name").fetchall()

            return [self._row_to_endpoint_profile(row) for row in rows]

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
        with self._lock:
            # Check if profile exists
            existing = self.conn.execute(
                "SELECT 1 FROM endpoint_profiles WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()

            if existing is None:
                return None

            # Build update query dynamically
            allowed_fields = {
                "name",
                "description",
                "api_key",
                "base_url",
                "model",
                "temperature",
                "kwargs",
                "timeout",
                "max_retries",
                "concurrency",
                "is_default",
                "token_limit",
                "tokens_used",
                "input_token_limit",
                "output_token_limit",
                "input_tokens_used",
                "output_tokens_used",
                "cached_input_tokens_used",
                "uncached_input_tokens_used",
            }
            update_fields = {k: v for k, v in updates.items() if k in allowed_fields}

            now = time.time()

            if update_fields:
                # Handle is_default boolean to int
                if "is_default" in update_fields:
                    update_fields["is_default"] = 1 if update_fields["is_default"] else 0
                # Handle kwargs dict to JSON string
                if "kwargs" in update_fields:
                    update_fields["kwargs"] = json.dumps(update_fields["kwargs"] or {})

                # Always update updated_at
                update_fields["updated_at"] = now

                set_clause = ", ".join(f"{field} = ?" for field in update_fields)
                values = list(update_fields.values())
                values.append(profile_id)

                self.conn.execute(
                    f"UPDATE endpoint_profiles SET {set_clause} WHERE profile_id = ?",
                    values,
                )

                self.conn.commit()
                self._checkpoint()

            return self.get_endpoint_profile(profile_id)

    def delete_endpoint_profile(self, profile_id: str) -> bool:
        """
        Delete an endpoint profile.

        Args:
            profile_id: ID of endpoint profile to delete

        Returns:
            True if profile was deleted, False if not found
        """
        with self._lock:
            # Check if profile exists
            existing = self.conn.execute(
                "SELECT 1 FROM endpoint_profiles WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()

            if existing is None:
                return False

            self.conn.execute(
                "DELETE FROM endpoint_profiles WHERE profile_id = ?",
                (profile_id,),
            )
            self.conn.commit()
            self._checkpoint()
            return True

    def set_default_endpoint_profile(self, profile_id: str) -> None:
        """
        Set an endpoint profile as the default.

        Args:
            profile_id: ID of endpoint profile to set as default

        Raises:
            ValueError: If profile doesn't exist
        """
        with self._lock:
            # Check if profile exists
            existing = self.conn.execute(
                "SELECT 1 FROM endpoint_profiles WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()

            if existing is None:
                raise ValueError(f"Endpoint profile not found: {profile_id}")

            # Clear existing default
            self.conn.execute("UPDATE endpoint_profiles SET is_default = 0 WHERE is_default = 1")

            # Set new default
            self.conn.execute(
                "UPDATE endpoint_profiles SET is_default = 1, updated_at = ? WHERE profile_id = ?",
                (time.time(), profile_id),
            )
            self.conn.commit()
            self._checkpoint()

    def has_any_endpoint_profile(self) -> bool:
        """
        Check if any endpoint profile exists.

        Returns:
            True if at least one endpoint profile exists, False otherwise
        """
        with self._lock:
            row = self.conn.execute("SELECT COUNT(*) FROM endpoint_profiles").fetchone()
            return bool(row[0] > 0)

    def _row_to_endpoint_profile(self, row: sqlite3.Row) -> EndpointProfile:
        """Convert a database row to an EndpointProfile instance."""
        return EndpointProfile(
            profile_id=row["profile_id"],
            name=row["name"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            description=row["description"],
            api_key=row["api_key"] or "",
            base_url=row["base_url"] or "",
            model=row["model"] or "",
            temperature=row["temperature"],
            kwargs=json.loads(row["kwargs"]) if row["kwargs"] else {},
            timeout=row["timeout"],
            max_retries=row["max_retries"],
            concurrency=row["concurrency"],
            is_default=bool(row["is_default"]),
            token_limit=row["token_limit"],
            tokens_used=row["tokens_used"],
            input_token_limit=row["input_token_limit"],
            output_token_limit=row["output_token_limit"],
            input_tokens_used=row["input_tokens_used"],
            output_tokens_used=row["output_tokens_used"],
            cached_input_tokens_used=row["cached_input_tokens_used"],
            uncached_input_tokens_used=row["uncached_input_tokens_used"],
        )

    # =========================================================================
    # Book CRUD Methods
    # =========================================================================

    def insert_book(self, book: Book) -> None:
        """
        Insert a new book into the registry.

        Args:
            book: Book instance to insert

        Raises:
            sqlite3.IntegrityError: If book_id already exists
        """
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO books(book_id, name, description, source_language, profile_id, created_at, updated_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book.book_id,
                    book.name,
                    book.description,
                    book.source_language,
                    book.profile_id,
                    book.created_at,
                    book.updated_at,
                    book.status.value,
                ),
            )
            self.conn.commit()
            self._checkpoint()

    def get_book(self, book_id: str) -> Book | None:
        """
        Retrieve a book by its ID.

        Args:
            book_id: Unique identifier of the book

        Returns:
            Book instance if found, None otherwise
        """
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM books WHERE book_id = ?",
                (book_id,),
            ).fetchone()

            if row is None:
                return None

            return self._row_to_book(row)

    def list_books(self, status: BookStatus | None = None) -> list[Book]:
        """
        List all books, optionally filtered by status.

        Args:
            status: Optional status filter (ACTIVE, ARCHIVED, DELETED)

        Returns:
            List of Book instances matching the filter
        """
        with self._lock:
            if status is not None:
                rows = self.conn.execute(
                    "SELECT * FROM books WHERE status = ? ORDER BY updated_at DESC",
                    (status.value,),
                ).fetchall()
            else:
                rows = self.conn.execute("SELECT * FROM books ORDER BY updated_at DESC").fetchall()

            return [self._row_to_book(row) for row in rows]

    def update_book(self, book_id: str, **updates: Any) -> Book | None:
        """
        Update book fields.

        Args:
            book_id: ID of book to update
            **updates: Field names and values to update (name, description, source_language, profile_id, status)

        Returns:
            Updated Book instance if found, None otherwise
        """
        with self._lock:
            # Check if book exists
            existing = self.conn.execute(
                "SELECT 1 FROM books WHERE book_id = ?",
                (book_id,),
            ).fetchone()

            if existing is None:
                return None

            # Build update query dynamically
            allowed_fields = {"name", "description", "source_language", "profile_id", "status"}
            update_fields = {k: v for k, v in updates.items() if k in allowed_fields}

            now = time.time()

            if update_fields:
                # Convert status enum to string if present
                if "status" in update_fields and isinstance(update_fields["status"], BookStatus):
                    update_fields["status"] = update_fields["status"].value

                # Always update updated_at
                update_fields["updated_at"] = now

                set_clause = ", ".join(f"{field} = ?" for field in update_fields)
                values = list(update_fields.values())
                values.append(book_id)

                self.conn.execute(
                    f"UPDATE books SET {set_clause} WHERE book_id = ?",
                    values,
                )

            self.conn.commit()
            self._checkpoint()

            return self.get_book(book_id)

    def delete_book(self, book_id: str, permanent: bool = False) -> bool:
        """
        Delete a book (soft delete by default, or permanent).

        Args:
            book_id: ID of book to delete
            permanent: If True, permanently delete; if False, set status to DELETED

        Returns:
            True if book was deleted, False if not found
        """
        with self._lock:
            # Check if book exists
            existing = self.conn.execute(
                "SELECT 1 FROM books WHERE book_id = ?",
                (book_id,),
            ).fetchone()

            if existing is None:
                return False

            if permanent:
                # Permanent delete - remove book and config
                self.conn.execute(
                    "DELETE FROM book_config WHERE book_id = ?",
                    (book_id,),
                )
                self.conn.execute(
                    "DELETE FROM books WHERE book_id = ?",
                    (book_id,),
                )
            else:
                # Soft delete - set status to DELETED
                self.conn.execute(
                    "UPDATE books SET status = ?, updated_at = ? WHERE book_id = ?",
                    (BookStatus.DELETED.value, time.time(), book_id),
                )

            self.conn.commit()
            self._checkpoint()
            return True

    def set_book_config(self, book_id: str, config: dict[str, Any]) -> None:
        """
        Store or update book-specific custom configuration.

        Used when a book has custom config (profile_id is NULL).

        Args:
            book_id: ID of the book
            config: Configuration dictionary to store

        Raises:
            sqlite3.IntegrityError: If book_id doesn't exist
        """
        with self._lock:
            now = time.time()
            config_json = json.dumps(config, ensure_ascii=False)

            self.conn.execute(
                """
                INSERT INTO book_config(book_id, config_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                    config_json = excluded.config_json,
                    updated_at = excluded.updated_at
                """,
                (book_id, config_json, now),
            )
            self.conn.commit()
            self._checkpoint()

    def get_book_config(self, book_id: str) -> dict[str, Any] | None:
        """
        Retrieve book-specific custom configuration.

        Args:
            book_id: ID of the book

        Returns:
            Configuration dictionary if found, None otherwise
        """
        with self._lock:
            row = self.conn.execute(
                "SELECT config_json FROM book_config WHERE book_id = ?",
                (book_id,),
            ).fetchone()

            if row is None:
                return None

            result: dict[str, Any] = json.loads(row["config_json"])
            return result

    def close(self) -> None:
        """Close the SQLite connection."""
        with self._lock:
            with contextlib.suppress(Exception):
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            self.conn.close()

    def increment_endpoint_tokens(
        self,
        profile_id: str,
        token_count: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_input_tokens: int = 0,
        uncached_input_tokens: int = 0,
    ) -> EndpointProfile | None:
        """Atomically increment token usage for an endpoint profile."""
        with self._lock:
            self.conn.execute(
                """UPDATE endpoint_profiles
                   SET tokens_used = tokens_used + ?,
                       input_tokens_used = input_tokens_used + ?,
                       output_tokens_used = output_tokens_used + ?,
                       cached_input_tokens_used = cached_input_tokens_used + ?,
                       uncached_input_tokens_used = uncached_input_tokens_used + ?
                   WHERE profile_id = ?""",
                (token_count, input_tokens, output_tokens, cached_input_tokens, uncached_input_tokens, profile_id),
            )
            self.conn.commit()
            self._checkpoint()
            return self.get_endpoint_profile(profile_id)

    def reset_endpoint_tokens(self, profile_id: str) -> EndpointProfile | None:
        """Reset token usage counters for an endpoint profile."""
        with self._lock:
            self.conn.execute(
                """UPDATE endpoint_profiles
                   SET tokens_used = 0, input_tokens_used = 0, output_tokens_used = 0,
                       cached_input_tokens_used = 0, uncached_input_tokens_used = 0
                   WHERE profile_id = ?""",
                (profile_id,),
            )
            self.conn.commit()
            self._checkpoint()
            return self.get_endpoint_profile(profile_id)

    def _row_to_book(self, row: sqlite3.Row) -> Book:
        """Convert a database row to a Book instance."""
        row_dict = dict(row)
        return Book(
            book_id=row["book_id"],
            name=row["name"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            description=row_dict.get("description"),
            source_language=row_dict.get("source_language"),
            status=BookStatus(row["status"]),
            profile_id=row_dict.get("profile_id"),
        )
