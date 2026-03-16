"""Tests for EPUBDocument class."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from context_aware_translation.config import OCRConfig
from context_aware_translation.documents.epub import METADATA_PATH, EPUBDocument
from context_aware_translation.documents.epub_container import (
    EpubBook,
    EpubItem,
    EpubMetadata,
    TocEntry,
    read_epub,
    write_epub,
)

# =========================================================================
# Fixtures
# =========================================================================


def _make_epub_file(
    tmp_path: Path,
    chapters: list[tuple[str, str]] | None = None,
    images: list[tuple[str, bytes, str]] | None = None,
    css: str | None = None,
    title: str = "Test Book",
    author: str = "Test Author",
    language: str = "en",
) -> Path:
    """Create an EPUB file on disk and return its path.

    Args:
        tmp_path: Directory to write the EPUB file into.
        chapters: List of (filename, xhtml_content) tuples for chapters.
        images: List of (filename, bytes, media_type) tuples for images.
        css: Optional CSS content.
        title: Book title.
        author: Book author.
        language: Book language.

    Returns:
        Path to the created EPUB file.
    """
    if chapters is None:
        chapters = [
            (
                "chapter1.xhtml",
                '<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Chapter 1</h1><p>Hello world.</p></body></html>',
            ),
        ]

    spine_items = [
        EpubItem(
            file_name=f"OEBPS/{filename}",
            media_type="application/xhtml+xml",
            content=content.encode("utf-8"),
        )
        for filename, content in chapters
    ]

    resources: list[EpubItem] = []

    if images:
        for filename, data, media_type in images:
            resources.append(EpubItem(file_name=f"OEBPS/{filename}", media_type=media_type, content=data))

    if css:
        resources.append(
            EpubItem(
                file_name="OEBPS/style.css",
                media_type="text/css",
                content=css.encode("utf-8"),
            )
        )

    toc = [TocEntry(title=filename, href=filename) for filename, _ in chapters]

    book = EpubBook(
        metadata=EpubMetadata(
            title=title,
            authors=[author],
            language=language,
            identifier="test-id-123",
        ),
        spine_items=spine_items,
        resources=resources,
        toc=toc,
    )

    dest = tmp_path / "test.epub"
    write_epub(dest, book)
    return dest


def _make_epub_with_nav_sections(tmp_path: Path) -> Path:
    """Create an EPUB that includes page-list and landmarks nav labels."""
    epub_path = tmp_path / "nav_sections.epub"

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Nav Labels</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="navdoc" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ncxdoc" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
  </manifest>
  <spine toc="ncxdoc">
    <itemref idref="ch1"/>
  </spine>
</package>"""

    nav_xhtml = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
  <body>
    <nav epub:type="toc">
      <ol><li><a href="ch1.xhtml">Chapter 1</a></li></ol>
    </nav>
    <nav epub:type="page-list">
      <ol><li><a href="ch1.xhtml#p1">Page i</a></li></ol>
    </nav>
    <nav epub:type="landmarks">
      <ol><li><a href="ch1.xhtml#cover" epub:type="cover">Cover</a></li></ol>
    </nav>
  </body>
</html>"""

    ncx_xml = """<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head></head>
  <docTitle><text>Nav Labels</text></docTitle>
  <navMap>
    <navPoint id="navPoint-1" playOrder="1">
      <navLabel><text>Chapter 1</text></navLabel>
      <content src="ch1.xhtml"/>
    </navPoint>
  </navMap>
</ncx>"""

    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        zf.writestr("OEBPS/ch1.xhtml", "<html><body><p>Hello</p></body></html>")
        zf.writestr("OEBPS/nav.xhtml", nav_xhtml)
        zf.writestr("OEBPS/toc.ncx", ncx_xml)
    return epub_path


def _make_epub_with_inline_toc_nav_label(tmp_path: Path) -> Path:
    """Create an EPUB with inline markup inside TOC nav labels."""
    epub_path = tmp_path / "nav_inline_toc.epub"

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Inline TOC Label</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="navdoc" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ncxdoc" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
  </manifest>
  <spine toc="ncxdoc">
    <itemref idref="ch1"/>
  </spine>
</package>"""

    nav_xhtml = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
  <body>
    <nav epub:type="toc">
      <ol><li><a href="ch1.xhtml"><em>Chapter</em> 1</a></li></ol>
    </nav>
  </body>
</html>"""

    ncx_xml = """<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head></head>
  <docTitle><text>Inline TOC Label</text></docTitle>
  <navMap>
    <navPoint id="navPoint-1" playOrder="1">
      <navLabel><text>Chapter 1</text></navLabel>
      <content src="ch1.xhtml"/>
    </navPoint>
  </navMap>
