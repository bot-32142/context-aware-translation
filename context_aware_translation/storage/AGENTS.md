<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# storage

## Purpose
SQLite-based persistence layer with WAL mode for concurrent access. Implements registry.db (global) and book.db (per-book) pattern. Owns persisted models, book-library management, context tree storage, repository access, task persistence, and batch job tracking.

## Key Files

| File | Description |
|------|-------------|
| `schema/registry_db.py` | Global SQLite registry database. Stores config profiles, endpoint profiles, book metadata, and cluster-level settings. Single shared database across all books. WAL mode enabled. |
| `schema/book_db.py` | Per-book SQLite database. Stores glossary term records (name, description, occurrence count, votes, translations, timestamps). Each book has its own `book.db` file. WAL mode enabled. |
| `library/book_manager.py` | Book lifecycle management. Creates/deletes books, manages folder structure, snapshots configs. Bridges UI/workflow to book metadata and storage. |
| `models/book.py` | Book data model: `Book` class with id, name, status (`BookStatus` enum), and timestamps. Lightweight metadata container. |
| `models/config_profile.py` | Config profile storage model. Stores complete workflow configs (extractor, translator, glossary, review, OCR, etc.) in JSON form. |
| `models/endpoint_profile.py` | Endpoint profile storage model. Stores API key, base_url, model, concurrency limits, token budgets, and other per-provider settings. |
| `schema/context_tree_db.py` | Context tree SQLite storage for hierarchical summarization. Stores compressed context nodes and LSM-tree metadata for token-efficient context retrieval. |
| `repositories/document_repository.py` | CRUD operations for documents within a book. Manages document metadata and associations with extracted content. |
| `repositories/term_repository.py` | Glossary term CRUD. Queries, inserts, updates, deletes terms from book_db. Handles multi-pass refinement (description, occurrence count, votes). |
| `repositories/task_store.py` | Persistence for workflow tasks. Stores task state, claims, progress metadata for resumable execution. |
| `repositories/llm_batch_store.py` | Batch job persistence for OpenAI batch API. Stores submitted requests and polls for completed results. |
| `repositories/translation_batch_task_store.py` | Specialized batch task storage for translation workflows. Tracks batch-level progress and partial results. |

## Subdirectories (if any)

| Directory | Purpose |
|-----------|---------|
| `schema/` | SQLite database owners and schema definitions (`book.db`, `registry.db`, `context_tree.db`). |
| `repositories/` | Repository-style access layers and task/batch stores built on top of the schema modules. |
| `models/` | Persisted storage records used by the schema and higher-level storage services. |
| `library/` | Book-library and filesystem management built on top of the registry schema. |

## For AI Agents

### Working In This Directory

**Database Pattern (WAL Mode):**
- All SQLite databases use WAL (Write-Ahead Logging) mode for safe concurrent access
- Registry database is global at `registry_root/registry.db`
- Per-book databases are at `book_path/book.db`
- Context tree database is at `book_path/context_tree.db`
- Always use transaction context managers: `with db.conn:` for atomic operations

**Config Profile System:**
- Configs are stored as JSON blobs in `registry_db.config_profiles` table
- Each profile has a name (unique), description, JSON payload, and is_default flag
- Use `ConfigProfile.from_dict()` to deserialize and `to_dict()` to serialize
- Endpoint profiles are referenced by name; resolution happens at load time

**Endpoint Profile System:**
- Endpoint profiles store API credentials, model selection, rate limits, and token budgets
- `endpoint_profiles` table in `registry_db` is the single source of truth
- Each profile has: api_key, base_url, model, temperature, timeout, max_retries, concurrency, token_limit, tokens_used
- Token usage is tracked and compared against token_limit for quota enforcement

**Book Lifecycle:**
- Books are created via `BookManager.create_book()` which initializes folder structure and SQLite databases
- Each book gets a unique id (UUID), folder path, and status enum (`BookStatus`: ACTIVE, ARCHIVED, DELETED)
- Deleting a book via `BookManager.delete_book()` removes folder and all associated databases

