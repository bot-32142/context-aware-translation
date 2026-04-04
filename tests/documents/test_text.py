from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from context_aware_translation.core.cancellation import OperationCancelledError
from context_aware_translation.documents.text import TextDocument
from context_aware_translation.storage.repositories.document_repository import DocumentRepository
from context_aware_translation.storage.schema.book_db import SQLiteBookDB
from context_aware_translation.utils.compression_marker import COMPRESSED_LINE_SENTINEL


def _setup_repo(tmp_path: Path) -> DocumentRepository:
    return DocumentRepository(SQLiteBookDB(tmp_path / "book.db"))


def test_process_ocr_is_noop():
    mock_repo = MagicMock()
    doc = TextDocument(mock_repo, 1)

    asyncio.run(doc.process_ocr(None))

    mock_repo.get_document_sources.assert_not_called()


def test_get_text_merges_sources_in_sequence_order():
    mock_repo = MagicMock()
    mock_repo.get_document_sources.return_value = [
        {"sequence_number": 1, "text_content": "Second"},
        {"sequence_number": 0, "text_content": "First"},
        {"sequence_number": 2, "text_content": "Third"},
    ]

    doc = TextDocument(mock_repo, 1)
    result = doc.get_text()

    assert result == "First\nSecond\nThird"
    mock_repo.get_document_sources.assert_called_once_with(1)


def test_get_text_skips_empty_text_content():
    mock_repo = MagicMock()
    mock_repo.get_document_sources.return_value = [
        {"sequence_number": 0, "text_content": "First"},
        {"sequence_number": 1, "text_content": None},
        {"sequence_number": 2, "text_content": ""},
        {"sequence_number": 3, "text_content": "Third"},
    ]

    doc = TextDocument(mock_repo, 1)
    result = doc.get_text()

    assert result == "First\nThird"


def test_is_text_added_returns_false_when_any_source_not_added():
    mock_repo = MagicMock()
    mock_repo.get_document_sources.return_value = [
        {"is_text_added": 1},
        {"is_text_added": 0},
        {"is_text_added": 1},
    ]

    doc = TextDocument(mock_repo, 1)
    result = doc.is_text_added()

    assert result is False


def test_is_text_added_returns_true_when_all_sources_added():
    mock_repo = MagicMock()
    mock_repo.get_document_sources.return_value = [
        {"is_text_added": 1},
        {"is_text_added": 1},
        {"is_text_added": 1},
    ]

    doc = TextDocument(mock_repo, 1)
    result = doc.is_text_added()

    assert result is True


def test_is_text_added_returns_true_when_no_sources():
    mock_repo = MagicMock()
    mock_repo.get_document_sources.return_value = []

    doc = TextDocument(mock_repo, 1)
    result = doc.is_text_added()

    assert result is True


def test_mark_text_added_calls_db_method():
    mock_repo = MagicMock()
    doc = TextDocument(mock_repo, 1)

    doc.mark_text_added()

    mock_repo.update_all_sources_text_added.assert_called_once_with(1)


def test_do_import_can_remove_hard_wraps(tmp_path: Path) -> None:
    source = tmp_path / "chapter.txt"
    source.write_text(
        "After a long conversation with the harbor master,\n"
        "Captain Leclere left Naples in agitation.\n"
        "Twenty-four hours later the fever took him.",
        encoding="utf-8",
    )

    repo = _setup_repo(tmp_path)
    result = TextDocument.do_import(repo, source, remove_hard_wraps=True)

    assert result == {"imported": 1, "skipped": 0}
    doc_row = repo.get_document_row()
    assert doc_row is not None
    sources = repo.get_document_sources(doc_row["document_id"])
    assert len(sources) == 1
    assert sources[0]["text_content"] == (
        "After a long conversation with the harbor master, "
        "Captain Leclere left Naples in agitation. "
        "Twenty-four hours later the fever took him."
    )


async def test_set_text_returns_line_count_and_stores_lines():
    mock_repo = MagicMock()
    doc = TextDocument(mock_repo, 1)

    lines = ["Line 1", "Line 2", "Line 3"]
    result = await doc.set_text(lines)

    assert result == 3
    assert doc._translated_lines == lines


async def test_export_txt_writes_file_correctly():
    mock_repo = MagicMock()
    doc = TextDocument(mock_repo, 1)
    await doc.set_text(["Line 1", "Line 2", "Line 3"])

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "output.txt"
        TextDocument.export_merged([doc], "txt", output_path)

        assert output_path.exists()
        assert output_path.read_text() == "Line 1\nLine 2\nLine 3"


async def test_export_txt_decodes_compressed_placeholder():
    mock_repo = MagicMock()
    doc = TextDocument(mock_repo, 1)
    await doc.set_text(["Line 1", COMPRESSED_LINE_SENTINEL, "Line 3"])

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "output.txt"
        TextDocument.export_merged([doc], "txt", output_path)

        assert output_path.exists()
        assert output_path.read_text() == "Line 1\n\nLine 3"


