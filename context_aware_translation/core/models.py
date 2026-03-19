from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

ALLOWED_TERM_TYPES = ("character", "organization", "other")
IMPORTED_DESCRIPTION_KEY = "imported"

TERM_TYPE_PRIORITY: dict[str, int] = {
    "character": 0,
    "organization": 1,
    "other": 2,
}


def parse_term_type(term_type: str | None) -> str | None:
    normalized = str(term_type or "").strip().lower().replace("-", " ").replace("_", " ")
    normalized = " ".join(normalized.split())
    if normalized in ALLOWED_TERM_TYPES:
        return normalized
    return None


def normalize_term_type(term_type: str | None) -> str:
    parsed = parse_term_type(term_type)
    if parsed is not None:
        return parsed
    return "other"


def normalize_term_type_votes(term_type_votes: dict[str, int] | None) -> dict[str, int]:
    normalized: Counter[str] = Counter()
    for raw_type, raw_votes in (term_type_votes or {}).items():
        try:
            votes = int(raw_votes)
        except (TypeError, ValueError):
            continue
        if votes <= 0:
            continue
        normalized[normalize_term_type(raw_type)] += votes
    return dict(normalized)


def normalize_term_type_state(
    term_type: str | None,
    term_type_votes: dict[str, int] | None,
    votes: int,
    *,
    descriptions: Mapping[str, str] | None = None,
) -> tuple[str, dict[str, int]]:
    normalized_type = normalize_term_type(term_type)
    normalized_votes = normalize_term_type_votes(term_type_votes)
    if normalized_votes:
        normalized_type = choose_term_type(normalized_votes)
    elif votes > 0 and (normalized_type != "other" or has_chunk_description_evidence(descriptions or {})):
        normalized_votes = {normalized_type: votes}
    return normalized_type, normalized_votes


def description_index(key: object) -> int | None:
    if key == IMPORTED_DESCRIPTION_KEY:
        return -1
    if isinstance(key, int):
        return key
    raw = str(key).strip()
    if raw == IMPORTED_DESCRIPTION_KEY:
        return -1
    if raw.lstrip("-").isdigit():
        return int(raw)
    return None


def ordered_description_entries(
    descriptions: Mapping[str, str],
    *,
    query_index: int | None = None,
) -> list[tuple[str, str]]:
    def _sort_key(raw_key: object) -> tuple[int, int | str]:
        idx = description_index(raw_key)
        if idx is None:
            return (2, str(raw_key))
        if idx == -1:
            return (0, -1)
        return (1, idx)

    entries: list[tuple[str, str]] = []
    for raw_key in sorted(descriptions.keys(), key=_sort_key):
        idx = description_index(raw_key)
        if idx is None:
            continue
        if idx >= 0 and query_index is not None and idx >= query_index:
            continue
        value = str(descriptions[raw_key]).strip()
        if value:
            entries.append((str(raw_key), value))
    return entries


def ordered_description_values(
    descriptions: Mapping[str, str],
    *,
    query_index: int | None = None,
) -> list[str]:
    return [value for _key, value in ordered_description_entries(descriptions, query_index=query_index)]


def has_chunk_description_evidence(descriptions: Mapping[str, str]) -> bool:
    return any((idx := description_index(key)) is not None and idx >= 0 for key in descriptions)


def choose_term_type(term_type_votes: dict[str, int]) -> str:
    if not term_type_votes:
        return "other"
    return min(
        term_type_votes.items(),
        key=lambda item: (-item[1], TERM_TYPE_PRIORITY.get(item[0], TERM_TYPE_PRIORITY["other"])),
    )[0]


def _effective_term_type_votes(term: Term) -> dict[str, int]:
    normalized = normalize_term_type_votes(term.term_type_votes)
    if normalized:
        return normalized
    if term.votes > 0 and (
        normalize_term_type(term.term_type) != "other" or has_chunk_description_evidence(term.descriptions)
    ):
        return {normalize_term_type(term.term_type): term.votes}
    return {}


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
    term_type: str = "other"
    term_type_votes: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.term_type, self.term_type_votes = normalize_term_type_state(
            self.term_type,
            self.term_type_votes,
            self.votes,
            descriptions=self.descriptions,
        )

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
        self.term_type_votes = dict(
            Counter(_effective_term_type_votes(self)) + Counter(_effective_term_type_votes(other))
        )
        self.term_type = choose_term_type(self.term_type_votes)
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
