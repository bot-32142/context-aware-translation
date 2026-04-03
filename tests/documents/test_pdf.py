from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pikepdf
import pypdfium2
import pytest
from PIL import Image

from context_aware_translation.config import OCRConfig
from context_aware_translation.core.progress import ProgressUpdate, WorkflowStep
from context_aware_translation.documents.content.ocr_content import MergedOCRContent
from context_aware_translation.documents.pdf import PDFDocument
from context_aware_translation.utils.image_utils import compress_image_for_ocr


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

    with (
        patch("context_aware_translation.documents.pdf.ocr_images", new_callable=AsyncMock) as mock_ocr,
        patch("context_aware_translation.documents.pdf.compress_image_for_ocr", side_effect=lambda x, _max_dpi=300: x),
    ):
        mock_ocr.side_effect = mock_ocr_side_effect

        doc = PDFDocument(mock_repo, 1, mock_ocr_config)
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
        doc = PDFDocument(mock_repo, 1, mock_ocr_config)
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

    with patch("context_aware_translation.documents.pdf.ocr_images", new_callable=AsyncMock) as mock_ocr:
        doc = PDFDocument(mock_repo, 1, mock_ocr_config)
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

    doc = PDFDocument(mock_repo, 1)
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

    doc = PDFDocument(mock_repo, 1)
    result = doc.get_text()

    assert result == "Has OCR"


def test_is_text_added_returns_false_when_any_source_not_added():
    mock_repo = MagicMock()
    mock_repo.get_document_sources.return_value = [
        {"is_text_added": 1},
        {"is_text_added": 0},
        {"is_text_added": 1},
    ]

    doc = PDFDocument(mock_repo, 1)
    result = doc.is_text_added()

    assert result is False


def test_is_text_added_returns_true_when_all_sources_added():
    mock_repo = MagicMock()
    mock_repo.get_document_sources.return_value = [
        {"is_text_added": 1},
        {"is_text_added": 1},
        {"is_text_added": 1},
    ]

    doc = PDFDocument(mock_repo, 1)
    result = doc.is_text_added()

    assert result is True


def test_is_text_added_returns_true_when_no_sources():
    mock_repo = MagicMock()
    mock_repo.get_document_sources.return_value = []

    doc = PDFDocument(mock_repo, 1)
    result = doc.is_text_added()

    assert result is True


def test_mark_text_added_calls_db_method():
    mock_repo = MagicMock()
    doc = PDFDocument(mock_repo, 1)

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

    doc = PDFDocument(mock_repo, 1)
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

    doc = PDFDocument(mock_repo, 1)
    lines = ["Translated"]
    consumed = await doc.set_text(lines)

    assert consumed == 1
    assert doc._merged_content is not None

    merged = doc._merged_content
    assert len(merged.elements) == 1


def test_export_md_writes_markdown_correctly(mock_ocr_content):
    mock_repo = MagicMock()
    doc = PDFDocument(mock_repo, 1, ocr_config=OCRConfig())
    doc._merged_content = mock_ocr_content

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "output.md"
        PDFDocument.export_merged([doc], "md", output_path)

        assert output_path.exists()
        content = output_path.read_text()
        assert "First paragraph" in content


def test_export_md_creates_parent_directories(mock_ocr_content):
    mock_repo = MagicMock()
    doc = PDFDocument(mock_repo, 1, ocr_config=OCRConfig())
    doc._merged_content = mock_ocr_content

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "subdir" / "nested" / "output.md"
        PDFDocument.export_merged([doc], "md", output_path)

        assert output_path.exists()


def test_export_epub_calls_pandoc(mock_ocr_content):
    mock_repo = MagicMock()
    doc = PDFDocument(mock_repo, 1, ocr_config=OCRConfig())
    doc._merged_content = mock_ocr_content

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "output.epub"

        with patch("context_aware_translation.utils.pandoc_export.pypandoc.convert_text") as mock_convert:
            PDFDocument.export_merged([doc], "epub", output_path)

            mock_convert.assert_called_once()
            args, kwargs = mock_convert.call_args
            assert args[0]
            assert kwargs["to"] == "epub"
            assert kwargs["format"] == "md"
            assert kwargs["outputfile"] == str(output_path)


def test_export_pdf_calls_pandoc(mock_ocr_content):
    mock_repo = MagicMock()
    doc = PDFDocument(mock_repo, 1)
    doc._merged_content = mock_ocr_content

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "output.pdf"

        with pytest.raises(ValueError, match="PDF documents only support"):
            PDFDocument.export_merged([doc], "pdf", output_path)


