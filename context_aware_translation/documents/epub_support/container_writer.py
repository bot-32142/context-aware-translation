"""EPUB writer implementation."""

from __future__ import annotations

import posixpath
import uuid
import xml.etree.ElementTree as _ET
import zipfile
from pathlib import Path
from typing import Any, cast

import defusedxml.ElementTree as DefusedET

from context_aware_translation.documents.epub_support.container_model import (
    DC_NS,
    EPUB_NS,
    MIMETYPE_CONTENT,
    NCX_NS,
    OPF_NS,
    XHTML_NS,
    EpubBook,
    EpubItem,
    EpubMetadata,
    TocEntry,
)
from context_aware_translation.documents.epub_support.container_shared import (
    is_remote_href,
    local_name,
    normalize_zip_path,
)

# =========================================================================
# Writer
# =========================================================================


def write_epub(path: str | Path, book: EpubBook) -> None:
    """Write an EpubBook to an EPUB file using local ZIP/XML logic."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    spine_items = list(book.spine_items)
    resources = list(book.resources)
    remote_resources = list(book.remote_resources)

    all_items = [*spine_items, *resources, *remote_resources]
    for item in all_items:
        if item.is_remote:
            continue
        normalized_name = normalize_zip_path(item.file_name)
        if not normalized_name:
            raise ValueError("EPUB item file_name must not be empty")
        item.file_name = normalized_name

    target_package_path = normalize_zip_path(book.package_path)
    local_items = [item for item in all_items if not item.is_remote]
    if not target_package_path:
        auto_package_dir = _determine_package_dir([item.file_name for item in local_items])
        target_package_path = posixpath.join(auto_package_dir, "content.opf") if auto_package_dir else "content.opf"

    package_dir = posixpath.dirname(target_package_path)

    has_nav_document = any(_is_nav_document_item(item) for item in local_items)
    has_ncx_document = any(_is_ncx_document_item(item) for item in local_items)

    reserved_ids: set[str] = set()
    if not has_nav_document:
        reserved_ids.add("nav")
    if not has_ncx_document:
        reserved_ids.add("ncx")
    _assign_item_ids(all_items, reserved_ids=reserved_ids)

    toc_entries = book.toc or _default_toc_from_spine(spine_items, package_dir)

    generated: list[EpubItem] = []
    if not has_ncx_document:
        ncx_name = posixpath.join(package_dir, "toc.ncx") if package_dir else "toc.ncx"
        generated.append(
            EpubItem(
                file_name=ncx_name,
                media_type="application/x-dtbncx+xml",
                content=_build_ncx_document(toc_entries, title=book.metadata.title or "Untitled"),
                item_id="ncx",
            )
        )

    if not has_nav_document:
        nav_name = posixpath.join(package_dir, "nav.xhtml") if package_dir else "nav.xhtml"
        generated.append(
            EpubItem(
                file_name=nav_name,
                media_type="application/xhtml+xml",
                content=_build_nav_document(toc_entries),
                item_id="nav",
                properties="nav",
            )
        )

    resources.extend(generated)
    local_items = [*spine_items, *resources]

    manifest_items = [*spine_items, *resources, *remote_resources]
    manifest_by_id = {item.item_id: item for item in manifest_items if item.item_id}
    ncx_manifest_id = next(
        (
            item.item_id
            for item in manifest_items
            if item.item_id and item.media_type.strip().lower() == "application/x-dtbncx+xml"
        ),
        "",
    )

    opf_bytes = _build_package_document(
        metadata=book.metadata,
        metadata_xml=book.metadata_xml,
        guide_xml=book.guide_xml,
        bindings_xml=book.bindings_xml,
        collection_xml=book.collection_xml,
        package_path=target_package_path,
        manifest_items=manifest_items,
        spine_items=spine_items,
        ncx_manifest_id=ncx_manifest_id,
    )

    try:
        with zipfile.ZipFile(path, "w") as zf:
            _write_mimetype_entry(zf)
            zf.writestr(
                "META-INF/container.xml", _build_container_xml(target_package_path), compress_type=zipfile.ZIP_DEFLATED
            )

            for item in local_items:
                zf.writestr(item.file_name, item.content, compress_type=zipfile.ZIP_DEFLATED)

            zf.writestr(target_package_path, opf_bytes, compress_type=zipfile.ZIP_DEFLATED)

            # Ensure every spine idref references an existing manifest item id.
            for spine_item in spine_items:
                if spine_item.item_id and spine_item.item_id not in manifest_by_id:
                    raise ValueError(f"Spine item '{spine_item.item_id}' missing from manifest")
    except Exception as e:
        raise ValueError(f"Failed to write EPUB '{path}': {e}") from e


def _write_mimetype_entry(zf: zipfile.ZipFile) -> None:
    info = zipfile.ZipInfo("mimetype")
    info.compress_type = zipfile.ZIP_STORED
    info.extra = b""
    zf.writestr(info, MIMETYPE_CONTENT)


def _build_container_xml(package_path: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        "  <rootfiles>\n"
        f'    <rootfile full-path="{package_path}" media-type="application/oebps-package+xml"/>\n'
        "  </rootfiles>\n"
        "</container>"
    ).encode()


def _build_package_document(
    *,
    metadata: EpubMetadata,
    metadata_xml: str,
    guide_xml: str,
    bindings_xml: str,
    collection_xml: list[str],
    package_path: str,
    manifest_items: list[EpubItem],
    spine_items: list[EpubItem],
    ncx_manifest_id: str,
) -> bytes:
    package_dir = posixpath.dirname(normalize_zip_path(package_path))

    root = _ET.Element(
        f"{{{OPF_NS}}}package",
        {
            "version": "3.0",
            "unique-identifier": "bookid",
        },
    )

    metadata_el = _parse_xml_fragment(metadata_xml)
    if metadata_el is None or local_name(metadata_el.tag) != "metadata":
        metadata_el = _build_metadata_element(metadata)
    root.append(metadata_el)

    manifest_el = _ET.SubElement(root, f"{{{OPF_NS}}}manifest")
    for item in manifest_items:
        href = _manifest_href_for_item(item, package_dir)
        attrs = {
            "id": item.item_id,
            "href": href,
            "media-type": item.media_type,
        }
        if item.properties:
            attrs["properties"] = item.properties
        if item.media_overlay:
            attrs["media-overlay"] = item.media_overlay
        if item.fallback:
            attrs["fallback"] = item.fallback
        manifest_el.append(_make_manifest_item(attrs))

    spine_attrs: dict[str, str] = {}
    if ncx_manifest_id:
        spine_attrs["toc"] = ncx_manifest_id
    spine_el = _ET.SubElement(root, f"{{{OPF_NS}}}spine", spine_attrs)
    for item in spine_items:
        itemref_attrs = {"idref": item.item_id}
        if not item.linear:
            itemref_attrs["linear"] = "no"
        if item.spine_properties:
            itemref_attrs["properties"] = item.spine_properties
        _ET.SubElement(spine_el, f"{{{OPF_NS}}}itemref", itemref_attrs)

    _append_optional_section(root, guide_xml, expected_local_name="guide")
    _append_optional_section(root, bindings_xml, expected_local_name="bindings")
    for serialized in collection_xml:
        _append_optional_section(root, serialized, expected_local_name="collection")

    return _serialize_xml(root)


def _build_metadata_element(metadata: EpubMetadata) -> _ET.Element:
    metadata_el = _ET.Element(f"{{{OPF_NS}}}metadata")

    identifier = metadata.identifier.strip() if metadata.identifier else ""
    if not identifier:
        identifier = f"urn:uuid:{uuid.uuid4()}"

    id_el = _ET.SubElement(metadata_el, f"{{{DC_NS}}}identifier", {"id": "bookid"})
    id_el.text = identifier

    title_el = _ET.SubElement(metadata_el, f"{{{DC_NS}}}title")
    title_el.text = metadata.title or "Untitled"

    lang_el = _ET.SubElement(metadata_el, f"{{{DC_NS}}}language")
    lang_el.text = metadata.language or "en"

    for author in metadata.authors:
        if author:
            creator_el = _ET.SubElement(metadata_el, f"{{{DC_NS}}}creator")
            creator_el.text = author

    return metadata_el


def _manifest_href_for_item(item: EpubItem, package_dir: str) -> str:
    if item.is_remote:
        return item.original_href or item.file_name

    if item.original_href and not is_remote_href(item.original_href):
        return item.original_href

    normalized = normalize_zip_path(item.file_name)
    if package_dir:
        return normalize_zip_path(posixpath.relpath(normalized, package_dir))
    return normalized


def _append_optional_section(root: _ET.Element, serialized: str, *, expected_local_name: str) -> None:
    if not serialized:
        return
    parsed = _parse_xml_fragment(serialized)
    if parsed is None:
        return
    if local_name(parsed.tag) != expected_local_name:
        return
    root.append(parsed)


def _parse_xml_fragment(serialized: str) -> _ET.Element | None:
    try:
        return DefusedET.fromstring(serialized.encode("utf-8"))
    except Exception:
        return None


def _make_manifest_item(attrs: dict[str, str]) -> _ET.Element:
    item_el = _ET.Element(f"{{{OPF_NS}}}item")
    for key, value in attrs.items():
        item_el.set(key, value)
    return item_el


def _serialize_xml(root: Any) -> bytes:
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + cast(bytes, _ET.tostring(root, encoding="utf-8"))


def _is_nav_document_item(item: EpubItem) -> bool:
    media_type = item.media_type.strip().lower()
    if media_type not in {"application/xhtml+xml", "text/html"}:
        return False
    return "nav" in item.properties.split()


def _is_ncx_document_item(item: EpubItem) -> bool:
    return item.media_type.strip().lower() == "application/x-dtbncx+xml"


def _assign_item_ids(items: list[EpubItem], *, reserved_ids: set[str] | None = None) -> None:
    """Assign stable unique item IDs and avoid reserved/nav collisions."""
    reserved = set(reserved_ids or set())
    seen_ids: set[str] = set()

    for item in items:
        if item.item_id and item.item_id not in reserved and item.item_id not in seen_ids:
            seen_ids.add(item.item_id)
        else:
            item.item_id = ""

    used_ids = set(seen_ids) | reserved
    counter = 0
    for item in items:
        if item.item_id:
            continue
        while f"item_{counter}" in used_ids:
            counter += 1
        item.item_id = f"item_{counter}"
        used_ids.add(item.item_id)
        counter += 1


def _default_toc_from_spine(spine_items: list[EpubItem], package_dir: str) -> list[TocEntry]:
    entries: list[TocEntry] = []
    for idx, item in enumerate(spine_items, start=1):
        href = _manifest_href_for_item(item, package_dir)
        title = Path(href).stem or f"Section {idx}"
        entries.append(TocEntry(title=title, href=href))
    return entries


def _build_nav_document(toc_entries: list[TocEntry]) -> bytes:
    html = _ET.Element(f"{{{XHTML_NS}}}html")
    html.set("{http://www.w3.org/2000/xmlns/}epub", EPUB_NS)
    body = _ET.SubElement(html, f"{{{XHTML_NS}}}body")
    nav = _ET.SubElement(body, f"{{{XHTML_NS}}}nav")
    nav.set(f"{{{EPUB_NS}}}type", "toc")
    ol = _ET.SubElement(nav, f"{{{XHTML_NS}}}ol")
    _append_nav_entries(ol, toc_entries)
    return _serialize_xml(html)


def _append_nav_entries(parent_ol: _ET.Element, entries: list[TocEntry]) -> None:
    for entry in entries:
        li = _ET.SubElement(parent_ol, f"{{{XHTML_NS}}}li")
        label_target: _ET.Element
        if entry.href:
            label_target = _ET.SubElement(li, f"{{{XHTML_NS}}}a", {"href": entry.href})
        else:
            label_target = _ET.SubElement(li, f"{{{XHTML_NS}}}span")
        label_target.text = entry.title
        if entry.children:
            child_ol = _ET.SubElement(li, f"{{{XHTML_NS}}}ol")
            _append_nav_entries(child_ol, entry.children)


def _build_ncx_document(toc_entries: list[TocEntry], *, title: str) -> bytes:
    ncx = _ET.Element(f"{{{NCX_NS}}}ncx", {"version": "2005-1"})
    _ET.SubElement(ncx, f"{{{NCX_NS}}}head")
    doc_title = _ET.SubElement(ncx, f"{{{NCX_NS}}}docTitle")
    title_text = _ET.SubElement(doc_title, f"{{{NCX_NS}}}text")
    title_text.text = title

    nav_map = _ET.SubElement(ncx, f"{{{NCX_NS}}}navMap")
    _append_ncx_entries(nav_map, toc_entries, [1])
    return _serialize_xml(ncx)


def _append_ncx_entries(parent: _ET.Element, entries: list[TocEntry], order_counter: list[int]) -> None:
    for entry in entries:
        nav_point = _ET.SubElement(
            parent,
            f"{{{NCX_NS}}}navPoint",
            {
                "id": f"navPoint-{order_counter[0]}",
                "playOrder": str(order_counter[0]),
            },
        )
        order_counter[0] += 1

        nav_label = _ET.SubElement(nav_point, f"{{{NCX_NS}}}navLabel")
        label_text = _ET.SubElement(nav_label, f"{{{NCX_NS}}}text")
        label_text.text = entry.title

        if entry.href:
            _ET.SubElement(nav_point, f"{{{NCX_NS}}}content", {"src": entry.href})
        else:
            _ET.SubElement(nav_point, f"{{{NCX_NS}}}content", {"src": ""})

        if entry.children:
            _append_ncx_entries(nav_point, entry.children, order_counter)


def _determine_package_dir(item_paths: list[str]) -> str:
    """Determine where content.opf/nav/toc should live.

    Uses common directory of item paths when possible. If item paths include
    root-level entries, returns empty string.
    """
    if not item_paths:
        return "OEBPS"

    dirs = [posixpath.dirname(normalize_zip_path(path)) for path in item_paths]
    if any(dir_part == "" for dir_part in dirs):
        return ""

    common_dir = posixpath.commonpath(dirs)
    if common_dir in ("", ".", "/"):
        return ""
    return common_dir
