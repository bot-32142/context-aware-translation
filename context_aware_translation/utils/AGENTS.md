<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# utils

## Purpose
Shared utility functions for text processing, file I/O, image handling, tokenization, format conversion, and string operations. Provides lower-level building blocks for document processing, chunking, normalization, and LLM JSON cleaning.

## Key Files

| File | Description |
|------|-------------|
| `chunking.py` | Token-based text chunking with sliding window overlap. Function: `chunk_text_by_tokens()` splits text using transformers tokenizer. Handles tokenizer lazy-loading and caching with fallback mechanism. |
| `semantic_chunker.py` | Semantic-aware text chunking. Function: `line_batched_semantic_chunker()`. Groups related lines into meaningful chunks preserving paragraph/section boundaries. |
| `cjk_normalize.py` | CJK (Chinese, Japanese, Korean) text normalization for matching and comparison. Function: `normalize_for_matching()` removes diacritics, spacing, unicode variants for fuzzy matching. |
| `string_similarity.py` | String similarity scoring. Function: `string_similarity()` computes Levenshtein-like distance. Used for term deduplication. |
| `hashing.py` | Content hashing for deduplication. Function: `compute_chunk_hash()` produces stable hash for chunk content. |
| `compression_marker.py` | Compression marker utilities for tracking summarized regions in context tree. |
| `image_utils.py` | Image processing helpers: resize, format conversion, EXIF rotation, quality optimization. Used by OCR and document import. |
| `file_utils.py` | File I/O utilities: safe path joining, directory creation, atomic writes. |
| `llm_json_cleaner.py` | Clean and repair LLM-generated JSON output. Handles missing quotes, trailing commas, incomplete structures. |
| `markdown_escape.py` | Markdown special character escaping. Prevents LLM output from breaking markdown parsing. |
| `pandoc_export.py` | Pandoc integration for document format conversion (Markdown to DOCX, PDF, etc.). |
| `symbol_check.py` | Validate strings against symbol-only patterns (e.g., punctuation, whitespace). |
| `__init__.py` | Package initialization. |

## Subdirectories
None. Utils is a flat module.

## For AI Agents

### Working In This Directory

**Text Processing:**
- `chunking.py`: line-based chunking with configurable overlap
- `semantic_chunker.py`: preserves semantic boundaries (use for long documents)
- Together they enable flexible document splitting strategies

**Normalization and Matching:**
- `cjk_normalize.py`: critical for CJK term deduplication (Chinese/Japanese/Korean)
- `string_similarity.py`: Levenshtein distance for fuzzy matching
- `hashing.py`: deterministic content hashing (same chunk → same hash)
- Used in `context_manager.py` for term deduplication

**Image Operations:**
- `image_utils.py`: PIL-based image resizing, format conversion, EXIF rotation
- Preprocessing step before OCR (standardize size/rotation)
- Used by `scanned_book.py`, `manga.py`, OCR modules

**File Safety:**
- `file_utils.py`: atomic writes, safe path joining
- Prevents partial writes and race conditions

**LLM Output Cleaning:**
- `llm_json_cleaner.py`: recover valid JSON from LLM hallucinations (missing quotes, commas)
- `markdown_escape.py`: escape special characters before markdown rendering
- Used in config parsing, glossary export, term translation

**Format Conversion:**
- `pandoc_export.py`: convert Markdown to DOCX, PDF, HTML
- Wrapper around pandoc CLI
- Used in document export operations

### Common Patterns

**Chunking a Document:**
```python
from context_aware_translation.utils.chunking import chunk_text_by_tokens, get_tokenizer
from context_aware_translation.utils.semantic_chunker import line_batched_semantic_chunker

# Token-based chunking with overlap
chunks = chunk_text_by_tokens(
    text=long_text,
    max_token_size=500,
    overlap_tokens=100,
    tokenizer_name="deepseek-v3"
)

# Semantic chunking (preserves paragraph boundaries)
chunks = line_batched_semantic_chunker(text, max_chunk_size=500)

# Get tokenizer for manual token counting
tokenizer = get_tokenizer("deepseek-v3")
token_count = len(tokenizer.encode(text))
```

**CJK Term Matching:**
```python
from context_aware_translation.utils.cjk_normalize import normalize_for_matching
from context_aware_translation.utils.string_similarity import string_similarity

# Normalize for matching
key1_norm = normalize_for_matching("你好")
key2_norm = normalize_for_matching("你 好")  # extra space
assert key1_norm == key2_norm  # True

# Fuzzy similarity
sim = string_similarity("hello", "helo")  # 0.8
```

**Content Hashing:**
```python
from context_aware_translation.utils.hashing import compute_chunk_hash

hash1 = compute_chunk_hash("same content")
hash2 = compute_chunk_hash("same content")
assert hash1 == hash2  # Deterministic
```

**Image Preprocessing:**
```python
from context_aware_translation.utils.image_utils import resize_image, fix_rotation

# Prepare image for OCR (standard size, correct rotation)
img = fix_rotation(img_path)
img_resized = resize_image(img, max_width=2400)
img_resized.save("preprocessed.png")
```

**Cleaning LLM JSON:**
```python
from context_aware_translation.utils.llm_json_cleaner import clean_json

malformed = '{"term": "hello, "translation": "你好}'
cleaned = clean_json(malformed)  # {"term": "hello", "translation": "你好"}
```

**Document Export:**
```python
from context_aware_translation.utils.pandoc_export import export_to_format

# Convert Markdown to DOCX
export_to_format(
    input_file="translated.md",
    output_file="output.docx",
    from_format="markdown",
    to_format="docx",
)
```

## Dependencies

### Internal
- None (utils has no internal dependencies; used by other modules)

### External
- `pillow` - Image processing (PIL.Image)
- `semchunk` - Semantic text chunking (line_batched_semantic_chunker)
- `difflib` (stdlib) - String similarity (SequenceMatcher for Levenshtein)
- `hashlib` (stdlib) - Content hashing (SHA256)
- `json` (stdlib) - JSON parsing/cleaning
- `pathlib` (stdlib) - Path manipulation
- `tempfile` (stdlib) - Atomic file operations
- `subprocess` (stdlib) - Pandoc subprocess calls (for pandoc_export)
- `re` (stdlib) - Regex for markdown escaping, symbol checking

<!-- MANUAL: -->