async def test_export_txt_creates_parent_directories():
    mock_repo = MagicMock()
    doc = TextDocument(mock_repo, 1)
    await doc.set_text(["Line 1"])

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "subdir" / "nested" / "output.txt"
        TextDocument.export_merged([doc], "txt", output_path)

        assert output_path.exists()
        assert output_path.read_text() == "Line 1"


async def test_export_epub_raises_value_error():
    mock_repo = MagicMock()
    doc = TextDocument(mock_repo, 1)
    await doc.set_text(["Line 1"])

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "output.epub"

        with pytest.raises(ValueError, match="Text documents only support"):
            TextDocument.export_merged([doc], "epub", output_path)


async def test_export_pdf_raises_value_error():
    mock_repo = MagicMock()
    doc = TextDocument(mock_repo, 1)
    await doc.set_text(["Line 1"])

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "output.pdf"

        with pytest.raises(ValueError, match="Text documents only support"):
            TextDocument.export_merged([doc], "pdf", output_path)


def test_export_without_set_text_raises_value_error():
    mock_repo = MagicMock()
    doc = TextDocument(mock_repo, 1)

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "output.txt"

        with pytest.raises(ValueError, match="[Nn]o translated text"):
            TextDocument.export_merged([doc], "txt", output_path)


async def test_export_preserve_structure_creates_files_per_source():
    mock_repo = MagicMock()
    mock_repo.get_document_sources.return_value = [
        {
            "sequence_number": 0,
            "relative_path": "chapter1.txt",
            "text_content": "Line 1\nLine 2\n",
        },
        {
            "sequence_number": 1,
            "relative_path": "chapter2.txt",
            "text_content": "Line 3\nLine 4\nLine 5",
        },
    ]

    doc = TextDocument(mock_repo, 1)
    await doc.set_text(["Line 1", "Line 2", "Line 3", "Line 4", "Line 5"])

    with tempfile.TemporaryDirectory() as tmpdir:
        output_folder = Path(tmpdir)
        doc.export_preserve_structure(output_folder)

        chapter1 = output_folder / "chapter1.txt"
        chapter2 = output_folder / "chapter2.txt"

        assert chapter1.exists()
        assert chapter1.read_text() == "Line 1\nLine 2"

        assert chapter2.exists()
        assert chapter2.read_text() == "Line 3\nLine 4\nLine 5"


async def test_export_preserve_structure_decodes_compressed_placeholder():
    mock_repo = MagicMock()
    mock_repo.get_document_sources.return_value = [
        {
            "sequence_number": 0,
            "relative_path": "chapter1.txt",
            "text_content": "Line 1\nLine 2\nLine 3",
        },
    ]

    doc = TextDocument(mock_repo, 1)
    await doc.set_text(["Line 1", COMPRESSED_LINE_SENTINEL, "Line 3"])

    with tempfile.TemporaryDirectory() as tmpdir:
        output_folder = Path(tmpdir)
        doc.export_preserve_structure(output_folder)
        assert (output_folder / "chapter1.txt").read_text() == "Line 1\n\nLine 3"


async def test_export_preserve_structure_creates_nested_directories():
    mock_repo = MagicMock()
    mock_repo.get_document_sources.return_value = [
        {
            "sequence_number": 0,
            "relative_path": "part1/chapter1.txt",
            "text_content": "Line 1\nLine 2\n",
        },
    ]

    doc = TextDocument(mock_repo, 1)
    await doc.set_text(["Line 1", "Line 2"])

    with tempfile.TemporaryDirectory() as tmpdir:
        output_folder = Path(tmpdir)
        doc.export_preserve_structure(output_folder)

        chapter1 = output_folder / "part1" / "chapter1.txt"

        assert chapter1.exists()
        assert chapter1.read_text() == "Line 1\nLine 2"


async def test_export_preserve_structure_skips_sources_without_relative_path():
    mock_repo = MagicMock()
    mock_repo.get_document_sources.return_value = [
        {
            "sequence_number": 0,
            "relative_path": "chapter1.txt",
            "text_content": "Line 1\nLine 2\n",
        },
        {
            "sequence_number": 1,
            "relative_path": None,
            "text_content": "Line 3\n",
        },
    ]

    doc = TextDocument(mock_repo, 1)
    await doc.set_text(["Line 1", "Line 2", "Line 3"])

    with tempfile.TemporaryDirectory() as tmpdir:
        output_folder = Path(tmpdir)
        doc.export_preserve_structure(output_folder)

        chapter1 = output_folder / "chapter1.txt"
        assert chapter1.exists()
        assert chapter1.read_text() == "Line 1\nLine 2"


