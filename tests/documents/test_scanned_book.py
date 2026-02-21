from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from context_aware_translation.config import OCRConfig
from context_aware_translation.documents.content.ocr_content import MergedOCRContent
from context_aware_translation.documents.scanned_book import ScannedBookDocument


def _png_bytes(color: tuple[int, int, int], size: tuple[int, int] = (4, 4)) -> bytes:
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes(color: tuple[int, int, int], size: tuple[int, int] = (4, 4)) -> bytes:
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def mock_ocr_content():
    raw_ocr_data = [
        (
            [
                {
                    "page_type": "content",
                    "content": [
                        {
                            "type": "paragraph",
                            "text": "First paragraph",
                            "continues_from_previous": False,
                            "continues_to_next": False,
                        },
                        {
                            "type": "paragraph",
                            "text": "Second paragraph",
                            "continues_from_previous": False,
                            "continues_to_next": False,
                        },
                    ],
                }
            ],
            None,
        )
    ]
    merged = MergedOCRContent.from_raw_ocr(raw_ocr_data)
    merged.set_texts(["First paragraph translated", "Second paragraph translated"])
    return merged


@pytest.mark.asyncio
async def test_process_ocr_calls_ocr_images_for_sources_needing_ocr():
    mock_repo = MagicMock()
    mock_repo.get_document_sources_needing_ocr.return_value = [
        {
            "source_id": 1,
            "sequence_number": 0,
            "binary_content": b"fake_image_data",
            "mime_type": "image/png",
        },
        {
            "source_id": 2,
            "sequence_number": 1,
            "binary_content": b"fake_image_data_2",
            "mime_type": "image/jpeg",
        },
    ]

    mock_ocr_pages = [
        {
            "page_type": "content",
            "content": [
                {
                    "type": "paragraph",
                    "text": "OCR text",
                    "continues_from_previous": False,
                    "continues_to_next": False,
                }
            ],
        },
        {
            "page_type": "content",
            "content": [
                {
                    "type": "paragraph",
                    "text": "OCR text",
                    "continues_from_previous": False,
                    "continues_to_next": False,
                }
            ],
        },
    ]

    def mock_ocr_side_effect(_image_data, _llm_client, _ocr_config, **kwargs):
        # Simulate calling callback for each image
        on_result = kwargs.get("on_result")
        for i, page in enumerate(mock_ocr_pages):
            if on_result:
                on_result(i, page)

    mock_ocr_config = MagicMock()
    mock_ocr_config.concurrency = 5
    mock_ocr_config.ocr_dpi = 150

    with (
        patch("context_aware_translation.documents.scanned_book.ocr_images", new_callable=AsyncMock) as mock_ocr,
        patch(
            "context_aware_translation.documents.scanned_book.compress_image_for_ocr",
            side_effect=lambda x, _max_dpi=150: x,
        ),
    ):
        mock_ocr.side_effect = mock_ocr_side_effect

        doc = ScannedBookDocument(mock_repo, 1, mock_ocr_config)
        await doc.process_ocr(MagicMock())

        assert mock_ocr.call_count == 1
        assert mock_repo.update_source_ocr.call_count == 2
        assert mock_repo.update_source_ocr_completed.call_count == 2

        stored_json = mock_repo.update_source_ocr.call_args_list[0][0][1]
        parsed = json.loads(stored_json)
        assert isinstance(parsed, dict)
        assert parsed["page_type"] == "content"
        assert parsed["content"][0]["type"] == "paragraph"
        assert parsed["content"][0]["text"] == "OCR text"


@pytest.mark.asyncio
async def test_process_ocr_skips_sources_already_ocrd():
    mock_repo = MagicMock()
    mock_repo.get_document_sources_needing_ocr.return_value = []

    mock_ocr_config = MagicMock()
    mock_ocr_config.concurrency = 5

    with patch("context_aware_translation.llm.ocr.ocr_images", new_callable=AsyncMock) as mock_ocr:
        doc = ScannedBookDocument(mock_repo, 1, mock_ocr_config)
        await doc.process_ocr(MagicMock())

        mock_ocr.assert_not_called()
        mock_repo.update_source_ocr.assert_not_called()


