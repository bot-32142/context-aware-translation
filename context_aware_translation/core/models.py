from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class KeyedContext(Protocol):
    """Protocol defining the interface for mergeable context terms."""

    key: str
    descriptions: dict
    ignored: bool

    def merge(self, other: KeyedContext) -> None:
        """Merge another term into this one in-place."""
        ...

    def get_key(self) -> str:
        """Return the key used for dictionary lookups."""
        ...


@dataclass
class Term:
    key: str
    descriptions: dict
    occurrence: dict
    votes: int
    total_api_calls: int
    new_translation: str | None = None
    translated_name: str | None = None
    ignored: bool = False

    def merge(self, other: KeyedContext) -> None:
        """Merge another term into this one in-place."""
        if not isinstance(other, Term):
            raise TypeError(f"Cannot merge {type(other)} into Term")
        if (
            self.new_translation is not None
            and other.new_translation is not None
            and self.new_translation != other.new_translation
        ):
            raise ValueError(
                f"New translation mismatch for {self.key}: {self.new_translation} != {other.new_translation}"
            )
        if (
            self.translated_name is not None
            and other.translated_name is not None
            and self.translated_name != other.translated_name
        ):
            raise ValueError(
                f"Translated name mismatch for {self.key}: {self.translated_name} != {other.translated_name}"
            )
        self.votes += other.votes
        self.total_api_calls += other.total_api_calls
        # Merge descriptions dict
        self.descriptions.update(other.descriptions)
        # Merge occurrence dict
        self.occurrence.update(other.occurrence)
        # Merge new translation - only overwrite if other is not None
        if other.new_translation is not None:
            self.new_translation = other.new_translation
        # Merge translated name - only overwrite if other is not None
        if other.translated_name is not None:
            self.translated_name = other.translated_name
        # Merge ignored
        self.ignored = self.ignored or other.ignored

    def get_key(self) -> str:
        """Return the key used for dictionary lookups."""
        return self.key