async def test_export_preserve_structure_skips_sources_with_zero_line_count():
    mock_repo = MagicMock()
    mock_repo.get_document_sources.return_value = [
        {
            "sequence_number": 0,
            "relative_path": "chapter1.txt",
            "text_content": "Line 1\nLine 2\n",
        },
        {
            "sequence_number": 1,
            "relative_path": "chapter2.txt",
            "text_content": "",
        },
    ]

    doc = TextDocument(mock_repo, 1)
    await doc.set_text(["Line 1", "Line 2"])

    with tempfile.TemporaryDirectory() as tmpdir:
        output_folder = Path(tmpdir)
        doc.export_preserve_structure(output_folder)

        chapter1 = output_folder / "chapter1.txt"
        chapter2 = output_folder / "chapter2.txt"

        assert chapter1.exists()
        assert not chapter2.exists()


def test_export_preserve_structure_without_set_text_raises_value_error():
    mock_repo = MagicMock()
    doc = TextDocument(mock_repo, 1)

    with tempfile.TemporaryDirectory() as tmpdir:
        output_folder = Path(tmpdir)

        with pytest.raises(ValueError, match="[Nn]o translated text"):
            doc.export_preserve_structure(output_folder)


class TestCanImport:
    """Test TextDocument.can_import() classmethod."""

    def test_single_txt_file(self, tmp_path):
        """Single .txt file should return True."""
        txt_file = tmp_path / "document.txt"
        txt_file.write_text("Hello world")

        assert TextDocument.can_import(txt_file) is True

    def test_single_md_file(self, tmp_path):
        """Single .md file should return True."""
        md_file = tmp_path / "document.md"
        md_file.write_text("# Hello world")

        assert TextDocument.can_import(md_file) is True

    def test_folder_of_text_files(self, tmp_path):
        """Folder containing only .txt and .md files should return True."""
        (tmp_path / "file1.txt").write_text("Content 1")
        (tmp_path / "file2.md").write_text("Content 2")
        (tmp_path / "file3.txt").write_text("Content 3")

        assert TextDocument.can_import(tmp_path) is True

    def test_rejects_single_image(self, tmp_path):
        """Single image file should return False."""
        img_file = tmp_path / "image.png"
        img_file.write_bytes(b"fake png data")

        assert TextDocument.can_import(img_file) is False

    def test_rejects_folder_with_mixed_files(self, tmp_path):
        """Folder with mixed text and image files should return False."""
        (tmp_path / "document.txt").write_text("Text content")
        (tmp_path / "image.png").write_bytes(b"fake png data")

        assert TextDocument.can_import(tmp_path) is False

    def test_rejects_pdf(self, tmp_path):
        """PDF file should return False."""
        pdf_file = tmp_path / "document.pdf"
        pdf_file.write_bytes(b"fake pdf data")

        assert TextDocument.can_import(pdf_file) is False

    def test_rejects_nonexistent_path(self, tmp_path):
        """Nonexistent path should return False."""
        nonexistent = tmp_path / "does_not_exist.txt"

        assert TextDocument.can_import(nonexistent) is False