@pytest.mark.asyncio
async def test_process_ocr_with_empty_source_ids_processes_none():
    mock_repo = MagicMock()
    mock_repo.get_document_sources_needing_ocr.return_value = [
        {
            "source_id": 1,
            "sequence_number": 0,
            "binary_content": b"fake_image_data",
            "mime_type": "image/png",
        }
    ]

    mock_ocr_config = MagicMock()
    mock_ocr_config.concurrency = 5

    with patch("context_aware_translation.documents.scanned_book.ocr_images", new_callable=AsyncMock) as mock_ocr:
        doc = ScannedBookDocument(mock_repo, 1, mock_ocr_config)
        processed = await doc.process_ocr(MagicMock(), source_ids=[])

        assert processed == 0
        mock_ocr.assert_not_called()
        mock_repo.update_source_ocr.assert_not_called()
        mock_repo.update_source_ocr_completed.assert_not_called()


def test_get_text_merges_ocr_results_from_all_sources():
    mock_repo = MagicMock()

    ocr_json_1 = json.dumps(
        [
            {
                "page_type": "content",
                "content": [
                    {
                        "type": "paragraph",
                        "text": "First page text",
                        "continues_from_previous": False,
                        "continues_to_next": False,
                    }
                ],
            }
        ]
    )

    ocr_json_2 = json.dumps(
        [
            {
                "page_type": "content",
                "content": [
                    {
                        "type": "paragraph",
                        "text": "Second page text",
                        "continues_from_previous": False,
                        "continues_to_next": False,
                    }
                ],
            }
        ]
    )

    mock_repo.get_document_sources.return_value = [
        {"sequence_number": 1, "ocr_json": ocr_json_2},
        {"sequence_number": 0, "ocr_json": ocr_json_1},
    ]

    doc = ScannedBookDocument(mock_repo, 1)
    result = doc.get_text()

    assert result == "First page text\nSecond page text"
    mock_repo.get_document_sources.assert_called_once_with(1)


def test_get_text_skips_sources_without_ocr_json():
    mock_repo = MagicMock()

    ocr_json = json.dumps(
        [
            {
                "page_type": "content",
                "content": [
                    {
                        "type": "paragraph",
                        "text": "Has OCR",
                        "continues_from_previous": False,
                        "continues_to_next": False,
                    }
                ],
            }
        ]
    )

    mock_repo.get_document_sources.return_value = [
        {"sequence_number": 0, "ocr_json": ocr_json},
        {"sequence_number": 1, "ocr_json": None},
        {"sequence_number": 2, "ocr_json": ""},
    ]

    doc = ScannedBookDocument(mock_repo, 1)
    result = doc.get_text()

    assert result == "Has OCR"


def test_is_text_added_returns_false_when_any_source_not_added():
    mock_repo = MagicMock()
    mock_repo.get_document_sources.return_value = [
        {"is_text_added": 1},
        {"is_text_added": 0},
        {"is_text_added": 1},
    ]

    doc = ScannedBookDocument(mock_repo, 1)
    result = doc.is_text_added()

    assert result is False


def test_is_text_added_returns_true_when_all_sources_added():
    mock_repo = MagicMock()
    mock_repo.get_document_sources.return_value = [
        {"is_text_added": 1},
        {"is_text_added": 1},
        {"is_text_added": 1},
    ]

    doc = ScannedBookDocument(mock_repo, 1)
    result = doc.is_text_added()

    assert result is True


def test_is_text_added_returns_true_when_no_sources():
    mock_repo = MagicMock()
    mock_repo.get_document_sources.return_value = []

    doc = ScannedBookDocument(mock_repo, 1)
    result = doc.is_text_added()

    assert result is True