def test_export_unsupported_format_raises_value_error(mock_ocr_content):
    mock_repo = MagicMock()
    doc = PDFDocument(mock_repo, 1)
    doc._merged_content = mock_ocr_content

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "output.docx"

        with pytest.raises(ValueError, match="PDF documents only support"):
            PDFDocument.export_merged([doc], "docx", output_path)


def test_export_without_set_text_raises_value_error():
    mock_repo = MagicMock()
    doc = PDFDocument(mock_repo, 1)

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "output.epub"

        with pytest.raises(ValueError, match="no translated content"):
            PDFDocument.export_merged([doc], "epub", output_path)


def test_export_preserve_structure_raises_not_implemented_error():
    mock_repo = MagicMock()
    doc = PDFDocument(mock_repo, 1)

    with tempfile.TemporaryDirectory() as tmpdir:
        output_folder = Path(tmpdir)

        with pytest.raises(NotImplementedError, match="PDF documents do not support structure-preserving export"):
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

    doc = PDFDocument(mock_repo, 1)
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

    doc = PDFDocument(mock_repo, 1)
    result = doc.get_text()

    assert result == "Actual content"


class TestCanImport:
    """Test PDFDocument.can_import() classmethod."""

    def test_single_pdf_file(self, tmp_path):
        """Returns True for a single .pdf file."""
        pdf_file = tmp_path / "document.pdf"
        pdf_file.write_text("fake pdf content")

        assert PDFDocument.can_import(pdf_file) is True

    def test_rejects_folder_with_pdf(self, tmp_path):
        """Returns False for a folder containing a PDF."""
        pdf_file = tmp_path / "document.pdf"
        pdf_file.write_text("fake pdf content")

        assert PDFDocument.can_import(tmp_path) is False

    def test_rejects_text_file(self, tmp_path):
        """Returns False for a text file."""
        text_file = tmp_path / "document.txt"
        text_file.write_text("text content")

        assert PDFDocument.can_import(text_file) is False

    def test_rejects_image_file(self, tmp_path):
        """Returns False for an image file."""
        image_file = tmp_path / "image.png"
        image_file.write_bytes(b"fake image data")

        assert PDFDocument.can_import(image_file) is False

    def test_rejects_nonexistent_path(self, tmp_path):
        """Returns False for a nonexistent path."""
        nonexistent = tmp_path / "does_not_exist.pdf"

        assert PDFDocument.can_import(nonexistent) is False


def _create_blank_pdf(pdf_path: Path, num_pages: int = 1) -> None:
    """Create a blank PDF with the specified number of pages."""
    pdf = pikepdf.Pdf.new()
    for _ in range(num_pages):
        pdf.add_blank_page(page_size=(612, 792))  # Letter size
    pdf.save(str(pdf_path))