**Boundary Note:**
- Glossary JSON import/export is no longer part of the storage package; it lives at `context_aware_translation.adapters.files.glossary_io`

**Term Record Structure (book_db):**
- Terms include: name, description (multi-pass gleaning), occurrence count, votes (for ranking), source_language, target_language
- Timestamps track creation and last_updated for stale data cleanup
- Use `TermRepository` for querying and inserting terms

**Task Persistence:**
- Task records store task_id, task_type, state, claims (resource reservations), progress metadata
- Enable resumable execution after crashes
- Use `TaskStore` to query and update task state

**Context Tree Storage:**
- Context trees are stored hierarchically in `context_tree_db`
- Nodes store summaries, occurrence counts, and child pointers (LSM-tree structure)
- Dramatically reduces token usage (99%+ compression) during translation

### Common Patterns

**Creating/Accessing a Book:**
```python
from context_aware_translation.storage.library.book_manager import BookManager

manager = BookManager(library_root=Path.home() / ".cat" / "library")
book = manager.create_book(name="My Translation Project")
# book.db is now available at book.path / "book.db"
```

**Storing and Retrieving Glossary Terms:**
```python
from context_aware_translation.storage.schema.book_db import SQLiteBookDB
from context_aware_translation.storage.repositories.term_repository import TermRepository

db = SQLiteBookDB(book_path / "book.db")
term_repo = TermRepository(db)

# Insert a term
term_repo.insert_term(
    name="context",
    description="hierarchical structure for LSM trees",
    occurrence_count=1,
    source_language="en",
    target_language="zh"
)

# Query terms
terms = term_repo.query_all()
```

**Managing Config Profiles:**
```python
from context_aware_translation.storage.models.config_profile import ConfigProfile
from context_aware_translation.storage.schema.registry_db import RegistryDB

registry = RegistryDB(registry_root / "registry.db")
profile = ConfigProfile(
    name="gpt4-strict",
    description="GPT-4 with strict settings",
    config_json={...}  # Full config dict
)
registry.save_config_profile(profile)
```

**Managing Endpoint Profiles:**
```python
from context_aware_translation.storage.models.endpoint_profile import EndpointProfile
from context_aware_translation.storage.schema.registry_db import RegistryDB

registry = RegistryDB(registry_root / "registry.db")
endpoint = EndpointProfile(
    name="openai-prod",
    api_key="sk-...",
    base_url="https://api.openai.com/v1",
    model="gpt-4-turbo",
    temperature=0.3,
    timeout=60,
    max_retries=3,
    concurrency=5,
    token_limit=1000000
)
registry.save_endpoint_profile(endpoint)
```

**Transaction Safety:**
```python
from context_aware_translation.storage.schema.book_db import SQLiteBookDB

db = SQLiteBookDB(book_path / "book.db")
# Use context manager for atomic operations
with db.conn:
    # All operations within this block are transactional
    term_repo.insert_term(...)
    document_repo.insert_document(...)
    # Auto-commit on success, auto-rollback on exception
```

**Task State Persistence:**
```python
from context_aware_translation.storage.repositories.task_store import TaskStore

task_store = TaskStore(db)
# Save task state
task_store.save_task_state(
    task_id="glossary-001",
    task_type="glossary_extraction",
    state="in_progress",
    progress_data={"chunks_processed": 50}
)
# Resume from checkpoint
state = task_store.load_task_state("glossary-001")
```

## Dependencies

### Internal
- `context_aware_translation.config` - Config models for validation and serialization
- `context_aware_translation.core.models` - `Term` and data models
- `context_aware_translation.storage.models.book` - `Book` and `BookStatus`
- `context_aware_translation.utils.*` - File utilities, hashing

### External
- `sqlite3` - SQLite database engine with WAL mode
- `platformdirs` - Platform-specific directory paths
- `pathlib` - Path handling
- `json` - JSON serialization for config/profile blobs
- `threading` - Thread safety for concurrent database access
- `uuid` - Unique identifier generation for books

<!-- MANUAL: -->
