<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# core

## Purpose
Core translation engine implementing hierarchical context trees (LSM-tree-like summaries), context management, translation strategy patterns, cancellation signals, progress tracking, and data models. Reduces token usage by 99%+ through intelligent hierarchical compression of long documents.

## Key Files

| File | Description |
|------|-------------|
| `context_tree.py` | LSM-tree-like hierarchical summary structure. Multi-threaded, thread-safe, persisted to SQLite. Summarizes long chunks recursively to reduce token usage; supports async operations and cancellation. Core class: `ContextTree`. |
| `context_manager.py` | Manages context tree operations across document lifecycle. Orchestrates gleaning (term extraction), summarization, context retrieval, and integration with glossary. Multi-pass term deduplication and noise filtering. Main class: `ContextManager`. |
| `context_tree_registry.py` | Registry for managing context trees across multiple documents. Tracks tree lifecycle and metadata. Class: `ContextTreeRegistry`. |
| `context_extractor.py` | Extracts context (section summaries, key terms, document structure) from raw document text. |
| `translation_strategies.py` | Abstract strategy patterns for document handlers, LLM operations: `SourceLanguageDetector`, `ChunkTranslationStrategy`, `GlossaryTranslationStrategy`, `TermReviewer`, `DescriptionSummarizer`, `DocumentTypeHandler`. |
| `progress.py` | Progress tracking and reporting. Classes: `ProgressUpdate`, `WorkflowStep`, `ProgressCallback`. |
| `models.py` | Core data models: `KeyedContext`, `Term`, and other domain objects. |
| `cancellation.py` | Cancellation token pattern. Functions for setting/checking cancellation state across threads. |
| `__init__.py` | Package initialization. |

## Subdirectories
None. Core is a flat module.

## For AI Agents

### Working In This Directory

**Context Tree Architecture:**
- `ContextTree` is an LSM-tree-like data structure for hierarchical summarization
- Splits long documents into chunks; summarizes chunks recursively to reduce token usage
- Multi-threaded with thread-safe operations
- Persists to SQLite via `ContextTreeDB` (in `storage/`)
- Max token size configurable (default 250 tokens per node)
- Supports cancellation via `raise_if_cancelled()` checks

**Context Manager Lifecycle:**
- Wraps `ContextTree` and manages document workflow
- Multi-pass term gleaning: extract → deduplicate → noise filter → review → translate
- Integrates glossary system (term matching, translation lookup)
- Tracks occurrence counts, voting, descriptions (multi-pass extraction)
- Handles both text and image-based documents (OCR integration)

**Strategy Patterns:**
- `DocumentTypeHandler`: abstract interface for document-specific operations
- `SourceLanguageDetector`: identify source language (used in config)
- `ChunkTranslationStrategy`: translate chunks with context
- `GlossaryTranslationStrategy`: translate terms with context
- `TermReviewer`: review and vote on term translations
- `DescriptionSummarizer`: summarize term descriptions

**Cancellation and Progress:**
- `raise_if_cancelled()` checks thread-local cancellation flag
- `ProgressCallback` reports workflow steps and updates to UI
- `WorkflowStep` enum: `GLEANING`, `EXTRACTION`, `REVIEW`, etc.

**Key Dependencies:**
- `context_aware_translation.storage.schema.context_tree_db` - SQLite backend for trees
- `context_aware_translation.storage.schema.book_db` - term records, chunk records
- `context_aware_translation.storage.repositories.term_repository` - term dedup and lookup
- `context_aware_translation.utils.*` - chunking, hashing, string similarity, CJK normalization
- `transformers.PreTrainedTokenizer` - tokenization for token counting

### Common Patterns

**Using ContextTree:**
```python
from context_aware_translation.core.context_tree import ContextTree
from context_aware_translation.storage.schema.context_tree_db import ContextTreeDB

tree = ContextTree(
    summarizer=summarizer,  # DescriptionSummarizer instance
    estimate_token_size_func=tokenizer.estimate_token_size,
    sqlite_path=db_path,
    max_token_size=250,
)
summary = await tree.summarize(long_text)
```

**Using ContextManager:**
```python
from context_aware_translation.core.context_manager import ContextManager

manager = ContextManager(
    context_tree=tree,
    glossary_translator=glossary_translator,
    term_repository=term_repo,
    progress_callback=progress_callback,
)
await manager.gleaning_pass(chunks)
```

**Cancellation:**
```python
from context_aware_translation.core.cancellation import set_cancellation, raise_if_cancelled

# In a worker thread, check cancellation:
raise_if_cancelled()  # Raises CancelledError if cancelled

# From parent thread:
set_cancellation(True)
```

**Progress Reporting:**
```python
from context_aware_translation.core.progress import ProgressCallback, WorkflowStep, ProgressUpdate

def on_progress(update: ProgressUpdate):
    print(f"{update.step.value}: {update.message}")

callback = ProgressCallback(on_progress)
```

## Dependencies

### Internal
- `context_aware_translation.storage.schema.context_tree_db` - SQLite persistence for context trees
- `context_aware_translation.storage.schema.book_db` - chunk and term records
- `context_aware_translation.storage.repositories.term_repository` - term deduplication and batch updates
- `context_aware_translation.utils.chunking` - text chunking utilities
- `context_aware_translation.utils.hashing` - content hashing for dedup
- `context_aware_translation.utils.cjk_normalize` - CJK text normalization for matching
- `context_aware_translation.utils.semantic_chunker` - semantic-aware text chunking
- `context_aware_translation.utils.string_similarity` - fuzzy string matching
- `context_aware_translation.utils.symbol_check` - symbol-only validation

### External
- `transformers` - `PreTrainedTokenizer` for token estimation
- `tenacity` - retry logic (for LLM calls in strategies)
- Python stdlib: `asyncio`, `threading`, `concurrent.futures`

<!-- MANUAL: -->