class TestDoImport:
    """Test PDFDocument.do_import() classmethod."""

    def test_imports_pdf_and_creates_document(self, tmp_path, temp_config):
        """Imports PDF file and creates document with type='pdf'."""
        from context_aware_translation.storage.repositories.document_repository import DocumentRepository
        from context_aware_translation.storage.schema.book_db import SQLiteBookDB

        pdf_path = tmp_path / "test.pdf"
        db = SQLiteBookDB(temp_config.sqlite_path)
        repo = DocumentRepository(db)

        # Create a simple valid PDF
        _create_blank_pdf(pdf_path, 1)

        PDFDocument.do_import(repo, pdf_path)

        doc_row = repo.get_document_row()
        assert doc_row is not None
        assert doc_row["document_type"] == "pdf"

    def test_extracts_pages_as_image_sources(self, tmp_path, temp_config):
        """Extracts PDF pages and stores as image sources."""
        from context_aware_translation.storage.repositories.document_repository import DocumentRepository
        from context_aware_translation.storage.schema.book_db import SQLiteBookDB

        pdf_path = tmp_path / "test.pdf"
        db = SQLiteBookDB(temp_config.sqlite_path)
        repo = DocumentRepository(db)

        # Create a 2-page PDF
        _create_blank_pdf(pdf_path, 2)

        PDFDocument.do_import(repo, pdf_path)

        doc_row = repo.get_document_row()
        document_id = doc_row["document_id"]
        sources = repo.get_document_sources(document_id)

        assert len(sources) == 2
        assert sources[0]["source_type"] == "image"
        assert sources[0]["sequence_number"] == 0
        assert sources[0]["mime_type"] == "image/png"
        assert sources[1]["source_type"] == "image"
        assert sources[1]["sequence_number"] == 1
        assert sources[1]["mime_type"] == "image/png"

    def test_rollback_on_error(self, tmp_path, temp_config):
        """Rolls back transaction if extraction fails."""
        from context_aware_translation.storage.repositories.document_repository import DocumentRepository
        from context_aware_translation.storage.schema.book_db import SQLiteBookDB

        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"invalid pdf bytes")
        db = SQLiteBookDB(temp_config.sqlite_path)
        repo = DocumentRepository(db)

        with pytest.raises(pypdfium2.PdfiumError):
            PDFDocument.do_import(repo, pdf_path)

        doc_row = repo.get_document_row()
        assert doc_row is None

    def test_stores_binary_content(self, tmp_path, temp_config):
        """Stores PNG binary content for each page."""
        from context_aware_translation.storage.repositories.document_repository import DocumentRepository
        from context_aware_translation.storage.schema.book_db import SQLiteBookDB

        pdf_path = tmp_path / "test.pdf"
        db = SQLiteBookDB(temp_config.sqlite_path)
        repo = DocumentRepository(db)

        # Create a simple valid PDF
        _create_blank_pdf(pdf_path, 1)

        PDFDocument.do_import(repo, pdf_path)

        doc_row = repo.get_document_row()
        document_id = doc_row["document_id"]
        sources = repo.get_document_sources(document_id)

        # Should have PNG binary content
        assert sources[0]["binary_content"] is not None
        assert len(sources[0]["binary_content"]) > 0
        # Verify it's a valid PNG (starts with PNG magic bytes)
        assert sources[0]["binary_content"][:8] == b"\x89PNG\r\n\x1a\n"

    def test_reports_progress_during_import(self, tmp_path, temp_config):
        """Reports import progress from 0 to total pages."""
        from context_aware_translation.storage.repositories.document_repository import DocumentRepository
        from context_aware_translation.storage.schema.book_db import SQLiteBookDB

        pdf_path = tmp_path / "test.pdf"
        db = SQLiteBookDB(temp_config.sqlite_path)
        repo = DocumentRepository(db)

        _create_blank_pdf(pdf_path, 2)
        updates: list[ProgressUpdate] = []

        PDFDocument.do_import(repo, pdf_path, progress_callback=updates.append)

        assert updates
        assert updates[0].step == WorkflowStep.EXPORT
        assert updates[0].current == 0
        assert updates[0].total == 2
        assert updates[-1].step == WorkflowStep.EXPORT
        assert updates[-1].current == 2
        assert updates[-1].total == 2


def test_supported_export_formats():
    mock_repo = MagicMock()
    doc = PDFDocument(mock_repo, 1)
    assert doc.supported_export_formats == ("epub", "md", "txt")


def test_can_export_epub_returns_true():
    mock_repo = MagicMock()
    doc = PDFDocument(mock_repo, 1)
    assert doc.can_export("epub") is True


def test_can_export_md_returns_true():
    mock_repo = MagicMock()
    doc = PDFDocument(mock_repo, 1)
    assert doc.can_export("md") is True


def test_can_export_txt_returns_true():
    mock_repo = MagicMock()
    doc = PDFDocument(mock_repo, 1)
    assert doc.can_export("txt") is True


def test_can_export_pdf_returns_false():
    mock_repo = MagicMock()
    doc = PDFDocument(mock_repo, 1)
    assert doc.can_export("pdf") is False


def test_export_unsupported_format_error_message(mock_ocr_content):
    mock_repo = MagicMock()
    doc = PDFDocument(mock_repo, 1)
    doc._merged_content = mock_ocr_content

    with pytest.raises(ValueError) as exc_info:
        PDFDocument.export_merged([doc], "pdf", Path("/tmp/out.pdf"))

    assert "epub" in str(exc_info.value)
    assert "md" in str(exc_info.value)
    assert "txt" in str(exc_info.value)
    assert "pdf" in str(exc_info.value)


def test_export_txt_calls_pandoc_plain(mock_ocr_content):
    mock_repo = MagicMock()
    doc = PDFDocument(mock_repo, 1, ocr_config=OCRConfig())
    doc._merged_content = mock_ocr_content

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "output.txt"

        with patch("context_aware_translation.utils.pandoc_export.pypandoc.convert_text") as mock_convert:
            PDFDocument.export_merged([doc], "txt", output_path)

            mock_convert.assert_called_once()
            args, kwargs = mock_convert.call_args
            assert args[0]
            assert kwargs["to"] == "plain"
            assert kwargs["format"] == "md"
            assert kwargs["outputfile"] == str(output_path)


