"""Tests for epub_container module — stdlib EPUB reader/writer."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from context_aware_translation.documents.epub_container import (
    EpubBook,
    EpubItem,
    EpubMetadata,
    TocEntry,
    read_epub,
    write_epub,
)


def test_write_read_roundtrip(tmp_path: Path) -> None:
    """Test write_epub + read_epub round-trip with full book structure."""
    epub_path = tmp_path / "test.epub"

    # Create a book with metadata, spine items, resources, and TOC
    metadata = EpubMetadata(
        title="Test Book",
        authors=["Author One", "Author Two"],
        language="en",
        identifier="test-123",
    )

    spine_items = [
        EpubItem(
            file_name="OEBPS/chapter1.xhtml",
            media_type="application/xhtml+xml",
            content=b"<html><body><h1>Chapter 1</h1></body></html>",
            item_id="chapter1",
        ),
        EpubItem(
            file_name="OEBPS/chapter2.xhtml",
            media_type="application/xhtml+xml",
            content=b"<html><body><h1>Chapter 2</h1></body></html>",
            item_id="chapter2",
        ),
    ]

    resources = [
        EpubItem(
            file_name="OEBPS/style.css",
            media_type="text/css",
            content=b"body { margin: 0; }",
            item_id="style",
        ),
        EpubItem(
            file_name="OEBPS/image.png",
            media_type="image/png",
            content=b"\x89PNG\r\n\x1a\n",  # PNG header
            item_id="image1",
        ),
    ]

    toc = [
        TocEntry(title="Chapter 1", href="chapter1.xhtml"),
        TocEntry(title="Chapter 2", href="chapter2.xhtml"),
    ]

    book = EpubBook(
        metadata=metadata,
        spine_items=spine_items,
        resources=resources,
        toc=toc,
    )

    # Write and read back
    write_epub(epub_path, book)
    read_book = read_epub(epub_path)

    # Verify metadata
    assert read_book.metadata.title == "Test Book"
    assert read_book.metadata.authors == ["Author One", "Author Two"]
    assert read_book.metadata.language == "en"
    assert read_book.metadata.identifier == "test-123"

    # Verify spine items
    assert len(read_book.spine_items) == 2
    assert read_book.spine_items[0].file_name == "OEBPS/chapter1.xhtml"
    assert read_book.spine_items[0].media_type == "application/xhtml+xml"
    assert b"Chapter 1" in read_book.spine_items[0].content
    assert read_book.spine_items[1].file_name == "OEBPS/chapter2.xhtml"
    assert b"Chapter 2" in read_book.spine_items[1].content

    # Verify resources
    assert len(read_book.resources) >= 2
    css_resource = next(r for r in read_book.resources if r.file_name == "OEBPS/style.css")
    assert css_resource.media_type == "text/css"
    assert css_resource.content == b"body { margin: 0; }"

    image_resource = next(r for r in read_book.resources if r.file_name == "OEBPS/image.png")
    assert image_resource.media_type == "image/png"
    assert image_resource.content == b"\x89PNG\r\n\x1a\n"

    # Verify TOC
    assert len(read_book.toc) == 2
    assert read_book.toc[0].title == "Chapter 1"
    assert read_book.toc[0].href == "chapter1.xhtml"
    assert read_book.toc[1].title == "Chapter 2"
    assert read_book.toc[1].href == "chapter2.xhtml"


def test_epub_zip_structure(tmp_path: Path) -> None:
    """Test that written EPUB has correct ZIP structure."""
    epub_path = tmp_path / "test.epub"

    metadata = EpubMetadata(title="Test")
    spine_items = [
        EpubItem(
            file_name="OEBPS/chapter1.xhtml",
            media_type="application/xhtml+xml",
            content=b"<html><body>Content</body></html>",
            item_id="ch1",
        ),
    ]

    book = EpubBook(
        metadata=metadata,
        spine_items=spine_items,
        resources=[],
        toc=[],
    )

    write_epub(epub_path, book)

    # Verify ZIP structure
    with zipfile.ZipFile(epub_path, "r") as zf:
        namelist = zf.namelist()

        # mimetype must be first entry and uncompressed
        assert namelist[0] == "mimetype"
        mimetype_info = zf.getinfo("mimetype")
        assert mimetype_info.compress_type == zipfile.ZIP_STORED

        # Required files exist
        assert "META-INF/container.xml" in namelist
        assert "OEBPS/content.opf" in namelist
        assert "OEBPS/toc.ncx" in namelist
        assert "OEBPS/nav.xhtml" in namelist

        # Verify mimetype content
        assert zf.read("mimetype") == b"application/epub+zip"


def test_read_epub_malformed_non_zip(tmp_path: Path) -> None:
    """Test read_epub raises ValueError for non-ZIP file."""
    bad_file = tmp_path / "bad.epub"
    bad_file.write_text("not a zip file")

    with pytest.raises(ValueError, match="Cannot open EPUB"):
        read_epub(bad_file)


def test_read_epub_malformed_missing_container(tmp_path: Path) -> None:
    """Test read_epub raises ValueError for ZIP without container.xml."""
    bad_epub = tmp_path / "bad.epub"

    with zipfile.ZipFile(bad_epub, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        # Missing META-INF/container.xml

    with pytest.raises(ValueError, match="META-INF/container.xml"):
        read_epub(bad_epub)


def test_read_epub_malformed_missing_opf(tmp_path: Path) -> None:
    """Test read_epub raises ValueError for container.xml pointing to missing OPF."""
    bad_epub = tmp_path / "bad.epub"

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    with zipfile.ZipFile(bad_epub, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container_xml)
        # Missing OEBPS/content.opf

    with pytest.raises(ValueError, match="OPF file.*not found"):
        read_epub(bad_epub)


def test_read_epub_malformed_missing_mimetype_entry(tmp_path: Path) -> None:
    """Test read_epub raises ValueError if mimetype entry is missing."""
    bad_epub = tmp_path / "bad.epub"

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Bad EPUB</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>"""

    with zipfile.ZipFile(bad_epub, "w") as zf:
        # Missing mimetype
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        zf.writestr("OEBPS/ch1.xhtml", "<html><body><p>Test</p></body></html>")

    with pytest.raises(ValueError, match="Missing 'mimetype' entry"):
        read_epub(bad_epub)


