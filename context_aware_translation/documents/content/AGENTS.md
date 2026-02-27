<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# content

## Purpose
Content data models for structured OCR-processed document representation. Defines OCRItem protocol and concrete item types (Chapter, Paragraph, Image, Table, etc.) for the translation pipeline, plus helpers for merging cross-page continuations and rendering to markdown.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package initialization. Exports `MergedOCRContent`. |
| `ocr_content.py` | `SinglePageOCRContent` and `MergedOCRContent` classes for managing OCR item collections. Functions: `parse_ocr_json()` to parse raw OCR API responses into item objects. |
| `ocr_items.py` | `OCRItem` protocol defining the translation pipeline interface. Concrete item types: `ChapterItem`, `SectionItem`, `SubsectionItem`, `ParagraphItem`, `ListItem`, `ImageItem`, `TableItem`, `QuoteItem`, `CoverItem`, `TocItem`, `BlankItem`. Utility types: `RenderContext`, `BoundingBox`. Factory functions for item construction. |

## For AI Agents

### Working In This Directory

**OCRItem Protocol:**
- All content items implement `OCRItem` protocol (Python Protocol, not ABC)
- Key methods: `get_texts()`, `consume_translations()`, `merge_continuation()`, `to_markdown()`, `prepare()`, `to_json()`
- Items are instantiated via factory functions (e.g., `_chapter_factory()`) registered in `_ITEM_REGISTRY` dict

**Translation Pipeline Stages:**
1. **OCR Extraction**: Raw JSON parsed into OCRItem objects via `parse_ocr_json()`
2. **Merge Continuations**: Cross-page content merged via `merge_continuation()` (e.g., paragraph split across pages)
3. **Extract Texts**: `get_texts()` collects all translatable strings as flat list
4. **Translate**: External LLM translates the flat list[str]
5. **Distribute Translations**: `consume_translations()` assigns translations back using pos cursor pattern
6. **Render**: `to_markdown()` outputs final Pandoc-compatible markdown

**Flat List Translation Pattern:**
- `get_texts()` returns flat `list[str]` (no nested structure)
- Each string is translated 1:1 by external LLM
- `consume_translations(translations, pos)` uses pos cursor to distribute:
  ```python
  # First item with 2 texts
  pos = item1.consume_translations(translations, 0)  # Returns 2
  # Second item with 1 text
  pos = item2.consume_translations(translations, 2)  # Returns 3
  ```

**Item Type Behaviors:**

| Type | get_texts() | merge_continuation() | to_markdown() | Example |
|------|----------|-----|----------|---------|
| ChapterItem | splits by \\n | Always False | "# text" | Chapter title |
| SectionItem | splits by \\n | Always False | "## text" | Section heading |
| SubsectionItem | splits by \\n | Always False | "### text" | Subsection heading |
| ParagraphItem | splits by \\n | True if continues flags match | text + newlines | Body text |
| ListItem | flattened from items | True if continues flags match | "- item1\\n- item2..." | Bulleted list |
| ImageItem | embedded_text + caption | Always False | ![caption](path) | Inline image |
| TableItem | text + caption | True if continues flags match | table markdown | Data table |
| QuoteItem | splits by \\n | True if continues flags match | "> text" | Block quote |
| CoverItem | [] (empty) | Always False | YAML frontmatter (first) | Book cover |
| TocItem | [] (empty) | Always False | "" (empty) | Table of contents page |
| BlankItem | [] (empty) | Always False | "" (empty) | Blank page |

**Resource Extraction:**
- `prepare(page)` called before merging to extract page resources (images)
- ImageItem and CoverItem extract image bytes via `bbox.crop_from_image()`
- `page` is SimpleNamespace with `source_image_bytes` attribute (full page image bytes)

**Markdown Rendering:**
- Uses `RenderContext` with `image_dir` (Path), `insert_new_page_before_chapter` (bool), `strip_llm_artifacts` (bool)
- ImageItem saves cropped images to disk and returns markdown link
- CoverItem saves cover and returns YAML frontmatter (first only) or full-page image
- Supports compression markers via `is_compressed_line()` - lines starting with specific marker are removed from output

**Cross-Page Merging:**
- Items with `continues_to_next=True` and next item with `continues_from_previous=True` are merged
- Merging concatenates text and translations (if both present)
- Only ParagraphItem, ListItem, TableItem, and QuoteItem support merging
- Example: paragraph split mid-sentence across pages becomes single item

**JSON Round-Trip:**
- `to_json()` serializes item back to OCR JSON dict format
- Used to update OCR JSON with translations
- Preserves original fields (continues_from_previous, continues_to_next, etc.)

### Common Patterns

**Parsing OCR Response:**
```python
from context_aware_translation.documents.content.ocr_content import parse_ocr_json

page_type, items = parse_ocr_json(ocr_json_dict, source_image_bytes=image_bytes)
# page_type: "cover", "toc", "blank", or "content"
# items: list[OCRItem] ready for translation pipeline
```

**Creating MergedOCRContent from Multiple Pages:**
```python
from context_aware_translation.documents.content.ocr_content import MergedOCRContent

pages = [
    (ocr_page1_list, image_bytes1),
    (ocr_page2_list, image_bytes2),
]
merged = MergedOCRContent.from_raw_ocr(pages)
texts = merged.get_texts()  # Flat list of all translatable strings
```

**Extracting and Translating:**
```python
# Extract texts
texts = merged.get_texts()
print(f"Found {len(texts)} translatable strings")

# Translate via LLM (external)
translated = await llm_translate(texts)

# Distribute back
merged.set_texts(translated)

# Render to markdown
markdown = merged.to_markdown(
    image_dir=Path("/output/images"),
    insert_new_page_before_chapter=True,
    strip_llm_artifacts=True
)
```

**Single-Page OCR (Review View):**
```python
from context_aware_translation.documents.content.ocr_content import SinglePageOCRContent

# Load from raw OCR JSON (single page)
single = SinglePageOCRContent.from_ocr_json(ocr_page_list)
texts = single.get_texts()

# Edit and save back
single.set_texts(new_texts)
updated_json = single.to_json()  # Back to OCR JSON format
```

**Working with BoundingBox:**
```python
from context_aware_translation.documents.content.ocr_items import BoundingBox

# Crop image using normalized coordinates (0.0-1.0)
bbox = BoundingBox(x=0.1, y=0.2, width=0.8, height=0.6)
cropped_bytes = bbox.crop_from_image(full_page_image_bytes)

# From dict
bbox = BoundingBox.from_dict({"x": 0.1, "y": 0.2, "width": 0.8, "height": 0.6})
```

## Dependencies

### Internal
- `context_aware_translation.utils.compression_marker` - `is_compressed_line()`, `decode_compressed_lines()`
- `context_aware_translation.utils.markdown_escape` - `escape_markdown_text()`

### External
- `pillow` (PIL) - Image cropping via `Image.open()`, `img.crop()`
- `dataclasses` - `@dataclass` decorator for item types
- `typing` - Protocol, dataclass field annotations

<!-- MANUAL: -->
