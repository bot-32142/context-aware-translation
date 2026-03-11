<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# documents

## Purpose
Document type implementations supporting multiple input formats: plain text, Markdown, PDF, scanned books (image-based OCR), manga/comics, and EPUB. Each document type handles format-specific import, content extraction, OCR, image processing, and export operations.

## Key Files

| File | Description |
|------|-------------|
| `base.py` | Abstract base class `Document` defining interface for all document types. Methods: `can_import()`, `do_import()`, `get_chunks()`, `export()`, `validate()`. Class properties: `document_type`, `supported_export_formats`, `requires_ocr_config`, `ocr_required_for_translation`. |
| `text.py` | Plain text and Markdown document handler. Class: `TextDocument`. Handles `.txt`, `.md` files. Simple line-based chunking. |
| `pdf.py` | PDF document handler using `pypdfium2` and `pikepdf`. Class: `PDFDocument`. Extracts text and images. OCR support for scanned PDFs. Preserves page structure. |
| `scanned_book.py` | Scanned book handler (image-based documents). Class: `ScannedBookDocument`. OCR-required. Supports page images (PNG, JPEG, TIFF). Layout analysis for reading order. |
| `manga.py` | Manga/comic handler with panel-aware processing. Class: `MangaDocument`. Supports `.cbz` (ZIP archives), loose images. Panel detection and text region extraction. Special handling for right-to-left reading. |
| `epub.py` | EPUB (electronic publication) handler. Class: `EPUBDocument`. Full XHTML support with preservation of semantic structure (headings, lists, etc.). Handles embedded images, stylesheets, and metadata. |
| `epub_container.py` | EPUB container metadata model. Classes: `EPUBContainer`, `OpfPackage`, `Manifest`, `Spine`. |
| `epub_xhtml_utils.py` | XHTML/XML utilities for EPUB processing. Functions for element tree manipulation, namespace handling, content extraction. |
| `manga_alignment.py` | Manga panel alignment and ordering. Handles reading direction detection and panel-by-panel processing. |
| `__init__.py` | Package initialization. |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `content/` | Content data models for structured document representation. Classes: `OCRContent`, `OCRItems` for image-based OCR results. |
| `epub_support/` | EPUB parsing and manipulation helpers. Modules: `container_model` (metadata), `container_reader` (parse EPUB), `container_writer` (write EPUB), `container_patch` (modify EPUB), `nav_ops` (TOC operations), `inline_markers` (text position tracking), `xml_utils`, `slot_lines`. |

## For AI Agents

### Working In This Directory

**Document Type Hierarchy:**
- All document types inherit from abstract `Document` base class
- Each type defines `document_type` string (e.g., `"text"`, `"pdf"`, `"manga"`)
- Each type defines `supported_export_formats` tuple (e.g., `("txt", "md")`)
- OCR capability is optional per type (`requires_ocr_config`, `ocr_required_for_translation`)

**Import/Export Pattern:**
- `can_import(path)` - check if document class handles file type
- `do_import(repo, path)` - parse file, populate document repository, return counts dict
- `get_chunks()` - retrieve text chunks in reading order
- `export(format, path, ...)` - write translated content to specified format

**OCR Integration:**
- OCR applied in document-specific way (full page vs. region of interest)
- Requires `OCRConfig` from main config
- May require `ImageReembeddingConfig` for image-to-text enhancement
- `scanned_book.py` and `manga.py` are OCR-intensive

**Content Models:**
- `OCRContent` - result of OCR on a page/region (text + regions)
- `OCRItems` - fine-grained text items with bounding boxes and confidence scores

**EPUB Specifics:**
- `EPUBDocument` preserves semantic structure (headings, lists, emphasis)
- `epub_support/` provides low-level utilities for ZIP extraction, XHTML parsing, manifest/spine manipulation
- `container_reader` parses EPUB metadata and content
- `container_writer` writes modified EPUB with translated content
- Namespace handling critical for valid XHTML output

**Manga Specifics:**
- Panel detection via image analysis (region proposal or grid-based)
- Right-to-left reading order support
- Text region extraction per panel
- Special handling for sound effects, dialog balloons
- `.cbz` files are ZIP archives of ordered images

### Common Patterns

**Checking Document Type:**
```python
from context_aware_translation.documents import text, pdf, manga

if TextDocument.can_import(path):
    doc = TextDocument.do_import(repo, path)
```

**Iterating Chunks:**
```python
doc = repository.get_document(doc_id)
chunks = doc.get_chunks()
for chunk in chunks:
    # translate, store result
```

**Exporting with Translation:**
```python
# Fetch translated chunks from DB
doc.export(format="pdf", output_path=out, translations=translations)
```

**EPUB Operations:**
```python
from context_aware_translation.documents.epub_support.container_reader import read_epub
from context_aware_translation.documents.epub_support.container_writer import write_epub

# Read
container = read_epub(epub_path)
for item_id, text in container.iter_text():
    # translate

# Write back
write_epub(output_path, container)
```

**OCR Processing:**
```python
from context_aware_translation.documents.scanned_book import ScannedBookDocument

doc = ScannedBookDocument(repo, doc_id)
if doc.requires_ocr_config:
    # OCR applied during import with OCRConfig
```

## Dependencies

### Internal
- `context_aware_translation.documents.base` - abstract Document class
- `context_aware_translation.documents.content.*` - OCR content models
- `context_aware_translation.storage.repositories.document_repository` - document CRUD
- `context_aware_translation.llm.ocr` - LLM-based OCR
- `context_aware_translation.llm.manga_ocr` - special OCR for manga
- `context_aware_translation.utils.chunking` - text chunking
- `context_aware_translation.utils.image_utils` - image processing
- `context_aware_translation.utils.markdown_escape` - markdown escaping for text docs

### External
- `pikepdf` - PDF reading/writing and page manipulation
- `pypdfium2` - high-quality PDF text extraction
- `pillow` - image processing (resize, format conversion, OCR input prep)
- `python-magic` - file type detection
- `zipfile` (stdlib) - `.cbz` archive handling
- `xml.etree.ElementTree` (stdlib) - XHTML parsing for EPUB
- `lxml` (optional, for XHTML validation)

<!-- MANUAL: -->
