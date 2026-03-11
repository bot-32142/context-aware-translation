<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# tests

## Purpose
Comprehensive test suite (107 tests) mirroring the main package structure. Tests cover core logic, LLM integrations, document handlers, storage/database operations, UI components, and end-to-end workflows. All tests run in parallel via pytest-xdist with async support.

## Key Files
| File | Description |
|------|-------------|
| `conftest.py` | Shared pytest fixtures: `temp_config` (Config with dummy API settings), `temp_db` (SQLiteBookDB), `temp_context_tree_db` (ContextTreeDB) |
| `test_glossary_io.py` | Glossary import/export: consolidation, validation, round-trip I/O |
| `data/` | Test fixtures: `test_chunk.txt`, `test_chunk2.txt` for document parsing tests |

## Subdirectories

| Directory | Purpose | Key Tests |
|-----------|---------|-----------|
| `config/` | Config model validation | `test_endpoint_profiles.py` |
| `core/` | Context tree, strategy, extraction | `test_context_tree.py` (1227 lines), `test_context_manager.py` (1235 lines), `test_translation_context_manager_strategy_api.py` (1343 lines), `test_context_extractor.py`, `test_noise_filtering_pipeline.py` |
| `documents/` | Document type handlers (Text, PDF, EPUB, scanned books, manga) | `test_epub.py` (2085 lines), `test_epub_container.py` (1377 lines), `test_scanned_book.py` (802 lines), `test_pdf.py` (855 lines), `test_manga.py` |
| `documents/content/` | Content preprocessing (xhtml utils, inline markers, OCR text embedding) | `test_epub_xhtml_utils.py` (743 lines), `test_epub_inline_markers.py`, `test_ocr_image_embedded_text.py` |
| `integration/` | End-to-end workflows | `test_business_logic.py`, `test_multi_document.py`, `test_service_bootstrap_lock.py`, `test_service_cancellation_semantics.py` |
| `llm/` | LLM clients, translators, extractors, OCR, batch gateways | `test_translator.py` (710 lines), `test_llm_client.py`, `test_extractor.py`, `test_ocr.py`, `test_gemini_backend.py`, `test_gemini_batch_gateway.py` |
| `storage/` | SQLite repositories, book manager, context tree DB | `test_book_db.py` (1444 lines), `test_book_manager.py` (1021 lines), `test_term_repository.py` (868 lines), `test_context_tree_db.py`, `test_document_repository.py` |
| `ui/` | PySide6 views, widgets, worker coordination | `test_glossary_view.py` (845 lines), `test_translation_view_refresh.py` (792 lines), `test_book_workspace_activity.py`, `test_config_editor.py`, `test_export_view.py` |
| `ui/tasks/` | Qt adapter task-engine tests | `test_task_engine.py` (13460 lines) |
| `ui/workers/` | Qt adapter worker tests (translation, glossary export/review, config snapshot) | `test_translation_text_task_worker.py` (11834 lines), `test_translation_manga_task_worker.py` (8441 lines), `test_glossary_export_task_worker.py` (15956 lines), `test_config_snapshot_workers.py` (11104 lines) |
| `utils/` | Utility functions (chunking, hashing, markdown, JSON cleaning) | `test_chunking.py`, `test_semantic_chunker.py`, `test_string_similarity.py`, `test_symbol_check.py` |
| `workflow/` | Workflow orchestration, session management, task handlers | `test_session.py`, `test_service_cancellation_semantics.py`, `test_translator_import_path.py` |
| `workflow/tasks/execution/` | Task execution primitives | (Subdirectory for execution handlers) |
| `workflow/tasks/handlers/` | Task handlers (batch translation, glossary export/review, text/manga translation) | `test_batch_translation_handler.py` (13869 lines), `test_glossary_export_handler.py` (14868 lines), `test_translation_text_handler.py` (13701 lines), `test_translation_manga_handler.py` (14589 lines) |

## For AI Agents

### Working In This Directory

#### Running Tests
```bash
# Run all tests in parallel (default via pytest.ini addopts)
make test
# or
uv run pytest tests/

# Run specific test file
uv run pytest tests/ui/test_glossary_view.py -v

# Run specific test
uv run pytest tests/core/test_context_tree.py::test_some_function -v

# Run with coverage
uv run pytest tests/ --cov=context_aware_translation

# Run without parallelism (debugging)
uv run pytest tests/ -n 0
```