def test_read_epub_malformed_wrong_mimetype_content(tmp_path: Path) -> None:
    """Test read_epub raises ValueError for wrong mimetype content."""
    bad_epub = tmp_path / "bad.epub"

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Bad EPUB</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>"""

    with zipfile.ZipFile(bad_epub, "w") as zf:
        zf.writestr("mimetype", "application/zip")
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        zf.writestr("OEBPS/ch1.xhtml", "<html><body><p>Test</p></body></html>")

    with pytest.raises(ValueError, match="Invalid EPUB mimetype content"):
        read_epub(bad_epub)


def test_read_epub_malformed_missing_manifest_resource(tmp_path: Path) -> None:
    """Test read_epub raises ValueError for missing non-spine manifest resources."""
    bad_epub = tmp_path / "bad.epub"

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Bad EPUB</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="css1" href="styles/main.css" media-type="text/css"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>"""

    with zipfile.ZipFile(bad_epub, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        zf.writestr("OEBPS/ch1.xhtml", "<html><body><p>Test</p></body></html>")
        # Missing OEBPS/styles/main.css

    with pytest.raises(ValueError, match="Manifest resource.*not found"):
        read_epub(bad_epub)


def test_read_epub_malformed_duplicate_manifest_id(tmp_path: Path) -> None:
    """Manifest item ids must be unique."""
    bad_epub = tmp_path / "bad_duplicate_manifest_id.epub"

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Duplicate Manifest ID</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch1" href="ch2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>"""

    with zipfile.ZipFile(bad_epub, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        zf.writestr("OEBPS/ch1.xhtml", "<html><body><p>One</p></body></html>")
        zf.writestr("OEBPS/ch2.xhtml", "<html><body><p>Two</p></body></html>")

    with pytest.raises(ValueError, match="Duplicate manifest item id"):
        read_epub(bad_epub)


def test_read_epub_malformed_manifest_item_missing_media_type(tmp_path: Path) -> None:
    """Manifest items missing media-type should fail import."""
    bad_epub = tmp_path / "bad_missing_media_type.epub"

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Missing Media Type</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>"""

    with zipfile.ZipFile(bad_epub, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        zf.writestr("OEBPS/ch1.xhtml", "<html><body><p>One</p></body></html>")

    with pytest.raises(ValueError, match="missing required 'media-type'"):
        read_epub(bad_epub)


def test_read_epub_malformed_duplicate_spine_itemref(tmp_path: Path) -> None:
    """Spine idrefs must not repeat."""
    bad_epub = tmp_path / "bad_duplicate_spine_idref.epub"

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Duplicate Spine</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
    <itemref idref="ch1"/>
  </spine>
</package>"""

    with zipfile.ZipFile(bad_epub, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        zf.writestr("OEBPS/ch1.xhtml", "<html><body><p>One</p></body></html>")

    with pytest.raises(ValueError, match="Duplicate spine itemref idref"):
        read_epub(bad_epub)


def test_read_epub_malformed_spine_missing_manifest_item(tmp_path: Path) -> None:
    """Spine idrefs must point to existing manifest items."""
    bad_epub = tmp_path / "bad_spine_missing_manifest_item.epub"

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Missing Spine Target</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="missing"/>
  </spine>
</package>"""

    with zipfile.ZipFile(bad_epub, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        zf.writestr("OEBPS/ch1.xhtml", "<html><body><p>One</p></body></html>")

    with pytest.raises(ValueError, match="references missing manifest item"):
        read_epub(bad_epub)


def test_read_epub_malformed_unsupported_zip_compression(tmp_path: Path) -> None:
    """Only STORED and DEFLATED compression methods are supported."""
    if not hasattr(zipfile, "ZIP_BZIP2"):
        pytest.skip("ZIP_BZIP2 is not available in this Python build")

    bad_epub = tmp_path / "bad_zip_compression.epub"

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Bad Compression</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>"""

    with zipfile.ZipFile(bad_epub, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        try:
            zf.writestr("META-INF/container.xml", container_xml, compress_type=zipfile.ZIP_BZIP2)
        except (RuntimeError, NotImplementedError):
            pytest.skip("BZIP2 compression is not supported by this runtime")
        zf.writestr("OEBPS/content.opf", opf_xml, compress_type=zipfile.ZIP_BZIP2)
        zf.writestr(
            "OEBPS/ch1.xhtml",
            "<html><body><p>One</p></body></html>",
            compress_type=zipfile.ZIP_BZIP2,
        )

    with pytest.raises(ValueError, match="unsupported ZIP compression method"):
        read_epub(bad_epub)


def test_read_epub_rejects_encrypted_epub(tmp_path: Path) -> None:
    """Encrypted/DRM EPUBs should fail fast with a clear error."""
    bad_epub = tmp_path / "encrypted.epub"

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Encrypted</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>"""

    encryption_xml = """<?xml version="1.0" encoding="UTF-8"?>
<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <EncryptedData xmlns="http://www.w3.org/2001/04/xmlenc#"/>
</encryption>"""

    with zipfile.ZipFile(bad_epub, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("META-INF/encryption.xml", encryption_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        zf.writestr("OEBPS/ch1.xhtml", "<html><body><p>Test</p></body></html>")

    with pytest.raises(ValueError, match="Encrypted/DRM EPUB is not supported"):
        read_epub(bad_epub)


def test_read_epub_allows_signed_epub(tmp_path: Path) -> None:
    """Signed EPUBs are valid and should not be treated as encrypted/DRM."""
    signed_epub = tmp_path / "signed.epub"

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Signed</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>"""

    signatures_xml = """<?xml version="1.0" encoding="UTF-8"?>
<signatures xmlns="urn:oasis:names:tc:opendocument:xmlns:container"/>"""

    with zipfile.ZipFile(signed_epub, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("META-INF/signatures.xml", signatures_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        zf.writestr("OEBPS/ch1.xhtml", "<html><body><p>Signed book</p></body></html>")

    book = read_epub(signed_epub)
    assert len(book.spine_items) == 1
    assert book.spine_items[0].file_name == "OEBPS/ch1.xhtml"


def test_read_epub_rejects_invalid_rootfile_media_type(tmp_path: Path) -> None:
    """container.xml rootfile media-type must point to OPF package documents."""
    bad_epub = tmp_path / "bad_rootfile.epub"

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/not-opf+xml"/>
  </rootfiles>
</container>"""

    with zipfile.ZipFile(bad_epub, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container_xml)

    with pytest.raises(ValueError, match="No valid OPF rootfile found"):
        read_epub(bad_epub)


def test_read_epub_rejects_multiple_rootfiles(tmp_path: Path) -> None:
    """Multiple OPF rootfiles (multi-rendition) are currently unsupported."""
    bad_epub = tmp_path / "multiple_rootfiles.epub"

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
    <rootfile full-path="OPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Two Renditions</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>"""

    with zipfile.ZipFile(bad_epub, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        zf.writestr("OPS/content.opf", opf_xml)
        zf.writestr("OEBPS/ch1.xhtml", "<html><body><p>A</p></body></html>")
        zf.writestr("OPS/ch1.xhtml", "<html><body><p>B</p></body></html>")

    with pytest.raises(ValueError, match="Multiple OPF rootfiles are not supported"):
        read_epub(bad_epub)


def test_read_epub_resolves_parent_relative_href(tmp_path: Path) -> None:
    """Manifest hrefs like ../chapters/ch1.xhtml should resolve correctly."""
    epub_path = tmp_path / "relative.epub"

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Relative Path Test</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="../chapters/ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>"""

    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        zf.writestr("chapters/ch1.xhtml", "<html><body><p>Resolved</p></body></html>")

    book = read_epub(epub_path)
    assert len(book.spine_items) == 1
    assert book.spine_items[0].file_name == "chapters/ch1.xhtml"
    assert b"Resolved" in book.spine_items[0].content


def test_read_epub_resolves_percent_encoded_manifest_href(tmp_path: Path) -> None:
    """Manifest hrefs with URL-encoded characters should resolve to ZIP members."""
    epub_path = tmp_path / "encoded_href.epub"

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Encoded Href</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="chapters/Chapter%201.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>"""

    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        zf.writestr("OEBPS/chapters/Chapter 1.xhtml", "<html><body><p>Encoded</p></body></html>")

    book = read_epub(epub_path)
    assert len(book.spine_items) == 1
    assert b"Encoded" in book.spine_items[0].content


def test_read_epub_resolves_xml_base_manifest_href(tmp_path: Path) -> None:
    """Manifest hrefs should respect xml:base inheritance."""
    epub_path = tmp_path / "xml_base.epub"

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OPS/package.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" xml:base="../">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>XML Base</dc:title>
  </metadata>
  <manifest xml:base="assets/">
    <item id="ch1" href="chapters/ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>"""

    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OPS/package.opf", opf_xml)
        zf.writestr("assets/chapters/ch1.xhtml", "<html><body><p>XML Base Text</p></body></html>")

    book = read_epub(epub_path)
    assert len(book.spine_items) == 1
    assert book.spine_items[0].file_name == "assets/chapters/ch1.xhtml"
    assert b"XML Base Text" in book.spine_items[0].content


def test_write_epub_uses_non_oebps_package_dir(tmp_path: Path) -> None:
    """Books rooted under non-OEBPS dirs should round-trip without broken hrefs."""
    epub_path = tmp_path / "non_oebps.epub"

    book = EpubBook(
        metadata=EpubMetadata(title="Non-OEBPS Root"),
        spine_items=[
            EpubItem(
                file_name="EPUB/chapter1.xhtml",
                media_type="application/xhtml+xml",
                content=b"<html><body><p>Chapter from EPUB/</p></body></html>",
                item_id="ch1",
            ),
        ],
        resources=[],
        toc=[TocEntry(title="Chapter 1", href="chapter1.xhtml")],
    )

    write_epub(epub_path, book)
    read_back = read_epub(epub_path)
    assert len(read_back.spine_items) == 1
    assert read_back.spine_items[0].file_name == "EPUB/chapter1.xhtml"
    assert b"Chapter from EPUB/" in read_back.spine_items[0].content

    with zipfile.ZipFile(epub_path, "r") as zf:
        container_data = zf.read("META-INF/container.xml").decode("utf-8")
        assert 'full-path="EPUB/content.opf"' in container_data
        assert "EPUB/content.opf" in zf.namelist()


def test_write_epub_preserves_custom_package_path(tmp_path: Path) -> None:
    """Writer should preserve explicit container rootfile paths and OPF filenames."""
    epub_path = tmp_path / "custom_package_path.epub"

    book = EpubBook(
        metadata=EpubMetadata(title="Custom OPF Path"),
        spine_items=[
            EpubItem(
                file_name="OPS/chapter1.xhtml",
                media_type="application/xhtml+xml",
                content=b"<html><body><p>Custom package path</p></body></html>",
                item_id="ch1",
            ),
        ],
        resources=[],
        toc=[TocEntry(title="Chapter 1", href="chapter1.xhtml")],
        package_path="OPS/custom-package.opf",
    )

    write_epub(epub_path, book)

    with zipfile.ZipFile(epub_path, "r") as zf:
        names = zf.namelist()
        assert "OPS/custom-package.opf" in names
        assert "OPS/content.opf" not in names
        container_data = zf.read("META-INF/container.xml").decode("utf-8")
        assert 'full-path="OPS/custom-package.opf"' in container_data

    read_back = read_epub(epub_path)
    assert read_back.package_path == "OPS/custom-package.opf"


def test_write_epub_supports_root_package_path(tmp_path: Path) -> None:
    """Root-level package paths should not be normalized into OEBPS/."""
    epub_path = tmp_path / "root_package_path.epub"

    book = EpubBook(
        metadata=EpubMetadata(title="Root OPF"),
        spine_items=[
            EpubItem(
                file_name="chapter1.xhtml",
                media_type="application/xhtml+xml",
                content=b"<html><body><p>Root chapter</p></body></html>",
                item_id="ch1",
            ),
        ],
        resources=[],
        toc=[TocEntry(title="Chapter 1", href="chapter1.xhtml")],
        package_path="root.opf",
    )

    write_epub(epub_path, book)

    with zipfile.ZipFile(epub_path, "r") as zf:
        names = zf.namelist()
        assert "root.opf" in names
        assert "chapter1.xhtml" in names
        assert "__ROOT__/root.opf" not in names
        assert "__ROOT__/chapter1.xhtml" not in names
        container_data = zf.read("META-INF/container.xml").decode("utf-8")
        assert 'full-path="root.opf"' in container_data

    read_back = read_epub(epub_path)
    assert read_back.package_path == "root.opf"
    assert read_back.spine_items[0].file_name == "chapter1.xhtml"


def test_write_epub_handles_xml_declaration_in_spine_content(tmp_path: Path) -> None:
    """Spine XHTML with XML declaration should not be emitted as empty content."""
    epub_path = tmp_path / "xml_decl.epub"

    book = EpubBook(
        metadata=EpubMetadata(title="XML Decl"),
        spine_items=[
            EpubItem(
                file_name="OEBPS/ch1.xhtml",
                media_type="application/xhtml+xml",
                content=(
                    b'<?xml version="1.0" encoding="UTF-8"?>\n'
                    b"<!DOCTYPE html>\n"
                    b'<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Declared</p></body></html>'
                ),
                item_id="ch1",
            )
        ],
        resources=[],
        toc=[TocEntry(title="Chapter 1", href="ch1.xhtml")],
    )

    write_epub(epub_path, book)

    with zipfile.ZipFile(epub_path, "r") as zf:
        chapter_payload = zf.read("OEBPS/ch1.xhtml")
        assert len(chapter_payload) > 0
        assert b"Declared" in chapter_payload

    read_back = read_epub(epub_path)
    assert len(read_back.spine_items) == 1
    assert b"Declared" in read_back.spine_items[0].content


def test_write_read_roundtrip_svg_spine_item(tmp_path: Path) -> None:
    """SVG content documents in spine should round-trip as spine items."""
    epub_path = tmp_path / "svg_spine.epub"

    book = EpubBook(
        metadata=EpubMetadata(title="SVG Spine"),
        spine_items=[
            EpubItem(
                file_name="OEBPS/figure.svg",
                media_type="image/svg+xml",
                content=b'<svg xmlns="http://www.w3.org/2000/svg"><text>Vector spine</text></svg>',
                item_id="svgspine",
            ),
        ],
        resources=[],
        toc=[],
    )

    write_epub(epub_path, book)
    read_back = read_epub(epub_path)

    assert len(read_back.spine_items) == 1
    assert read_back.spine_items[0].media_type == "image/svg+xml"
    assert b"Vector spine" in read_back.spine_items[0].content


def test_write_read_roundtrip_raster_spine_item(tmp_path: Path) -> None:
    """Lenient reader should accept raster image media types in spine."""
    epub_path = tmp_path / "raster_spine.epub"
    png_payload = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"

    book = EpubBook(
        metadata=EpubMetadata(title="Raster Spine"),
        spine_items=[
            EpubItem(
                file_name="OEBPS/page1.png",
                media_type="image/png",
                content=png_payload,
                item_id="imgspine",
            ),
        ],
        resources=[],
        toc=[],
    )

    write_epub(epub_path, book)
    read_back = read_epub(epub_path)

    assert len(read_back.spine_items) == 1
    assert read_back.spine_items[0].media_type == "image/png"
    assert read_back.spine_items[0].content == png_payload


def test_metadata_extraction(tmp_path: Path) -> None:
    """Test all metadata fields are correctly extracted after round-trip."""
    epub_path = tmp_path / "test.epub"

    metadata = EpubMetadata(
        title="Complete Metadata Test",
        authors=["First Author", "Second Author", "Third Author"],
        language="fr",
        identifier="isbn:1234567890",
    )

    spine_items = [
        EpubItem(
            file_name="OEBPS/content.xhtml",
            media_type="application/xhtml+xml",
            content=b"<html><body>Test</body></html>",
            item_id="content",
        ),
    ]

    book = EpubBook(
        metadata=metadata,
        spine_items=spine_items,
        resources=[],
        toc=[],
    )

    write_epub(epub_path, book)
    read_book = read_epub(epub_path)

    assert read_book.metadata.title == "Complete Metadata Test"
    assert read_book.metadata.authors == ["First Author", "Second Author", "Third Author"]
    assert read_book.metadata.language == "fr"
    assert read_book.metadata.identifier == "isbn:1234567890"


def test_toc_with_nested_children(tmp_path: Path) -> None:
    """Test TOC with nested children is preserved after round-trip."""
    epub_path = tmp_path / "test.epub"

    metadata = EpubMetadata(title="Nested TOC Test")
    spine_items = [
        EpubItem(
            file_name="OEBPS/part1.xhtml",
            media_type="application/xhtml+xml",
            content=b"<html><body>Part 1</body></html>",
            item_id="part1",
        ),
        EpubItem(
            file_name="OEBPS/chapter1.xhtml",
            media_type="application/xhtml+xml",
            content=b"<html><body>Chapter 1</body></html>",
            item_id="ch1",
        ),
        EpubItem(
            file_name="OEBPS/chapter2.xhtml",
            media_type="application/xhtml+xml",
            content=b"<html><body>Chapter 2</body></html>",
            item_id="ch2",
        ),
    ]

    toc = [
        TocEntry(
            title="Part 1",
            href="part1.xhtml",
            children=[
                TocEntry(title="Chapter 1", href="chapter1.xhtml"),
                TocEntry(title="Chapter 2", href="chapter2.xhtml"),
            ],
        ),
    ]

    book = EpubBook(
        metadata=metadata,
        spine_items=spine_items,
        resources=[],
        toc=toc,
    )

    write_epub(epub_path, book)
    read_book = read_epub(epub_path)

    # Verify nested structure
    assert len(read_book.toc) == 1
    assert read_book.toc[0].title == "Part 1"
    assert read_book.toc[0].href == "part1.xhtml"
    assert read_book.toc[0].children is not None
    assert len(read_book.toc[0].children) == 2
    assert read_book.toc[0].children[0].title == "Chapter 1"
    assert read_book.toc[0].children[0].href == "chapter1.xhtml"
    assert read_book.toc[0].children[1].title == "Chapter 2"
    assert read_book.toc[0].children[1].href == "chapter2.xhtml"


def test_empty_book(tmp_path: Path) -> None:
    """Test that an empty book with no spine, resources, or TOC can be written and read."""
    epub_path = tmp_path / "empty.epub"

    metadata = EpubMetadata(title="Empty Book")
    book = EpubBook(
        metadata=metadata,
        spine_items=[],
        resources=[],
        toc=[],
    )

    write_epub(epub_path, book)
    read_book = read_epub(epub_path)

    assert read_book.metadata.title == "Empty Book"
    assert len(read_book.spine_items) == 0
    assert len(read_book.resources) == 2
    assert any(r.media_type == "application/x-dtbncx+xml" for r in read_book.resources)
    assert any("nav" in r.properties.split() for r in read_book.resources)
    assert len(read_book.toc) == 0


def test_resources_preserved(tmp_path: Path) -> None:
    """Test that CSS and image resources survive round-trip with correct media_type and content."""
    epub_path = tmp_path / "test.epub"

    metadata = EpubMetadata(title="Resources Test")
    spine_items = [
        EpubItem(
            file_name="OEBPS/index.xhtml",
            media_type="application/xhtml+xml",
            content=b"<html><body>Index</body></html>",
            item_id="index",
        ),
    ]

    # Various resource types
    css_content = b"h1 { color: blue; font-size: 24px; }"
    png_content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"  # PNG header + partial data
    jpg_content = b"\xff\xd8\xff\xe0"  # JPEG header

    resources = [
        EpubItem(
            file_name="OEBPS/styles/main.css",
            media_type="text/css",
            content=css_content,
            item_id="css1",
        ),
        EpubItem(
            file_name="OEBPS/images/cover.png",
            media_type="image/png",
            content=png_content,
            item_id="img1",
        ),
        EpubItem(
            file_name="OEBPS/images/photo.jpg",
            media_type="image/jpeg",
            content=jpg_content,
            item_id="img2",
        ),
    ]

    book = EpubBook(
        metadata=metadata,
        spine_items=spine_items,
        resources=resources,
        toc=[],
    )

    write_epub(epub_path, book)
    read_book = read_epub(epub_path)

    # Verify all resources preserved
    assert len(read_book.resources) >= 3

    css = next(r for r in read_book.resources if "css" in r.file_name)
    assert css.media_type == "text/css"
    assert css.content == css_content

    png = next(r for r in read_book.resources if "cover.png" in r.file_name)
    assert png.media_type == "image/png"
    assert png.content == png_content

    jpg = next(r for r in read_book.resources if "photo.jpg" in r.file_name)
    assert jpg.media_type == "image/jpeg"
    assert jpg.content == jpg_content


def test_read_epub_resolves_spine_fallback_chain(tmp_path: Path) -> None:
    """Foreign spine items should resolve through fallback chains to XHTML content."""
    epub_path = tmp_path / "fallback.epub"

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Fallback Test</dc:title>
  </metadata>
  <manifest>
    <item id="foreign" href="media/ch1.dat" media-type="application/x-custom" fallback="ch1"/>
    <item id="ch1" href="chapters/ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="foreign" linear="no" properties="page-spread-left"/>
  </spine>
</package>"""

    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        zf.writestr("OEBPS/media/ch1.dat", b"placeholder")
        zf.writestr(
            "OEBPS/chapters/ch1.xhtml",
            '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Resolved fallback text</p></body></html>',
        )

    book = read_epub(epub_path)
    assert len(book.spine_items) == 1
    spine_item = book.spine_items[0]
    assert spine_item.item_id == "foreign"
    assert spine_item.linear is False
    assert spine_item.spine_properties == "page-spread-left"
    assert spine_item.file_name == "OEBPS/chapters/ch1.xhtml"
    assert b"Resolved fallback text" in spine_item.content
    assert len(book.resources) == 0


def test_read_epub_prefers_textual_fallback_over_raster_spine(tmp_path: Path) -> None:
    """Raster spine items should resolve to textual fallback when available."""
    epub_path = tmp_path / "image_fallback.epub"

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Image Fallback</dc:title>
  </metadata>
  <manifest>
    <item id="img1" href="page1.png" media-type="image/png" fallback="ch1"/>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="img1"/>
  </spine>
</package>"""

    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        zf.writestr("OEBPS/page1.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
        zf.writestr(
            "OEBPS/ch1.xhtml",
            '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Fallback chapter</p></body></html>',
        )

    book = read_epub(epub_path)
    assert len(book.spine_items) == 1
    spine_item = book.spine_items[0]
    assert spine_item.item_id == "img1"
    assert spine_item.media_type == "application/xhtml+xml"
    assert spine_item.file_name == "OEBPS/ch1.xhtml"
    assert b"Fallback chapter" in spine_item.content
    assert len(book.resources) == 0


def test_write_epub_preserves_manifest_and_spine_attributes(tmp_path: Path) -> None:
    """Exported OPF should keep per-item manifest attrs and spine itemref attrs."""
    epub_path = tmp_path / "attrs.epub"

    book = EpubBook(
        metadata=EpubMetadata(title="Attrs"),
        spine_items=[
            EpubItem(
                file_name="OEBPS/ch1.xhtml",
                media_type="application/xhtml+xml",
                content=b'<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Text</p></body></html>',
                item_id="ch1",
                properties="scripted",
                media_overlay="mo1",
                linear=False,
                spine_properties="page-spread-left",
            )
        ],
        resources=[
            EpubItem(
                file_name="OEBPS/mo.smil",
                media_type="application/smil+xml",
                content=b"<smil/>",
                item_id="mo1",
            )
        ],
        toc=[TocEntry(title="Chapter 1", href="ch1.xhtml")],
    )

    write_epub(epub_path, book)

    with zipfile.ZipFile(epub_path, "r") as zf:
        opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert 'id="ch1"' in opf
        assert 'properties="scripted"' in opf
        assert 'media-overlay="mo1"' in opf
        assert 'itemref idref="ch1"' in opf
        assert 'linear="no"' in opf
        assert 'properties="page-spread-left"' in opf


def test_write_read_roundtrip_with_remote_manifest_resource(tmp_path: Path) -> None:
    """Remote non-spine manifest items should be preserved in OPF and reader output."""
    epub_path = tmp_path / "remote_resource.epub"

    book = EpubBook(
        metadata=EpubMetadata(title="Remote Resource Book"),
        spine_items=[
            EpubItem(
                file_name="OEBPS/ch1.xhtml",
                media_type="application/xhtml+xml",
                content=b'<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Body</p></body></html>',
                item_id="ch1",
            )
        ],
        resources=[],
        remote_resources=[
            EpubItem(
                file_name="https://example.com/styles.css",
                media_type="text/css",
                content=b"",
                item_id="remote_css",
                properties="remote-resources",
                original_href="https://example.com/styles.css",
                is_remote=True,
            )
        ],
        toc=[TocEntry(title="Chapter 1", href="ch1.xhtml")],
    )

    write_epub(epub_path, book)

    with zipfile.ZipFile(epub_path, "r") as zf:
        opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert 'id="remote_css"' in opf
        assert 'href="https://example.com/styles.css"' in opf
        assert 'properties="remote-resources"' in opf

    read_back = read_epub(epub_path)
    assert len(read_back.remote_resources) == 1
    assert read_back.remote_resources[0].item_id == "remote_css"
    assert read_back.remote_resources[0].is_remote is True


def test_write_read_preserves_nav_page_list_sections(tmp_path: Path) -> None:
    """Custom nav sections (e.g. page-list) should survive import/export."""
    input_epub = tmp_path / "nav_sections_input.epub"
    output_epub = tmp_path / "nav_sections_output.epub"

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Nav Sections</dc:title>
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
  </body>
</html>"""

    ncx_xml = """<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head></head>
  <docTitle><text>Nav Sections</text></docTitle>
  <navMap>
    <navPoint id="navPoint-1" playOrder="1">
      <navLabel><text>Chapter 1</text></navLabel>
      <content src="ch1.xhtml"/>
    </navPoint>
  </navMap>
</ncx>"""

    with zipfile.ZipFile(input_epub, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        zf.writestr("OEBPS/ch1.xhtml", "<html><body><p>Hello</p></body></html>")
        zf.writestr("OEBPS/nav.xhtml", nav_xhtml)
        zf.writestr("OEBPS/toc.ncx", ncx_xml)

    book = read_epub(input_epub)
    write_epub(output_epub, book)

    with zipfile.ZipFile(output_epub, "r") as zf:
        nav_out = zf.read("OEBPS/nav.xhtml").decode("utf-8")
        assert "page-list" in nav_out
        assert "Page i" in nav_out


def test_read_epub_parses_prefixed_toc_nav_type(tmp_path: Path) -> None:
    """Nav TOC parsing should handle prefixed tokens like z3998:toc."""
    epub_path = tmp_path / "prefixed_toc.epub"

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Prefixed TOC</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="navdoc" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>"""

    nav_xhtml = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
  <body>
    <nav epub:type="z3998:toc">
      <ol><li><a href="ch1.xhtml">Chapter 1</a></li></ol>
    </nav>
  </body>
</html>"""

    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        zf.writestr("OEBPS/ch1.xhtml", "<html><body><p>Hello</p></body></html>")
        zf.writestr("OEBPS/nav.xhtml", nav_xhtml)

    book = read_epub(epub_path)
    assert len(book.toc) == 1
    assert book.toc[0].title == "Chapter 1"
    assert book.toc[0].href == "ch1.xhtml"
