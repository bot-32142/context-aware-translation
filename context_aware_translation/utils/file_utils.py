from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Literal

TEXT_EXTENSIONS = {".txt", ".md"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def classify_file(path: Path) -> Literal["text", "image"] | None:
    ext = path.suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return "text"
    elif ext in IMAGE_EXTENSIONS:
        return "image"
    return None


def get_mime_type(path: Path) -> str | None:
    mime_type, _ = mimetypes.guess_type(str(path))
    return mime_type


def scan_folder(folder_path: Path) -> list[Path]:
    """Scan folder for supported files (top-level only, does not recurse into subdirectories)."""
    if not folder_path.is_dir():
        raise ValueError(f"Path is not a directory: {folder_path}")

    files = []
    for item in sorted(folder_path.iterdir()):
        if item.is_file() and classify_file(item) is not None:
            files.append(item)
    return files
