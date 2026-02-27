<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# epub_support

## Purpose
EPUB format support: reading, writing, and patching EPUB containers with translation content. Handles ZIP archive extraction, XHTML parsing, manifest/spine manipulation, table-of-contents operations, and translation marker tracking for accurate text positioning.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package initialization. Exports container reader/writer functions. |
| `container_model.py` | EPUB container data model. Classes: `EpubItem` (single file in EPUB), `TocEntry` (table of contents entry). Constants: XML namespace URIs (DC_NS, OPF_NS, CONTAINER_NS, NCX_NS, XHTML_NS, EPUB_NS). |
| `container_reader.py` | Parse EPUB files into in-memory container. Function: `read_epub(path)` returns `EpubContainer` with metadata, manifest, spine, TOC. Handles ZIP extraction, XML parsing, namespace resolution. |
| `container_writer.py` | Write modified EPUB container back to ZIP. Function: `write_epub(path, container)` serializes container to EPUB file. Preserves manifest/spine/metadata structure. |
| `container_patch.py` | Patch EPUB content with translations. Functions for in-place text updates, inline marker insertion/removal. |
| `container_shared.py` | Shared utilities for container operations. Helpers for ZIP handling, namespace resolution, item ID generation. |
| `inline_markers.py` | Inline translation markers for precise text position tracking. Classes: `InlineMarker`, marker insertion/extraction functions. Enables character-level mapping between source and translated text. |
| `nav_ops.py` | EPUB navigation (table of contents) operations. Functions for TOC parsing, entry manipulation, hierarchical structure handling. |
| `slot_lines.py` | Slot-based line handling for text chunking. Maps text lines to XHTML slots for granular updates. |
| `xml_utils.py` | XML utility functions for XHTML processing. Namespace handling, element tree manipulation, content extraction/modification. |

## For AI Agents

### Working In This Directory

**EPUB Structure:**
- EPUB is a ZIP archive containing XHTML files, stylesheets, metadata, and a manifest
- Root metadata file referenced in `META-INF/container.xml` (usually `OEBPS/content.opf`)
- Package document (OPF) lists all files in `<manifest>` and reading order in `<spine>`
- XHTML files are semantic: `<h1>`, `<h2>`, `<p>`, `<ul>`, `<li>`, `<img>`, etc.
- Optional TOC file (`nav.xhtml` or `.ncx`) for navigation

**Container Model:**
- `EpubContainer` holds metadata, manifest (list of items), spine (reading order), and TOC
- Each item is `EpubItem` with `file_name`, `media_type`, `content` (bytes), and manifest properties
- `TocEntry` represents hierarchical TOC structure

**Read/Write Cycle:**
```python
from context_aware_translation.documents.epub_support.container_reader import read_epub
from context_aware_translation.documents.epub_support.container_writer import write_epub

# Read EPUB
container = read_epub("book.epub")
for item in container.manifest:
    if item.media_type == "application/xhtml+xml":
        # Parse and translate XHTML content
        ...

# Write back
write_epub("book_translated.epub", container)
```

**XML/XHTML Processing:**
- Use `xml_utils.py` for namespace-aware element tree operations
- Register namespaces before parsing: `_ET.register_namespace("", XHTML_NS)`
- Query elements with full namespace URIs: `"{http://www.w3.org/1999/xhtml}p"`
- Or use convenience helpers from `xml_utils.py`

**Inline Markers for Translation:**
- `inline_markers.py` provides marker insertion/extraction to track text positions
- Markers enable character-level alignment between source and translated text
- Inserted during pre-translation processing, extracted after translation

**Navigation (TOC):**
- `nav_ops.py` handles TOC parsing and manipulation
- Supports both modern nav.xhtml (EPUB 3) and legacy .ncx (EPUB 2)
- `TocEntry` forms hierarchical structure (title, href, children)
- Important for maintaining reading order and semantic structure

**Patching Strategy:**
- Read EPUB, extract XHTML content
- Translate text while tracking positions via inline markers
- Use `container_patch.py` to update XHTML with translations
- Preserve semantic structure (don't remove `<h1>`, `<em>`, etc.)
- Write patched container back to ZIP

**Manifest and Spine:**
- Manifest: list of all files in EPUB with MIME types and properties
- Spine: ordered list of manifest items (reading order)
- Properties: `cover-image`, `nav` (TOC file), `remote-resources`, etc.
- Each spine entry can have `linear="no"` for non-primary content (backmatter)

### Common Patterns

**Reading EPUB and Extracting Text:**
```python
from context_aware_translation.documents.epub_support.container_reader import read_epub
from context_aware_translation.documents.epub_support.xml_utils import get_text

container = read_epub("input.epub")

for item in container.manifest:
    if item.media_type == "application/xhtml+xml":
        # Parse XHTML
        from xml.etree import ElementTree as ET
        root = ET.fromstring(item.content)

        # Extract text
        text = get_text(root)
        print(text)
```

**Updating XHTML Content:**
```python
from xml.etree import ElementTree as ET
from context_aware_translation.documents.epub_support.xml_utils import set_text

# Parse
root = ET.fromstring(item.content)

# Update
set_text(root, translated_text)

# Serialize back
item.content = ET.tostring(root, encoding="utf-8")
```

**Working with Namespaces:**
```python
from context_aware_translation.documents.epub_support.container_model import XHTML_NS

# Find all paragraphs in XHTML
ns = {"xhtml": XHTML_NS}
for p in root.findall(".//xhtml:p", ns):
    # Process paragraph
    pass
```

**Inserting Inline Markers:**
```python
from context_aware_translation.documents.epub_support.inline_markers import insert_marker

# Before translation, insert markers to track positions
marked_text = insert_marker(source_text, marker_id=1)

# After translation with marked positions
marked_translation = translate(marked_text)

# Extract positions from marked translation
positions = extract_marker_positions(marked_translation)
```

**Handling Table of Contents:**
```python
from context_aware_translation.documents.epub_support.nav_ops import parse_toc

toc = parse_toc(container)

def print_toc(entries, indent=0):
    for entry in entries:
        print("  " * indent + entry.title)
        if entry.children:
            print_toc(entry.children, indent + 1)

print_toc(toc)
```

**Preserving Cover Image:**
```python
# Manifest items may have properties
for item in container.manifest:
    if "cover-image" in item.properties:
        # This is the cover image
        cover_item = item
```

## Dependencies

### Internal
- `context_aware_translation.documents.epub_support.container_model` - `EpubItem`, `TocEntry`, namespace constants
- `context_aware_translation.documents.epub_support.xml_utils` - XML element manipulation
- `context_aware_translation.documents.epub_support.container_shared` - Shared utilities

### External
- `zipfile` (stdlib) - ZIP archive handling for EPUB extraction/creation
- `xml.etree.ElementTree` (stdlib) - XHTML parsing and serialization
- `lxml` (optional) - XML validation and pretty-printing
- `re` (stdlib) - Regular expressions for marker and text patterns

<!-- MANUAL: -->
