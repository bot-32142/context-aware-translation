from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock

from PIL import Image

from context_aware_translation.config import OCRConfig
from context_aware_translation.documents.pdf import PDFDocument
from context_aware_translation.documents.scanned_book import ScannedBookDocument


def _make_png_bytes() -> bytes:
    img = Image.new("RGB", (10, 10), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_single_image_ocr_json() -> str:
    return json.dumps(
        [
            {
                "page_type": "content",
                "content": [
                    {
                        "type": "image",
                        "text": None,
                        "bbox": {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8},
                        "embedded_text": "EMBEDDED",
                        "caption": "CAPTION",
                        "continues_from_previous": False,
                        "continues_to_next": False,
                    }
                ],
            }
        ]
    )


async def test_pdf_document_get_text_and_export_caption_only(tmp_path: Path) -> None:
    png_bytes = _make_png_bytes()
    ocr_json = _make_single_image_ocr_json()

    mock_repo = MagicMock()
    mock_repo.get_document_sources.return_value = [
        {"sequence_number": 0, "ocr_json": ocr_json, "binary_content": png_bytes}
    ]

    doc = PDFDocument(mock_repo, 1, ocr_config=OCRConfig())

    assert doc.get_text() == "EMBEDDED\nCAPTION"

    consumed = await doc.set_text(["EMBEDDED_T", "CAPTION_T"])
    assert consumed == 2

    out_path = tmp_path / "out.md"
    type(doc).export_merged([doc], "md", out_path)
    exported = out_path.read_text()
    # Caption appears in markdown output (escaping delegated to LLM)
    assert "CAPTION_T" in exported
    assert "EMBEDDED_T" not in exported


async def test_scanned_book_document_get_text_and_export_caption_only(tmp_path: Path) -> None:
    png_bytes = _make_png_bytes()
    ocr_json = _make_single_image_ocr_json()

    mock_repo = MagicMock()
    mock_repo.get_document_sources.return_value = [
        {"sequence_number": 0, "ocr_json": ocr_json, "binary_content": png_bytes}
    ]

    doc = ScannedBookDocument(mock_repo, 1, ocr_config=OCRConfig())

    assert doc.get_text() == "EMBEDDED\nCAPTION"

    consumed = await doc.set_text(["EMBEDDED_T", "CAPTION_T"])
    assert consumed == 2

    out_path = tmp_path / "out.md"
    type(doc).export_merged([doc], "md", out_path)
    exported = out_path.read_text()
    # Caption appears in markdown output (escaping delegated to LLM)
    assert "CAPTION_T" in exported
    assert "EMBEDDED_T" not in exported
