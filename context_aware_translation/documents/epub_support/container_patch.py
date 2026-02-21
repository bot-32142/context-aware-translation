"""Patch members in existing EPUB archives while preserving ZIP structure."""

from __future__ import annotations

import io
import zipfile

from context_aware_translation.documents.epub_support.container_shared import normalize_zip_path


def patch_epub_members(base_epub_bytes: bytes, updates: dict[str, bytes]) -> bytes:
    """Patch members in an existing EPUB archive without rewriting structure."""
    if not updates:
        return base_epub_bytes

    normalized_updates = {
        normalize_zip_path(name): payload for name, payload in updates.items() if normalize_zip_path(name)
    }

    source = io.BytesIO(base_epub_bytes)
    output = io.BytesIO()
    with zipfile.ZipFile(source, "r") as zin, zipfile.ZipFile(output, "w") as zout:
        seen: set[str] = set()
        for info in zin.infolist():
            name = normalize_zip_path(info.filename)
            payload = normalized_updates.get(name)
            if payload is None:
                payload = zin.read(info.filename)
            else:
                seen.add(name)

            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.comment = info.comment
            zi.extra = info.extra
            zi.external_attr = info.external_attr
            zout.writestr(zi, payload, compress_type=info.compress_type)

        missing = [name for name in normalized_updates if name not in seen]
        if missing:
            raise ValueError(f"Cannot patch missing EPUB members: {', '.join(sorted(missing))}")

    return output.getvalue()
