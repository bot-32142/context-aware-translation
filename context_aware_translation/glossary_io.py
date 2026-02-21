"""Glossary import/export functionality."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context_aware_translation.storage.book_db import SQLiteBookDB
    from context_aware_translation.storage.context_tree_db import ContextTreeDB

from context_aware_translation.storage.book_db import TermRecord


def _sort_key(key: str) -> int:
    if key == "imported":
        return -1
    try:
        return int(key)
    except (TypeError, ValueError):
        return 0


def _consolidate_description(descriptions: dict[str, str]) -> str:
    sorted_keys = sorted(descriptions.keys(), key=_sort_key)
    return " ".join(descriptions[k] for k in sorted_keys if descriptions[k])


def export_glossary(
    db: SQLiteBookDB,
    output_path: Path,
    summarized_descriptions: dict[str, str] | None = None,
) -> int:
    """Export all glossary terms to a JSON file.

    Returns the number of terms exported.
    """
    terms = db.list_terms()
    entries = []
    for term in terms:
        description = (
            summarized_descriptions.get(term.key)
            if summarized_descriptions is not None and term.key in summarized_descriptions
            else _consolidate_description(term.descriptions)
        )
        entries.append(
            {
                "key": term.key,
                "translated_name": term.translated_name,
                "description": description,
                "ignored": term.ignored,
                "is_reviewed": term.is_reviewed,
            }
        )

    data = {"version": 1, "terms": entries}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return len(entries)


def _validate_glossary_json(data: object) -> None:
    """Validate glossary JSON structure. Raises ValueError on invalid data."""
    if not isinstance(data, dict):
        raise ValueError("Invalid glossary file: expected a JSON object")

    version = data.get("version")
    if version is not None and version > 1:
        raise ValueError(
            f"Unsupported glossary format version: {version}. This version of the application supports version 1."
        )

    if "terms" not in data:
        raise ValueError("Invalid glossary file: missing 'terms' key")

    terms = data["terms"]
    if not isinstance(terms, list):
        raise ValueError("Invalid glossary file: 'terms' must be a list")

    for i, entry in enumerate(terms):
        if not isinstance(entry, dict):
            raise ValueError(f"Invalid glossary file: entry {i} must be a dict")
        if "key" not in entry or not entry["key"]:
            raise ValueError(f"Invalid glossary file: entry {i} missing or empty 'key'")


def import_glossary(
    db: SQLiteBookDB,
    context_tree_db: ContextTreeDB,
    input_path: Path,
    include_translations: bool = True,
) -> int:
    """Import glossary terms from a JSON file, replacing all existing terms.

    Returns the number of terms imported.
    """
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    _validate_glossary_json(data)

    # Wipe existing data
    context_tree_db.delete_all()
    db.conn.execute("DELETE FROM terms")

    # Build and insert term records
    now = time.time()
    term_records = []
    for entry in data["terms"]:
        description = entry.get("description", "")
        term_record = TermRecord(
            key=entry["key"],
            descriptions={"imported": description} if description else {},
            occurrence={},
            votes=1,
            total_api_calls=1,
            new_translation=None,
            translated_name=entry.get("translated_name") if include_translations else None,
            ignored=entry.get("ignored", False),
            is_reviewed=entry.get("is_reviewed", False),
            created_at=now,
            updated_at=now,
        )
        term_records.append(term_record)

    db.upsert_terms(term_records)
    return len(term_records)
