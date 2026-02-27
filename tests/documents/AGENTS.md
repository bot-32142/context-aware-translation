<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# documents

## Purpose
Tests for all document type implementations.

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| content | Test data and fixtures |

## Key Files
| File | Description |
|------|-------------|
| test_base.py | Base document class behavior |
| test_text.py | Plain text document handling |
| test_pdf.py | PDF parsing and extraction |
| test_scanned_book.py | Scanned book image processing |
| test_epub.py | EPUB document handling |
| test_epub_container.py | EPUB container structure |
| test_epub_xhtml_utils.py | EPUB XHTML utilities |
| test_epub_inline_markers.py | EPUB inline marker handling |
| test_manga.py | Manga (CBZ) document handling |
| test_manga_alignment.py | Manga page alignment and text mapping |
| test_ocr_image_embedded_text.py | OCR with embedded text detection |

## For AI Agents
### Working In This Directory
- Follow existing test patterns and naming conventions
- Use pytest fixtures from conftest.py
- Tests run in parallel (pytest-xdist)

<!-- MANUAL: -->