def test_mark_text_added_calls_db_method():
    mock_repo = MagicMock()
    doc = ScannedBookDocument(mock_repo, 1)

    doc.mark_text_added()

    mock_repo.update_all_sources_text_added.assert_called_once_with(1)


async def test_set_text_distributes_to_merged_ocr_content():
    mock_repo = MagicMock()

    ocr_json_1 = json.dumps(
        [
            {
                "page_type": "content",
                "content": [
                    {
                        "type": "paragraph",
                        "text": "Original 1",
                        "continues_from_previous": False,
                        "continues_to_next": False,
                    },
                    {
                        "type": "paragraph",
                        "text": "Original 2",
                        "continues_from_previous": False,
                        "continues_to_next": False,
                    },
                ],
            }
        ]
    )

    ocr_json_2 = json.dumps(
        [
            {
                "page_type": "content",
                "content": [
                    {
                        "type": "paragraph",
                        "text": "Original 3",
                        "continues_from_previous": False,
                        "continues_to_next": False,
                    }
                ],
            }
        ]
    )

    mock_repo.get_document_sources.return_value = [
        {"sequence_number": 0, "ocr_json": ocr_json_1},
        {"sequence_number": 1, "ocr_json": ocr_json_2},
    ]

    doc = ScannedBookDocument(mock_repo, 1)
    lines = ["Translated 1", "Translated 2", "Translated 3"]
    consumed = await doc.set_text(lines)

    assert consumed == 3
    assert doc._merged_content is not None

    merged = doc._merged_content
    assert len(merged.elements) == 3
    assert merged.elements[0].translated_lines == ["Translated 1"]
    assert merged.elements[1].translated_lines == ["Translated 2"]
    assert merged.elements[2].translated_lines == ["Translated 3"]


async def test_set_text_skips_sources_without_ocr_json():
    mock_repo = MagicMock()

    ocr_json = json.dumps(
        [
            {
                "page_type": "content",
                "content": [
                    {
                        "type": "paragraph",
                        "text": "Original",
                        "continues_from_previous": False,
                        "continues_to_next": False,
                    }
                ],
            }
        ]
    )

    mock_repo.get_document_sources.return_value = [
        {"sequence_number": 0, "ocr_json": None},
        {"sequence_number": 1, "ocr_json": ocr_json},
    ]

    doc = ScannedBookDocument(mock_repo, 1)
    lines = ["Translated"]
    consumed = await doc.set_text(lines)

    assert consumed == 1
    assert doc._merged_content is not None

    merged = doc._merged_content
    assert len(merged.elements) == 1


def test_export_md_writes_markdown_correctly(mock_ocr_content):
    mock_repo = MagicMock()
    doc = ScannedBookDocument(mock_repo, 1, ocr_config=OCRConfig())
    doc._merged_content = mock_ocr_content

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "output.md"
        ScannedBookDocument.export_merged([doc], "md", output_path)

        assert output_path.exists()
        content = output_path.read_text()
        assert "First paragraph" in content


def test_export_md_creates_parent_directories(mock_ocr_content):
    mock_repo = MagicMock()
    doc = ScannedBookDocument(mock_repo, 1, ocr_config=OCRConfig())
    doc._merged_content = mock_ocr_content

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "subdir" / "nested" / "output.md"
        ScannedBookDocument.export_merged([doc], "md", output_path)

        assert output_path.exists()


def test_export_epub_calls_pandoc(mock_ocr_content):
    mock_repo = MagicMock()
    doc = ScannedBookDocument(mock_repo, 1, ocr_config=OCRConfig())
    doc._merged_content = mock_ocr_content

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "output.epub"

        with patch("context_aware_translation.utils.pandoc_export.pypandoc.convert_text") as mock_convert:
            ScannedBookDocument.export_merged([doc], "epub", output_path)

            mock_convert.assert_called_once()
            args, kwargs = mock_convert.call_args
            assert args[0]
            assert kwargs["to"] == "epub"
            assert kwargs["format"] == "md"
            assert kwargs["outputfile"] == str(output_path)


