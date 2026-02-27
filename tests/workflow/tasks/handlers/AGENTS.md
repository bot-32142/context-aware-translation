<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# workflow/tasks/handlers

## Purpose
Tests for all task handler implementations covering translation, glossary operations, batch processing, and content-specific handlers.

## Key Files
| File | Description |
|------|-------------|
| `test_batch_translation_handler.py` | Batch translation task handler: multi-document orchestration, resource claims (13,869 lines) |
| `test_chunk_retranslation_handler.py` | Chunk retranslation handler: selective re-execution, context preservation (11,638 lines) |
| `test_glossary_export_handler.py` | Glossary export task handler: term collection, formatting, validation (14,868 lines) |
| `test_glossary_review_handler.py` | Glossary review task handler: interactive term selection, filtering (14,697 lines) |
| `test_translation_text_handler.py` | Text translation handler: document chunking, sequential translation (13,701 lines) |
| `test_translation_manga_handler.py` | Manga translation handler: image-based translation with OCR integration (14,589 lines) |

## For AI Agents

### Working In This Directory

#### Running Tests
```bash
# Run all tests in this directory
uv run pytest tests/workflow/tasks/handlers/ -v

# Run specific test file
uv run pytest tests/workflow/tasks/handlers/test_batch_translation_handler.py -v

# Run specific test
uv run pytest tests/workflow/tasks/handlers/test_translation_text_handler.py::test_function_name -v

# Run with coverage
uv run pytest tests/workflow/tasks/handlers/ --cov=context_aware_translation.workflow
```

#### Testing Requirements

- **Async Support**: All handlers are async; use `async def test_*()` syntax
- **Fixtures**: `temp_config`, `temp_db`, `temp_context_tree_db` from conftest
- **Mocking**: Mock LLM calls (translator, extractor), file I/O, OCR services
- **Database**: Temporary SQLite DBs for books and context tree storage
- **Test Data**: Use `tmp_path` for temporary document files (no hardcoded paths)

#### Handler Testing Patterns

1. **Handler Initialization**: Verify handler accepts configuration and resource claims
2. **Input Validation**: Test with valid and invalid input specifications
3. **Execution**: Verify handler processes input and produces expected output
4. **Progress Tracking**: Confirm progress callbacks fire at expected intervals
5. **Error Handling**: Test recovery from LLM failures, I/O errors, timeouts
6. **Cleanup**: Verify resources released on completion or cancellation
7. **State Persistence**: Task state saved to database; verify recovery

#### Translation Handler Patterns
```python
from context_aware_translation.workflow.tasks.handlers import TranslationTextHandler

handler = TranslationTextHandler(config=temp_config, db=temp_db)

# Mock LLM calls
with patch("context_aware_translation.llm.translator.Translator.translate") as mock_translate:
    mock_translate.return_value = "translated text"

    # Execute handler
    result = await handler.execute(spec, progress_callback=mock_callback)

    # Verify output
    assert result.status == "complete"
    assert len(result.translated_chunks) > 0
```

#### Glossary Handler Patterns
```python
from context_aware_translation.workflow.tasks.handlers import GlossaryExportHandler

handler = GlossaryExportHandler(config=temp_config, db=temp_db)

# Execute glossary export
result = await handler.execute(spec, progress_callback=mock_callback)

# Verify format and completeness
assert "glossary" in result
assert all("term" in entry and "definition" in entry for entry in result["glossary"])
```

#### Batch Handler Patterns
```python
from context_aware_translation.workflow.tasks.handlers import BatchTranslationHandler

handler = BatchTranslationHandler(config=temp_config, db=temp_db)

# Submit multiple documents
spec = {..., "documents": [doc1, doc2, doc3]}
result = await handler.execute(spec, progress_callback=mock_callback)

# Verify all documents processed
assert len(result.translated_documents) == 3
```

### Handler Categories

**Translation Handlers**
- `test_translation_text_handler.py`: Text document translation
- `test_translation_manga_handler.py`: Manga/image-based translation with OCR
- `test_chunk_retranslation_handler.py`: Selective chunk re-translation with context

**Glossary Handlers**
- `test_glossary_export_handler.py`: Extract and export glossary terms
- `test_glossary_review_handler.py`: Interactive glossary term review and filtering

**Batch Handlers**
- `test_batch_translation_handler.py`: Multi-document batch translation orchestration

<!-- MANUAL: -->
