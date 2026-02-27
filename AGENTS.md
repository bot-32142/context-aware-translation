<!-- Generated: 2026-02-26 -->

# context-aware-translation

## Purpose
A Python 3.12+ document translation system that uses LLMs with context-aware glossary management. Translates text, PDF, scanned books, and manga with hierarchical context trees that reduce token usage by 99%+.

## Key Files

| File | Description |
|------|-------------|
| `pyproject.toml` | Project config: dependencies, tooling (ruff, mypy, pytest) |
| `Makefile` | Build commands: `make check`, `make test`, `make build-ui` |
| `cat-ui.spec` | PyInstaller spec for standalone UI builds |
| `uv.lock` | Locked dependency versions (managed by uv) |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `context_aware_translation/` | Main package: core logic, LLM, documents, storage, UI (see `context_aware_translation/AGENTS.md`) |
| `tests/` | Test suites mirroring main package structure (see `tests/AGENTS.md`) |
| `scripts/` | Build and evaluation scripts (see `scripts/AGENTS.md`) |
| `installer/` | Platform-specific installer configs (see `installer/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- Use `uv` for dependency management (`uv sync`, `uv run`)
- Entry points: `cat-ui` (PySide6 GUI via `context_aware_translation.ui.main:main`)
- Run `make check` before committing (lint, format, typecheck, lupdate)
- All translation strings must have zh_CN translations; `make lupdate` will fail on unfinished entries

### Testing Requirements
- Run `make test` or `uv run pytest tests/`
- Tests run in parallel via pytest-xdist (`-n auto`)
- Async tests use pytest-asyncio with `auto` mode

### Common Patterns
- Config models in `config.py` using dataclasses
- SQLite with WAL mode for all storage (registry.db global, book.db per-book)
- 5 required config sections: extractor, summarizor, translator, glossary, review
- Ruff for linting+formatting, mypy for type checking (strict, excludes ui/ and tests/)
- PySide6 i18n with `.ts`/`.qm` translation files

## Dependencies

### External
- `pyside6` - Qt-based GUI framework
- `openai`, `google-genai` - LLM API clients
- `torch`, `transformers` - ML models for embeddings/tokenization
- `faiss-cpu` - Vector similarity search
- `pikepdf`, `pypdfium2` - PDF handling
- `pypandoc-binary` - Document format conversion
- `semchunk` - Semantic text chunking
- `tenacity` - Retry logic for API calls

<!-- MANUAL: -->
