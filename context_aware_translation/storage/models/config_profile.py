from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class ConfigProfile:
    """
    Represents a configuration profile for translation settings.

    A profile contains LLM configuration and translation settings that can be
    shared across multiple books. Books can either reference a profile or have
    custom configuration stored separately.
    """

    profile_id: str
    name: str
    created_at: float
    updated_at: float
    config: dict[str, Any]  # Full config JSON including translation_target_language
    description: str | None = None
    is_default: bool = False

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize to dictionary for JSON/DB storage.

        Returns:
            Dictionary representation with all fields.
        """
        return {
            "profile_id": self.profile_id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "config": self.config,
            "description": self.description,
            "is_default": self.is_default,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConfigProfile:
        """
        Deserialize from dictionary.

        Args:
            data: Dictionary with profile fields.

        Returns:
            ConfigProfile instance reconstructed from the dictionary.
        """
        # Handle timestamps - provide defaults if missing
        now = time.time()
        created_at = data.get("created_at", now)
        updated_at = data.get("updated_at", now)

        return cls(
            profile_id=data["profile_id"],
            name=data["name"],
            created_at=created_at,
            updated_at=updated_at,
            config=data["config"],
            description=data.get("description"),
            is_default=data.get("is_default", False),
        )
