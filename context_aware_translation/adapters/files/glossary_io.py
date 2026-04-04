"""Glossary import/export functionality."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

from context_aware_translation.core.models import normalize_term_type, ordered_description_values

if TYPE_CHECKING:
    from context_aware_translation.storage.schema.book_db import SQLiteBookDB

from context_aware_translation.storage.schema.book_db import TermRecord


def _consolidate_description(descriptions: dict[str, str]) -> str:
    return " ".join(ordered_description_values(descriptions))


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
                "term_type": term.term_type,
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


def _validate_simple_glossary_json(data: object) -> None:
    """Validate flat term-to-translation JSON mappings."""
    if not isinstance(data, dict):
        raise ValueError("Invalid glossary file: expected a JSON object")
    for key, value in data.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Invalid glossary file: flat mapping keys must be non-empty strings")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Invalid glossary file: flat mapping values must be non-empty strings")


def _build_import_term_record(
    key: str,
    *,
    translated_name: str | None = None,
    description: str = "",
    term_type: str | None = None,
    ignored: bool = False,
    is_reviewed: bool = False,
) -> TermRecord:
    now = time.time()
    return TermRecord(
        key=key,
        descriptions={"imported": description} if description else {},
        occurrence={},
        votes=1,
        total_api_calls=1,
        term_type=normalize_term_type(term_type),
        new_translation=None,
        translated_name=translated_name,
        ignored=ignored,
        is_reviewed=is_reviewed,
        created_at=now,
        updated_at=now,
    )


def _import_structured_glossary(
    db: SQLiteBookDB,
    data: dict[str, object],
    *,
    include_translations: bool,
) -> int:
    # Wipe existing data
    db.delete_all_term_memory(auto_commit=False)
    db.conn.execute("DELETE FROM terms")

    term_records = []
    for entry in cast(list[object], data["terms"]):
        if not isinstance(entry, dict):
            continue
        term_records.append(
            _build_import_term_record(
                str(entry["key"]),
                translated_name=entry.get("translated_name") if include_translations else None,
                description=str(entry.get("description", "")),
                term_type=entry.get("term_type") if isinstance(entry.get("term_type"), str) else None,
                ignored=bool(entry.get("ignored", False)),
                is_reviewed=bool(entry.get("is_reviewed", False)),
            )
        )

    db.upsert_terms(term_records)
    return len(term_records)


def _import_simple_glossary(
    db: SQLiteBookDB,
    data: dict[str, object],
    *,
    include_translations: bool,
) -> int:
    term_records: list[TermRecord] = []
    now = time.time()
    for raw_key, raw_value in data.items():
        key = raw_key.strip()
        translated_name = raw_value.strip() if isinstance(raw_value, str) else ""
        if not key:
            raise ValueError("Invalid glossary file: flat mapping keys must be non-empty strings")
        existing = db.get_term(key)
        if existing is not None:
            existing.translated_name = translated_name if include_translations else None
            existing.ignored = False
            existing.is_reviewed = True
            existing.updated_at = now
            term_records.append(existing)
            continue
        term_records.append(
            _build_import_term_record(
                key,
                translated_name=translated_name if include_translations else None,
                ignored=False,
                is_reviewed=True,
            )
        )

    if term_records:
        db.upsert_terms(term_records)
    return len(term_records)


def import_glossary(
    db: SQLiteBookDB,
    input_path: Path,
    include_translations: bool = True,
) -> int:
    """Import glossary terms from a JSON file.

    Structured glossary JSON preserves current replace-all behavior.
    Flat term-to-translation JSON mappings are merged into the existing glossary.

    Returns the number of terms processed.
    """
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and ("terms" in data or "version" in data):
        _validate_glossary_json(data)
        return _import_structured_glossary(db, data, include_translations=include_translations)

    _validate_simple_glossary_json(data)
    return _import_simple_glossary(db, data, include_translations=include_translations)