def test_export_pdf_calls_pandoc(mock_ocr_content):
    mock_repo = MagicMock()
    doc = ScannedBookDocument(mock_repo, 1)
    doc._merged_content = mock_ocr_content

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "output.pdf"

        with pytest.raises(ValueError, match="Scanned book documents only support"):
            ScannedBookDocument.export_merged([doc], "pdf", output_path)


def test_export_unsupported_format_raises_value_error(mock_ocr_content):
    mock_repo = MagicMock()
    doc = ScannedBookDocument(mock_repo, 1)
    doc._merged_content = mock_ocr_content

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "output.docx"

        with pytest.raises(ValueError, match="Scanned book documents only support"):
            ScannedBookDocument.export_merged([doc], "docx", output_path)


def test_export_without_set_text_raises_value_error():
    mock_repo = MagicMock()
    doc = ScannedBookDocument(mock_repo, 1)

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "output.epub"

        with pytest.raises(ValueError, match="no translated content"):
            ScannedBookDocument.export_merged([doc], "epub", output_path)


def test_export_preserve_structure_raises_not_implemented_error():
    mock_repo = MagicMock()
    doc = ScannedBookDocument(mock_repo, 1)

    with tempfile.TemporaryDirectory() as tmpdir:
        output_folder = Path(tmpdir)

        with pytest.raises(
            NotImplementedError, match="Scanned book documents do not support structure-preserving export"
        ):
            doc.export_preserve_structure(output_folder)


def test_get_text_merges_cross_page_paragraphs():
    mock_repo = MagicMock()

    ocr_json_1 = json.dumps(
        [
            {
                "page_type": "content",
                "content": [
                    {
                        "type": "paragraph",
                        "text": "This paragraph starts on page 1 and",
                        "continues_from_previous": False,
                        "continues_to_next": True,
                    }
                ],
            }
        ]
    )

    ocr_json_2 = json.dumps(
        [
            {
                "page_type": "content",
                "content": [
                    {
                        "type": "paragraph",
                        "text": " continues on page 2.",
                        "continues_from_previous": True,
                        "continues_to_next": False,
                    }
                ],
            }
        ]
    )

    mock_repo.get_document_sources.return_value = [
        {"sequence_number": 0, "ocr_json": ocr_json_1},
        {"sequence_number": 1, "ocr_json": ocr_json_2},
    ]

    doc = ScannedBookDocument(mock_repo, 1)
    result = doc.get_text()

    assert result == "This paragraph starts on page 1 and continues on page 2."


def test_get_text_skips_blank_and_toc_pages():
    mock_repo = MagicMock()

    blank_json = json.dumps([{"page_type": "blank", "content": []}])
    toc_json = json.dumps(
        [
            {
                "page_type": "toc",
                "content": [
                    {
                        "type": "paragraph",
                        "text": "TOC entry",
                        "continues_from_previous": False,
                        "continues_to_next": False,
                    }
                ],
            }
        ]
    )
    content_json = json.dumps(
        [
            {
                "page_type": "content",
                "content": [
                    {
                        "type": "paragraph",
                        "text": "Actual content",
                        "continues_from_previous": False,
                        "continues_to_next": False,
                    }
                ],
            }
        ]
    )

    mock_repo.get_document_sources.return_value = [
        {"sequence_number": 0, "ocr_json": blank_json},
        {"sequence_number": 1, "ocr_json": toc_json},
        {"sequence_number": 2, "ocr_json": content_json},
    ]

    doc = ScannedBookDocument(mock_repo, 1)
    result = doc.get_text()

    assert result == "Actual content"


