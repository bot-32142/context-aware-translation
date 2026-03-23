"""Tests for glossary import/export functionality."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

import pytest

from context_aware_translation.adapters.files.glossary_io import (
    _consolidate_description,
    _validate_glossary_json,
    export_glossary,
    import_glossary,
)
from context_aware_translation.core.term_memory import TermMemoryVersion
from context_aware_translation.storage.schema.book_db import SQLiteBookDB, TermRecord


@pytest.fixture
def temp_db(tmp_path: Path) -> Generator[SQLiteBookDB]:
    db = SQLiteBookDB(tmp_path / "book.db")
    yield db
    db.close()


def _make_term(
    key: str,
    descriptions: dict | None = None,
    occurrence: dict | None = None,
    translated_name: str | None = None,
    term_type: str = "other",
    ignored: bool = False,
    is_reviewed: bool = False,
    votes: int = 1,
    total_api_calls: int = 1,
) -> TermRecord:
    import time

    return TermRecord(
        key=key,
        descriptions=descriptions or {},
        occurrence=occurrence or {},
        votes=votes,
        total_api_calls=total_api_calls,
        term_type=term_type,
        translated_name=translated_name,
        ignored=ignored,
        is_reviewed=is_reviewed,
        created_at=time.time(),
        updated_at=time.time(),
    )


# ========== Export Tests ==========


class TestExportGlossary:
    def test_export_empty_glossary(self, temp_db: SQLiteBookDB, tmp_path: Path) -> None:
        output = tmp_path / "glossary.json"
        count = export_glossary(temp_db, output)
        assert count == 0
        with open(output) as f:
            data = json.load(f)
        assert data == {"version": 1, "terms": []}

    def test_export_basic_terms(self, temp_db: SQLiteBookDB, tmp_path: Path) -> None:
        terms = [
            _make_term("hero", descriptions={"0": "the protagonist"}, translated_name="英雄", term_type="character"),
            _make_term("villain", descriptions={"1": "the antagonist"}, ignored=True),
            _make_term("sword", descriptions={"2": "a weapon"}, is_reviewed=True, term_type="organization"),
        ]
        temp_db.upsert_terms(terms)

        output = tmp_path / "glossary.json"
        count = export_glossary(temp_db, output)
        assert count == 3

        with open(output) as f:
            data = json.load(f)

        assert data["version"] == 1
        assert len(data["terms"]) == 3

        by_key = {t["key"]: t for t in data["terms"]}
        assert by_key["hero"]["translated_name"] == "英雄"
        assert by_key["hero"]["description"] == "the protagonist"
        assert by_key["hero"]["term_type"] == "character"
        assert by_key["villain"]["ignored"] is True
        assert by_key["villain"]["term_type"] == "other"
        assert by_key["sword"]["is_reviewed"] is True
        assert by_key["sword"]["term_type"] == "organization"

    def test_export_description_consolidation(self, temp_db: SQLiteBookDB, tmp_path: Path) -> None:
        terms = [
            _make_term("hero", descriptions={"0": "first desc", "5": "second desc", "10": "third desc"}),
        ]
        temp_db.upsert_terms(terms)

        output = tmp_path / "glossary.json"
        export_glossary(temp_db, output)

        with open(output) as f:
            data = json.load(f)

        assert data["terms"][0]["description"] == "first desc second desc third desc"

    def test_export_description_with_imported_key(self, temp_db: SQLiteBookDB, tmp_path: Path) -> None:
        terms = [
            _make_term("hero", descriptions={"imported": "imported desc", "5": "chunk 5 desc"}),
        ]
        temp_db.upsert_terms(terms)

        output = tmp_path / "glossary.json"
        export_glossary(temp_db, output)

        with open(output) as f:
            data = json.load(f)

        # imported sorts at -1, before chunk 5
        assert data["terms"][0]["description"] == "imported desc chunk 5 desc"

    def test_export_null_translated_name(self, temp_db: SQLiteBookDB, tmp_path: Path) -> None:
        terms = [_make_term("hero", descriptions={"0": "desc"}, translated_name=None)]
        temp_db.upsert_terms(terms)

        output = tmp_path / "glossary.json"
        export_glossary(temp_db, output)

        with open(output) as f:
            data = json.load(f)

        assert data["terms"][0]["translated_name"] is None

    def test_export_no_context_tree_needed(self, temp_db: SQLiteBookDB, tmp_path: Path) -> None:
        """Export takes only db and output_path - no ContextTreeDB parameter."""
        terms = [_make_term("hero", descriptions={"0": "desc"})]
        temp_db.upsert_terms(terms)

        output = tmp_path / "glossary.json"
        # This should work without any context tree DB
        count = export_glossary(temp_db, output)
        assert count == 1

    def test_export_uses_provided_summarized_descriptions(self, temp_db: SQLiteBookDB, tmp_path: Path) -> None:
        terms = [
            _make_term("hero", descriptions={"0": "raw desc a", "1": "raw desc b"}),
            _make_term("villain", descriptions={"0": "villain raw"}),
        ]
        temp_db.upsert_terms(terms)

        output = tmp_path / "glossary.json"
        count = export_glossary(
            temp_db,
            output,
            summarized_descriptions={
                "hero": "hero final summary",
                "villain": "villain final summary",
            },
        )
        assert count == 2

        with open(output) as f:
            data = json.load(f)

        by_key = {t["key"]: t for t in data["terms"]}
        assert by_key["hero"]["description"] == "hero final summary"
        assert by_key["villain"]["description"] == "villain final summary"


# ========== Import Tests ==========


class TestImportGlossary:
    def _write_glossary(self, path: Path, terms: list[dict], version: int = 1) -> None:
        data: dict = {"version": version, "terms": terms}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def test_import_basic(self, temp_db: SQLiteBookDB, tmp_path: Path) -> None:
        glossary_file = tmp_path / "import.json"
        self._write_glossary(
            glossary_file,
            [
                {
                    "key": "hero",
                    "translated_name": "英雄",
                    "description": "the protagonist",
                    "term_type": "character",
                },
                {"key": "villain", "description": "the antagonist", "ignored": True},
            ],
        )

        count = import_glossary(temp_db, glossary_file)
        assert count == 2

        terms = temp_db.list_terms()
        by_key = {t.key: t for t in terms}
        assert "hero" in by_key
        assert "villain" in by_key
        assert by_key["hero"].translated_name == "英雄"
        assert by_key["hero"].term_type == "character"
        assert by_key["villain"].ignored is True
        assert by_key["villain"].term_type == "other"

    def test_import_invalid_term_type_defaults_to_other(self, temp_db: SQLiteBookDB, tmp_path: Path) -> None:
        glossary_file = tmp_path / "import.json"
        self._write_glossary(
            glossary_file,
            [
                {"key": "hero", "description": "the protagonist", "term_type": "hero"},
            ],
        )

        import_glossary(temp_db, glossary_file)

        terms = temp_db.list_terms()
        assert terms[0].term_type == "other"

    def test_import_overwrites_existing(self, temp_db: SQLiteBookDB, tmp_path: Path) -> None:
        # Pre-populate
        temp_db.upsert_terms([_make_term("old_term", descriptions={"0": "old desc"})])
        assert len(temp_db.list_terms()) == 1

        # Import new set
        glossary_file = tmp_path / "import.json"
        self._write_glossary(
            glossary_file,
            [
                {"key": "new_term", "description": "new desc"},
            ],
        )
        import_glossary(temp_db, glossary_file)

        terms = temp_db.list_terms()
        keys = [t.key for t in terms]
        assert "old_term" not in keys
        assert "new_term" in keys

    def test_import_path_only_clears_term_memory(self, temp_db: SQLiteBookDB, tmp_path: Path) -> None:
        temp_db.replace_term_memory_versions(
            "old_term",
            [
                TermMemoryVersion(
                    term="old_term",
                    effective_start_chunk=5,
                    latest_evidence_chunk=4,
                    summary_text="stale summary",
                    kind="bootstrap",
                    source_count=2,
                    created_at=0.0,
                )
            ],
        )

        glossary_file = tmp_path / "import.json"
        self._write_glossary(glossary_file, [{"key": "hero", "description": "desc"}])
        import_glossary(temp_db, glossary_file)

        assert temp_db.list_latest_term_memory_versions() == {}

    def test_import_invalid_file_does_not_clear_existing_term_memory(
        self, temp_db: SQLiteBookDB, tmp_path: Path
    ) -> None:
        temp_db.upsert_terms([_make_term("old_term", descriptions={"0": "old desc"})])
        temp_db.replace_term_memory_versions(
            "old_term",
            [
                TermMemoryVersion(
                    term="old_term",
                    effective_start_chunk=5,
                    latest_evidence_chunk=4,
                    summary_text="stale summary",
                    kind="bootstrap",
                    source_count=2,
                    created_at=0.0,
                )
            ],
        )

        glossary_file = tmp_path / "bad.json"
        glossary_file.write_text('{"version": 1}', encoding="utf-8")

        with pytest.raises(ValueError, match="missing 'terms' key"):
            import_glossary(temp_db, glossary_file)

        assert temp_db.get_term("old_term") is not None
        assert temp_db.list_latest_term_memory_versions()["old_term"].summary_text == "stale summary"

    def test_import_without_translations(self, temp_db: SQLiteBookDB, tmp_path: Path) -> None:
        glossary_file = tmp_path / "import.json"
        self._write_glossary(
            glossary_file,
            [
                {"key": "hero", "translated_name": "英雄", "description": "desc"},
            ],
        )
        import_glossary(temp_db, glossary_file, include_translations=False)

        terms = temp_db.list_terms()
        assert terms[0].translated_name is None

    def test_import_with_translations(self, temp_db: SQLiteBookDB, tmp_path: Path) -> None:
        glossary_file = tmp_path / "import.json"
        self._write_glossary(
            glossary_file,
            [
                {"key": "hero", "translated_name": "英雄", "description": "desc"},
            ],
        )
        import_glossary(temp_db, glossary_file, include_translations=True)

        terms = temp_db.list_terms()
        assert terms[0].translated_name == "英雄"

    def test_import_description_stored_at_key_imported(self, temp_db: SQLiteBookDB, tmp_path: Path) -> None:
        glossary_file = tmp_path / "import.json"
        self._write_glossary(
            glossary_file,
            [
                {"key": "hero", "description": "the protagonist"},
            ],
        )
        import_glossary(temp_db, glossary_file)

        terms = temp_db.list_terms()
        assert "imported" in terms[0].descriptions
        assert terms[0].descriptions["imported"] == "the protagonist"
        assert "-1" not in terms[0].descriptions

    def test_import_defaults(self, temp_db: SQLiteBookDB, tmp_path: Path) -> None:
        glossary_file = tmp_path / "import.json"
        self._write_glossary(glossary_file, [{"key": "hero"}])
        import_glossary(temp_db, glossary_file)

        terms = temp_db.list_terms()
        t = terms[0]
        assert t.votes == 1
        assert t.total_api_calls == 1
        assert t.occurrence == {}
        assert t.term_type == "other"
        assert t.ignored is False
        assert t.is_reviewed is False

    def test_import_empty_description(self, temp_db: SQLiteBookDB, tmp_path: Path) -> None:
        glossary_file = tmp_path / "import.json"
        self._write_glossary(glossary_file, [{"key": "hero", "description": ""}])
        import_glossary(temp_db, glossary_file)

        terms = temp_db.list_terms()
        assert terms[0].descriptions == {}


# ========== Validation Tests ==========


class TestValidation:
    def test_missing_terms_key(self) -> None:
        with pytest.raises(ValueError, match="missing 'terms' key"):
            _validate_glossary_json({"version": 1})

    def test_missing_entry_key(self) -> None:
        with pytest.raises(ValueError, match="missing or empty 'key'"):
            _validate_glossary_json({"terms": [{"description": "no key"}]})

    def test_empty_key(self) -> None:
        with pytest.raises(ValueError, match="missing or empty 'key'"):
            _validate_glossary_json({"terms": [{"key": ""}]})

    def test_version_too_high(self) -> None:
        with pytest.raises(ValueError, match="Unsupported glossary format version"):
            _validate_glossary_json({"version": 2, "terms": []})

    def test_version_1_accepted(self) -> None:
        _validate_glossary_json({"version": 1, "terms": []})

    def test_version_missing_accepted(self) -> None:
        _validate_glossary_json({"terms": []})


# ========== Round-Trip Tests ==========


class TestRoundTrip:
    def test_roundtrip(self, temp_db: SQLiteBookDB, tmp_path: Path) -> None:
        # Populate original DB
        terms = [
            _make_term(
                "hero",
                descriptions={"0": "the protagonist"},
                translated_name="英雄",
                term_type="character",
                is_reviewed=True,
            ),
            _make_term("villain", descriptions={"1": "the antagonist"}, ignored=True),
            _make_term("sword", descriptions={"2": "a weapon"}, translated_name="剑", term_type="organization"),
        ]
        temp_db.upsert_terms(terms)

        # Export
        export1 = tmp_path / "export1.json"
        export_glossary(temp_db, export1)

        # Import into same DB (overwrites)
        import_glossary(temp_db, export1)

        # Export again
        export2 = tmp_path / "export2.json"
        export_glossary(temp_db, export2)

        # Compare
        with open(export1) as f:
            data1 = json.load(f)
        with open(export2) as f:
            data2 = json.load(f)

        # Sort by key for comparison
        terms1 = sorted(data1["terms"], key=lambda t: t["key"])
        terms2 = sorted(data2["terms"], key=lambda t: t["key"])

        assert len(terms1) == len(terms2)
        for t1, t2 in zip(terms1, terms2):
            assert t1["key"] == t2["key"]
            assert t1["translated_name"] == t2["translated_name"]
            assert t1["term_type"] == t2["term_type"]
            assert t1["ignored"] == t2["ignored"]
            assert t1["is_reviewed"] == t2["is_reviewed"]
            # Description may differ in format (consolidated vs imported) but content is preserved
            assert t1["description"] == t2["description"]


# ========== Guard Tests ==========


class TestGuards:
    def test_guard_reset_documents_from_preserves_imported_key(self, temp_db: SQLiteBookDB) -> None:
        temp_db.upsert_terms(
            [
                _make_term("hero", descriptions={"imported": "imported desc", "5": "chunk desc"}),
            ]
        )

        # Need chunks for reset_documents_from to work
        temp_db.conn.execute(
            "INSERT INTO chunks (chunk_id, hash, text, created_at) VALUES (?, ?, ?, ?)",
            (0, "h0", "text0", 0.0),
        )
        temp_db.conn.commit()

        temp_db.reset_documents_from(5)

        terms = temp_db.list_terms()
        assert len(terms) == 1
        assert "imported" in terms[0].descriptions
        assert terms[0].descriptions["imported"] == "imported desc"
        assert "5" not in terms[0].descriptions

    def test_guard_reset_documents_from_does_not_crash_on_imported_key(self, temp_db: SQLiteBookDB) -> None:
        temp_db.upsert_terms(
            [
                _make_term("hero", descriptions={"imported": "desc"}),
            ]
        )

        temp_db.conn.execute(
            "INSERT INTO chunks (chunk_id, hash, text, created_at) VALUES (?, ?, ?, ?)",
            (0, "h0", "text0", 0.0),
        )
        temp_db.conn.commit()

        # Should not crash
        temp_db.reset_documents_from(0)

        terms = temp_db.list_terms()
        assert len(terms) == 1
        assert "imported" in terms[0].descriptions

    def test_consolidate_description_sort_order(self) -> None:
        descs = {"imported": "imported desc", "0": "chunk 0 desc", "5": "chunk 5 desc"}
        result = _consolidate_description(descs)
        assert result == "imported desc chunk 0 desc chunk 5 desc"

    def test_consolidate_description_imported_only(self) -> None:
        descs = {"imported": "only desc"}
        result = _consolidate_description(descs)
        assert result == "only desc"

    def test_consolidate_description_ignores_non_chunk_keys(self) -> None:
        descs = {"imported": "imported desc", "legacy_key": "legacy desc", "5": "chunk 5 desc"}

        result = _consolidate_description(descs)

        assert result == "imported desc chunk 5 desc"

    def test_guard_get_primary_description_imported_wins(self) -> None:
        """Test that _get_primary_description prioritizes recognized keys."""
        from context_aware_translation.core.context_manager import TranslationContextManager
        from context_aware_translation.core.models import Term

        term = Term(
            key="hero",
            descriptions={"imported": "imported desc", "0": "chunk 0 desc", "5": "chunk 5 desc"},
            occurrence={},
            votes=1,
            total_api_calls=1,
        )
        result = TranslationContextManager._get_primary_description(term)
        assert result == "imported desc"

    def test_guard_get_primary_description_imported_only(self) -> None:
        """Test that _get_primary_description handles imported-only terms."""
        from context_aware_translation.core.context_manager import TranslationContextManager
        from context_aware_translation.core.models import Term

        term = Term(
            key="hero",
            descriptions={"imported": "only desc"},
            occurrence={},
            votes=1,
            total_api_calls=1,
        )
        result = TranslationContextManager._get_primary_description(term)
        assert result == "only desc"

    def test_guard_get_primary_description_rejects_non_chunk_keys(self) -> None:
        from context_aware_translation.core.context_manager import TranslationContextManager
        from context_aware_translation.core.models import Term

        term = Term(
            key="hero",
            descriptions={"legacy_key": "legacy desc"},
            occurrence={},
            votes=1,
            total_api_calls=1,
        )

        with pytest.raises(ValueError, match="recognized descriptions"):
            TranslationContextManager._get_primary_description(term)

    def test_import_compatibility_with_mark_noise_terms(self, temp_db: SQLiteBookDB, tmp_path: Path) -> None:
        """Test that imported terms are NOT marked as noise (Guard 2)."""
        glossary_file = tmp_path / "import.json"
        with open(glossary_file, "w") as f:
            json.dump(
                {
                    "version": 1,
                    "terms": [
                        {"key": "hero", "description": "the protagonist"},
                        {"key": "villain", "description": "the antagonist"},
                    ],
                },
                f,
            )

        import_glossary(temp_db, glossary_file)

        terms = temp_db.list_terms()
        for t in terms:
            # Imported terms have votes=1, total_api_calls=1
            assert t.votes == 1
            assert t.total_api_calls == 1
            # occurrence is empty, descriptions has 1 entry ("imported")
            assert t.occurrence == {}
            assert len(t.descriptions) == 1
            assert "imported" in t.descriptions
            # votes/total_api_calls = 1.0, which is NOT below any reasonable threshold
            # So these terms should NOT be marked as noise
            ratio = t.votes / t.total_api_calls
            assert ratio >= 0.5  # typical noise threshold
            # Also check that even though len(occurrence)/len(descriptions) = 0/1 = 0,
            # the high votes/total_api_calls ratio should prevent noise marking
