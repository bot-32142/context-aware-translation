"""Tests for term_db.py

Tests are organized to match the code structure:
- TermRecord (dataclass)
- ChunkRecord (dataclass)
- TranslationChunkRecord (dataclass)
- SQLiteBookDB (class)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from context_aware_translation.storage.schema.book_db import (
    ChunkRecord,
    SQLiteBookDB,
    TermRecord,
    TranslationChunkRecord,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_db(tmp_path: Path) -> SQLiteBookDB:
    """Create a temporary database for testing."""
    db_path = tmp_path / "test.db"
    db = SQLiteBookDB(db_path)
    yield db
    db.close()


# ============================================================================
# TermRecord (dataclass) Tests
# ============================================================================


def test_term_record_creation():
    """Test creating a TermRecord."""
    term = TermRecord(
        key="term1",
        descriptions={"chunk1": "description1"},
        occurrence={"chunk1": 1},
        votes=1,
        total_api_calls=1,
    )
    assert term.key == "term1"
    assert term.descriptions == {"chunk1": "description1"}
    assert term.occurrence == {"chunk1": 1}
    assert term.votes == 1
    assert term.total_api_calls == 1
    assert term.new_translation is None
    assert term.translated_name is None
    assert term.ignored is False


def test_term_record_optional_fields():
    """Test TermRecord with optional fields."""
    term = TermRecord(
        key="term1",
        descriptions={},
        occurrence={},
        votes=1,
        total_api_calls=1,
        new_translation="新翻译",
        translated_name="翻译名",
        ignored=True,
    )
    assert term.new_translation == "新翻译"
    assert term.translated_name == "翻译名"
    assert term.ignored is True


# ============================================================================
# ChunkRecord (dataclass) Tests
# ============================================================================


def test_chunk_record_creation():
    """Test creating a ChunkRecord."""
    chunk = ChunkRecord(
        chunk_id=1,
        hash="hash1",
        text="text1",
        is_extracted=False,
        is_summarized=False,
    )
    assert chunk.chunk_id == 1
    assert chunk.hash == "hash1"
    assert chunk.text == "text1"
    assert chunk.is_extracted is False
    assert chunk.is_summarized is False
    assert chunk.created_at is None


# ============================================================================
# TranslationChunkRecord (dataclass) Tests
# ============================================================================


def test_translation_chunk_record_creation():
    """Test creating a TranslationChunkRecord."""
    chunk = TranslationChunkRecord(
        chunk_id=1,
        hash="hash1",
        text="text1",
        is_extracted=True,
        is_summarized=True,
        is_occurrence_mapped=True,
        is_translated=True,
        translation="translation1",
    )
    assert chunk.chunk_id == 1
    assert chunk.is_occurrence_mapped is True
    assert chunk.is_translated is True
    assert chunk.translation == "translation1"


# ============================================================================
# SQLiteBookDB (class) Tests
# ============================================================================

# --- Initialization ---


def test_term_db_init(temp_db: SQLiteBookDB):
    """Test database initialization."""
    assert temp_db.db_path.exists()
    assert temp_db.schema_version == 2


# --- Term Operations ---


def test_upsert_terms(temp_db: SQLiteBookDB):
    """Test upserting terms."""
    term1 = TermRecord(
        key="term1",
        descriptions={"chunk1": "description1"},
        occurrence={"chunk1": 1},
        votes=1,
        total_api_calls=1,
    )
    term2 = TermRecord(
        key="term2",
        descriptions={"chunk2": "description2"},
        occurrence={"chunk2": 2},
        votes=2,
        total_api_calls=2,
    )

    temp_db.upsert_terms([term1, term2])

    # Retrieve and verify
    retrieved1 = temp_db.get_term("term1")
    assert retrieved1 is not None
    assert retrieved1.key == "term1"
    assert retrieved1.descriptions == {"chunk1": "description1"}
    assert retrieved1.occurrence == {"chunk1": 1}
    assert retrieved1.votes == 1
    assert retrieved1.total_api_calls == 1

    retrieved2 = temp_db.get_term("term2")
    assert retrieved2 is not None
    assert retrieved2.key == "term2"


def test_upsert_terms_update_existing(temp_db: SQLiteBookDB):
    """Test updating existing terms."""
    term1 = TermRecord(
        key="term1",
        descriptions={"chunk1": "description1"},
        occurrence={},
        votes=1,
        total_api_calls=1,
    )
    temp_db.upsert_terms([term1])

    # Update the term
    term1_updated = TermRecord(
        key="term1",
        descriptions={"chunk1": "description1", "chunk2": "description2"},
        occurrence={"chunk1": 2},
        votes=2,
        total_api_calls=2,
    )
    temp_db.upsert_terms([term1_updated])

    retrieved = temp_db.get_term("term1")
    assert retrieved is not None
    assert retrieved.votes == 2
    assert retrieved.total_api_calls == 2
    assert len(retrieved.descriptions) == 2


def test_get_term_nonexistent(temp_db: SQLiteBookDB):
    """Test getting a non-existent term."""
    result = temp_db.get_term("nonexistent")
    assert result is None


def test_list_terms(temp_db: SQLiteBookDB):
    """Test listing all terms."""
    terms = [
        TermRecord(
            key=f"term{i}",
            descriptions={},
            occurrence={},
            votes=i,
            total_api_calls=i,
        )
        for i in range(5)
    ]
    temp_db.upsert_terms(terms)

    all_terms = temp_db.list_terms()
    assert len(all_terms) == 5
    assert {t.key for t in all_terms} == {f"term{i}" for i in range(5)}


def test_search_terms_matches_key_and_translated_name(temp_db: SQLiteBookDB):
    """Search should match both source key and translated_name."""
    temp_db.upsert_terms(
        [
            TermRecord(
                key="alpha",
                descriptions={},
                occurrence={},
                votes=1,
                total_api_calls=1,
                translated_name="阿尔法",
            ),
            TermRecord(
                key="beta",
                descriptions={},
                occurrence={},
                votes=1,
                total_api_calls=1,
                translated_name="贝塔",
            ),
            TermRecord(
                key="gamma",
                descriptions={},
                occurrence={},
                votes=1,
                total_api_calls=1,
                translated_name=None,
            ),
        ]
    )

    by_key = temp_db.search_terms("alp")
    assert [t.key for t in by_key] == ["alpha"]

    by_translation = temp_db.search_terms("贝")
    assert [t.key for t in by_translation] == ["beta"]


def test_list_terms_sort_by_ignored_is_supported(temp_db: SQLiteBookDB):
    """Test sorting terms by ignored flag."""
    temp_db.upsert_terms(
        [
            TermRecord(key="zeta", descriptions={}, occurrence={}, votes=1, total_api_calls=1, ignored=False),
            TermRecord(key="beta", descriptions={}, occurrence={}, votes=1, total_api_calls=1, ignored=True),
            TermRecord(key="alpha", descriptions={}, occurrence={}, votes=1, total_api_calls=1, ignored=False),
            TermRecord(key="eta", descriptions={}, occurrence={}, votes=1, total_api_calls=1, ignored=True),
        ]
    )

    asc = temp_db.list_terms(sort_by="ignored", sort_desc=False)
    desc = temp_db.list_terms(sort_by="ignored", sort_desc=True)

    assert [t.key for t in asc] == ["alpha", "zeta", "beta", "eta"]
    assert [t.key for t in desc] == ["beta", "eta", "alpha", "zeta"]


def test_list_terms_sorting_is_deterministic_for_ties(temp_db: SQLiteBookDB):
    """Test sorting uses key tie-break to keep order deterministic."""
    temp_db.upsert_terms(
        [
            TermRecord(key="charlie", descriptions={}, occurrence={}, votes=2, total_api_calls=1),
            TermRecord(key="alpha", descriptions={}, occurrence={}, votes=2, total_api_calls=1),
            TermRecord(key="bravo", descriptions={}, occurrence={}, votes=2, total_api_calls=1),
        ]
    )

    terms = temp_db.list_terms(sort_by="votes", sort_desc=False)
    assert [t.key for t in terms] == ["alpha", "bravo", "charlie"]


def test_list_terms_sort_by_occurrence_count(temp_db: SQLiteBookDB):
    """Test sorting terms by occurrence count."""
    temp_db.upsert_terms(
        [
            TermRecord(
                key="alpha",
                descriptions={},
                occurrence={"1": 1},
                votes=1,
                total_api_calls=1,
            ),
            TermRecord(
                key="bravo",
                descriptions={},
                occurrence={"1": 1, "2": 1, "3": 1},
                votes=1,
                total_api_calls=1,
            ),
            TermRecord(
                key="charlie",
                descriptions={},
                occurrence={},
                votes=1,
                total_api_calls=1,
            ),
        ]
    )

    asc = temp_db.list_terms(sort_by="occurrence_count", sort_desc=False)
    desc = temp_db.list_terms(sort_by="occurrence_count", sort_desc=True)

    assert [t.key for t in asc] == ["charlie", "alpha", "bravo"]
    assert [t.key for t in desc] == ["bravo", "alpha", "charlie"]


def test_get_term_stats_includes_unignored_metrics(temp_db: SQLiteBookDB):
    """Test term stats expose unignored and unignored+reviewed counts."""
    temp_db.upsert_terms(
        [
            TermRecord(
                key="a", descriptions={}, occurrence={}, votes=1, total_api_calls=1, ignored=False, is_reviewed=True
            ),
            TermRecord(
                key="b", descriptions={}, occurrence={}, votes=1, total_api_calls=1, ignored=False, is_reviewed=False
            ),
            TermRecord(
                key="c", descriptions={}, occurrence={}, votes=1, total_api_calls=1, ignored=True, is_reviewed=True
            ),
        ]
    )

    stats = temp_db.get_term_stats()
    assert stats["unignored"] == 2
    assert stats["unignored_reviewed"] == 1


def test_get_terms_to_translate(temp_db: SQLiteBookDB):
    """Test getting terms that need translation."""
    term1 = TermRecord(
        key="term1",
        descriptions={},
        occurrence={},
        votes=1,
        total_api_calls=1,
        translated_name=None,  # Needs translation
    )
    term2 = TermRecord(
        key="term2",
        descriptions={},
        occurrence={},
        votes=1,
        total_api_calls=1,
        translated_name="翻译2",  # Already translated
    )
    temp_db.upsert_terms([term1, term2])

    to_translate = temp_db.get_terms_to_translate()
    assert len(to_translate) == 1
    assert to_translate[0].key == "term1"


def test_get_translation(temp_db: SQLiteBookDB):
    """Test getting translation for a term."""
    term = TermRecord(
        key="term1",
        descriptions={},
        occurrence={},
        votes=1,
        total_api_calls=1,
        translated_name="翻译1",
    )
    temp_db.upsert_terms([term])

    translation = temp_db.get_translation("term1")
    assert translation == "翻译1"

    # Non-existent term
    assert temp_db.get_translation("nonexistent") is None


def test_term_with_optional_fields(temp_db: SQLiteBookDB):
    """Test term with optional fields."""
    term = TermRecord(
        key="term1",
        descriptions={},
        occurrence={},
        votes=1,
        total_api_calls=1,
        new_translation="新翻译",
        translated_name="翻译名",
        ignored=True,
    )
    temp_db.upsert_terms([term])

    retrieved = temp_db.get_term("term1")
    assert retrieved is not None
    assert retrieved.new_translation == "新翻译"
    assert retrieved.translated_name == "翻译名"
    assert retrieved.ignored is True


# --- Term Edge Cases ---


def test_upsert_terms_empty_iterable(temp_db: SQLiteBookDB):
    """Test upserting empty iterable."""
    temp_db.upsert_terms([])
    assert len(temp_db.list_terms()) == 0


def test_upsert_terms_none_descriptions(temp_db: SQLiteBookDB):
    """Test upserting term with None descriptions."""
    term = TermRecord(
        key="term1",
        descriptions=None,  # Should be handled as {}
        occurrence={},
        votes=1,
        total_api_calls=1,
    )
    temp_db.upsert_terms([term])

    retrieved = temp_db.get_term("term1")
    assert retrieved is not None
    assert retrieved.descriptions == {}


def test_upsert_terms_none_occurrence(temp_db: SQLiteBookDB):
    """Test upserting term with None occurrence."""
    term = TermRecord(
        key="term1",
        descriptions={},
        occurrence=None,  # Should be handled as {}
        votes=1,
        total_api_calls=1,
    )
    temp_db.upsert_terms([term])

    retrieved = temp_db.get_term("term1")
    assert retrieved is not None
    assert retrieved.occurrence == {}


def test_upsert_terms_complex_json(temp_db: SQLiteBookDB):
    """Test upserting term with complex nested JSON structures."""
    term = TermRecord(
        key="term1",
        descriptions={
            "chunk1": "desc1",
            "chunk2": {"nested": "value", "list": [1, 2, 3]},
        },
        occurrence={"chunk1": 5, "chunk2": {"count": 10}},
        votes=1,
        total_api_calls=1,
    )
    temp_db.upsert_terms([term])

    retrieved = temp_db.get_term("term1")
    assert retrieved is not None
    assert retrieved.descriptions["chunk2"]["nested"] == "value"
    assert retrieved.descriptions["chunk2"]["list"] == [1, 2, 3]


def test_upsert_terms_empty_string_key(temp_db: SQLiteBookDB):
    """Test upserting term with empty string key."""
    term = TermRecord(
        key="",  # Empty key
        descriptions={},
        occurrence={},
        votes=1,
        total_api_calls=1,
    )
    temp_db.upsert_terms([term])

    retrieved = temp_db.get_term("")
    assert retrieved is not None
    assert retrieved.key == ""


def test_upsert_terms_very_long_key(temp_db: SQLiteBookDB):
    """Test upserting term with very long key."""
    long_key = "a" * 10000
    term = TermRecord(
        key=long_key,
        descriptions={},
        occurrence={},
        votes=1,
        total_api_calls=1,
    )
    temp_db.upsert_terms([term])

    retrieved = temp_db.get_term(long_key)
    assert retrieved is not None
    assert retrieved.key == long_key


def test_upsert_terms_negative_votes(temp_db: SQLiteBookDB):
    """Test upserting term with negative votes (edge case)."""
    term = TermRecord(
        key="term1",
        descriptions={},
        occurrence={},
        votes=-1,  # Negative votes
        total_api_calls=1,
    )
    temp_db.upsert_terms([term])

    retrieved = temp_db.get_term("term1")
    assert retrieved is not None
    assert retrieved.votes == -1


def test_upsert_terms_zero_votes(temp_db: SQLiteBookDB):
    """Test upserting term with zero votes."""
    term = TermRecord(
        key="term1",
        descriptions={},
        occurrence={},
        votes=0,
        total_api_calls=0,
    )
    temp_db.upsert_terms([term])

    retrieved = temp_db.get_term("term1")
    assert retrieved is not None
    assert retrieved.votes == 0
    assert retrieved.total_api_calls == 0


def test_get_term_sql_injection_attempt(temp_db: SQLiteBookDB):
    """Test that SQL injection attempts are handled safely."""
    # Try to inject SQL
    malicious_key = "term1'; DROP TABLE terms; --"
    term = TermRecord(
        key=malicious_key,
        descriptions={},
        occurrence={},
        votes=1,
        total_api_calls=1,
    )
    temp_db.upsert_terms([term])

    # Should retrieve the term with the literal key, not execute SQL
    retrieved = temp_db.get_term(malicious_key)
    assert retrieved is not None
    assert retrieved.key == malicious_key

    # Table should still exist
    all_terms = temp_db.list_terms()
    assert len(all_terms) >= 1


def test_term_key_special_characters(temp_db: SQLiteBookDB):
    """Test term keys with special characters."""
    special_keys = [
        "term with spaces",
        "term\twith\ttabs",
        "term\nwith\nnewlines",
        "term'with'quotes",
        'term"with"double_quotes',
        "term/with/slashes",
        "term\\with\\backslashes",
    ]

    for key in special_keys:
        term = TermRecord(
            key=key,
            descriptions={},
            occurrence={},
            votes=1,
            total_api_calls=1,
        )
        temp_db.upsert_terms([term])
        retrieved = temp_db.get_term(key)
        assert retrieved is not None
        assert retrieved.key == key


def test_term_with_all_none_optional_fields(temp_db: SQLiteBookDB):
    """Test term with all optional fields as None."""
    term = TermRecord(
        key="term1",
        descriptions={},
        occurrence={},
        votes=1,
        total_api_calls=1,
        new_translation=None,
        translated_name=None,
        ignored=False,
        created_at=None,
        updated_at=None,
    )
    temp_db.upsert_terms([term])

    retrieved = temp_db.get_term("term1")
    assert retrieved is not None
    assert retrieved.new_translation is None
    assert retrieved.translated_name is None
    assert retrieved.created_at is not None  # Should be set by upsert_terms
    assert retrieved.updated_at is not None  # Should be set by upsert_terms


def test_json_serialization_special_characters(temp_db: SQLiteBookDB):
    """Test JSON serialization with special characters."""
    term = TermRecord(
        key="term1",
        descriptions={
            "chunk1": "Description with \"quotes\" and 'apostrophes' and\nnewlines",
            "chunk2": {"nested": "value with \t tabs"},
        },
        occurrence={"chunk1": 1},
        votes=1,
        total_api_calls=1,
    )
    temp_db.upsert_terms([term])

    retrieved = temp_db.get_term("term1")
    assert retrieved is not None
    assert '"quotes"' in retrieved.descriptions["chunk1"]
    assert "\nnewlines" in retrieved.descriptions["chunk1"]
    assert "\t tabs" in retrieved.descriptions["chunk2"]["nested"]


def test_get_terms_to_translate_excludes_empty_string(temp_db: SQLiteBookDB):
    """Test that empty string translated_name is treated differently from None."""
    term1 = TermRecord(
        key="term1",
        descriptions={},
        occurrence={},
        votes=1,
        total_api_calls=1,
        translated_name=None,  # Should be in to_translate
    )
    term2 = TermRecord(
        key="term2",
        descriptions={},
        occurrence={},
        votes=1,
        total_api_calls=1,
        translated_name="",  # Empty string, should NOT be in to_translate
    )
    temp_db.upsert_terms([term1, term2])

    to_translate = temp_db.get_terms_to_translate()
    # Only term1 should be in the list (translated_name IS NULL)
    assert len(to_translate) == 1
    assert to_translate[0].key == "term1"


def test_get_translation_returns_empty_string(temp_db: SQLiteBookDB):
    """Test that get_translation returns empty string if stored."""
    term = TermRecord(
        key="term1",
        descriptions={},
        occurrence={},
        votes=1,
        total_api_calls=1,
        translated_name="",  # Empty string
    )
    temp_db.upsert_terms([term])

    translation = temp_db.get_translation("term1")
    assert translation == ""


def test_upsert_terms_large_batch(temp_db: SQLiteBookDB):
    """Test upserting a large batch of terms."""
    terms = [
        TermRecord(
            key=f"term{i}",
            descriptions={},
            occurrence={},
            votes=i,
            total_api_calls=i,
        )
        for i in range(1000)
    ]
    temp_db.upsert_terms(terms)

    all_terms = temp_db.list_terms()
    assert len(all_terms) == 1000


def test_json_deserialization_error_handling(temp_db: SQLiteBookDB):
    """Test that corrupted JSON in database is handled gracefully."""
    # Insert a term with valid JSON
    term = TermRecord(
        key="term1",
        descriptions={"chunk1": "desc1"},
        occurrence={},
        votes=1,
        total_api_calls=1,
    )
    temp_db.upsert_terms([term])

    # Manually corrupt the JSON in the database
    temp_db.conn.execute("UPDATE terms SET descriptions_json = 'invalid json{' WHERE key = 'term1'")
    temp_db.conn.commit()

    # Getting the term should raise JSONDecodeError
    with pytest.raises(json.JSONDecodeError):
        temp_db.get_term("term1")


def test_concurrent_upsert_same_term(temp_db: SQLiteBookDB):
    """Test concurrent-like upsert of same term (simulated)."""
    term1 = TermRecord(
        key="term1",
        descriptions={"chunk1": "desc1"},
        occurrence={},
        votes=1,
        total_api_calls=1,
    )
    term2 = TermRecord(
        key="term1",  # Same key
        descriptions={"chunk2": "desc2"},
        occurrence={},
        votes=2,
        total_api_calls=2,
    )

    # Simulate concurrent updates
    temp_db.upsert_terms([term1])
    temp_db.upsert_terms([term2])

    retrieved = temp_db.get_term("term1")
    assert retrieved is not None
    # Last write wins
    assert retrieved.votes == 2
    assert "chunk2" in retrieved.descriptions


# --- Chunk Operations ---


def test_upsert_chunks(temp_db: SQLiteBookDB):
    """Test upserting chunks."""
    chunks = [
        ChunkRecord(
            chunk_id=i,
            hash=f"hash{i}",
            text=f"text{i}",
            is_extracted=False,
            is_summarized=False,
        )
        for i in range(3)
    ]

    inserted = temp_db.upsert_chunks(chunks)
    assert len(inserted) == 3
    assert set(inserted) == {0, 1, 2}

    # Verify chunks exist
    for i in range(3):
        chunk_id = temp_db.chunk_exists_by_hash(f"hash{i}")
        assert chunk_id == i


def test_upsert_chunks_duplicate_hash(temp_db: SQLiteBookDB):
    """Test upserting chunks with duplicate hash."""
    chunk1 = ChunkRecord(
        chunk_id=1,
        hash="same_hash",
        text="text1",
        is_extracted=False,
        is_summarized=False,
    )
    chunk2 = ChunkRecord(
        chunk_id=2,
        hash="same_hash",  # Duplicate hash
        text="text2",
        is_extracted=False,
        is_summarized=False,
    )

    inserted = temp_db.upsert_chunks([chunk1, chunk2])
    # Only first chunk should be inserted
    assert len(inserted) == 1
    assert inserted[0] == 1


def test_upsert_chunks_update_existing(temp_db: SQLiteBookDB):
    """Test updating existing chunks.

    Note: When updating existing chunks, only flags are updated, not the text.
    The text field is not updated to preserve the original chunk content.
    """
    chunk = ChunkRecord(
        chunk_id=1,
        hash="hash1",
        text="text1",
        is_extracted=False,
        is_summarized=False,
    )
    temp_db.upsert_chunks([chunk])

    # Update chunk flags
    chunk_updated = TranslationChunkRecord(
        chunk_id=1,
        hash="hash1",
        text="text1_updated",  # Text won't be updated for existing chunks
        is_extracted=True,
        is_summarized=True,
        is_occurrence_mapped=True,
        is_translated=True,
        translation="translation1",
    )
    temp_db.upsert_chunks([chunk_updated])

    chunks = temp_db.list_chunks()
    assert len(chunks) == 1
    # Text is preserved, not updated
    assert chunks[0].text == "text1"
    # Flags are updated
    assert chunks[0].is_extracted is True
    assert chunks[0].is_translated is True
    assert chunks[0].translation == "translation1"


def test_chunk_exists_by_hash(temp_db: SQLiteBookDB):
    """Test checking if chunk exists by hash."""
    chunk = ChunkRecord(
        chunk_id=1,
        hash="hash1",
        text="text1",
        is_extracted=False,
        is_summarized=False,
    )
    temp_db.upsert_chunks([chunk])

    assert temp_db.chunk_exists_by_hash("hash1") == 1
    assert temp_db.chunk_exists_by_hash("nonexistent") is None


def test_get_max_chunk_id(temp_db: SQLiteBookDB):
    """Test getting max chunk ID."""
    # No chunks yet
    assert temp_db.get_max_chunk_id() == -1

    chunks = [
        ChunkRecord(
            chunk_id=i,
            hash=f"hash{i}",
            text=f"text{i}",
            is_extracted=False,
            is_summarized=False,
        )
        for i in range(5)
    ]
    temp_db.upsert_chunks(chunks)

    assert temp_db.get_max_chunk_id() == 4


def test_get_chunks_to_extract(temp_db: SQLiteBookDB):
    """Test getting chunks that need extraction."""
    chunks = [
        ChunkRecord(
            chunk_id=1,
            hash="hash1",
            text="text1",
            is_extracted=False,
            is_summarized=False,
        ),
        ChunkRecord(
            chunk_id=2,
            hash="hash2",
            text="text2",
            is_extracted=True,  # Already extracted
            is_summarized=False,
        ),
    ]
    temp_db.upsert_chunks(chunks)

    to_extract = temp_db.get_chunks_to_extract()
    assert len(to_extract) == 1
    assert to_extract[0].chunk_id == 1


def test_get_chunks_to_map_occurrence(temp_db: SQLiteBookDB):
    """Test getting chunks that need occurrence mapping."""
    chunks = [
        TranslationChunkRecord(
            chunk_id=1,
            hash="hash1",
            text="text1",
            is_extracted=True,
            is_summarized=False,
            is_occurrence_mapped=False,
            is_translated=False,
        ),
        TranslationChunkRecord(
            chunk_id=2,
            hash="hash2",
            text="text2",
            is_extracted=True,
            is_summarized=False,
            is_occurrence_mapped=True,  # Already mapped
            is_translated=False,
        ),
    ]
    temp_db.upsert_chunks(chunks)

    to_map = temp_db.get_chunks_to_map_occurrence()
    assert len(to_map) == 1
    assert to_map[0].chunk_id == 1


def test_get_chunks_to_translate(temp_db: SQLiteBookDB):
    """Test getting chunks that need translation."""
    chunks = [
        TranslationChunkRecord(
            chunk_id=1,
            hash="hash1",
            text="text1",
            is_extracted=True,
            is_summarized=True,
            is_occurrence_mapped=True,
            is_translated=False,
        ),
        TranslationChunkRecord(
            chunk_id=2,
            hash="hash2",
            text="text2",
            is_extracted=True,
            is_summarized=True,
            is_occurrence_mapped=True,
            is_translated=True,  # Already translated
            translation="translation2",
        ),
    ]
    temp_db.upsert_chunks(chunks)

    to_translate = temp_db.get_chunks_to_translate()
    assert len(to_translate) == 1
    assert to_translate[0].chunk_id == 1


def test_get_chunks_to_translate_with_empty_document_ids_returns_empty(temp_db: SQLiteBookDB):
    chunks = [
        TranslationChunkRecord(
            chunk_id=1,
            hash="hash1",
            text="text1",
            is_extracted=True,
            is_summarized=True,
            is_occurrence_mapped=True,
            is_translated=False,
        )
    ]
    temp_db.upsert_chunks(chunks)

    assert temp_db.get_chunks_to_translate(document_ids=[]) == []


def test_list_chunks(temp_db: SQLiteBookDB):
    """Test listing all chunks."""
    chunks = [
        ChunkRecord(
            chunk_id=i,
            hash=f"hash{i}",
            text=f"text{i}",
            is_extracted=False,
            is_summarized=False,
        )
        for i in range(5)
    ]
    temp_db.upsert_chunks(chunks)

    all_chunks = temp_db.list_chunks()
    assert len(all_chunks) == 5
    assert {c.chunk_id for c in all_chunks} == {0, 1, 2, 3, 4}


def test_list_chunks_with_empty_document_ids_returns_empty(temp_db: SQLiteBookDB):
    chunks = [
        ChunkRecord(
            chunk_id=0,
            hash="hash0",
            text="text0",
            is_extracted=False,
            is_summarized=False,
        )
    ]
    temp_db.upsert_chunks(chunks)

    assert temp_db.list_chunks(document_ids=[]) == []


# --- Chunk Edge Cases ---


def test_upsert_chunks_empty_iterable(temp_db: SQLiteBookDB):
    """Test upserting empty chunks iterable."""
    result = temp_db.upsert_chunks([])
    assert result == []


def test_upsert_chunks_negative_chunk_id(temp_db: SQLiteBookDB):
    """Test upserting chunk with negative chunk_id."""
    chunk = ChunkRecord(
        chunk_id=-1,  # Negative ID
        hash="hash1",
        text="text1",
        is_extracted=False,
        is_summarized=False,
    )
    result = temp_db.upsert_chunks([chunk])
    assert -1 in result

    chunks = temp_db.list_chunks()
    assert any(c.chunk_id == -1 for c in chunks)


def test_upsert_chunks_zero_chunk_id(temp_db: SQLiteBookDB):
    """Test upserting chunk with zero chunk_id."""
    chunk = ChunkRecord(
        chunk_id=0,
        hash="hash0",
        text="text0",
        is_extracted=False,
        is_summarized=False,
    )
    result = temp_db.upsert_chunks([chunk])
    assert 0 in result


def test_upsert_chunks_empty_hash(temp_db: SQLiteBookDB):
    """Test upserting chunk with empty hash."""
    chunk = ChunkRecord(
        chunk_id=1,
        hash="",  # Empty hash
        text="text1",
        is_extracted=False,
        is_summarized=False,
    )
    result = temp_db.upsert_chunks([chunk])
    assert 1 in result

    assert temp_db.chunk_exists_by_hash("") == 1


def test_upsert_chunks_empty_text(temp_db: SQLiteBookDB):
    """Test upserting chunk with empty text."""
    chunk = ChunkRecord(
        chunk_id=1,
        hash="hash1",
        text="",  # Empty text
        is_extracted=False,
        is_summarized=False,
    )
    result = temp_db.upsert_chunks([chunk])
    assert 1 in result

    chunks = temp_db.list_chunks()
    assert chunks[0].text == ""


def test_upsert_chunks_very_long_text(temp_db: SQLiteBookDB):
    """Test upserting chunk with very long text."""
    long_text = "a" * 100000
    chunk = ChunkRecord(
        chunk_id=1,
        hash="hash1",
        text=long_text,
        is_extracted=False,
        is_summarized=False,
    )
    result = temp_db.upsert_chunks([chunk])
    assert 1 in result

    chunks = temp_db.list_chunks()
    assert len(chunks[0].text) == 100000


def test_upsert_chunks_unicode_text(temp_db: SQLiteBookDB):
    """Test upserting chunk with unicode text."""
    unicode_text = "测试文本 🚀 日本語 中文"
    chunk = ChunkRecord(
        chunk_id=1,
        hash="hash1",
        text=unicode_text,
        is_extracted=False,
        is_summarized=False,
    )
    result = temp_db.upsert_chunks([chunk])
    assert 1 in result

    chunks = temp_db.list_chunks()
    assert chunks[0].text == unicode_text


def test_upsert_chunks_same_hash_different_ids(temp_db: SQLiteBookDB):
    """Test upserting chunks with same hash but different chunk_ids."""
    chunk1 = ChunkRecord(
        chunk_id=1,
        hash="same_hash",
        text="text1",
        is_extracted=False,
        is_summarized=False,
    )
    chunk2 = ChunkRecord(
        chunk_id=2,
        hash="same_hash",  # Same hash, different ID
        text="text2",
        is_extracted=False,
        is_summarized=False,
    )

    temp_db.upsert_chunks([chunk1])
    temp_db.upsert_chunks([chunk2])

    # Second insert should update existing chunk, not create new one
    chunks = temp_db.list_chunks()
    assert len(chunks) == 1
    # The chunk_id should remain as the first one (1)
    assert chunks[0].chunk_id == 1


def test_chunk_exists_by_hash_empty_string(temp_db: SQLiteBookDB):
    """Test checking chunk existence with empty hash."""
    assert temp_db.chunk_exists_by_hash("") is None

    chunk = ChunkRecord(
        chunk_id=1,
        hash="",
        text="text1",
        is_extracted=False,
        is_summarized=False,
    )
    temp_db.upsert_chunks([chunk])

    assert temp_db.chunk_exists_by_hash("") == 1


def test_get_max_chunk_id_with_gaps(temp_db: SQLiteBookDB):
    """Test getting max chunk ID when there are gaps in IDs."""
    chunks = [
        ChunkRecord(
            chunk_id=i,
            hash=f"hash{i}",
            text=f"text{i}",
            is_extracted=False,
            is_summarized=False,
        )
        for i in range(1, 4)  # IDs: 1, 2, 3
    ]
    chunks.append(
        ChunkRecord(
            chunk_id=10,
            hash="hash10",
            text="text10",
            is_extracted=False,
            is_summarized=False,
        )
    )

    temp_db.upsert_chunks(chunks)

    assert temp_db.get_max_chunk_id() == 10


def test_upsert_chunks_return_type(temp_db: SQLiteBookDB):
    """Test that upsert_chunks returns correct type (list[int])."""
    chunks = [
        ChunkRecord(
            chunk_id=i,
            hash=f"hash{i}",
            text=f"text{i}",
            is_extracted=False,
            is_summarized=False,
        )
        for i in range(5)
    ]
    result = temp_db.upsert_chunks(chunks)

    assert isinstance(result, list)
    assert all(isinstance(x, int) for x in result)
    assert result == [0, 1, 2, 3, 4]


def test_chunk_with_all_none_optional_fields(temp_db: SQLiteBookDB):
    """Test chunk with all optional fields as None."""
    chunk = TranslationChunkRecord(
        chunk_id=1,
        hash="hash1",
        text="text1",
        created_at=None,
        is_extracted=False,
        is_summarized=False,
        is_occurrence_mapped=False,
        is_translated=False,
        translation=None,
    )
    temp_db.upsert_chunks([chunk])

    chunks = temp_db.list_chunks()
    assert len(chunks) == 1
    assert chunks[0].created_at is not None  # Should be set by upsert_chunks
    assert chunks[0].translation is None


def test_chunk_hash_special_characters(temp_db: SQLiteBookDB):
    """Test chunk hashes with special characters."""
    special_hashes = [
        "hash with spaces",
        "hash\twith\ttabs",
        "hash\nwith\nnewlines",
        "hash'with'quotes",
    ]

    for i, hash_val in enumerate(special_hashes):
        chunk = ChunkRecord(
            chunk_id=i,
            hash=hash_val,
            text=f"text{i}",
            is_extracted=False,
            is_summarized=False,
        )
        temp_db.upsert_chunks([chunk])
        assert temp_db.chunk_exists_by_hash(hash_val) == i


def test_upsert_chunks_duplicate_chunk_id_different_hash(temp_db: SQLiteBookDB):
    """Test upserting chunks with same chunk_id but different hash (should fail)."""
    chunk1 = ChunkRecord(
        chunk_id=1,
        hash="hash1",
        text="text1",
        is_extracted=False,
        is_summarized=False,
    )
    chunk2 = ChunkRecord(
        chunk_id=1,  # Same chunk_id
        hash="hash2",  # Different hash
        text="text2",
        is_extracted=False,
        is_summarized=False,
    )

    temp_db.upsert_chunks([chunk1])
    # This should raise IntegrityError because chunk_id is PRIMARY KEY
    with pytest.raises(sqlite3.IntegrityError):
        temp_db.upsert_chunks([chunk2])


def test_upsert_chunks_large_batch(temp_db: SQLiteBookDB):
    """Test upserting a large batch of chunks."""
    chunks = [
        ChunkRecord(
            chunk_id=i,
            hash=f"hash{i}",
            text=f"text{i}",
            is_extracted=False,
            is_summarized=False,
        )
        for i in range(1000)
    ]
    result = temp_db.upsert_chunks(chunks)
    assert len(result) == 1000


def test_chunk_id_overflow_handling(temp_db: SQLiteBookDB):
    """Test handling of very large chunk IDs."""
    # Test with a large but reasonable chunk_id
    large_id = 2**31 - 1  # Max 32-bit signed int
    chunk = ChunkRecord(
        chunk_id=large_id,
        hash="hash_large",
        text="text",
        is_extracted=False,
        is_summarized=False,
    )
    result = temp_db.upsert_chunks([chunk])
    assert large_id in result

    assert temp_db.get_max_chunk_id() == large_id


def test_upsert_chunks_mixed_chunk_types(temp_db: SQLiteBookDB):
    """Test upserting mix of ChunkRecord and TranslationChunkRecord."""
    chunks = [
        ChunkRecord(
            chunk_id=1,
            hash="hash1",
            text="text1",
            is_extracted=False,
            is_summarized=False,
        ),
        TranslationChunkRecord(
            chunk_id=2,
            hash="hash2",
            text="text2",
            is_extracted=True,
            is_summarized=True,
            is_occurrence_mapped=True,
            is_translated=True,
            translation="translation2",
        ),
    ]
    result = temp_db.upsert_chunks(chunks)
    assert len(result) == 2

    chunks_list = temp_db.list_chunks()
    assert len(chunks_list) == 2
    assert chunks_list[0].is_extracted is False
    assert chunks_list[1].is_extracted is True
    assert chunks_list[1].translation == "translation2"


def test_concurrent_upsert_same_chunk_hash(temp_db: SQLiteBookDB):
    """Test concurrent-like upsert of same chunk hash."""
    chunk1 = ChunkRecord(
        chunk_id=1,
        hash="same_hash",
        text="text1",
        is_extracted=False,
        is_summarized=False,
    )
    chunk2 = ChunkRecord(
        chunk_id=2,
        hash="same_hash",  # Same hash
        text="text2",
        is_extracted=True,  # Different flags
        is_summarized=True,
    )

    temp_db.upsert_chunks([chunk1])
    result = temp_db.upsert_chunks([chunk2])

    # Should update existing chunk, return original chunk_id
    assert 1 in result
    chunks = temp_db.list_chunks()
    assert len(chunks) == 1
    assert chunks[0].chunk_id == 1  # Original ID preserved
    assert chunks[0].is_extracted is True  # Flags updated


# --- Source Language Operations ---


def test_set_get_source_language(temp_db: SQLiteBookDB):
    """Test setting and getting source language."""
    # Initially None
    assert temp_db.get_source_language() is None

    # Set source language
    temp_db.set_source_language("日语")
    assert temp_db.get_source_language() == "日语"

    # Update source language
    temp_db.set_source_language("英语")
    assert temp_db.get_source_language() == "英语"


def test_get_source_language_before_set(temp_db: SQLiteBookDB):
    """Test getting source language before it's set."""
    # Should return None initially
    assert temp_db.get_source_language() is None