class TestPageImageExtraction:
    """Integration tests for page image extraction with real PDFs."""

    def test_vector_page_uses_vector_dpi(self, tmp_path):
        """Pure vector page (text only) should use vector_dpi."""
        # Create a PDF with only a blank page (no images)
        pdf_path = tmp_path / "vector.pdf"
        _create_blank_pdf(pdf_path, 1)

        # Read PDF bytes and extract
        pdf_bytes = pdf_path.read_bytes()
        pdfium_doc = pypdfium2.PdfDocument(pdf_bytes)
        pikepdf_doc = pikepdf.open(io.BytesIO(pdf_bytes))

        page = pdfium_doc[0]
        page_width_pts, page_height_pts = page.get_size()

        # Should use vector_dpi (150) since no images
        image_bytes, mime_type = PDFDocument._extract_page_image_for_storage(
            pdf_bytes, pikepdf_doc, 0, page_width_pts, page_height_pts, vector_dpi=150
        )

        pdfium_doc.close()
        pikepdf_doc.close()

        assert mime_type == "image/png"
        assert len(image_bytes) > 0

        # Verify dimensions match 150 DPI (Letter = 8.5x11 inches)
        img = Image.open(io.BytesIO(image_bytes))
        # At 150 DPI: 8.5*150=1275, 11*150=1650
        assert abs(img.width - 1275) < 10  # Allow small rounding
        assert abs(img.height - 1650) < 10

    def test_compress_image_for_ocr(self):
        """compress_image_for_ocr should downscale large images to the specified max_dpi."""
        # Create a high-res image (600 DPI equivalent for Letter page)
        # 8.5 x 11 inches at 600 DPI = 5100 x 6600 pixels
        high_res_width, high_res_height = 5100, 6600
        high_res_img = Image.new("RGB", (high_res_width, high_res_height), color=(200, 200, 255))
        high_res_buffer = io.BytesIO()
        high_res_img.save(high_res_buffer, format="PNG")
        high_res_bytes = high_res_buffer.getvalue()

        # Compress to 300 DPI
        compressed_bytes = compress_image_for_ocr(high_res_bytes, max_dpi=300)

        # Verify compression
        compressed_img = Image.open(io.BytesIO(compressed_bytes))

        # At 300 DPI: 8.5*300=2550, 11*300=3300
        assert abs(compressed_img.width - 2550) < 50  # Allow some tolerance
        assert abs(compressed_img.height - 3300) < 50

        # Verify smaller file size (compressed should be much smaller)
        assert len(compressed_bytes) < len(high_res_bytes)

    def test_compress_image_for_ocr_skips_small_images(self):
        """compress_image_for_ocr should not resize images already at or below target DPI."""
        # Create a low-res image (150 DPI equivalent for Letter page)
        # 8.5 x 11 inches at 150 DPI = 1275 x 1650 pixels
        low_res_width, low_res_height = 1275, 1650
        low_res_img = Image.new("RGB", (low_res_width, low_res_height), color=(255, 200, 200))
        low_res_buffer = io.BytesIO()
        low_res_img.save(low_res_buffer, format="PNG")
        low_res_bytes = low_res_buffer.getvalue()

        # Compress to 300 DPI (should be a no-op since already below)
        result_bytes = compress_image_for_ocr(low_res_bytes, max_dpi=300)

        # Should return original bytes unchanged
        assert result_bytes == low_res_bytes

    def test_estimate_image_dpi(self):
        """Test _estimate_image_dpi calculates DPI correctly."""
        # Image at 600 DPI on Letter page
        # 8.5 x 11 inches at 600 DPI = 5100 x 6600 pixels
        # Page in points: 612 x 792 (Letter at 72 DPI)
        dpi = PDFDocument._estimate_image_dpi(5100, 6600, 612, 792)
        # (5100 / 612) * 72 = 600
        assert abs(dpi - 600) < 5

    def test_estimate_image_dpi_returns_default_for_zero_page_size(self):
        """Test _estimate_image_dpi returns default when page size is zero."""
        dpi = PDFDocument._estimate_image_dpi(1000, 1000, 0, 0)
        assert dpi == PDFDocument.DEFAULT_VECTOR_DPI