#### Pytest Configuration
- **Entry point:** `testpaths = ["tests"]` in `pyproject.toml`
- **Parallelism:** `addopts = "-v --tb=short -n auto"` (pytest-xdist auto-detects CPU count)
- **Async mode:** `asyncio_mode = "auto"` with `asyncio_default_fixture_loop_scope = "function"`
- **Test discovery:** `python_files = ["test_*.py"]`, `python_functions = ["test_*"]`

### Testing Requirements

#### Fixtures (conftest.py)
- `temp_config`: Pre-configured `Config` object with dummy API keys for safe testing
- `temp_db`: Temporary SQLiteBookDB; auto-closed in teardown
- `temp_context_tree_db`: Temporary ContextTreeDB; auto-closed in teardown
- All paths use `tmp_path` pytest fixture for isolation

#### Test Data
- Located in `tests/data/`: `test_chunk.txt`, `test_chunk2.txt`
- Document fixtures (PDF, EPUB, images, manga) in subdirectories under `documents/content/`
- Use `tmp_path` for file-based tests; do not hardcode paths

#### PySide6 UI Tests
- Tests skip gracefully if PySide6 not installed: `pytestmark = pytest.mark.skipif(not HAS_PYSIDE6, reason="PySide6 not available")`
- Use `@pytest.fixture(autouse=True, scope="module")` to ensure QApplication singleton initialized once per module
- Mock QApplication interactions where possible; avoid real Qt event loops in unit tests

#### Common Patterns

**1. Database Tests**
```python
@pytest.fixture
def temp_db(tmp_path: Path) -> Generator[SQLiteBookDB]:
    db = SQLiteBookDB(tmp_path / "book.db")
    yield db
    db.close()

def test_db_operation(temp_db):
    # Use temp_db directly
    pass
```

**2. Config Tests**
```python
def test_with_config(temp_config: Config):
    # temp_config has dummy API settings
    assert temp_config.working_dir.exists()
```

**3. Async Tests**
- Use `async def test_*()` syntax; no `@pytest.mark.asyncio` needed (auto mode enabled)
- Framework auto-creates event loops per function

**4. Mocking LLM Responses**
```python
from unittest.mock import patch, MagicMock
# Patch specific LLM client methods to avoid real API calls
with patch("context_aware_translation.llm.llm_client.SomeClient.request") as mock:
    mock.return_value = {"response": "mocked"}
```

**5. UI Tests with State**
- Use `MagicMock` to replace real Qt widgets where testing logic only
- Examples in `tests/ui/test_glossary_view.py`: noop `__init__` replacement to test view state without full Qt initialization

**6. Document Handler Tests**
- Use `temp_path` to create temporary test documents
- Verify round-trip: load → extract → validate → export
- Example: `tests/documents/test_epub.py` tests EPUB parsing without requiring actual EPUB files in repo

### Integration Testing
- `tests/integration/`: End-to-end workflows (bootstrap, cancellation semantics, multi-document)
- Use real `Config`, temporary databases, and mock LLM clients
- Verify task execution flow, resource claims, and cleanup

### Linting & Type Checking
- Tests excluded from mypy strict checking (see `pyproject.toml` `exclude = ["tests/"]`)
- Tests follow ruff lint rules; note `tests/*` exemption for `B905` (zip without strict)
- Run `make check` to validate lint across entire codebase

## Dependencies

### Test Framework
- `pytest>=9.0.2` - Test runner and fixtures
- `pytest-asyncio>=0.25.0` - Async test support with auto mode
- `pytest-cov>=6.0.0` - Coverage reporting
- `pytest-xdist>=3.8.0` - Parallel test execution

### Project Dependencies
Tests import from main package:
- `context_aware_translation.config` - Config models
- `context_aware_translation.core` - Context tree, strategies
- `context_aware_translation.documents` - Document handlers
- `context_aware_translation.llm` - LLM clients, translators
- `context_aware_translation.storage` - Database repositories
- `context_aware_translation.ui` - PySide6 UI components (conditional)
- `context_aware_translation.workflow` - Task orchestration

### Optional (UI Tests Only)
- `PySide6>=6.6.0` - Qt framework (tests skip if not available)

<!-- MANUAL: -->
