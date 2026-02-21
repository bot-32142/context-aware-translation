"""Public EPUB container API (facade over internal EPUB support modules)."""

from __future__ import annotations

from context_aware_translation.documents.epub_support.container_model import (
    EpubBook,
    EpubItem,
    EpubMetadata,
    TocEntry,
)
from context_aware_translation.documents.epub_support.container_patch import patch_epub_members
from context_aware_translation.documents.epub_support.container_reader import read_epub
from context_aware_translation.documents.epub_support.container_writer import write_epub

__all__ = [
    "EpubBook",
    "EpubItem",
    "EpubMetadata",
    "TocEntry",
    "read_epub",
    "write_epub",
    "patch_epub_members",
]