class TestCanImport:
    """Tests for ScannedBookDocument.can_import() classmethod."""

    def test_single_image_file(self, tmp_path):
        """Single image file should return True."""
        image_file = tmp_path / "page.png"
        image_file.write_bytes(b"fake image data")

        assert ScannedBookDocument.can_import(image_file) is True

    def test_folder_of_images(self, tmp_path):
        """Folder containing only image files should return True."""
        (tmp_path / "page1.png").write_bytes(b"fake image 1")
        (tmp_path / "page2.jpg").write_bytes(b"fake image 2")
        (tmp_path / "page3.jpeg").write_bytes(b"fake image 3")

        assert ScannedBookDocument.can_import(tmp_path) is True

    def test_rejects_text_file(self, tmp_path):
        """Text file should return False."""
        text_file = tmp_path / "document.txt"
        text_file.write_text("Some text content")

        assert ScannedBookDocument.can_import(text_file) is False

    def test_rejects_folder_with_mixed_files(self, tmp_path):
        """Folder with both images and text files should return False."""
        (tmp_path / "page1.png").write_bytes(b"fake image")
        (tmp_path / "notes.txt").write_text("Some notes")

        assert ScannedBookDocument.can_import(tmp_path) is False

    def test_rejects_pdf(self, tmp_path):
        """PDF file should return False (handled by PDFDocument)."""
        pdf_file = tmp_path / "document.pdf"
        pdf_file.write_bytes(b"fake pdf data")

        assert ScannedBookDocument.can_import(pdf_file) is False

    def test_rejects_nonexistent_path(self, tmp_path):
        """Nonexistent path should return False."""
        nonexistent = tmp_path / "does_not_exist.png"

        assert ScannedBookDocument.can_import(nonexistent) is False