def test_set_source_language_empty_string(temp_db: SQLiteBookDB):
    """Test setting source language to empty string."""
    temp_db.set_source_language("")
    result = temp_db.get_source_language()
    # Empty string should be preserved (after bug fix)
    assert result == ""


def test_set_source_language_unicode(temp_db: SQLiteBookDB):
    """Test setting source language with unicode characters."""
    temp_db.set_source_language("日本語 🚀 中文")
    assert temp_db.get_source_language() == "日本語 🚀 中文"


def test_set_source_language_multiple_times(temp_db: SQLiteBookDB):
    """Test setting source language multiple times."""
    temp_db.set_source_language("语言1")
    assert temp_db.get_source_language() == "语言1"

    temp_db.set_source_language("语言2")
    assert temp_db.get_source_language() == "语言2"

    temp_db.set_source_language("语言3")
    assert temp_db.get_source_language() == "语言3"


# --- Transaction Operations ---


def test_transaction_rollback(temp_db: SQLiteBookDB):
    """Test transaction rollback.

    Note: upsert_terms commits immediately, so it doesn't participate in transactions.
    This test verifies that rollback works for operations that do use transactions.
    """
    term = TermRecord(
        key="term1",
        descriptions={},
        occurrence={},
        votes=1,
        total_api_calls=1,
    )

    # upsert_terms commits immediately, so the term will persist even after rollback
    temp_db.upsert_terms([term])
    temp_db.begin()
    temp_db.rollback()

    # Term should still exist because upsert_terms committed immediately
    assert temp_db.get_term("term1") is not None


def test_transaction_commit(temp_db: SQLiteBookDB):
    """Test transaction commit."""
    term = TermRecord(
        key="term1",
        descriptions={},
        occurrence={},
        votes=1,
        total_api_calls=1,
    )

    temp_db.begin()
    temp_db.upsert_terms([term])
    temp_db.commit()

    # Term should exist after commit
    assert temp_db.get_term("term1") is not None
