from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any


class BookStatus(Enum):
    """Status of a book in the system."""

    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


@dataclass
class Book:
    """
    Represents a book/translation project.

    A book is a container for documents that share translation settings,
    terminology, and context. Each book references either a config profile
    (profile_id is set) or has custom configuration stored in book_config table
    (profile_id is None).
    """

    book_id: str
    name: str
    created_at: float
    updated_at: float
    description: str | None = None
    source_language: str | None = None
    status: BookStatus = BookStatus.ACTIVE
    profile_id: str | None = None  # References config_profiles.profile_id, None for custom config

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize to dictionary for JSON/DB storage.

        Returns:
            Dictionary representation with all fields, including enum as string value.
        """
        return {
            "book_id": self.book_id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "description": self.description,
            "source_language": self.source_language,
            "status": self.status.value,
            "profile_id": self.profile_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Book:
        """
        Deserialize from dictionary.

        Args:
            data: Dictionary with book fields. The 'status' field can be either
                  a string value or a BookStatus enum instance.

        Returns:
            Book instance reconstructed from the dictionary.
        """
        # Handle status field - convert string to enum if needed
        status_value = data.get("status", BookStatus.ACTIVE.value)
        status = BookStatus(status_value) if isinstance(status_value, str) else status_value

        # Handle timestamps - provide defaults if missing
        now = time.time()
        created_at = data.get("created_at", now)
        updated_at = data.get("updated_at", now)

        return cls(
            book_id=data["book_id"],
            name=data["name"],
            created_at=created_at,
            updated_at=updated_at,
            description=data.get("description"),
            source_language=data.get("source_language"),
            status=status,
            profile_id=data.get("profile_id"),
        )
