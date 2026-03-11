"""Tests for document and document_sources tables in SQLiteBookDB."""

import tempfile
from pathlib import Path

import pytest

from context_aware_translation.storage.schema.book_db import SQLiteBookDB


@pytest.fixture
def db():
    """Create a fresh SQLiteBookDB for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    db = SQLiteBookDB(db_path)
    yield db
    db.close()
    db_path.unlink(missing_ok=True)


class TestDocumentTable:
    def test_get_document_row_returns_none_for_empty_db(self, db):
        result = db.get_document_row()
        assert result is None

    def test_insert_document_returns_id(self, db):
        doc_id = db.insert_document("text")
        assert doc_id == 1

    def test_insert_document_stores_type(self, db):
        db.insert_document("pdf")
        row = db.get_document_row()
        assert row is not None
        assert row["document_type"] == "pdf"

    def test_insert_document_stores_created_at(self, db):
        db.insert_document("scanned_book")
        row = db.get_document_row()
        assert row is not None
        assert row["created_at"] > 0


class TestDocumentSourcesTable:
    def test_insert_document_source_returns_id(self, db):
        doc_id = db.insert_document("text")
        source_id = db.insert_document_source(doc_id, 0, "text")
        assert source_id == 1

    def test_insert_document_source_with_all_params(self, db):
        doc_id = db.insert_document("text")
        source_id = db.insert_document_source(
            doc_id,
            0,
            "text",
            relative_path="chapter1.txt",
            text_content="Hello world",
        )
        sources = db.get_document_sources(doc_id)
        assert len(sources) == 1
        assert sources[0]["source_id"] == source_id
        assert sources[0]["relative_path"] == "chapter1.txt"
        assert sources[0]["text_content"] == "Hello world"

    def test_insert_image_source_with_binary(self, db):
        doc_id = db.insert_document("pdf")
        binary_data = b"\x89PNG\r\n\x1a\n"
        db.insert_document_source(
            doc_id,
            0,
            "image",
            binary_content=binary_data,
            mime_type="image/png",
        )
        sources = db.get_document_sources(doc_id)
        assert sources[0]["binary_content"] == binary_data
        assert sources[0]["mime_type"] == "image/png"

    def test_get_document_sources_ordered_by_sequence_number(self, db):
        doc_id = db.insert_document("pdf")
        db.insert_document_source(doc_id, 2, "image")
        db.insert_document_source(doc_id, 0, "image")
        db.insert_document_source(doc_id, 1, "image")

        sources = db.get_document_sources(doc_id)
        assert len(sources) == 3
        assert sources[0]["sequence_number"] == 0
        assert sources[1]["sequence_number"] == 1
        assert sources[2]["sequence_number"] == 2

    def test_get_document_sources_returns_empty_for_no_sources(self, db):
        doc_id = db.insert_document("text")
        sources = db.get_document_sources(doc_id)
        assert sources == []


class TestDocumentSourcesOCR:
    def test_get_sources_needing_ocr_filters_correctly(self, db):
        doc_id = db.insert_document("pdf")
        db.insert_document_source(doc_id, 0, "image", is_ocr_completed=False)
        db.insert_document_source(doc_id, 1, "image", is_ocr_completed=True)
        db.insert_document_source(doc_id, 2, "text")

        needing_ocr = db.get_document_sources_needing_ocr(doc_id)
        assert len(needing_ocr) == 1
        assert needing_ocr[0]["sequence_number"] == 0

    def test_get_sources_needing_ocr_returns_empty_when_all_done(self, db):
        doc_id = db.insert_document("pdf")
        db.insert_document_source(doc_id, 0, "image", is_ocr_completed=True)
        db.insert_document_source(doc_id, 1, "image", is_ocr_completed=True)

        needing_ocr = db.get_document_sources_needing_ocr(doc_id)
        assert needing_ocr == []

    def test_update_source_ocr(self, db):
        doc_id = db.insert_document("pdf")
        source_id = db.insert_document_source(doc_id, 0, "image")

        db.update_source_ocr(source_id, '{"text": "Hello"}')

        sources = db.get_document_sources(doc_id)
        assert sources[0]["ocr_json"] == '{"text": "Hello"}'

    def test_update_source_ocr_completed(self, db):
        doc_id = db.insert_document("pdf")
        source_id = db.insert_document_source(doc_id, 0, "image")

        assert db.get_document_sources(doc_id)[0]["is_ocr_completed"] == 0

        db.update_source_ocr_completed(source_id)

        assert db.get_document_sources(doc_id)[0]["is_ocr_completed"] == 1


class TestDocumentSourcesTextAdded:
    def test_update_source_text_added(self, db):
        doc_id = db.insert_document("text")
        source_id = db.insert_document_source(doc_id, 0, "text")

        assert db.get_document_sources(doc_id)[0]["is_text_added"] == 0

        db.update_source_text_added(source_id)

        assert db.get_document_sources(doc_id)[0]["is_text_added"] == 1

    def test_update_all_sources_text_added(self, db):
        doc_id = db.insert_document("text")
        db.insert_document_source(doc_id, 0, "text")
        db.insert_document_source(doc_id, 1, "text")
        db.insert_document_source(doc_id, 2, "text")

        sources = db.get_document_sources(doc_id)
        assert all(s["is_text_added"] == 0 for s in sources)

        db.update_all_sources_text_added(doc_id)

        sources = db.get_document_sources(doc_id)
        assert all(s["is_text_added"] == 1 for s in sources)


class TestForeignKeyCascade:
    def test_delete_document_cascades_to_sources(self, db):
        doc_id = db.insert_document("pdf")
        db.insert_document_source(doc_id, 0, "image")
        db.insert_document_source(doc_id, 1, "image")

        sources_before = db.get_document_sources(doc_id)
        assert len(sources_before) == 2

        db.conn.execute("DELETE FROM document WHERE document_id = ?", (doc_id,))
        db.conn.commit()

        sources_after = db.conn.execute("SELECT * FROM document_sources").fetchall()
        assert len(sources_after) == 0
