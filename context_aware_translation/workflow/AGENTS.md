<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# workflow

## Purpose
Workflow orchestration layer connecting UI actions to core translation operations. Manages service lifecycle, sessions, task execution, and coordinates document processing pipelines (OCR, glossary building, translation, export).

## Key Files

| File | Description |
|------|-------------|
| `service.py` | Main workflow service (`WorkflowService`) orchestrating all operations: document loading, OCR, glossary building, glossary translation, term review, document translation, chunk retranslation, and export. Handles LLM prerequisites and document preflight. |
| `session.py` | Workflow session management (`WorkflowSession`) providing context manager lifecycle for runtime resource initialization. Supports creation from book manager or config snapshot. Handles context tree registry. |
| `bootstrap.py` | Service initialization and dependency wiring. Builds LLM client, context tree, translation manager, and manga document handler. Factory functions: `build_workflow_runtime()`. |
| `runtime.py` | Workflow runtime dataclass (`WorkflowRuntime`) bundling owned resources: config, LLM client, context tree, translation manager, database, document repository. |
| `image_fetcher.py` | Image fetcher for manga translation (`RepoImageFetcher`) backed by document repository with per-document caching for efficient page image lookup. |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `tasks/` | Task execution engine with operation handlers for background workflows. Includes `execution/` (batch translation operations) and `handlers/` (task handler implementations for glossary, translation, review, export). |

## For AI Agents

### Working In This Directory

**WorkflowService Architecture:**
- Main entry point for translation workflows
- Operates on loaded documents via document repository
- Manages LLM prerequisites (OCR, text extraction, language detection)
- Supports document selection (all documents, or specific document IDs)
- Coordinates with context tree for hierarchical summaries
- Handles both text and manga document types

**Core Workflow Steps:**
1. `run_ocr()` - OCR images to extract text (optional, image documents only)
2. `build_glossary()` - Extract terms and build occurrence mapping
3. `translate_glossary()` - Translate extracted glossary terms
4. `review_terms()` - Review and vote on term translations
5. `translate()` - Translate document chunks using glossary context
6. `retranslate_chunk()` - Re-translate a single chunk on demand
7. `export()` - Apply translations and export to file
8. `export_preserve_structure()` - Export while preserving document structure

**Session Lifecycle:**
- Create session from book manager or config snapshot
- Use as context manager: `with WorkflowSession(config) as service:`
- Session handles runtime bootstrap and resource cleanup
- Context tree is registered in global registry for multi-session sharing

**Document Preflight:**
- LLM steps require text to be extracted and language detected
- `_prepare_llm_prerequisites()` handles this setup automatically
- Scoped to selected documents, but respects chunk ordering (all documents <= selected_max)
- Glossary-only steps use `_ensure_glossary_source_language()` with fallback

**Export Modes:**
- Merged export: all documents to single file
- Preserve structure: per-document folder exports (EPUB-specific)
- Fallback semantics: untranslated chunks use original text or empty (manga)

### Common Patterns

**Using WorkflowService:**
```python
from context_aware_translation.workflow import WorkflowSession

with WorkflowSession(config) as service:
    # Build glossary
    await service.build_glossary(document_ids=[1, 2])

    # Translate glossary
    await service.translate_glossary()

    # Translate documents
    await service.translate(document_ids=[1, 2])

    # Export
    await service.export(Path("output.txt"))
```

**Progress Callback:**
```python
from context_aware_translation.core.progress import ProgressCallback, ProgressUpdate, WorkflowStep

def on_progress(update: ProgressUpdate):
    print(f"{update.step.value}: {update.message} ({update.current}/{update.total})")

await service.build_glossary(progress_callback=on_progress)
```

**Cancellation:**
```python
import threading

cancel_flag = {"cancelled": False}

def cancel_check():
    return cancel_flag["cancelled"]

# Start workflow
task = asyncio.create_task(service.translate(cancel_check=cancel_check))

# Cancel from another thread
cancel_flag["cancelled"] = True
```

**Session from Config Snapshot:**
```python
json_snapshot = book_manager.get_config_snapshot_json(book_id)
with WorkflowSession.from_snapshot(json_snapshot, book_id) as service:
    await service.translate()
```

### Task System Integration

The `tasks/` subdirectory implements a pure-Python task engine (`EngineCore`) with:
- Task handler protocol: each operation type (glossary_extraction, translation, etc.) has a handler
- Resource claims system: prevents concurrent conflicting operations on same resources
- Task store: persists task records with status, payload, and metadata
- Worker dispatch: spawns workers (UI threads or background processes) based on task type
- Cancellation support: handlers implement cancellation policies and outcome classification

**Handler Pattern:**
Each handler implements `TaskTypeHandler` protocol:
- `decode_payload()` - deserialize task parameters
- `scope()` - document scope affected by task
- `claims()` - resource locks required (glossary, document, etc.)
- `can()` - check if action is allowed given current state
- `can_autorun()` - check if task should auto-start
- `build_worker()` - create worker instance
- `cancel_dispatch_policy()` - how to handle cancellation

### Key Dependencies

**Internal:**
- `context_aware_translation.core` - context tree, context manager, progress tracking, cancellation
- `context_aware_translation.documents` - document types (text, PDF, manga, etc.)
- `context_aware_translation.llm` - LLM client and translation strategies
- `context_aware_translation.storage` - SQLite persistence, book DB, document repository, term repository
- `context_aware_translation.ui` - (reverse dependency) UI invokes workflow via WorkflowSession

**External:**
- `asyncio` - async/await for LLM operations
- `threading` - per-book bootstrap locks, cancellation signals
- `transformers` - tokenizer for chunk estimation
- `tenacity` - retry logic in LLM calls

## Dependencies

### Internal
- `context_aware_translation.core.context_tree` - hierarchical summarization
- `context_aware_translation.core.context_manager` - glossary and translation orchestration
- `context_aware_translation.core.progress` - progress reporting
- `context_aware_translation.core.cancellation` - cancellation token pattern
- `context_aware_translation.documents` - document type loading and exporting
- `context_aware_translation.llm.client` - LLM operations
- `context_aware_translation.storage.schema.book_db` - chunk and term persistence
- `context_aware_translation.storage.repositories.document_repository` - document metadata and sources
- `context_aware_translation.storage.repositories.term_repository` - term deduplication and lookup
- `context_aware_translation.config` - configuration models

### External
- `asyncio` - async workflow orchestration
- `threading` - synchronization and cancellation
- `pathlib.Path` - file path handling
- `dataclasses` - runtime dataclass definitions

<!-- MANUAL: -->
