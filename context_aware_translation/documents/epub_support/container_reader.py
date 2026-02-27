"""EPUB reader implementation."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import defusedxml.ElementTree as DefusedET

from context_aware_translation.documents.epub_support.container_model import (
    CONTAINER_NS,
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
    manifest_href_to_zip_path,
    normalize_zip_path,
    resolve_manifest_href,
    safe_read,
    serialize_section,
    xml_base,
)

_RUBY_ANNOTATION_TAGS = frozenset({"rt", "rp", "rtc"})


def _local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _itertext_skip_ruby(elem: Any) -> list[str]:
    """Like ``Element.itertext()`` but skips <rt>/<rp>/<rtc> content."""
    parts: list[str] = []

    def _walk(el: Any) -> None:
        if _local_tag(el.tag) in _RUBY_ANNOTATION_TAGS:
            return
        if el.text:
            parts.append(el.text)
        for child in el:
            _walk(child)
            if child.tail:
                parts.append(child.tail)

    _walk(elem)
    return parts


# =========================================================================
# Reader
# =========================================================================


def read_epub(path: str | Path) -> EpubBook:
    """Read an EPUB file and return an EpubBook.

    Raises:
        ValueError: If the file is not a valid EPUB, encrypted, or malformed.
    """
    path = Path(path)
    try:
        zf = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, FileNotFoundError, OSError) as e:
        raise ValueError(f"Cannot open EPUB: {e}") from e

    with zf:
        _validate_mimetype_entry(zf)
        _validate_not_encrypted(zf)
        opf_path, opf_root = _load_opf_root(zf)

        manifest = _parse_manifest(opf_root, opf_path=opf_path)
        spine_refs, ncx_id = _parse_spine(opf_root)
        nav_ids = {mid for mid, mdata in manifest.items() if "nav" in mdata["properties"].split()}
        metadata_xml, guide_xml, bindings_xml, collection_xml = _extract_opf_sections(opf_root)

        _validate_manifest_members_exist(
            zf,
            manifest=manifest,
            spine_refs=spine_refs,
            nav_ids=nav_ids,
            ncx_id=ncx_id,
        )

        metadata = _parse_metadata(opf_root)

        spine_items: list[EpubItem] = []
        spine_manifest_ids: set[str] = set()
        for spine_ref in spine_refs:
            idref = spine_ref["idref"]
            if idref in nav_ids:
                continue
            _resolved_idref, mdata, chain_ids = _resolve_spine_manifest_item(idref, manifest)
            spine_manifest_ids.update(chain_ids)
            href = mdata["resolved-href"]
            if is_remote_href(href):
                raise ValueError(f"Unsupported remote spine item href '{href}'")
            file_name = manifest_href_to_zip_path(href)
            content = safe_read(zf, file_name, required=True, label="Spine item")
            spine_items.append(
                EpubItem(
                    file_name=file_name,
                    media_type=mdata["media-type"],
                    content=content,
                    item_id=idref,
                    properties=mdata["properties"],
                    fallback=mdata["fallback"],
                    media_overlay=mdata["media-overlay"],
                    linear=spine_ref["linear"],
                    spine_properties=spine_ref["properties"],
                    original_href=mdata["href"],
                )
            )

        resources: list[EpubItem] = []
        remote_resources: list[EpubItem] = []
        for mid, mdata in manifest.items():
            if mid in spine_manifest_ids:
                continue

            href = mdata["resolved-href"]
            if is_remote_href(href):
                remote_resources.append(
                    EpubItem(
                        file_name=href,
                        media_type=mdata["media-type"],
                        content=b"",
                        item_id=mid,
                        properties=mdata["properties"],
                        fallback=mdata["fallback"],
                        media_overlay=mdata["media-overlay"],
                        original_href=mdata["href"],
                        is_remote=True,
                    )
                )
                continue

            file_name = manifest_href_to_zip_path(href)
            content = safe_read(zf, file_name, required=True, label="Manifest resource")
            resources.append(
                EpubItem(
                    file_name=file_name,
                    media_type=mdata["media-type"],
                    content=content,
                    item_id=mid,
                    properties=mdata["properties"],
                    fallback=mdata["fallback"],
                    media_overlay=mdata["media-overlay"],
                    original_href=mdata["href"],
                )
            )

        toc = _parse_ncx_toc(zf, manifest, ncx_id) or _parse_nav_toc(zf, manifest, nav_ids)

    return EpubBook(
        metadata=metadata,
        spine_items=spine_items,
        resources=resources,
        remote_resources=remote_resources,
        toc=toc,
        package_path=opf_path,
        metadata_xml=metadata_xml,
        guide_xml=guide_xml,
        bindings_xml=bindings_xml,
        collection_xml=collection_xml,
    )


# =========================================================================
# Reader helpers
# =========================================================================


def _validate_mimetype_entry(zf: zipfile.ZipFile) -> None:
    """Validate EPUB mimetype file presence and required ZIP constraints."""
    try:
        info = zf.getinfo("mimetype")
    except KeyError as e:
        raise ValueError("Missing 'mimetype' entry — not a valid EPUB") from e

    if info.compress_type != zipfile.ZIP_STORED:
        raise ValueError("Invalid EPUB: 'mimetype' entry must be uncompressed (ZIP_STORED)")
    if info.extra:
        raise ValueError("Invalid EPUB: 'mimetype' entry must not include ZIP extra fields")

    infos = zf.infolist()
    if not infos or infos[0].filename != "mimetype":
        raise ValueError("Invalid EPUB: 'mimetype' entry must be the first ZIP member")

    allowed_compression = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
    for member in infos:
        if member.compress_type not in allowed_compression:
            raise ValueError(f"Invalid EPUB: unsupported ZIP compression method for '{member.filename}'")

    mimetype_data = zf.read("mimetype")
    if mimetype_data != MIMETYPE_CONTENT:
        raise ValueError("Invalid EPUB mimetype content: expected 'application/epub+zip'")


def _validate_not_encrypted(zf: zipfile.ZipFile) -> None:
    """Reject encrypted/DRM EPUBs (including obfuscated resources)."""
    for blocked in ("META-INF/encryption.xml", "META-INF/rights.xml"):
        if blocked in zf.namelist():
            raise ValueError("Encrypted/DRM EPUB is not supported")

    for info in zf.infolist():
        # ZIP general purpose bit 0 indicates traditional ZIP encryption.
        if info.flag_bits & 0x1:
            raise ValueError("Encrypted/DRM EPUB is not supported")


def _load_opf_root(zf: zipfile.ZipFile) -> tuple[str, Any]:
    """Load OPF XML root from container.xml rootfile declaration."""
    try:
        container_bytes = zf.read("META-INF/container.xml")
    except KeyError as e:
        raise ValueError("Missing META-INF/container.xml — not a valid EPUB") from e

    try:
        container_root = DefusedET.fromstring(container_bytes)
    except Exception as e:  # pragma: no cover - parser details not stable
        raise ValueError("Invalid container.xml (malformed XML)") from e

    rootfiles = container_root.findall(f".//{{{CONTAINER_NS}}}rootfile")
    if not rootfiles:
        raise ValueError("No <rootfile> found in container.xml")

    candidate_paths: list[str] = []
    for rootfile_el in rootfiles:
        media_type = rootfile_el.get("media-type", "").strip()
        if media_type and media_type != "application/oebps-package+xml":
            continue
        full_path = rootfile_el.get("full-path", "")
        if not full_path:
            continue
        normalized = normalize_zip_path(full_path)
        if normalized and normalized not in candidate_paths:
            candidate_paths.append(normalized)

    if not candidate_paths:
        raise ValueError("No valid OPF rootfile found in container.xml")
    if len(candidate_paths) > 1:
        raise ValueError("Multiple OPF rootfiles are not supported (multiple renditions are not handled)")

    errors: list[str] = []
    for opf_path in candidate_paths:
        try:
            opf_bytes = zf.read(opf_path)
        except KeyError:
            errors.append(f"OPF file '{opf_path}' not found in archive")
            continue

        try:
            opf_root = DefusedET.fromstring(opf_bytes)
        except Exception:
            errors.append(f"Invalid OPF XML in '{opf_path}'")
            continue

        return opf_path, opf_root

    joined = "; ".join(errors) if errors else "No parseable OPF rootfile found"
    raise ValueError(joined)


def _parse_manifest(opf_root: Any, *, opf_path: str) -> dict[str, dict[str, str]]:
    """Build manifest mapping: id -> href/media-type/properties."""
    manifest_el = opf_root.find(f"{{{OPF_NS}}}manifest")
    if manifest_el is None:
        raise ValueError("No <manifest> in OPF")

    package_base = xml_base(opf_root)
    manifest_base = xml_base(manifest_el)

    manifest: dict[str, dict[str, str]] = {}
    for item_el in manifest_el.findall(f"{{{OPF_NS}}}item"):
        item_id = item_el.get("id", "").strip()
        if not item_id:
            raise ValueError("Manifest item is missing required 'id' attribute")
        if item_id in manifest:
            raise ValueError(f"Duplicate manifest item id '{item_id}'")

        href = item_el.get("href", "").strip()
        if not href:
            raise ValueError(f"Manifest item '{item_id}' is missing required 'href' attribute")

        media_type = item_el.get("media-type", "").strip()
        if not media_type:
            raise ValueError(f"Manifest item '{item_id}' is missing required 'media-type' attribute")

        item_base = xml_base(item_el)
        resolved_href = resolve_manifest_href(
            opf_path=opf_path,
            href=href,
            bases=[package_base, manifest_base, item_base],
        )

        manifest[item_id] = {
            "href": href,
            "resolved-href": resolved_href,
            "media-type": media_type,
            "properties": item_el.get("properties", ""),
            "fallback": item_el.get("fallback", ""),
            "media-overlay": item_el.get("media-overlay", ""),
        }
    return manifest


def _parse_spine(opf_root: Any) -> tuple[list[dict[str, Any]], str]:
    """Extract spine references and optional NCX id from OPF."""
    spine_el = opf_root.find(f"{{{OPF_NS}}}spine")
    if spine_el is None:
        return [], ""

    ncx_id = spine_el.get("toc", "")
    spine_refs: list[dict[str, Any]] = []
    seen_idrefs: set[str] = set()
    for itemref in spine_el.findall(f"{{{OPF_NS}}}itemref"):
        idref = itemref.get("idref", "").strip()
        if not idref:
            raise ValueError("Spine itemref is missing required 'idref' attribute")
        if idref in seen_idrefs:
            raise ValueError(f"Duplicate spine itemref idref '{idref}'")
        seen_idrefs.add(idref)

        linear = itemref.get("linear", "yes").strip().lower() != "no"
        spine_refs.append(
            {
                "idref": idref,
                "linear": linear,
                "properties": itemref.get("properties", ""),
            }
        )
    return spine_refs, ncx_id


def _resolve_spine_manifest_item(
    idref: str,
    manifest: dict[str, dict[str, str]],
) -> tuple[str, dict[str, str], set[str]]:
    """Resolve a spine idref through OPF fallback chains.

    Preference order:
    1) Textual/document spine content (XHTML/HTML/SVG)
    2) Raster image spine content (lenient fixed-layout support)

    If a raster spine item declares a fallback chain that reaches textual
    content, the textual fallback is preferred.
    """
    current = idref
    visited: set[str] = set()
    first_raster: tuple[str, dict[str, str]] | None = None

    while current:
        if current in visited:
            raise ValueError(f"Cyclic fallback chain detected for spine item '{idref}'")
        visited.add(current)

        mdata = manifest.get(current)
        if mdata is None:
            raise ValueError(f"Spine itemref '{idref}' references missing manifest item '{current}'")

        media_type = mdata.get("media-type", "")
        if _is_textual_spine_media_type(media_type):
            return current, mdata, visited
        if _is_supported_spine_media_type(media_type) and first_raster is None:
            first_raster = (current, mdata)

        fallback = mdata.get("fallback", "")
        if not fallback:
            if first_raster is not None:
                raster_id, raster_data = first_raster
                return raster_id, raster_data, visited
            raise ValueError(f"Unsupported spine media type '{media_type}' for idref '{idref}' with no valid fallback")
        current = fallback

    if first_raster is not None:
        raster_id, raster_data = first_raster
        return raster_id, raster_data, visited

    raise ValueError(f"Unable to resolve spine item '{idref}'")


def _is_textual_spine_media_type(media_type: str) -> bool:
    mt = media_type.strip().lower()
    return mt in {"application/xhtml+xml", "text/html", "image/svg+xml"}


def _is_supported_spine_media_type(media_type: str) -> bool:
    mt = media_type.strip().lower()
    if _is_textual_spine_media_type(mt):
        return True
    # Lenient mode: support image-based fixed-layout variants that put raster
    # assets directly in the spine.
    return mt.startswith("image/")


def _validate_manifest_members_exist(
    zf: zipfile.ZipFile,
    *,
    manifest: dict[str, dict[str, str]],
    spine_refs: list[dict[str, Any]],
    nav_ids: set[str],
    ncx_id: str,
) -> None:
    """Validate that referenced ZIP members for local items exist."""
    spine_manifest_ids: set[str] = set()

    for spine_ref in spine_refs:
        idref = spine_ref["idref"]
        if idref in nav_ids:
            continue
        _resolved_idref, mdata, chain_ids = _resolve_spine_manifest_item(idref, manifest)
        spine_manifest_ids.update(chain_ids)
        href = mdata["resolved-href"]
        if is_remote_href(href):
            raise ValueError(f"Unsupported remote spine item href '{href}'")
        file_name = manifest_href_to_zip_path(href)
        safe_read(zf, file_name, required=True, label="Spine item")

    for mid, mdata in manifest.items():
        if mid in spine_manifest_ids or mid in nav_ids or mid == ncx_id:
            continue
        href = mdata["resolved-href"]
        if is_remote_href(href):
            continue
        file_name = manifest_href_to_zip_path(href)
        safe_read(zf, file_name, required=True, label="Manifest resource")


def _extract_opf_sections(opf_root: Any) -> tuple[str, str, str, list[str]]:
    """Extract raw OPF sections that should be preserved during round-trip export."""
    metadata_xml = serialize_section(opf_root.find(f"{{{OPF_NS}}}metadata"))
    guide_xml = serialize_section(opf_root.find(f"{{{OPF_NS}}}guide"))
    bindings_xml = serialize_section(opf_root.find(f"{{{OPF_NS}}}bindings"))
    collection_xml: list[str] = []
    for collection in opf_root.findall(f"{{{OPF_NS}}}collection"):
        serialized = serialize_section(collection)
        if serialized:
            collection_xml.append(serialized)
    return metadata_xml, guide_xml, bindings_xml, collection_xml


def _parse_metadata(opf_root: Any) -> EpubMetadata:
    """Extract Dublin Core metadata directly from OPF root."""
    meta = EpubMetadata()
    metadata_el = opf_root.find(f"{{{OPF_NS}}}metadata")
    if metadata_el is None:
        return meta

    title_el = metadata_el.find(f"{{{DC_NS}}}title")
    if title_el is not None and title_el.text:
        meta.title = title_el.text.strip()

    for creator_el in metadata_el.findall(f"{{{DC_NS}}}creator"):
        if creator_el.text:
            meta.authors.append(creator_el.text.strip())

    lang_el = metadata_el.find(f"{{{DC_NS}}}language")
    if lang_el is not None and lang_el.text:
        meta.language = lang_el.text.strip()

    id_el = metadata_el.find(f"{{{DC_NS}}}identifier")
    if id_el is not None and id_el.text:
        meta.identifier = id_el.text.strip()

    if not meta.language:
        meta.language = "en"
    return meta


def _parse_ncx_toc(
    zf: zipfile.ZipFile,
    manifest: dict[str, dict[str, str]],
    ncx_id: str,
) -> list[TocEntry]:
    """Parse toc.ncx for navigation entries."""
    if not ncx_id or ncx_id not in manifest:
        return []

    ncx_href = manifest_href_to_zip_path(manifest[ncx_id]["resolved-href"])
    ncx_bytes = safe_read(zf, ncx_href)
    if not ncx_bytes:
        return []

    try:
        ncx_root = DefusedET.fromstring(ncx_bytes)
    except Exception:
        return []

    nav_map = ncx_root.find(f"{{{NCX_NS}}}navMap")
    if nav_map is None:
        return []

    return _parse_ncx_navpoints(nav_map)


def _parse_ncx_navpoints(parent: Any) -> list[TocEntry]:
    """Recursively parse NCX navPoint elements."""
    entries: list[TocEntry] = []
    for nav_point in parent.findall(f"{{{NCX_NS}}}navPoint"):
        label_el = nav_point.find(f"{{{NCX_NS}}}navLabel/{{{NCX_NS}}}text")
        content_el = nav_point.find(f"{{{NCX_NS}}}content")
        title = label_el.text.strip() if label_el is not None and label_el.text else ""
        href = content_el.get("src", "") if content_el is not None else ""
        children = _parse_ncx_navpoints(nav_point)
        entries.append(TocEntry(title=title, href=href, children=children or None))
    return entries


def _parse_nav_toc(
    zf: zipfile.ZipFile,
    manifest: dict[str, dict[str, str]],
    nav_ids: set[str],
) -> list[TocEntry]:
    """Parse EPUB3 nav.xhtml for TOC entries (fallback if no NCX)."""
    if not nav_ids:
        return []

    nav_id = next(iter(nav_ids))
    if nav_id not in manifest:
        return []

    nav_href = manifest_href_to_zip_path(manifest[nav_id]["resolved-href"])
    nav_bytes = safe_read(zf, nav_href)
    if not nav_bytes:
        return []

    try:
        nav_root = DefusedET.fromstring(nav_bytes)
    except Exception:
        return []

    from context_aware_translation.documents.epub_support.nav_ops import (
        normalize_nav_types,  # local import avoids circular dependency
    )

    for nav_el in nav_root.iter(f"{{{XHTML_NS}}}nav"):
        epub_type = nav_el.get(f"{{{EPUB_NS}}}type", "") or nav_el.get("type", "")
        if "toc" not in normalize_nav_types(epub_type):
            continue
        ol = nav_el.find(f"{{{XHTML_NS}}}ol")
        if ol is not None:
            return _parse_nav_ol(ol)
    return []


def _parse_nav_ol(ol_el: Any) -> list[TocEntry]:
    """Parse an <ol> element from nav.xhtml into TocEntry list."""
    entries: list[TocEntry] = []
    for li in ol_el.findall(f"{{{XHTML_NS}}}li"):
        title = ""
        href = ""

        a_el = li.find(f"{{{XHTML_NS}}}a")
        if a_el is not None:
            title = "".join(_itertext_skip_ruby(a_el)).strip()
            href = a_el.get("href", "")
        else:
            span_el = li.find(f"{{{XHTML_NS}}}span")
            if span_el is not None:
                title = "".join(_itertext_skip_ruby(span_el)).strip()

        child_ol = li.find(f"{{{XHTML_NS}}}ol")
        children = _parse_nav_ol(child_ol) if child_ol is not None else None

        if title or href or children:
            entries.append(TocEntry(title=title, href=href, children=children or None))
    return entries
