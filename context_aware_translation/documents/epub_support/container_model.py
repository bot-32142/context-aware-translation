"""Shared data model and constants for EPUB container IO."""

from __future__ import annotations

import xml.etree.ElementTree as _ET
from dataclasses import dataclass, field

# =========================================================================
# Data model constants
# =========================================================================

DC_NS = "http://purl.org/dc/elements/1.1/"
OPF_NS = "http://www.idpf.org/2007/opf"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
XHTML_NS = "http://www.w3.org/1999/xhtml"
EPUB_NS = "http://www.idpf.org/2007/ops"
XML_NS = "http://www.w3.org/XML/1998/namespace"

MIMETYPE_CONTENT = b"application/epub+zip"

_ET.register_namespace("", XHTML_NS)
_ET.register_namespace("epub", EPUB_NS)


@dataclass
class EpubItem:
    """A single item (file) within the EPUB archive."""

    file_name: str  # path within ZIP (e.g., "OEBPS/chapter1.xhtml")
    media_type: str  # MIME type (e.g., "application/xhtml+xml")
    content: bytes  # raw bytes
    item_id: str = ""  # manifest ID
    properties: str = ""
    fallback: str = ""
    media_overlay: str = ""
    linear: bool = True
    spine_properties: str = ""
    original_href: str = ""
    is_remote: bool = False


@dataclass
class TocEntry:
    """A table-of-contents entry."""

    title: str
    href: str
    children: list[TocEntry] | None = None


@dataclass
class EpubMetadata:
    """Dublin Core metadata for an EPUB book."""

    title: str = ""
    authors: list[str] = field(default_factory=list)
    language: str = "en"
    identifier: str = ""


@dataclass
class EpubBook:
    """In-memory representation of an EPUB book."""

    metadata: EpubMetadata = field(default_factory=EpubMetadata)
    spine_items: list[EpubItem] = field(default_factory=list)  # XHTML/SVG in spine order
    resources: list[EpubItem] = field(default_factory=list)  # CSS, images, fonts, etc.
    remote_resources: list[EpubItem] = field(default_factory=list)  # remote href items in manifest
    toc: list[TocEntry] = field(default_factory=list)
    package_path: str = ""  # OPF path as declared by META-INF/container.xml
    metadata_xml: str = ""  # serialized OPF <metadata> section
    guide_xml: str = ""  # serialized OPF <guide> section (EPUB2)
    bindings_xml: str = ""  # serialized OPF <bindings> section
    collection_xml: list[str] = field(default_factory=list)  # serialized OPF <collection> sections
