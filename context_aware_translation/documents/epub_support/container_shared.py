"""Shared helper functions for EPUB container read/write/patch operations."""

from __future__ import annotations

import posixpath
import zipfile
from typing import Any
from urllib.parse import unquote, urljoin, urlparse, urlsplit

from context_aware_translation.documents.epub_support.container_model import XML_NS


def normalize_zip_path(path: str) -> str:
    """Normalize ZIP-internal path to stable POSIX form."""
    normalized = posixpath.normpath(path.replace("\\", "/"))
    if normalized == ".":
        return ""
    return normalized.lstrip("/")


def xml_base(elem: Any | None) -> str:
    if elem is None:
        return ""
    return str(elem.get(f"{{{XML_NS}}}base", "")).strip()


def serialize_section(elem: Any | None) -> str:
    if elem is None:
        return ""
    import xml.etree.ElementTree as _ET

    return _ET.tostring(elem, encoding="unicode")


def _zip_path_to_file_url(path: str) -> str:
    normalized = normalize_zip_path(path)
    return f"file:///{normalized}" if normalized else "file:///"


def manifest_href_to_zip_path(href: str) -> str:
    """Convert resolved manifest href into normalized ZIP path."""
    parsed = urlsplit(href)
    if parsed.scheme in {"", "file"}:
        return normalize_zip_path(unquote(parsed.path))
    return href


def resolve_manifest_href(*, opf_path: str, href: str, bases: list[str]) -> str:
    """Resolve href against OPF location and xml:base ancestors."""
    base_url = _zip_path_to_file_url(opf_path)
    for base in bases:
        if base:
            base_url = urljoin(base_url, base)
    return urljoin(base_url, href)


def is_remote_href(href: str) -> bool:
    href_path = href.split("#", 1)[0].split("?", 1)[0].strip()
    if not href_path:
        return False
    if href_path.startswith("//"):
        return True
    parsed = urlparse(href_path)
    return bool(parsed.scheme and parsed.scheme.lower() not in {"file"})


def zip_lookup_candidates(name: str) -> list[str]:
    """Return ZIP member candidates, including percent-decoded paths."""
    normalized = normalize_zip_path(name)
    if not normalized:
        return []

    candidates = [normalized]
    decoded = normalize_zip_path(unquote(normalized))
    if decoded and decoded not in candidates:
        candidates.append(decoded)
    return candidates


def try_read_member(zf: zipfile.ZipFile, name: str) -> bytes | None:
    """Read a ZIP member by candidate names; return None when absent."""
    for candidate in zip_lookup_candidates(name):
        try:
            return zf.read(candidate)
        except KeyError:
            continue
    return None


def safe_read(
    zf: zipfile.ZipFile,
    name: str,
    *,
    required: bool = False,
    label: str = "File",
) -> bytes:
    """Read a file from ZIP."""
    payload = try_read_member(zf, name)
    if payload is not None:
        return payload

    if required:
        raise ValueError(f"{label} '{name}' not found in archive")
    return b""


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag
