<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# ui/workers

## Purpose
Tests for UI background worker classes handling translation, glossary export/review, and config snapshot operations.

## Key Files
| File | Description |
|------|-------------|
| `test_batch_task_overlap_guard.py` | Concurrency guard: prevents overlapping batch tasks |
| `test_config_snapshot_workers.py` | Config snapshot capture and recovery during batch operations (11,104 lines) |
| `test_glossary_export_task_worker.py` | Glossary export worker: UI signaling, batch processing, error recovery (15,956 lines) |
| `test_glossary_review_task_worker.py` | Glossary review worker: interactive glossary selection and validation |
| `test_operation_tracker.py` | Resource tracking: active operation monitoring and cleanup |
| `test_translation_text_task_worker.py` | Text translation worker: batch document processing, progress reporting (11,834 lines) |
| `test_translation_manga_task_worker.py` | Manga translation worker: image-based content processing (8,441 lines) |

## For AI Agents

### Working In This Directory

#### Running Tests
```bash
# Run all tests in this directory
uv run pytest tests/ui/workers/ -v

# Run specific test file
uv run pytest tests/ui/workers/test_translation_text_task_worker.py -v

# Run specific test
uv run pytest tests/ui/workers/test_glossary_export_task_worker.py::test_function_name -v

# Run with coverage
uv run pytest tests/ui/workers/ --cov=context_aware_translation.ui.workers
```

#### Testing Requirements

- **Async Support**: All workers use async; pytest-asyncio auto mode enabled
- **Qt Threading**: Workers use QThread; mock Qt signals in tests
- **Fixtures**: `temp_config`, `temp_db`, `temp_context_tree_db` from conftest
- **Mocking**: Mock LLM calls, file I/O, and Qt signals to avoid external dependencies

#### Worker Testing Patterns

1. **Initialization**: Verify worker setup with required resources
2. **Signal Emission**: Mock Qt signals; verify correct signal sequence on state changes
3. **Error Handling**: Test worker behavior on LLM failures, I/O errors, cancellation
4. **Progress Tracking**: Verify progress signals emitted at expected intervals
5. **Cleanup**: Ensure resources released on worker completion or cancellation

#### Common Patterns
```python
from unittest.mock import MagicMock, patch, AsyncMock
from context_aware_translation.ui.workers import TranslationTextTaskWorker

# Mock Qt signals
worker.progress_updated = MagicMock()
worker.finished = MagicMock()

# Mock LLM calls
with patch("context_aware_translation.llm.translator.Translator.translate") as mock_translate:
    mock_translate.return_value = "translated text"
```

<!-- MANUAL: -->