class TestDoImport:
    """Tests for ScannedBookDocument.do_import() classmethod."""

    def test_imports_single_image(self, tmp_path, temp_config):
        """Import single image file."""
        from context_aware_translation.storage.book_db import SQLiteBookDB
        from context_aware_translation.storage.document_repository import DocumentRepository

        image_file = tmp_path / "page.png"
        image_file.write_bytes(_png_bytes((120, 40, 90)))

        db = SQLiteBookDB(temp_config.sqlite_path)
        repo = DocumentRepository(db)

        ScannedBookDocument.do_import(repo, image_file)

        doc_row = repo.get_document_row()
        assert doc_row is not None
        assert doc_row["document_type"] == "scanned_book"

        sources = repo.get_document_sources(doc_row["document_id"])
        assert len(sources) == 1
        assert sources[0]["source_type"] == "image"
        assert sources[0]["sequence_number"] == 0

    def test_imports_folder_of_images(self, tmp_path, temp_config):
        """Import folder containing multiple image files."""
        from context_aware_translation.storage.book_db import SQLiteBookDB
        from context_aware_translation.storage.document_repository import DocumentRepository

        (tmp_path / "page1.png").write_bytes(_png_bytes((1, 2, 3)))
        (tmp_path / "page2.jpg").write_bytes(_jpeg_bytes((4, 5, 6)))
        (tmp_path / "page3.jpeg").write_bytes(_jpeg_bytes((7, 8, 9)))

        db = SQLiteBookDB(temp_config.sqlite_path)
        repo = DocumentRepository(db)

        ScannedBookDocument.do_import(repo, tmp_path)

        doc_row = repo.get_document_row()
        assert doc_row is not None

        sources = repo.get_document_sources(doc_row["document_id"])
        assert len(sources) == 3
        assert all(s["source_type"] == "image" for s in sources)

    def test_preserves_alphabetical_order(self, tmp_path, temp_config):
        """Sources should be inserted in alphabetical order."""
        from context_aware_translation.storage.book_db import SQLiteBookDB
        from context_aware_translation.storage.document_repository import DocumentRepository

        c_bytes = _png_bytes((200, 1, 1))
        a_bytes = _png_bytes((1, 200, 1))
        b_bytes = _png_bytes((1, 1, 200))
        (tmp_path / "c.png").write_bytes(c_bytes)
        (tmp_path / "a.png").write_bytes(a_bytes)
        (tmp_path / "b.png").write_bytes(b_bytes)

        db = SQLiteBookDB(temp_config.sqlite_path)
        repo = DocumentRepository(db)

        ScannedBookDocument.do_import(repo, tmp_path)

        doc_row = repo.get_document_row()
        assert doc_row is not None
        sources = repo.get_document_sources(doc_row["document_id"])

        assert len(sources) == 3
        assert sources[0]["sequence_number"] == 0
        assert sources[1]["sequence_number"] == 1
        assert sources[2]["sequence_number"] == 2
        assert sources[0]["binary_content"] == a_bytes
        assert sources[1]["binary_content"] == b_bytes
        assert sources[2]["binary_content"] == c_bytes

    def test_rollback_on_error(self, tmp_path, temp_config):
        """Transaction should rollback on error."""
        from unittest.mock import patch

        from context_aware_translation.storage.book_db import SQLiteBookDB
        from context_aware_translation.storage.document_repository import DocumentRepository

        image_file = tmp_path / "page.png"
        image_file.write_bytes(_png_bytes((9, 8, 7)))

        db = SQLiteBookDB(temp_config.sqlite_path)
        repo = DocumentRepository(db)

        with (
            patch.object(repo, "insert_document_source", side_effect=RuntimeError("Simulated error")),
            pytest.raises(RuntimeError, match="Simulated error"),
        ):
            ScannedBookDocument.do_import(repo, image_file)

        doc_row = repo.get_document_row()
        assert doc_row is None

    def test_stores_binary_content(self, tmp_path, temp_config):
        """Binary content and mime_type should be stored correctly."""
        from context_aware_translation.storage.book_db import SQLiteBookDB
        from context_aware_translation.storage.document_repository import DocumentRepository

        image_file = tmp_path / "page.png"
        test_data = _png_bytes((99, 88, 77))
        image_file.write_bytes(test_data)

        db = SQLiteBookDB(temp_config.sqlite_path)
        repo = DocumentRepository(db)

        ScannedBookDocument.do_import(repo, image_file)

        doc_row = repo.get_document_row()
        assert doc_row is not None
        sources = repo.get_document_sources(doc_row["document_id"])

        assert len(sources) == 1
        assert sources[0]["binary_content"] == test_data
        assert sources[0]["mime_type"] in ("image/png", "application/octet-stream")

    def test_rejects_invalid_image_bytes(self, tmp_path, temp_config):
        """Import should fail fast when image bytes are not decodable."""
        from context_aware_translation.storage.book_db import SQLiteBookDB
        from context_aware_translation.storage.document_repository import DocumentRepository

        image_file = tmp_path / "broken.png"
        image_file.write_bytes(b"not-a-real-image")

        db = SQLiteBookDB(temp_config.sqlite_path)
        repo = DocumentRepository(db)

        with pytest.raises(ValueError, match="Invalid image data"):
            ScannedBookDocument.do_import(repo, image_file)

        assert repo.get_document_row() is None


def test_supported_export_formats():
    mock_repo = MagicMock()
    doc = ScannedBookDocument(mock_repo, 1)
    assert doc.supported_export_formats == ("epub", "md")


def test_can_export_epub_returns_true():
    mock_repo = MagicMock()
    doc = ScannedBookDocument(mock_repo, 1)
    assert doc.can_export("epub") is True


def test_can_export_md_returns_true():
    mock_repo = MagicMock()
    doc = ScannedBookDocument(mock_repo, 1)
    assert doc.can_export("md") is True


def test_can_export_txt_returns_false():
    mock_repo = MagicMock()
    doc = ScannedBookDocument(mock_repo, 1)
    assert doc.can_export("txt") is False


def test_export_unsupported_format_error_message(mock_ocr_content):
    mock_repo = MagicMock()
    doc = ScannedBookDocument(mock_repo, 1)
    doc._merged_content = mock_ocr_content

    with pytest.raises(ValueError) as exc_info:
        ScannedBookDocument.export_merged([doc], "txt", Path("/tmp/out.txt"))

    assert "epub" in str(exc_info.value)
    assert "md" in str(exc_info.value)
