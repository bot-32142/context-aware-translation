"""Tests for document_repository.py

Tests are organized to match the code structure:
- DocumentRepository (class)
  - Document methods
  - Document source methods
  - Document source update methods
  - Transaction methods
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from context_aware_translation.storage.repositories.document_repository import DocumentRepository

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_db() -> MagicMock:
    """Create a mock SQLiteBookDB for testing."""
    return MagicMock()


@pytest.fixture
def document_repository(mock_db: MagicMock) -> DocumentRepository:
    """Create a DocumentRepository with mock db."""
    return DocumentRepository(mock_db)


# ============================================================================
# DocumentRepository (class) Tests
# ============================================================================

# --- Initialization ---


def test_document_repository_init(mock_db: MagicMock):
    """Test DocumentRepository initialization stores db reference."""
    repo = DocumentRepository(mock_db)
    assert repo.db is mock_db


# --- Document Methods ---


def test_get_document_row(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test get_document_row delegates to db."""
    mock_db.get_document_row.return_value = {"document_id": 1, "document_type": "text"}

    result = document_repository.get_document_row()

    mock_db.get_document_row.assert_called_once_with()
    assert result == {"document_id": 1, "document_type": "text"}


def test_get_document_row_none(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test get_document_row returns None when no document exists."""
    mock_db.get_document_row.return_value = None

    result = document_repository.get_document_row()

    mock_db.get_document_row.assert_called_once_with()
    assert result is None


def test_insert_document(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test insert_document delegates to db."""
    mock_db.insert_document.return_value = 42

    result = document_repository.insert_document("text", auto_commit=True)

    mock_db.insert_document.assert_called_once_with("text", True)
    assert result == 42


def test_insert_document_no_auto_commit(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test insert_document with auto_commit=False."""
    mock_db.insert_document.return_value = 99

    result = document_repository.insert_document("image", auto_commit=False)

    mock_db.insert_document.assert_called_once_with("image", False)
    assert result == 99


# --- Document Source Methods ---


def test_insert_document_source_minimal(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test insert_document_source with minimal arguments."""
    mock_db.insert_document_source.return_value = 10

    result = document_repository.insert_document_source(1, 0, "text")

    mock_db.insert_document_source.assert_called_once_with(
        1,
        0,
        "text",
        relative_path=None,
        text_content=None,
        binary_content=None,
        mime_type=None,
        ocr_json=None,
        is_ocr_completed=False,
        is_text_added=False,
        auto_commit=True,
    )
    assert result == 10


def test_insert_document_source_full(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test insert_document_source with all arguments."""
    mock_db.insert_document_source.return_value = 20

    result = document_repository.insert_document_source(
        document_id=1,
        sequence_number=5,
        source_type="image",
        relative_path="path/to/file.png",
        text_content="some text",
        binary_content=b"binary data",
        mime_type="image/png",
        ocr_json='{"text": "OCR result"}',
        is_ocr_completed=True,
        is_text_added=True,
        auto_commit=False,
    )

    mock_db.insert_document_source.assert_called_once_with(
        1,
        5,
        "image",
        relative_path="path/to/file.png",
        text_content="some text",
        binary_content=b"binary data",
        mime_type="image/png",
        ocr_json='{"text": "OCR result"}',
        is_ocr_completed=True,
        is_text_added=True,
        auto_commit=False,
    )
    assert result == 20


def test_get_document_sources(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test get_document_sources delegates to db."""
    mock_sources = [
        {"source_id": 1, "sequence_number": 0},
        {"source_id": 2, "sequence_number": 1},
    ]
    mock_db.get_document_sources.return_value = mock_sources

    result = document_repository.get_document_sources(1)

    mock_db.get_document_sources.assert_called_once_with(1)
    assert result == mock_sources


def test_get_document_sources_empty(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test get_document_sources returns empty list when no sources exist."""
    mock_db.get_document_sources.return_value = []

    result = document_repository.get_document_sources(999)

    mock_db.get_document_sources.assert_called_once_with(999)
    assert result == []


def test_get_document_sources_needing_ocr(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test get_document_sources_needing_ocr delegates to db."""
    mock_sources = [
        {"source_id": 1, "source_type": "image", "is_ocr_completed": 0},
    ]
    mock_db.get_document_sources_needing_ocr.return_value = mock_sources

    result = document_repository.get_document_sources_needing_ocr(1)

    mock_db.get_document_sources_needing_ocr.assert_called_once_with(1)
    assert result == mock_sources


def test_get_document_sources_needing_ocr_empty(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test get_document_sources_needing_ocr returns empty list when all OCR completed."""
    mock_db.get_document_sources_needing_ocr.return_value = []

    result = document_repository.get_document_sources_needing_ocr(1)

    mock_db.get_document_sources_needing_ocr.assert_called_once_with(1)
    assert result == []


# --- Document Source Update Methods ---


def test_update_source_ocr(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test update_source_ocr delegates to db."""
    document_repository.update_source_ocr(1, '{"text": "OCR"}', auto_commit=True)

    mock_db.update_source_ocr.assert_called_once_with(1, '{"text": "OCR"}', True)


def test_update_source_ocr_no_auto_commit(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test update_source_ocr with auto_commit=False."""
    document_repository.update_source_ocr(2, '{"data": "test"}', auto_commit=False)

    mock_db.update_source_ocr.assert_called_once_with(2, '{"data": "test"}', False)


def test_update_source_ocr_completed(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test update_source_ocr_completed delegates to db."""
    document_repository.update_source_ocr_completed(3, auto_commit=True)

    mock_db.update_source_ocr_completed.assert_called_once_with(3, True)


def test_update_source_ocr_completed_no_auto_commit(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test update_source_ocr_completed with auto_commit=False."""
    document_repository.update_source_ocr_completed(4, auto_commit=False)

    mock_db.update_source_ocr_completed.assert_called_once_with(4, False)


def test_update_source_text_added(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test update_source_text_added delegates to db."""
    document_repository.update_source_text_added(5, auto_commit=True)

    mock_db.update_source_text_added.assert_called_once_with(5, True)


def test_update_source_text_added_no_auto_commit(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test update_source_text_added with auto_commit=False."""
    document_repository.update_source_text_added(6, auto_commit=False)

    mock_db.update_source_text_added.assert_called_once_with(6, False)


def test_update_all_sources_text_added(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test update_all_sources_text_added delegates to db."""
    document_repository.update_all_sources_text_added(1, auto_commit=True)

    mock_db.update_all_sources_text_added.assert_called_once_with(1, True)


def test_update_all_sources_text_added_no_auto_commit(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test update_all_sources_text_added with auto_commit=False."""
    document_repository.update_all_sources_text_added(2, auto_commit=False)

    mock_db.update_all_sources_text_added.assert_called_once_with(2, False)


# --- Transaction Methods ---


def test_begin(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test begin delegates to db."""
    document_repository.begin()

    mock_db.begin.assert_called_once_with()


def test_commit(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test commit delegates to db."""
    document_repository.commit()

    mock_db.commit.assert_called_once_with()


def test_rollback(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test rollback delegates to db."""
    document_repository.rollback()

    mock_db.rollback.assert_called_once_with()


# --- Transaction Flow Tests ---


def test_transaction_flow(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test typical transaction flow."""
    mock_db.insert_document.return_value = 1
    mock_db.insert_document_source.return_value = 10

    # Begin transaction
    document_repository.begin()
    mock_db.begin.assert_called_once()

    # Perform operations
    doc_id = document_repository.insert_document("text", auto_commit=False)
    assert doc_id == 1

    source_id = document_repository.insert_document_source(doc_id, 0, "text", auto_commit=False)
    assert source_id == 10

    # Commit transaction
    document_repository.commit()
    mock_db.commit.assert_called_once()


def test_transaction_rollback_flow(document_repository: DocumentRepository, mock_db: MagicMock):
    """Test transaction rollback flow."""
    # Begin transaction
    document_repository.begin()
    mock_db.begin.assert_called_once()

    # Rollback transaction
    document_repository.rollback()
    mock_db.rollback.assert_called_once()