</ncx>"""

    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        zf.writestr("OEBPS/ch1.xhtml", "<html><body><p>Hello</p></body></html>")
        zf.writestr("OEBPS/nav.xhtml", nav_xhtml)
        zf.writestr("OEBPS/toc.ncx", ncx_xml)
    return epub_path


def _setup_repo(tmp_path: Path):
    """Create a DocumentRepository backed by a temporary SQLite DB."""
    from context_aware_translation.storage.repositories.document_repository import DocumentRepository
    from context_aware_translation.storage.schema.book_db import SQLiteBookDB

    db = SQLiteBookDB(tmp_path / "book.db")
    return DocumentRepository(db)


def _png_bytes(color: tuple[int, int, int], size: tuple[int, int] = (4, 4)) -> bytes:
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# =========================================================================
# Tests: can_import
# =========================================================================


class TestCanImport:
    def test_can_import_epub_file(self, tmp_path: Path):
        epub_path = _make_epub_file(tmp_path)
        assert EPUBDocument.can_import(epub_path) is True

    def test_can_import_non_epub(self, tmp_path: Path):
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("hello")
        assert EPUBDocument.can_import(txt_file) is False

        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")
        assert EPUBDocument.can_import(pdf_file) is False

    def test_can_import_folder(self, tmp_path: Path):
        folder = tmp_path / "folder"
        folder.mkdir()
        assert EPUBDocument.can_import(folder) is False

    def test_can_import_nonexistent(self, tmp_path: Path):
        assert EPUBDocument.can_import(tmp_path / "nonexistent.epub") is False


# =========================================================================
# Tests: do_import
# =========================================================================


class TestDoImport:
    def test_import_stores_chapters(self, tmp_path: Path):
        epub_path = _make_epub_file(tmp_path)
        repo = _setup_repo(tmp_path)

        result = EPUBDocument.do_import(repo, epub_path)
        assert result["imported"] == 1
        assert result["skipped"] == 0

        docs = repo.list_documents()
        assert len(docs) == 1
        assert docs[0]["document_type"] == "epub"

        sources = repo.get_document_sources(docs[0]["document_id"])
        chapter_sources = [s for s in sources if EPUBDocument._is_chapter_source(s)]
        assert len(chapter_sources) >= 1

    def test_import_stores_non_spine_xhtml_resources_as_text(self, tmp_path: Path):
        book = EpubBook(
            metadata=EpubMetadata(title="Extra XHTML"),
            spine_items=[
                EpubItem(
                    file_name="OEBPS/ch1.xhtml",
                    media_type="application/xhtml+xml",
                    content=b"<html><body><p>Main chapter</p></body></html>",
                    item_id="ch1",
                ),
            ],
            resources=[
                EpubItem(
                    file_name="OEBPS/appendix.xhtml",
                    media_type="application/xhtml+xml",
                    content=b"<html><body><p>Appendix text</p></body></html>",
                    item_id="appendix",
                    properties="",
                ),
            ],
            toc=[],
        )
        epub_path = tmp_path / "extra_xhtml.epub"
        write_epub(epub_path, book)

        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)
        doc_row = repo.list_documents()[0]
        sources = repo.get_document_sources(doc_row["document_id"])

        appendix = next(s for s in sources if s.get("relative_path") == "OEBPS/appendix.xhtml")
        assert appendix["source_type"] == "text"
        assert appendix["is_ocr_completed"] == 1
        assert EPUBDocument._is_chapter_source(appendix) is True

    def test_import_media_type_checks_are_case_insensitive(self, tmp_path: Path):
        book = EpubBook(
            metadata=EpubMetadata(title="Mixed Media Types"),
            spine_items=[
                EpubItem(
                    file_name="OEBPS/ch1.xhtml",
                    media_type="application/xhtml+xml",
                    content=b"<html><body><p>Chapter</p></body></html>",
                    item_id="ch1",
                ),
            ],
            resources=[
                EpubItem(
                    file_name="OEBPS/style.css",
                    media_type="Text/CSS",
                    content=b"body { color: red; }",
                    item_id="css1",
                ),
                EpubItem(
                    file_name="OEBPS/fonts/book.otf",
                    media_type="FONT/OTF",
                    content=b"font-bytes",
                    item_id="font1",
                ),
                EpubItem(
                    file_name="OEBPS/images/fig.png",
                    media_type="IMAGE/PNG",
                    content=_png_bytes((90, 20, 200)),
                    item_id="img1",
                ),
            ],
            toc=[],
        )
        epub_path = tmp_path / "mixed_media_type.epub"
        write_epub(epub_path, book)

        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)
        doc_row = repo.list_documents()[0]
        sources = repo.get_document_sources(doc_row["document_id"])

        css = next(s for s in sources if s.get("relative_path") == "OEBPS/style.css")
        assert css["source_type"] == "text"
        assert css["is_ocr_completed"] == 1

        font = next(s for s in sources if s.get("relative_path") == "OEBPS/fonts/book.otf")
        assert font["source_type"] == "asset"
        assert font["is_ocr_completed"] == 1

        image = next(s for s in sources if s.get("relative_path") == "OEBPS/images/fig.png")
        assert image["source_type"] == "image"
        assert image["is_ocr_completed"] == 0

    def test_import_stores_metadata(self, tmp_path: Path):
        epub_path = _make_epub_file(tmp_path)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        docs = repo.list_documents()
        sources = repo.get_document_sources(docs[0]["document_id"])

        metadata_sources = [s for s in sources if s.get("relative_path") == METADATA_PATH]
        assert len(metadata_sources) == 1
        meta = metadata_sources[0]
        assert meta["is_text_added"] == 1
        assert meta["is_ocr_completed"] == 1
        assert meta["source_type"] == "text"

        # Verify metadata JSON is parseable
        metadata = json.loads(meta["text_content"])
        assert "title" in metadata
        assert "spine" in metadata

    def test_import_stores_css(self, tmp_path: Path):
        epub_path = _make_epub_file(tmp_path, css="body { color: red; }")
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        docs = repo.list_documents()
        sources = repo.get_document_sources(docs[0]["document_id"])

        css_sources = [
            s
            for s in sources
            if s["source_type"] == "text"
            and (str(s.get("mime_type", "")).lower() == "text/css" or str(s.get("relative_path", "")).endswith(".css"))
        ]
        assert len(css_sources) >= 1
        for css_src in css_sources:
            assert css_src["is_text_added"] == 1
            assert css_src["is_ocr_completed"] == 1

    def test_import_decodes_css_with_declared_charset(self, tmp_path: Path):
        css_text = '@charset "windows-1251";\nbody::before{content:"Привет";}\n'
        css_bytes = css_text.encode("cp1251")
        book = EpubBook(
            metadata=EpubMetadata(title="CSS Charset"),
            spine_items=[
                EpubItem(
                    file_name="OEBPS/ch1.xhtml",
                    media_type="application/xhtml+xml",
                    content=b"<html><body><p>Hello</p></body></html>",
                    item_id="ch1",
                ),
            ],
            resources=[
                EpubItem(
                    file_name="OEBPS/styles.css",
                    media_type="text/css",
                    content=css_bytes,
                    item_id="css1",
                ),
            ],
            toc=[],
        )
        epub_path = tmp_path / "css_declared_charset.epub"
        write_epub(epub_path, book)

        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)
        doc_row = repo.list_documents()[0]
        sources = repo.get_document_sources(doc_row["document_id"])

        css_source = next(s for s in sources if s.get("relative_path") == "OEBPS/styles.css")
        assert css_source["source_type"] == "text"
        assert "Привет" in css_source["text_content"]

    def test_import_stores_images(self, tmp_path: Path):
        fake_png = _png_bytes((120, 40, 90))
        epub_path = _make_epub_file(
            tmp_path,
            images=[("images/fig1.png", fake_png, "image/png")],
        )
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        docs = repo.list_documents()
        sources = repo.get_document_sources(docs[0]["document_id"])

        image_sources = [s for s in sources if EPUBDocument._is_content_image(s)]
        assert len(image_sources) >= 1
        # Content images should NOT be pre-marked (need OCR)
        for img_src in image_sources:
            assert img_src["is_ocr_completed"] == 0

    def test_import_stores_raster_spine_item_as_ocr_image(self, tmp_path: Path):
        spine_png = _png_bytes((80, 150, 40), size=(16, 16))
        book = EpubBook(
            metadata=EpubMetadata(title="Raster Spine"),
            spine_items=[
                EpubItem(
                    file_name="OEBPS/page1.png",
                    media_type="image/png",
                    content=spine_png,
                    item_id="p1",
                ),
            ],
            resources=[],
            toc=[TocEntry(title="Page 1", href="page1.png")],
        )
        epub_path = tmp_path / "raster_spine.epub"
        write_epub(epub_path, book)

        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)
        doc_row = repo.list_documents()[0]
        sources = repo.get_document_sources(doc_row["document_id"])

        spine_image = next(s for s in sources if s.get("relative_path") == "OEBPS/page1.png")
        assert spine_image["source_type"] == "image"
        assert spine_image["is_ocr_completed"] == 0
        assert spine_image["is_text_added"] == 0

        ocr_needed = repo.get_document_sources_needing_ocr(doc_row["document_id"])
        assert any(s["source_id"] == spine_image["source_id"] for s in ocr_needed)

    def test_import_prefers_textual_fallback_over_raster_spine(self, tmp_path: Path):
        spine_png = _png_bytes((30, 120, 200), size=(16, 16))
        book = EpubBook(
            metadata=EpubMetadata(title="Raster Fallback"),
            spine_items=[
                EpubItem(
                    file_name="OEBPS/page1.png",
                    media_type="image/png",
                    content=spine_png,
                    item_id="img1",
                    fallback="ch1",
                ),
            ],
            resources=[
                EpubItem(
                    file_name="OEBPS/ch1.xhtml",
                    media_type="application/xhtml+xml",
                    content=b'<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Fallback chapter text</p></body></html>',
                    item_id="ch1",
                ),
            ],
            toc=[TocEntry(title="Chapter 1", href="ch1.xhtml")],
        )
        epub_path = tmp_path / "raster_fallback.epub"
        write_epub(epub_path, book)

        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)
        doc_row = repo.list_documents()[0]
        sources = repo.get_document_sources(doc_row["document_id"])

        assert not any(s.get("relative_path") == "OEBPS/page1.png" for s in sources)
        chapter_source = next(s for s in sources if s.get("relative_path") == "OEBPS/ch1.xhtml")
        assert chapter_source["source_type"] == "text"
        assert chapter_source["is_ocr_completed"] == 1
        assert chapter_source["is_text_added"] == 0

        ocr_needed = repo.get_document_sources_needing_ocr(doc_row["document_id"])
        assert not ocr_needed

        text = EPUBDocument(repo, doc_row["document_id"]).get_text()
        assert "Fallback chapter text" in text

    def test_import_marks_svg_sources_as_pending_translation(self, tmp_path: Path):
        book = EpubBook(
            metadata=EpubMetadata(title="SVG Translation"),
            spine_items=[
                EpubItem(
                    file_name="OEBPS/ch1.svg",
                    media_type="image/svg+xml",
                    content=b'<svg xmlns="http://www.w3.org/2000/svg"><text>Hello SVG</text></svg>',
                    item_id="svgspine",
                ),
            ],
            resources=[
                EpubItem(
                    file_name="OEBPS/images/diagram.svg",
                    media_type="image/svg+xml",
                    content=b'<svg xmlns="http://www.w3.org/2000/svg"><text>Resource SVG</text></svg>',
                    item_id="svgres",
                ),
            ],
            toc=[TocEntry(title="Chapter 1", href="ch1.svg")],
        )
        epub_path = tmp_path / "svg_pending.epub"
        write_epub(epub_path, book)

        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)
        doc_row = repo.list_documents()[0]
        sources = repo.get_document_sources(doc_row["document_id"])

        spine_svg = next(s for s in sources if s.get("relative_path") == "OEBPS/ch1.svg")
        resource_svg = next(s for s in sources if s.get("relative_path") == "OEBPS/images/diagram.svg")
        for svg_source in (spine_svg, resource_svg):
            assert svg_source["source_type"] == "text"
            assert svg_source["is_ocr_completed"] == 1
            assert svg_source["is_text_added"] == 0

        pending = repo.list_documents_pending_glossary()
        assert any(doc["document_id"] == doc_row["document_id"] for doc in pending)

    def test_import_skips_duplicate(self, tmp_path: Path):
        epub_path = _make_epub_file(tmp_path)
        repo = _setup_repo(tmp_path)

        result1 = EPUBDocument.do_import(repo, epub_path)
        assert result1["imported"] == 1

        result2 = EPUBDocument.do_import(repo, epub_path)
        assert result2["imported"] == 0
        assert result2["skipped"] == 1

    def test_import_dedup_uses_archive_bytes_not_first_chapter_only(self, tmp_path: Path):
        epub_path1 = _make_epub_file(
            tmp_path,
            chapters=[
                ("ch1.xhtml", "<html><body><p>Shared opener</p></body></html>"),
                ("ch2.xhtml", "<html><body><p>Book A body</p></body></html>"),
            ],
            title="Book A",
        )
        repo = _setup_repo(tmp_path)
        result1 = EPUBDocument.do_import(repo, epub_path1)
        assert result1 == {"imported": 1, "skipped": 0}

        second_dir = tmp_path / "book_b"
        second_dir.mkdir()
        epub_path2 = _make_epub_file(
            second_dir,
            chapters=[
                ("ch1.xhtml", "<html><body><p>Shared opener</p></body></html>"),
                ("ch2.xhtml", "<html><body><p>Book B body</p></body></html>"),
            ],
            title="Book B",
        )
        result2 = EPUBDocument.do_import(repo, epub_path2)
        assert result2 == {"imported": 1, "skipped": 0}

        docs = repo.list_documents()
        assert len(docs) == 2

    def test_import_malformed_epub(self, tmp_path: Path):
        bad_file = tmp_path / "bad.epub"
        bad_file.write_bytes(b"this is not an epub")

        repo = _setup_repo(tmp_path)
        with pytest.raises(ValueError, match="Failed to read EPUB"):
            EPUBDocument.do_import(repo, bad_file)

    def test_import_rejects_malformed_xhtml_chapter(self, tmp_path: Path):
        epub_path = tmp_path / "broken.epub"
        container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
        opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Broken XHTML</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="broken.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>"""

        with zipfile.ZipFile(epub_path, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip")
            zf.writestr("META-INF/container.xml", container_xml)
            zf.writestr("OEBPS/content.opf", opf_xml)
            zf.writestr("OEBPS/broken.xhtml", "<html><body><p>Broken chapter")

        repo = _setup_repo(tmp_path)

        with pytest.raises(ValueError, match="Invalid XHTML chapter"):
            EPUBDocument.do_import(repo, epub_path)

    def test_import_rejects_invalid_raster_image_resource(self, tmp_path: Path):
        epub_path = _make_epub_file(
            tmp_path,
            images=[("images/broken.png", b"not-a-real-image", "image/png")],
        )
        repo = _setup_repo(tmp_path)

        with pytest.raises(ValueError, match="Invalid image data"):
            EPUBDocument.do_import(repo, epub_path)

        assert repo.list_documents() == []

    def test_import_spine_order(self, tmp_path: Path):
        chapters = [
            (
                "ch1.xhtml",
                "<html><body><p>Chapter 1</p></body></html>",
            ),
            (
                "ch2.xhtml",
                "<html><body><p>Chapter 2</p></body></html>",
            ),
            (
                "ch3.xhtml",
                "<html><body><p>Chapter 3</p></body></html>",
            ),
        ]
        epub_path = _make_epub_file(tmp_path, chapters=chapters)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        docs = repo.list_documents()
        sources = repo.get_document_sources(docs[0]["document_id"])
        chapter_sources = [s for s in sources if EPUBDocument._is_chapter_source(s)]
        # Chapters should be in spine order (by sequence_number)
        seq_numbers = [s["sequence_number"] for s in chapter_sources]
        assert seq_numbers == sorted(seq_numbers)
        assert len(chapter_sources) == 3


# =========================================================================
# Tests: OCR
# =========================================================================


class TestOCR:
    def test_is_ocr_completed_no_images(self, tmp_path: Path):
        epub_path = _make_epub_file(tmp_path)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        docs = repo.list_documents()
        doc = EPUBDocument(repo, docs[0]["document_id"])
        assert doc.is_ocr_completed() is True

    def test_is_ocr_completed_with_pending_images(self, tmp_path: Path):
        fake_png = _png_bytes((10, 120, 40))
        epub_path = _make_epub_file(
            tmp_path,
            images=[("images/fig1.png", fake_png, "image/png")],
        )
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        docs = repo.list_documents()
        doc = EPUBDocument(repo, docs[0]["document_id"])
        assert doc.is_ocr_completed() is False

    @pytest.mark.asyncio
    async def test_process_ocr_stores_image_embedded_text_payload(self, tmp_path: Path):
        epub_path = _make_epub_file(
            tmp_path,
            chapters=[("ch1.xhtml", "<html><body><p>Body</p></body></html>")],
            images=[("images/fig1.png", _png_bytes((90, 30, 10)), "image/png")],
        )
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        doc_row = repo.list_documents()[0]
        doc = EPUBDocument(repo, doc_row["document_id"], ocr_config=OCRConfig())

        async def _fake_epub_ocr(_image_data, _llm_client, _ocr_config, on_result):
            on_result(0, "Embedded line 1\nEmbedded line 2")

        with patch(
            "context_aware_translation.documents.epub.ocr_epub_images",
            new_callable=AsyncMock,
        ) as mock_ocr:
            mock_ocr.side_effect = _fake_epub_ocr
            processed = await doc.process_ocr(object())

        assert processed == 1
        sources = repo.get_document_sources(doc_row["document_id"])
        image_source = next(s for s in sources if EPUBDocument._is_content_image(s))
        assert image_source["is_ocr_completed"] == 1

        parsed = json.loads(image_source["ocr_json"])
        assert parsed == {"embedded_text": "Embedded line 1\nEmbedded line 2"}


# =========================================================================
# Tests: get_text
# =========================================================================


class TestGetText:
    def test_get_text_returns_chapter_text(self, tmp_path: Path):
        chapters = [
            (
                "ch1.xhtml",
                "<html><body><p>Hello world.</p><p>Second paragraph.</p></body></html>",
            ),
        ]
        epub_path = _make_epub_file(tmp_path, chapters=chapters)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        docs = repo.list_documents()
        doc = EPUBDocument(repo, docs[0]["document_id"])
        text = doc.get_text()

        assert "Hello world." in text
        assert "Second paragraph." in text

    def test_get_text_excludes_metadata(self, tmp_path: Path):
        epub_path = _make_epub_file(tmp_path)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        docs = repo.list_documents()
        doc = EPUBDocument(repo, docs[0]["document_id"])
        text = doc.get_text()

        assert "__epub_metadata__" not in text
        assert "spine" not in text

    def test_get_text_excludes_css(self, tmp_path: Path):
        epub_path = _make_epub_file(tmp_path, css="body { color: red; }")
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        docs = repo.list_documents()
        doc = EPUBDocument(repo, docs[0]["document_id"])
        text = doc.get_text()

        assert "color: red" not in text

    def test_get_text_multiple_chapters(self, tmp_path: Path):
        chapters = [
            ("ch1.xhtml", "<html><body><p>Chapter one.</p></body></html>"),
            ("ch2.xhtml", "<html><body><p>Chapter two.</p></body></html>"),
        ]
        epub_path = _make_epub_file(tmp_path, chapters=chapters)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        docs = repo.list_documents()
        doc = EPUBDocument(repo, docs[0]["document_id"])
        text = doc.get_text()

        lines = text.split("\n")
        assert "Chapter one." in lines
        assert "Chapter two." in lines

    def test_get_text_includes_toc_titles(self, tmp_path: Path):
        chapters = [
            ("ch1.xhtml", "<html><body><p>Body text</p></body></html>"),
        ]
        epub_path = _make_epub_file(tmp_path, chapters=chapters)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        doc_row = repo.list_documents()[0]
        doc = EPUBDocument(repo, doc_row["document_id"])
        lines = doc.get_text().splitlines()

        assert "Body text" in lines
        assert "ch1.xhtml" in lines

    def test_get_text_includes_book_title_for_translation(self, tmp_path: Path):
        epub_path = _make_epub_file(tmp_path, title="Original Book Name")
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        doc_row = repo.list_documents()[0]
        doc = EPUBDocument(repo, doc_row["document_id"])
        lines = doc.get_text().splitlines()

        assert "Original Book Name" in lines

    def test_get_text_includes_page_list_and_landmarks_labels(self, tmp_path: Path):
        epub_path = _make_epub_with_nav_sections(tmp_path)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        doc_row = repo.list_documents()[0]
        doc = EPUBDocument(repo, doc_row["document_id"])
        lines = doc.get_text().splitlines()

        assert "Hello" in lines
        assert "Chapter 1" in lines
        assert "Page i" in lines
        assert "Cover" in lines

    def test_get_text_respects_non_utf8_xml_declaration(self, tmp_path: Path):
        epub_path = tmp_path / "latin1.epub"

        container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

        opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Latin1</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>"""

        chapter = (
            '<?xml version="1.0" encoding="iso-8859-1"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>café</p></body></html>'
        ).encode("latin-1")

        with zipfile.ZipFile(epub_path, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            zf.writestr("META-INF/container.xml", container_xml)
            zf.writestr("OEBPS/content.opf", opf_xml)
            zf.writestr("OEBPS/ch1.xhtml", chapter)

        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)
        doc_row = repo.list_documents()[0]
        doc = EPUBDocument(repo, doc_row["document_id"])
        lines = doc.get_text().splitlines()
        assert lines[0] == "café"

    def test_get_text_uses_only_embedded_image_text_from_ocr(self, tmp_path: Path):
        epub_path = _make_epub_file(
            tmp_path,
            chapters=[("ch1.xhtml", "<html><body><p>Body</p></body></html>")],
            images=[("images/fig1.png", _png_bytes((15, 30, 45)), "image/png")],
        )
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        doc_row = repo.list_documents()[0]
        sources = repo.get_document_sources(doc_row["document_id"])
        image_source = next(s for s in sources if EPUBDocument._is_content_image(s))
        ocr_json = [
            {
                "page_type": "content",
                "content": [
                    {"type": "paragraph", "text": "Paragraph OCR"},
                    {
                        "type": "image",
                        "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
                        "embedded_text": "Embedded OCR",
                        "caption": "Caption OCR",
                    },
                    {"type": "image", "embedded_text": "Embedded without bbox"},
                ],
            }
        ]
        repo.update_source_ocr(image_source["source_id"], json.dumps(ocr_json))
        repo.update_source_ocr_completed(image_source["source_id"])

        doc = EPUBDocument(repo, doc_row["document_id"])
        lines = doc.get_text().splitlines()
        assert "Embedded OCR" in lines
        assert "Embedded without bbox" in lines
        assert "Paragraph OCR" not in lines
        assert "Caption OCR" not in lines


# =========================================================================
# Tests: set_text
# =========================================================================


class TestSetText:
    @pytest.mark.asyncio
    async def test_set_text_injects_translations(self, tmp_path: Path):
        chapters = [
            ("ch1.xhtml", "<html><body><p>Hello</p><p>World</p></body></html>"),
        ]
        epub_path = _make_epub_file(tmp_path, chapters=chapters)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        docs = repo.list_documents()
        doc = EPUBDocument(repo, docs[0]["document_id"])

        source_lines = doc.get_text().splitlines()
        translations = ["Hola", "Mundo", *source_lines[2:]]
        consumed = await doc.set_text(translations)
        assert consumed == len(translations)
        assert len(doc._translated_chapters) == 1

    @pytest.mark.asyncio
    async def test_set_text_returns_consumed_count(self, tmp_path: Path):
        chapters = [
            ("ch1.xhtml", "<html><body><p>A</p><p>B</p><p>C</p></body></html>"),
        ]
        epub_path = _make_epub_file(tmp_path, chapters=chapters)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        docs = repo.list_documents()
        doc = EPUBDocument(repo, docs[0]["document_id"])

        source_lines = doc.get_text().splitlines()
        translations = [f"T{idx}" for idx in range(len(source_lines))]
        consumed = await doc.set_text(translations)
        assert consumed == len(translations)

    @pytest.mark.asyncio
    async def test_set_text_line_count_mismatch_fewer_lines(self, tmp_path: Path):
        """Fewer translated lines than blocks raises ValueError."""
        chapters = [
            ("ch1.xhtml", "<html><body><p>A</p><p>B</p><p>C</p></body></html>"),
        ]
        epub_path = _make_epub_file(tmp_path, chapters=chapters)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        docs = repo.list_documents()
        doc = EPUBDocument(repo, docs[0]["document_id"])

        with pytest.raises(ValueError, match="line count mismatch"):
            await doc.set_text(["Only one"])

    @pytest.mark.asyncio
    async def test_set_text_line_count_mismatch_extra_lines(self, tmp_path: Path):
        """More translated lines than blocks raises ValueError."""
        chapters = [
            ("ch1.xhtml", "<html><body><p>A</p></body></html>"),
        ]
        epub_path = _make_epub_file(tmp_path, chapters=chapters)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        docs = repo.list_documents()
        doc = EPUBDocument(repo, docs[0]["document_id"])

        with pytest.raises(ValueError, match="line count mismatch"):
            await doc.set_text([*doc.get_text().splitlines(), "Extra1", "Extra2"])

    @pytest.mark.asyncio
    async def test_set_text_line_count_match(self, tmp_path: Path):
        chapters = [
            ("ch1.xhtml", "<html><body><p>A</p><p>B</p></body></html>"),
            ("ch2.xhtml", "<html><body><p>C</p></body></html>"),
        ]
        epub_path = _make_epub_file(tmp_path, chapters=chapters)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        docs = repo.list_documents()
        doc = EPUBDocument(repo, docs[0]["document_id"])

        source_lines = doc.get_text().splitlines()
        translations = [f"T{idx}" for idx in range(len(source_lines))]
        consumed = await doc.set_text(translations)
        assert consumed == len(translations)
        assert len(doc._translated_chapters) == 2

    @pytest.mark.asyncio
    async def test_set_text_handles_inline_marker_drop_best_effort(self, tmp_path: Path):
        chapters = [
            ("ch1.xhtml", "<html><body><p>This is <em>italic</em> text</p></body></html>"),
        ]
        epub_path = _make_epub_file(tmp_path, chapters=chapters)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        doc = EPUBDocument(repo, repo.list_documents()[0]["document_id"])
        source_lines = doc.get_text().splitlines()
        marker_idx = next(i for i, line in enumerate(source_lines) if "⟪" in line and ":" in line)

        translations = list(source_lines)
        translations[marker_idx] = "This is italic text"

        consumed = await doc.set_text(translations)
        assert consumed == len(translations)
        assert len(doc._translated_chapters) == 1

    @pytest.mark.asyncio
    async def test_set_text_handles_multiline_slot_counting(self, tmp_path: Path):
        chapters = [
            ("ch1.xhtml", "<html><body><pre>line one\nline two</pre></body></html>"),
        ]
        epub_path = _make_epub_file(tmp_path, chapters=chapters)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        doc_row = repo.list_documents()[0]
        doc = EPUBDocument(repo, doc_row["document_id"])
        source_lines = doc.get_text().splitlines()

        consumed = await doc.set_text(source_lines)
        assert consumed == len(source_lines)
        assert len(doc._translated_chapters) == 1

    @pytest.mark.asyncio
    async def test_set_text_translates_non_spine_xhtml_resources(self, tmp_path: Path):
        book = EpubBook(
            metadata=EpubMetadata(title="Extra XHTML"),
            spine_items=[
                EpubItem(
                    file_name="OEBPS/ch1.xhtml",
                    media_type="application/xhtml+xml",
                    content=b"<html><body><p>Main chapter</p></body></html>",
                    item_id="ch1",
                ),
            ],
            resources=[
                EpubItem(
                    file_name="OEBPS/appendix.xhtml",
                    media_type="application/xhtml+xml",
                    content=b"<html><body><p>Appendix note</p></body></html>",
                    item_id="appendix",
                    properties="",
                ),
            ],
            toc=[],
        )
        epub_path = tmp_path / "translate_extra_xhtml.epub"
        write_epub(epub_path, book)

        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)
        doc_row = repo.list_documents()[0]
        doc = EPUBDocument(repo, doc_row["document_id"])

        lines = doc.get_text().splitlines()
        lines[lines.index("Appendix note")] = "Nota del apendice"
        consumed = await doc.set_text(lines)
        assert consumed == len(lines)

        output = tmp_path / "translate_extra_xhtml_out.epub"
        EPUBDocument.export_merged([doc], "epub", output)
        with zipfile.ZipFile(output, "r") as zf:
            appendix_out = zf.read("OEBPS/appendix.xhtml").decode("utf-8")
            assert "Nota del apendice" in appendix_out

    @pytest.mark.asyncio
    async def test_set_text_stores_translated_image_ocr(self, tmp_path: Path):
        epub_path = _make_epub_file(
            tmp_path,
            chapters=[("ch1.xhtml", "<html><body></body></html>")],
            images=[("images/fig1.png", _png_bytes((20, 40, 60)), "image/png")],
        )
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        doc_row = repo.list_documents()[0]
        sources = repo.get_document_sources(doc_row["document_id"])
        image_source = next(s for s in sources if EPUBDocument._is_content_image(s))

        ocr_json = [
            {
                "page_type": "content",
                "content": [
                    {
                        "type": "image",
                        "bbox": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
                        "embedded_text": "Original embedded text",
                    }
                ],
            }
        ]
        repo.update_source_ocr(image_source["source_id"], json.dumps(ocr_json))
        repo.update_source_ocr_completed(image_source["source_id"])

        doc = EPUBDocument(repo, doc_row["document_id"])
        source_lines = doc.get_text().splitlines()
        translations = ["Translated embedded text", *source_lines[1:]]
        consumed = await doc.set_text(translations)
        assert consumed == len(translations)

        translated = doc._translated_image_texts[image_source["source_id"]]
        assert translated == "Translated embedded text"

    @pytest.mark.asyncio
    async def test_set_text_translates_only_embedded_image_text_from_ocr(self, tmp_path: Path):
        epub_path = _make_epub_file(
            tmp_path,
            chapters=[("ch1.xhtml", "<html><body><p>Body</p></body></html>")],
            images=[("images/fig1.png", _png_bytes((12, 34, 56)), "image/png")],
        )
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        doc_row = repo.list_documents()[0]
        sources = repo.get_document_sources(doc_row["document_id"])
        image_source = next(s for s in sources if EPUBDocument._is_content_image(s))
        ocr_json = [
            {
                "page_type": "content",
                "content": [
                    {"type": "paragraph", "text": "Should be ignored"},
                    {"type": "image", "embedded_text": "Embedded A", "caption": "Caption A"},
                    {"type": "image", "embedded_text": "Embedded B"},
                ],
            }
        ]
        repo.update_source_ocr(image_source["source_id"], json.dumps(ocr_json))
        repo.update_source_ocr_completed(image_source["source_id"])

        doc = EPUBDocument(repo, doc_row["document_id"])
        lines = doc.get_text().splitlines()
        translations = list(lines)
        translations[lines.index("Embedded A")] = "Translated A"
        translations[lines.index("Embedded B")] = "Translated B"

        consumed = await doc.set_text(translations)
        assert consumed == len(translations)

        translated = doc._translated_image_texts[image_source["source_id"]]
        assert translated == "Translated A\nTranslated B"

    @pytest.mark.asyncio
    async def test_set_text_updates_toc_titles_for_export(self, tmp_path: Path):
        chapters = [
            ("ch1.xhtml", "<html><body><p>Hello</p></body></html>"),
        ]
        epub_path = _make_epub_file(tmp_path, chapters=chapters)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        doc_row = repo.list_documents()[0]
        doc = EPUBDocument(repo, doc_row["document_id"])
        source_lines = doc.get_text().splitlines()
        assert source_lines[-1] == "ch1.xhtml"

        translations = [*source_lines[:-1], "Capitulo Uno"]
        consumed = await doc.set_text(translations)
        assert consumed == len(translations)

        output = tmp_path / "toc_translated.epub"
        EPUBDocument.export_merged([doc], "epub", output)

        read_back = read_epub(output)
        assert len(read_back.toc) == 1
        assert read_back.toc[0].title == "Capitulo Uno"

    @pytest.mark.asyncio
    async def test_set_text_updates_inline_toc_nav_labels_without_duplication(self, tmp_path: Path):
        epub_path = _make_epub_with_inline_toc_nav_label(tmp_path)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        doc_row = repo.list_documents()[0]
        doc = EPUBDocument(repo, doc_row["document_id"])
        source_lines = doc.get_text().splitlines()

        translated_lines = list(source_lines)
        translated_lines[source_lines.index("Chapter 1")] = "Capitulo 1"
        consumed = await doc.set_text(translated_lines)
        assert consumed == len(translated_lines)

        output = tmp_path / "inline_toc_translated.epub"
        EPUBDocument.export_merged([doc], "epub", output)

        with zipfile.ZipFile(output, "r") as zf:
            nav_out = zf.read("OEBPS/nav.xhtml").decode("utf-8")
            assert "<em>Capitulo</em> 1" in nav_out
            assert "Chapter" not in nav_out
            assert "<em />" not in nav_out
            assert "<em>" in nav_out

    @pytest.mark.asyncio
    async def test_set_text_updates_page_list_and_landmarks_labels_for_export(self, tmp_path: Path):
        epub_path = _make_epub_with_nav_sections(tmp_path)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        doc_row = repo.list_documents()[0]
        doc = EPUBDocument(repo, doc_row["document_id"])
        source_lines = doc.get_text().splitlines()

        translations = list(source_lines)
        translations[source_lines.index("Page i")] = "Pagina i"
        translations[source_lines.index("Cover")] = "Cubierta"
        consumed = await doc.set_text(translations)
        assert consumed == len(translations)

        output = tmp_path / "nav_labels_translated.epub"
        EPUBDocument.export_merged([doc], "epub", output)

        with zipfile.ZipFile(output, "r") as zf:
            nav_out = zf.read("OEBPS/nav.xhtml").decode("utf-8")
            assert "Pagina i" in nav_out
            assert "Cubierta" in nav_out


# =========================================================================
# Tests: source classification
# =========================================================================


class TestSourceClassification:
    def test_is_content_image_by_extension(self):
        for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"]:
            source = {"source_type": "image", "relative_path": f"images/fig{ext}"}
            assert EPUBDocument._is_content_image(source) is True

    def test_is_not_content_image_fonts(self):
        for ext in [".otf", ".ttf", ".woff", ".woff2"]:
            source = {"source_type": "image", "relative_path": f"fonts/font{ext}"}
            assert EPUBDocument._is_content_image(source) is False

    def test_is_content_image_after_ocr(self):
        """Content images still identified correctly even after is_ocr_completed=1."""
        source = {
            "source_type": "image",
            "relative_path": "images/fig.png",
            "is_ocr_completed": 1,
        }
        assert EPUBDocument._is_content_image(source) is True

    def test_is_content_image_by_mime_type(self):
        source = {
            "source_type": "image",
            "relative_path": "images/figure.unknown",
            "mime_type": "image/jpeg",
        }
        assert EPUBDocument._is_content_image(source) is True

    def test_is_not_content_image_svg_mime(self):
        source = {
            "source_type": "image",
            "relative_path": "images/diagram.vector",
            "mime_type": "image/svg+xml",
        }
        assert EPUBDocument._is_content_image(source) is False

    def test_is_chapter_source(self):
        assert (
            EPUBDocument._is_chapter_source(
                {
                    "source_type": "text",
                    "relative_path": "chapter1.xhtml",
                }
            )
            is True
        )
        assert (
            EPUBDocument._is_chapter_source(
                {
                    "source_type": "text",
                    "relative_path": "chapter1.html",
                }
            )
            is True
        )
        assert (
            EPUBDocument._is_chapter_source(
                {
                    "source_type": "text",
                    "relative_path": METADATA_PATH,
                }
            )
            is False
        )
        assert (
            EPUBDocument._is_chapter_source(
                {
                    "source_type": "text",
                    "relative_path": "style.css",
                }
            )
            is False
        )

    def test_is_chapter_source_by_mime_type(self):
        assert (
            EPUBDocument._is_chapter_source(
                {
                    "source_type": "text",
                    "relative_path": "chapter.weird",
                    "mime_type": "application/xhtml+xml",
                }
            )
            is True
        )

    def test_is_metadata_source(self):
        assert EPUBDocument._is_metadata_source({"relative_path": METADATA_PATH}) is True
        assert EPUBDocument._is_metadata_source({"relative_path": "chapter1.xhtml"}) is False


# =========================================================================
# Tests: can_export
# =========================================================================


class TestCanExport:
    def test_can_export_supported_formats(self, tmp_path: Path):
        repo = _setup_repo(tmp_path)
        doc = EPUBDocument(repo, 1)
        assert doc.can_export("epub") is True
        assert doc.can_export("md") is True
        assert doc.can_export("docx") is True
        assert doc.can_export("html") is True

    def test_can_export_unsupported_formats(self, tmp_path: Path):
        repo = _setup_repo(tmp_path)
        doc = EPUBDocument(repo, 1)
        assert doc.can_export("txt") is False
        assert doc.can_export("pdf") is False
        assert doc.can_export("anything") is False


# =========================================================================
# Tests: export
# =========================================================================


class TestExport:
    def test_export_preserve_structure_raises(self, tmp_path: Path):
        repo = _setup_repo(tmp_path)
        doc = EPUBDocument(repo, 1)
        with pytest.raises(NotImplementedError):
            doc.export_preserve_structure(tmp_path / "output")

    def test_export_epub_single_doc_native(self, tmp_path: Path):
        """Single doc EPUB export produces a valid EPUB file."""
        chapters = [
            ("ch1.xhtml", "<html><body><h1>Title</h1><p>Content here.</p></body></html>"),
        ]
        epub_path = _make_epub_file(tmp_path, chapters=chapters)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        docs = repo.list_documents()
        doc = EPUBDocument(repo, docs[0]["document_id"])

        # Simulate translated chapters
        sources = repo.get_document_sources(docs[0]["document_id"])
        for s in sources:
            if EPUBDocument._is_chapter_source(s):
                doc._translated_chapters[s["source_id"]] = (
                    "<html><body><h1>Titulo</h1><p>Contenido aqui.</p></body></html>"
                )

        output = tmp_path / "output.epub"
        EPUBDocument.export_merged([doc], "epub", output)
        assert output.exists()
        assert output.stat().st_size > 0

        # Verify it's a valid EPUB (can be read back)
        read_back = read_epub(output)
        assert read_back is not None

        # Verify translated content appears in re-read chapters
        assert len(read_back.spine_items) > 0
        content = read_back.spine_items[0].content.decode("utf-8")
        assert "Titulo" in content or "Contenido aqui." in content

    @pytest.mark.asyncio
    async def test_export_epub_updates_opf_dc_title_from_translated_metadata_title(self, tmp_path: Path):
        epub_path = _make_epub_file(
            tmp_path,
            chapters=[("ch1.xhtml", "<html><body><p>Body text</p></body></html>")],
            title="Original Book Name",
            language="ja",
        )
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        doc_row = repo.list_documents()[0]
        doc = EPUBDocument(repo, doc_row["document_id"])
        source_lines = doc.get_text().splitlines()
        translations = ["Libro Traducido" if line == "Original Book Name" else line for line in source_lines]
        consumed = await doc.set_text(translations)
        assert consumed == len(translations)

        output = tmp_path / "title_translated.epub"
        EPUBDocument.export_merged([doc], "epub", output)

        read_back = read_epub(output)
        assert read_back.metadata.title == "Libro Traducido"

    @pytest.mark.asyncio
    async def test_export_epub_updates_opf_dc_language_from_target_language(self, tmp_path: Path):
        epub_path = _make_epub_file(
            tmp_path,
            chapters=[("ch1.xhtml", "<html><body><p>Body text</p></body></html>")],
            title="Book",
            language="ja",
        )
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        doc_row = repo.list_documents()[0]
        doc = EPUBDocument(repo, doc_row["document_id"])
        source_lines = doc.get_text().splitlines()
        consumed = await doc.set_text(source_lines)
        assert consumed == len(source_lines)
        doc.set_translation_target_language("简体中文")

        output = tmp_path / "language_translated.epub"
        EPUBDocument.export_merged([doc], "epub", output)

        read_back = read_epub(output)
        assert read_back.metadata.language == "zh-Hans"

    @pytest.mark.asyncio
    async def test_export_epub_normalizes_xml_header_encoding_to_utf8(self, tmp_path: Path):
        epub_path = tmp_path / "latin1_export.epub"

        container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

        opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Latin1</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>"""

        chapter = (
            '<?xml version="1.0" encoding="iso-8859-1"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>café</p></body></html>'
        ).encode("latin-1")

        with zipfile.ZipFile(epub_path, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            zf.writestr("META-INF/container.xml", container_xml)
            zf.writestr("OEBPS/content.opf", opf_xml)
            zf.writestr("OEBPS/ch1.xhtml", chapter)

        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)
        doc_row = repo.list_documents()[0]
        doc = EPUBDocument(repo, doc_row["document_id"])
        source_lines = doc.get_text().splitlines()
        consumed = await doc.set_text(source_lines)
        assert consumed == len(source_lines)

        output = tmp_path / "latin1_export_out.epub"
        EPUBDocument.export_merged([doc], "epub", output)

        with zipfile.ZipFile(output, "r") as zf:
            xhtml_out = zf.read("OEBPS/ch1.xhtml")
            assert b'encoding="utf-8"' in xhtml_out
            decoded = xhtml_out.decode("utf-8")
            assert "café" in decoded

    def test_export_epub_normalizes_xml_header_encoding_without_translation(self, tmp_path: Path):
        epub_path = tmp_path / "latin1_export_untranslated.epub"

        container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

        opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Latin1</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>"""

        chapter = (
            '<?xml version="1.0" encoding="iso-8859-1"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>café</p></body></html>'
        ).encode("latin-1")

        with zipfile.ZipFile(epub_path, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            zf.writestr("META-INF/container.xml", container_xml)
            zf.writestr("OEBPS/content.opf", opf_xml)
            zf.writestr("OEBPS/ch1.xhtml", chapter)

        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)
        doc_row = repo.list_documents()[0]
        doc = EPUBDocument(repo, doc_row["document_id"])

        output = tmp_path / "latin1_export_untranslated_out.epub"
        EPUBDocument.export_merged([doc], "epub", output)

        with zipfile.ZipFile(output, "r") as zf:
            xhtml_out = zf.read("OEBPS/ch1.xhtml")
            assert b'encoding="utf-8"' in xhtml_out
            assert b"iso-8859-1" not in xhtml_out.lower()
            decoded = xhtml_out.decode("utf-8")
            assert "café" in decoded

    def test_export_epub_normalizes_css_charset_to_utf8(self, tmp_path: Path):
        css_bytes = b'@charset "iso-8859-1";\nbody::before{content:"caf\xe9";}\n'
        book = EpubBook(
            metadata=EpubMetadata(title="CSS Charset"),
            spine_items=[
                EpubItem(
                    file_name="OEBPS/ch1.xhtml",
                    media_type="application/xhtml+xml",
                    content=(
                        b'<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                        b'<link rel="stylesheet" href="styles.css"/>'
                        b"</head><body><p>Hello</p></body></html>"
                    ),
                    item_id="ch1",
                )
            ],
            resources=[
                EpubItem(
                    file_name="OEBPS/styles.css",
                    media_type="text/css",
                    content=css_bytes,
                    item_id="css1",
                ),
            ],
            toc=[TocEntry(title="Chapter 1", href="ch1.xhtml")],
        )
        epub_path = tmp_path / "css_charset.epub"
        write_epub(epub_path, book)

        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)
        doc_row = repo.list_documents()[0]
        doc = EPUBDocument(repo, doc_row["document_id"])

        output = tmp_path / "css_charset_out.epub"
        EPUBDocument.export_merged([doc], "epub", output)

        with zipfile.ZipFile(output, "r") as zf:
            css_out = zf.read("OEBPS/styles.css")
            assert b'@charset "utf-8";' in css_out.lower()
            assert b"iso-8859-1" not in css_out.lower()
            assert b"caf\xc3\xa9" in css_out

    def test_export_md_produces_markdown(self, tmp_path: Path):
        chapters = [
            ("ch1.xhtml", "<html><body><p>Hello world.</p></body></html>"),
        ]
        epub_path = _make_epub_file(tmp_path, chapters=chapters)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        docs = repo.list_documents()
        doc = EPUBDocument(repo, docs[0]["document_id"])

        sources = repo.get_document_sources(docs[0]["document_id"])
        for s in sources:
            if EPUBDocument._is_chapter_source(s):
                doc._translated_chapters[s["source_id"]] = "<html><body><p>Hola mundo.</p></body></html>"

        output = tmp_path / "output.md"
        EPUBDocument.export_merged([doc], "md", output)
        assert output.exists()
        content = output.read_text()
        assert "Hola mundo." in content

    def test_export_non_epub_uses_intermediate_epub_conversion(self, tmp_path: Path):
        chapters = [
            ("ch1.xhtml", "<html><body><p>Hello world.</p></body></html>"),
        ]
        epub_path = _make_epub_file(tmp_path, chapters=chapters)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        docs = repo.list_documents()
        doc = EPUBDocument(repo, docs[0]["document_id"])
        output = tmp_path / "output.md"

        def _fake_convert(input_path: Path, output_path: Path, fmt: str, from_fmt: str) -> None:
            assert input_path.suffix == ".epub"
            assert input_path.exists()
            assert output_path == output
            assert fmt == "md"
            assert from_fmt == "epub"
            output_path.write_text("converted")

        with patch("context_aware_translation.documents.epub.export_pandoc_file", side_effect=_fake_convert) as mock:
            EPUBDocument.export_merged([doc], "md", output)

        assert mock.call_count == 1
        assert output.read_text() == "converted"

    def test_export_no_documents_raises(self):
        with pytest.raises(ValueError, match="No documents to export"):
            EPUBDocument.export_merged([], "epub", Path("/tmp/test.epub"))

    def test_export_txt_raises_unsupported_format(self, tmp_path: Path):
        chapters = [
            ("ch1.xhtml", "<html><body><p>Hello world.</p></body></html>"),
        ]
        epub_path = _make_epub_file(tmp_path, chapters=chapters)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        docs = repo.list_documents()
        doc = EPUBDocument(repo, docs[0]["document_id"])

        with pytest.raises(ValueError, match="Requested format 'txt' is not supported"):
            EPUBDocument.export_merged([doc], "txt", tmp_path / "output.txt")

    def test_export_md_multi_document(self, tmp_path: Path):
        """EPUB export path should reject multi-document calls."""
        # Create first EPUB with one chapter
        chapters1 = [
            ("ch1.xhtml", "<html><body><p>First book chapter one.</p></body></html>"),
        ]
        epub_path1 = _make_epub_file(tmp_path, chapters=chapters1, title="Book One", author="Author One")

        # Create second EPUB with different content
        book2_dir = tmp_path / "book2"
        book2_dir.mkdir()
        chapters2 = [
            ("ch2.xhtml", "<html><body><p>Second book chapter one.</p></body></html>"),
        ]
        epub_path2 = _make_epub_file(book2_dir, chapters=chapters2, title="Book Two", author="Author Two")

        # Import both into same repo
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path1)
        EPUBDocument.do_import(repo, epub_path2)

        docs = repo.list_documents()
        assert len(docs) == 2

        # Create EPUBDocument instances
        doc1 = EPUBDocument(repo, docs[0]["document_id"])
        doc2 = EPUBDocument(repo, docs[1]["document_id"])

        # Set translated chapters on both
        sources1 = repo.get_document_sources(docs[0]["document_id"])
        for s in sources1:
            if EPUBDocument._is_chapter_source(s):
                doc1._translated_chapters[s["source_id"]] = (
                    "<html><body><p>Primer libro capitulo uno.</p></body></html>"
                )

        sources2 = repo.get_document_sources(docs[1]["document_id"])
        for s in sources2:
            if EPUBDocument._is_chapter_source(s):
                doc2._translated_chapters[s["source_id"]] = (
                    "<html><body><p>Segundo libro capitulo uno.</p></body></html>"
                )

        output = tmp_path / "merged_output.md"
        with pytest.raises(ValueError, match="supports exactly one document"):
            EPUBDocument.export_merged([doc1, doc2], "md", output)

    def test_export_epub_preserves_svg_resources(self, tmp_path: Path):
        book = EpubBook(
            metadata=EpubMetadata(title="SVG Book"),
            spine_items=[
                EpubItem(
                    file_name="OEBPS/ch1.xhtml",
                    media_type="application/xhtml+xml",
                    content=b"<html><body><p>Hello</p></body></html>",
                    item_id="ch1",
                ),
            ],
            resources=[
                EpubItem(
                    file_name="OEBPS/images/diagram.svg",
                    media_type="image/svg+xml",
                    content=b'<svg xmlns="http://www.w3.org/2000/svg"><text>Hi</text></svg>',
                    item_id="svg1",
                ),
            ],
            toc=[],
        )
        epub_path = tmp_path / "svg_input.epub"
        write_epub(epub_path, book)

        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)
        doc_row = repo.list_documents()[0]
        doc = EPUBDocument(repo, doc_row["document_id"])

        for source in repo.get_document_sources(doc_row["document_id"]):
            if EPUBDocument._is_chapter_source(source):
                doc._translated_chapters[source["source_id"]] = source["text_content"]

        output = tmp_path / "svg_output.epub"
        EPUBDocument.export_merged([doc], "epub", output)

        with zipfile.ZipFile(output, "r") as zf:
            assert "OEBPS/images/diagram.svg" in zf.namelist()
            assert b"<svg" in zf.read("OEBPS/images/diagram.svg")

    @pytest.mark.asyncio
    async def test_export_epub_applies_translated_spine_svg_text(self, tmp_path: Path):
        book = EpubBook(
            metadata=EpubMetadata(title="SVG Spine Book"),
            spine_items=[
                EpubItem(
                    file_name="OEBPS/ch1.svg",
                    media_type="image/svg+xml",
                    content=b'<svg xmlns="http://www.w3.org/2000/svg"><text>Hello SVG</text></svg>',
                    item_id="ch1",
                ),
            ],
            resources=[],
            toc=[TocEntry(title="Chapter 1", href="ch1.svg")],
        )
        epub_path = tmp_path / "svg_spine_input.epub"
        write_epub(epub_path, book)

        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        doc_row = repo.list_documents()[0]
        doc = EPUBDocument(repo, doc_row["document_id"])
        lines = doc.get_text().splitlines()
        lines[0] = "Hola SVG"

        consumed = await doc.set_text(lines)
        assert consumed == len(lines)

        output = tmp_path / "svg_spine_output.epub"
        EPUBDocument.export_merged([doc], "epub", output)

        with zipfile.ZipFile(output, "r") as zf:
            svg_out = zf.read("OEBPS/ch1.svg").decode("utf-8")
            assert "Hola SVG" in svg_out
            assert "Hello SVG" not in svg_out

    def test_export_epub_preserves_nested_toc_parent_href(self, tmp_path: Path):
        book = EpubBook(
            metadata=EpubMetadata(title="TOC Book"),
            spine_items=[
                EpubItem(
                    file_name="OEBPS/part1.xhtml",
                    media_type="application/xhtml+xml",
                    content=b"<html><body><p>Part 1</p></body></html>",
                    item_id="part1",
                ),
                EpubItem(
                    file_name="OEBPS/ch1.xhtml",
                    media_type="application/xhtml+xml",
                    content=b"<html><body><p>Chapter 1</p></body></html>",
                    item_id="ch1",
                ),
            ],
            resources=[],
            toc=[
                TocEntry(
                    title="Part 1",
                    href="part1.xhtml",
                    children=[TocEntry(title="Chapter 1", href="ch1.xhtml")],
                ),
            ],
        )
        epub_path = tmp_path / "toc_input.epub"
        write_epub(epub_path, book)

        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)
        doc_row = repo.list_documents()[0]
        doc = EPUBDocument(repo, doc_row["document_id"])

        for source in repo.get_document_sources(doc_row["document_id"]):
            if EPUBDocument._is_chapter_source(source):
                doc._translated_chapters[source["source_id"]] = source["text_content"]

        output = tmp_path / "toc_output.epub"
        EPUBDocument.export_merged([doc], "epub", output)
        read_back = read_epub(output)
        assert len(read_back.toc) == 1
        assert read_back.toc[0].href == "part1.xhtml"
        assert read_back.toc[0].children is not None
        assert read_back.toc[0].children[0].href == "ch1.xhtml"

    @pytest.mark.asyncio
    async def test_export_epub_syncs_toc_from_chapter_heading_when_matching(self, tmp_path: Path):
        """When original TOC title matches a chapter heading, export uses the
        chapter heading translation for the TOC entry."""
        book = EpubBook(
            metadata=EpubMetadata(title="Sync Book"),
            spine_items=[
                EpubItem(
                    file_name="OEBPS/ch1.xhtml",
                    media_type="application/xhtml+xml",
                    content=b"<html><body><h1>Chapter One</h1><p>Hello world.</p></body></html>",
                    item_id="ch1",
                ),
            ],
            resources=[],
            toc=[TocEntry(title="Chapter One", href="ch1.xhtml")],
        )
        epub_path = tmp_path / "sync_input.epub"
        write_epub(epub_path, book)

        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)
        doc_row = repo.list_documents()[0]
        doc = EPUBDocument(repo, doc_row["document_id"])

        source_lines = doc.get_text().splitlines()
        # Lines: "Chapter One" (heading), "Hello world." (paragraph), "Chapter One" (TOC)
        assert source_lines[0] == "Chapter One"
        assert source_lines[-1] == "Chapter One"

        # Provide *different* translations for heading vs TOC to prove sync works
        translations = list(source_lines)
        translations[0] = "Capitulo Uno"  # heading translation
        translations[1] = "Hola mundo."
        translations[2] = "TOC Diferente"  # intentionally different TOC translation
        consumed = await doc.set_text(translations)
        assert consumed == len(translations)

        output = tmp_path / "sync_output.epub"
        EPUBDocument.export_merged([doc], "epub", output)

        read_back = read_epub(output)
        assert len(read_back.toc) == 1
        # TOC should use the chapter heading translation, NOT the separate TOC translation
        assert read_back.toc[0].title == "Capitulo Uno"

    @pytest.mark.asyncio
    async def test_export_epub_syncs_nested_toc_children_from_headings(self, tmp_path: Path):
        """Nested TOC children are also synced with chapter heading translations."""
        book = EpubBook(
            metadata=EpubMetadata(title="Nested Sync"),
            spine_items=[
                EpubItem(
                    file_name="OEBPS/part1.xhtml",
                    media_type="application/xhtml+xml",
                    content=b"<html><body><h1>Part One</h1><p>Intro.</p></body></html>",
                    item_id="part1",
                ),
                EpubItem(
                    file_name="OEBPS/ch1.xhtml",
                    media_type="application/xhtml+xml",
                    content=b"<html><body><h2>Chapter Alpha</h2><p>Text.</p></body></html>",
                    item_id="ch1",
                ),
            ],
            resources=[],
            toc=[
                TocEntry(
                    title="Part One",
                    href="part1.xhtml",
                    children=[TocEntry(title="Chapter Alpha", href="ch1.xhtml")],
                ),
            ],
        )
        epub_path = tmp_path / "nested_sync_input.epub"
        write_epub(epub_path, book)

        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)
        doc_row = repo.list_documents()[0]
        doc = EPUBDocument(repo, doc_row["document_id"])

        source_lines = doc.get_text().splitlines()
        translations = list(source_lines)
        # Translate headings in chapters
        translations[source_lines.index("Part One")] = "Primera Parte"
        translations[source_lines.index("Chapter Alpha")] = "Capitulo Alfa"
        # Provide different translations for TOC entries
        toc_start = len(translations) - 2  # last two lines are TOC titles
        translations[toc_start] = "TOC Part"
        translations[toc_start + 1] = "TOC Chapter"
        consumed = await doc.set_text(translations)
        assert consumed == len(translations)

        output = tmp_path / "nested_sync_output.epub"
        EPUBDocument.export_merged([doc], "epub", output)

        read_back = read_epub(output)
        assert len(read_back.toc) == 1
        # Parent synced from heading
        assert read_back.toc[0].title == "Primera Parte"
        # Child synced from heading
        assert read_back.toc[0].children is not None
        assert read_back.toc[0].children[0].title == "Capitulo Alfa"

    @pytest.mark.asyncio
    async def test_export_epub_keeps_toc_translation_when_not_matching_heading(self, tmp_path: Path):
        """When original TOC title does NOT match any chapter heading, the
        independently translated TOC title is preserved."""
        book = EpubBook(
            metadata=EpubMetadata(title="No Sync Book"),
            spine_items=[
                EpubItem(
                    file_name="OEBPS/ch1.xhtml",
                    media_type="application/xhtml+xml",
                    content=b"<html><body><h1>Chapter One</h1><p>Content.</p></body></html>",
                    item_id="ch1",
                ),
            ],
            resources=[],
            # TOC title is different from the heading
            toc=[TocEntry(title="1. First Chapter", href="ch1.xhtml")],
        )
        epub_path = tmp_path / "nosync_input.epub"
        write_epub(epub_path, book)

        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)
        doc_row = repo.list_documents()[0]
        doc = EPUBDocument(repo, doc_row["document_id"])

        source_lines = doc.get_text().splitlines()
        translations = list(source_lines)
        translations[source_lines.index("Chapter One")] = "Capitulo Uno"  # heading
        translations[source_lines.index("Content.")] = "Contenido."
        translations[source_lines.index("1. First Chapter")] = "1. Primer Capitulo"  # TOC (different from heading)
        consumed = await doc.set_text(translations)
        assert consumed == len(translations)

        output = tmp_path / "nosync_output.epub"
        EPUBDocument.export_merged([doc], "epub", output)

        read_back = read_epub(output)
        assert len(read_back.toc) == 1
        # TOC should keep its own independent translation
        assert read_back.toc[0].title == "1. Primer Capitulo"

    def test_export_epub_applies_persisted_reembedded_image(self, tmp_path: Path):
        original_png = _png_bytes((10, 10, 10), size=(8, 8))
        replacement_png = _png_bytes((220, 30, 30), size=(8, 8))

        epub_path = _make_epub_file(
            tmp_path,
            chapters=[("ch1.xhtml", "<html><body><p>Hello</p></body></html>")],
            images=[("images/fig1.png", original_png, "image/png")],
        )
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        doc_row = repo.list_documents()[0]
        source_rows = repo.get_document_sources(doc_row["document_id"])
        image_source = next(s for s in source_rows if EPUBDocument._is_content_image(s))
        source_id = image_source["source_id"]

        ocr_json = [
            {
                "page_type": "content",
                "content": [
                    {
                        "type": "image",
                        "bbox": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
                        "embedded_text": "Original",
                    }
                ],
            }
        ]
        repo.update_source_ocr(source_id, json.dumps(ocr_json))
        repo.update_source_ocr_completed(source_id)
        repo.save_reembedded_image(doc_row["document_id"], source_id * 1_000_000, replacement_png, "image/png")

        doc = EPUBDocument(repo, doc_row["document_id"])
        for source in source_rows:
            if EPUBDocument._is_chapter_source(source):
                doc._translated_chapters[source["source_id"]] = source["text_content"]

        output = tmp_path / "reembedded_output.epub"
        EPUBDocument.export_merged([doc], "epub", output)
        read_back = read_epub(output)
        exported_image = next(r for r in read_back.resources if r.file_name.endswith("fig1.png"))

        pixel = Image.open(io.BytesIO(exported_image.content)).convert("RGB").getpixel((0, 0))
        assert pixel == (220, 30, 30)


# =========================================================================
# Tests: is_text_added / mark_text_added
# =========================================================================


class TestTextAdded:
    def test_is_text_added_initially_false(self, tmp_path: Path):
        chapters = [
            ("ch1.xhtml", "<html><body><p>Hello</p></body></html>"),
        ]
        epub_path = _make_epub_file(tmp_path, chapters=chapters)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        docs = repo.list_documents()
        doc = EPUBDocument(repo, docs[0]["document_id"])
        # Not all sources have is_text_added=1 (chapters don't)
        assert doc.is_text_added() is False

    def test_mark_text_added(self, tmp_path: Path):
        chapters = [
            ("ch1.xhtml", "<html><body><p>Hello</p></body></html>"),
        ]
        epub_path = _make_epub_file(tmp_path, chapters=chapters)
        repo = _setup_repo(tmp_path)
        EPUBDocument.do_import(repo, epub_path)

        docs = repo.list_documents()
        doc = EPUBDocument(repo, docs[0]["document_id"])

        doc.mark_text_added()
        assert doc.is_text_added() is True
