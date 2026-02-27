<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# documents/content

## Purpose
Tests for OCR content models and data structures used in document preprocessing and text extraction.

## Key Files
| File | Description |
|------|-------------|
| `test_ocr_content.py` | Tests for OCR content model initialization, serialization, and state management |
| `test_ocr_items.py` | Tests for OCR item (word, line, block) data structures and text embedding operations |

## For AI Agents

### Working In This Directory

#### Running Tests
```bash
# Run all tests in this directory
uv run pytest tests/documents/content/ -v

# Run specific test file
uv run pytest tests/documents/content/test_ocr_content.py -v

# Run specific test
uv run pytest tests/documents/content/test_ocr_content.py::test_function_name -v

# Run with coverage
uv run pytest tests/documents/content/ --cov=context_aware_translation.documents
```

#### Testing Requirements

- Fixture dependencies: `temp_config`, `temp_db` from `tests/conftest.py`
- No external OCR services required (all mocked)
- Tests use temporary file paths via pytest `tmp_path` fixture

#### Common Test Patterns

1. **OCR Item Construction**: Create and validate OCR items (words, lines, blocks)
2. **State Transitions**: Test initialization, update, and finalization of content models
3. **Text Embedding**: Verify text extraction and coordinate mapping from OCR structures
4. **Round-trip Validation**: Load → parse → serialize → validate

<!-- MANUAL: -->
