from __future__ import annotations

import io
import json
import re
from pathlib import Path
from unittest.mock import MagicMock

from PIL import Image

from context_aware_translation.config import OCRConfig
from context_aware_translation.documents.content.ocr_items import BoundingBox, ImageItem, RenderContext
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


def _extract_markdown_image_path(markdown: str) -> Path:
    match = re.search(r"\]\((.+)\)$", markdown)
    assert match is not None
    return Path(match.group(1))


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


def test_image_item_markdown_prefers_reembedded_bytes_by_default(tmp_path: Path) -> None:
    original_png = _make_png_bytes()
    replacement_png = Image.new("RGB", (10, 10), color=(220, 30, 30))
    replacement_buffer = io.BytesIO()
    replacement_png.save(replacement_buffer, format="PNG")

    item = ImageItem(
        bbox=BoundingBox(x=0.0, y=0.0, width=1.0, height=1.0),
        caption="CAPTION",
        translated_lines=["CAPTION_T"],
        image_bytes=original_png,
        reembedded_image_bytes=replacement_buffer.getvalue(),
    )

    markdown = item.to_markdown(
        RenderContext(
            image_dir=tmp_path,
            insert_new_page_before_chapter=False,
        )
    )
    exported_image = Image.open(_extract_markdown_image_path(markdown)).convert("RGB")

    assert exported_image.getpixel((0, 0)) == (220, 30, 30)


def test_image_item_markdown_can_keep_original_bytes(tmp_path: Path) -> None:
    original_png = Image.new("RGB", (10, 10), color=(10, 20, 30))
    original_buffer = io.BytesIO()
    original_png.save(original_buffer, format="PNG")

    replacement_png = Image.new("RGB", (10, 10), color=(220, 30, 30))
    replacement_buffer = io.BytesIO()
    replacement_png.save(replacement_buffer, format="PNG")

    item = ImageItem(
        bbox=BoundingBox(x=0.0, y=0.0, width=1.0, height=1.0),
        caption="CAPTION",
        translated_lines=["CAPTION_T"],
        image_bytes=original_buffer.getvalue(),
        reembedded_image_bytes=replacement_buffer.getvalue(),
    )

    markdown = item.to_markdown(
        RenderContext(
            image_dir=tmp_path,
            insert_new_page_before_chapter=False,
            use_original_images=True,
        )
    )
    exported_image = Image.open(_extract_markdown_image_path(markdown)).convert("RGB")

    assert exported_image.getpixel((0, 0)) == (10, 20, 30)