class TestDoImport:
    """Test TextDocument.do_import() classmethod."""

    def test_imports_single_text_file(self, tmp_path, temp_config):
        """Import single .txt file creates document and source."""
        from context_aware_translation.storage.repositories.document_repository import DocumentRepository
        from context_aware_translation.storage.schema.book_db import SQLiteBookDB

        txt_file = tmp_path / "document.txt"
        txt_file.write_text("Line 1\nLine 2\nLine 3")

        db = SQLiteBookDB(temp_config.sqlite_path)
        repo = DocumentRepository(db)

        TextDocument.do_import(repo, txt_file)

        doc_row = repo.get_document_row()
        assert doc_row is not None
        assert doc_row["document_type"] == "text"

        sources = repo.get_document_sources(doc_row["document_id"])
        assert len(sources) == 1
        assert sources[0]["sequence_number"] == 0
        assert sources[0]["source_type"] == "text"
        assert sources[0]["relative_path"] == "document.txt"
        assert sources[0]["text_content"] == "Line 1\nLine 2\nLine 3"

    def test_imports_folder_of_text_files(self, tmp_path, temp_config):
        """Import folder creates document with multiple sources."""
        from context_aware_translation.storage.repositories.document_repository import DocumentRepository
        from context_aware_translation.storage.schema.book_db import SQLiteBookDB

        (tmp_path / "file1.txt").write_text("Content 1")
        (tmp_path / "file2.md").write_text("Content 2")
        (tmp_path / "file3.txt").write_text("Content 3")

        db = SQLiteBookDB(temp_config.sqlite_path)
        repo = DocumentRepository(db)

        TextDocument.do_import(repo, tmp_path)

        doc_row = repo.get_document_row()
        assert doc_row is not None
        assert doc_row["document_type"] == "text"

        sources = repo.get_document_sources(doc_row["document_id"])
        assert len(sources) == 3

    def test_preserves_alphabetical_order(self, tmp_path, temp_config):
        """Sources are inserted in alphabetical order by filename."""
        from context_aware_translation.storage.repositories.document_repository import DocumentRepository
        from context_aware_translation.storage.schema.book_db import SQLiteBookDB

        (tmp_path / "zebra.txt").write_text("Z")
        (tmp_path / "apple.txt").write_text("A")
        (tmp_path / "middle.txt").write_text("M")

        db = SQLiteBookDB(temp_config.sqlite_path)
        repo = DocumentRepository(db)

        TextDocument.do_import(repo, tmp_path)

        doc_row = repo.get_document_row()
        sources = repo.get_document_sources(doc_row["document_id"])
        assert len(sources) == 3
        assert sources[0]["relative_path"] == "apple.txt"
        assert sources[0]["sequence_number"] == 0
        assert sources[1]["relative_path"] == "middle.txt"
        assert sources[1]["sequence_number"] == 1
        assert sources[2]["relative_path"] == "zebra.txt"
        assert sources[2]["sequence_number"] == 2

    def test_rollback_on_error(self, tmp_path, temp_config):
        """Transaction rolls back if error occurs during import."""
        from unittest.mock import patch

        from context_aware_translation.storage.repositories.document_repository import DocumentRepository
        from context_aware_translation.storage.schema.book_db import SQLiteBookDB

        txt_file = tmp_path / "document.txt"
        txt_file.write_text("Content")

        db = SQLiteBookDB(temp_config.sqlite_path)
        repo = DocumentRepository(db)

        with (
            patch.object(repo, "insert_document_source", side_effect=RuntimeError("Test error")),
            pytest.raises(RuntimeError, match="Test error"),
        ):
            TextDocument.do_import(repo, txt_file)

        doc_row = repo.get_document_row()
        assert doc_row is None

    def test_import_can_be_cancelled_and_rolls_back(self, tmp_path, temp_config):
        """Cancellation during import rolls back all inserts."""
        from context_aware_translation.storage.repositories.document_repository import DocumentRepository
        from context_aware_translation.storage.schema.book_db import SQLiteBookDB

        (tmp_path / "file1.txt").write_text("Content 1")
        (tmp_path / "file2.txt").write_text("Content 2")
        (tmp_path / "file3.txt").write_text("Content 3")

        db = SQLiteBookDB(temp_config.sqlite_path)
        repo = DocumentRepository(db)

        state = {"calls": 0}

        def cancel_check() -> bool:
            state["calls"] += 1
            return state["calls"] >= 5

        with pytest.raises(OperationCancelledError):
            TextDocument.do_import(repo, tmp_path, cancel_check=cancel_check)

        doc_row = repo.get_document_row()
        assert doc_row is None

    def test_stores_text_content(self, tmp_path, temp_config):
        """Text content is stored correctly for each source."""
        from context_aware_translation.storage.repositories.document_repository import DocumentRepository
        from context_aware_translation.storage.schema.book_db import SQLiteBookDB

        txt_file = tmp_path / "test.txt"
        content = "First line\nSecond line\nThird line"
        txt_file.write_text(content)

        db = SQLiteBookDB(temp_config.sqlite_path)
        repo = DocumentRepository(db)

        TextDocument.do_import(repo, txt_file)

        doc_row = repo.get_document_row()
        sources = repo.get_document_sources(doc_row["document_id"])
        assert len(sources) == 1
        assert sources[0]["text_content"] == content


def test_supported_export_formats():
    mock_repo = MagicMock()
    doc = TextDocument(mock_repo, 1)
    assert doc.supported_export_formats == ("txt",)


def test_can_export_txt_returns_true():
    mock_repo = MagicMock()
    doc = TextDocument(mock_repo, 1)
    assert doc.can_export("txt") is True
    assert doc.can_export("TXT") is True  # case insensitive


def test_can_export_epub_returns_false():
    mock_repo = MagicMock()
    doc = TextDocument(mock_repo, 1)
    assert doc.can_export("epub") is False


def test_can_export_md_returns_false():
    mock_repo = MagicMock()
    doc = TextDocument(mock_repo, 1)
    assert doc.can_export("md") is False


async def test_export_unsupported_format_error_message():
    mock_repo = MagicMock()
    doc = TextDocument(mock_repo, 1)
    await doc.set_text(["Line 1"])

    with pytest.raises(ValueError) as exc_info:
        TextDocument.export_merged([doc], "epub", Path("/tmp/out.epub"))

    assert "txt" in str(exc_info.value)
    assert "epub" in str(exc_info.value)
