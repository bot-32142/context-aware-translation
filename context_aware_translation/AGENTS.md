<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# context_aware_translation

## Purpose
Core package for LLM-powered document translation with context-aware glossary management. Implements hierarchical context trees (LSM-tree-like), multi-pass glossary extraction, SQLite storage with WAL mode, and PySide6 GUI. Supports text, PDF, scanned books, and manga documents.

## Key Files

| File | Description |
|------|-------------|
| `config.py` | All config dataclasses: `LLMConfig`, `ExtractorConfig`, `SummarizerConfig`, `TranslatorConfig`, `GlossaryConfig`, `ReviewConfig`, `OCRConfig`, `ImageReembeddingConfig`, `MangaTranslatorConfig`, `EndpointProfile`. Central config hub; note: `num_of_chunks_per_llm_call` must NOT exceed 10. |
| `glossary_io.py` | Glossary import/export to/from JSON files; handles term consolidation and validation. |
| `__init__.py` | Package initialization and logging configuration via `configure_logging()`. |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `core/` | Context tree and translation strategies: `context_tree.py` (hierarchical summarization), `context_manager.py` (context lifecycle), `translation_strategies.py` (strategy patterns), `context_extractor.py`, `progress.py`, `models.py`. |
| `documents/` | Document type implementations: `text.py`, `pdf.py`, `scanned_book.py`, `manga.py`, `base.py` (abstract Document class), plus EPUB support and alignment utilities. |
| `llm/` | LLM integration layer: `client.py` (OpenAI client with retry/timeout), `translator.py`, `extractor.py`, `glossary_translator.py`, `summarizor.py`, `reviewer.py`, `ocr.py`, `manga_ocr.py`, `language_detector.py`, `token_tracker.py`, `image_backends/` (PIL, DALL-E, etc.), `batch_jobs/` (batch processing). |
| `storage/` | SQLite persistence layer: `book_db.py` (term records), `registry_db.py` (global registry), `book_manager.py` (book lifecycle), `task_store.py` (task records), `context_tree_db.py` (context tree storage), `document_repository.py`, `endpoint_profile.py`, `config_profile.py`, `term_repository.py`, plus batch task stores. |
| `ui/` | PySide6 GUI: `main_window.py` (sidebar navigation), `main.py` (entry point), `views/` (translation_view, glossary_view, book_workspace, etc.), `widgets/` (task_status_card, task_activity_panel, config_editor, etc.), `workers/` (task workers), `tasks/` (Qt task engine), `dialogs/`, `models/`, `i18n.py` (zh_CN translations). |
| `workflow/` | Task orchestration and execution: `service.py` (WorkflowService), `runtime.py`, `bootstrap.py`, `session.py`, `tasks/` (EngineCore, task handlers, claims, execution), `__init__.py` (exports entry points). |
| `utils/` | Helper utilities: `chunking.py`, `cjk_normalize.py`, `markdown_escape.py`, `image_utils.py`, `hashing.py`, `file_utils.py`, semantic chunking, string similarity, symbol checking. |
| `resources/` | Static assets: tokenizer data and other resources. |

## For AI Agents

### Working In This Directory

**Config Management:**
- Central config hub is `config.py` (all dataclasses for 5 required + 3 optional steps)
- `EndpointProfile` allows reusable API endpoint configs; step configs can reference profiles
- **Critical:** `num_of_chunks_per_llm_call` must NOT exceed 10 (causes hallucinations; default 5)
- `noise_filtering_threshold`: 0.5 default (0=lenient, 1=strict)
- `max_gleaning`: 3 default (multi-pass extraction; more = thorough but costlier)
- `ocr_dpi`: 150 default (72-300 range)

**Architecture:**
- `workflow/service.py` is the main orchestrator (WorkflowService)
- `workflow/tasks/engine_core.py` is the pure-Python task scheduling engine (no Qt)
- Task handlers in `workflow/tasks/handlers/` implement task_type-specific logic
- UI workers in `ui/workers/` bridge Qt signals to task engine
- SQLite with WAL mode everywhere (registry.db global, book.db per-book, context_tree.db)

**Type Safety:**
- mypy strict mode enabled (excludes ui/ and tests/)
- All core logic is type-checked
- Config models are dataclass-based with validation in `__post_init__`

**Entry Points:**
- UI: `ui.main:main` (PySide6 GUI application)
- Workflow: `workflow.service:WorkflowService` (programmatic translation)

### Testing Requirements

- Tests mirror main package structure in `tests/`
- Run `uv run pytest tests/` or `make test`
- Tests run in parallel via pytest-xdist
- Async tests use pytest-asyncio with auto mode
- Key test files: `test_context_tree.py`, `test_book_db.py`, `test_translation_view.py`, `test_glossary_view.py`, task worker tests

### Common Patterns

**Config and Dataclasses:**
- All config classes inherit from `LLMConfig` or extend it
- Use `to_dict()` / `from_dict()` for serialization
- Profile references are resolved at config load time

**SQLite Storage:**
- All tables use WAL mode for concurrent access
- Use transaction context managers (`with db.conn:`)
- Term records include descriptions (multi-pass gleaning), occurrence counts, votes, timestamps

**Document Abstraction:**
- `Document` base class in `documents/base.py`
- Subclasses: `TextDocument`, `PDFDocument`, `ScannedBookDocument`, `MangaDocument`
- Document type determines available operations (OCR, image extraction, etc.)

**Context Trees:**
- Hierarchical summaries stored in `context_tree_db`
- Reduces token usage by 99%+ via LSM-tree-like compression
- Managed by `ContextManager` and `ContextTree` in core/

**LLM Integration:**
- `LLMClient` wraps OpenAI API with retry logic (tenacity)
- All LLM calls go through `client.py` (single source of truth for API config)
- Async execution with configurable concurrency
- Token tracking via `TokenTracker`

**PySide6 UI:**
- Main window navigation via `QListWidget` sidebar
- Stacked widget for view switching
- Translation strings in `.ts` / `.qm` files (zh_CN)
- Workers for long-running operations (glossary extraction, OCR, translation)
- Task status monitoring via `TaskStatusCard` and `TaskActivityPanel`

**Task Execution:**
- Pure-Python `EngineCore` in `workflow/tasks/engine_core.py`
- Task handlers implement `TaskTypeHandler` interface
- Claims-based resource arbitration to prevent concurrent conflicts
- Config snapshot capture for fault tolerance

## Dependencies

### Internal
- `context_aware_translation.config` - central config models
- `context_aware_translation.core.*` - context tree, strategies, progress tracking
- `context_aware_translation.documents.*` - document type implementations
- `context_aware_translation.llm.*` - LLM client, translator, extractor, OCR
- `context_aware_translation.storage.*` - SQLite repos, book manager
- `context_aware_translation.workflow.*` - task orchestration
- `context_aware_translation.ui.*` - PySide6 GUI (type-checked separately)
- `context_aware_translation.utils.*` - text/image processing utilities

### External (Top-Level)
- `pyside6` - Qt GUI framework (mypy strict excluded)
- `openai` - OpenAI API client
- `google-genai` - Google Gemini API client
- `tenacity` - Exponential backoff retry logic
- `torch`, `transformers` - ML models for embeddings, tokenization
- `faiss-cpu` - Vector similarity for context relevance
- `pikepdf`, `pypdfium2` - PDF parsing and extraction
- `pypandoc-binary` - Document format conversion (Markdown, DOCX)
- `semchunk` - Semantic text chunking
- `yaml` - Config file parsing
- `pillow` - Image processing
- `pydantic` - Config validation (used selectively)

<!-- MANUAL: -->
