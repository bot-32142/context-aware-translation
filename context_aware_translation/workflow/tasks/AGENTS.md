<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# tasks

## Purpose

Task execution engine managing operation lifecycle for all workflow operations. Implements pure-Python task scheduling, resource arbitration, handler dispatch, and worker lifecycle management. Decoupled from UI (Qt) to enable CLI and programmatic use.

## Key Files

| File | Description |
|------|-------------|
| `engine_core.py` | Central task orchestrator (`EngineCore`). Manages task lifecycle: validation, admission, worker spawning, resource arbitration via claims, cancellation handling, and state transitions. No Qt dependency. |
| `claims.py` | Resource arbitration system (`ResourceClaim`, `ClaimArbiter`, `DocumentScope`). Defines claim modes (READ_SHARED, WRITE_EXCLUSIVE, WRITE_COOPERATIVE) and conflict detection. Prevents concurrent conflicting operations on same resources (documents, glossary, embeddings). |
| `models.py` | Task data models and status constants. Defines task status (queued, running, paused, cancel_requested, cancelling, cancelled, completed, completed_with_errors, failed), phase constants, `TaskAction` enum (run/cancel/delete), `Decision` (allowed/code/reason), and `ActionSnapshot`. |
| `exceptions.py` | Task workflow exceptions (`CancelDispatchRaceError`, `RunValidationError`). Used during cancellation handling and worker validation. |
| `worker_deps.py` | Worker dependency injection (`WorkerDeps`). Frozen dataclass bundling `book_manager`, `task_store`, `create_workflow_session` factory, and `notify_task_changed` callback. Passed to handler methods for accessing infrastructure. |
| `glossary_preflight.py` | Glossary pre-flight validation. `GlossaryPreflightResult` and `compute_glossary_preflight()` check OCR blockers before glossary extraction. `resolve_effective_pending_ids()` filters stale document IDs. |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `execution/` | Batch translation execution pipeline. Implements stage-based translation (submission, polling, validation, fallback) with Gemini batch job integration. |
| `handlers/` | Task handler implementations. Each operation type (glossary_extraction, translation, review, export, etc.) has a handler extending `TaskTypeHandler` protocol. |

## For AI Agents

### Working In This Directory

**Task Engine Architecture:**
- `EngineCore` is the central orchestrator — all task operations route through it
- Handlers are plugged in via `register_handler()` and dispatched by task_type
- Resource claims prevent conflicting concurrent operations (read-shared vs write-exclusive)
- Document scope (AllDocuments, SomeDocuments, NoDocuments) determines affected resources
- Task store (SQLite) persists task records with status, payload, metadata, and config snapshot
- Workers are spawned by handlers and linked to task records via task_id

**Lifecycle Flow:**
1. Submit: validate params → capture config snapshot → create task record (queued)
2. Admit: check claims conflict → check preflight conditions (e.g., glossary blockers) → admit task (queued -> running or blocked)
3. Run: build worker → validate on entry → execute worker → update task record (running -> terminal)
4. Cancel: check policy (local vs remote) → dispatch cancellation → classify outcome
5. Delete: pre-delete hook (cleanup refs) → remove task record

**Claims System:**
- Defines resource "namespaces": "doc", "glossary", "embedding_index", etc.
- Per-book (book_id) and per-resource (key: "*" for all, or specific ID)
- Three modes: READ_SHARED (allow parallel), WRITE_EXCLUSIVE (exclusive), WRITE_COOPERATIVE (coordinated write)
- `ClaimArbiter` checks if wanted claims conflict with active claims
- Wildcard ("*") matches all specific keys in namespace; specific keys match wildcard

**Glossary Preflight:**
- Glossary extraction requires text extraction and OCR completion for certain document types (scanned books)
- `compute_glossary_preflight()` identifies blocking OCR tasks and whether extraction can proceed
- `resolve_effective_pending_ids()` filters requested doc IDs against currently pending glossary work

### Common Patterns

**Registering a New Handler:**
```python
from context_aware_translation.workflow.tasks.handlers.base import TaskTypeHandler

class MyOperationHandler:
    task_type = "my_operation"

    def decode_payload(self, record: TaskRecord) -> dict[str, object]:
        return json.loads(record.payload_json)

    def scope(self, record: TaskRecord, payload: object) -> DocumentScope:
        # Return which documents this task affects
        return AllDocuments(book_id=record.book_id)

    def claims(self, record: TaskRecord, payload: object) -> frozenset[ResourceClaim]:
        # Return what resources this task claims
        return frozenset([
            ResourceClaim("doc", record.book_id, "*", ClaimMode.WRITE_EXCLUSIVE)
        ])

    def can(self, action: TaskAction, record: TaskRecord, payload: object, snapshot: ActionSnapshot) -> Decision:
        # Check if action is allowed given current state
        if action == TaskAction.RUN and record.status == "queued":
            return Decision(allowed=True)
        return Decision(allowed=False, reason="Invalid state transition")

    # Implement other protocol methods...

# In main_window.py or bootstrap:
engine.register_handler(MyOperationHandler())
```

**Submitting a Task:**
```python
from context_aware_translation.workflow.tasks.models import TaskAction

# Decision can be (allowed=False) if validation fails
decision = handler.validate_submit(book_id, params, deps)
if not decision.allowed:
    raise RuntimeError(f"Cannot submit: {decision.reason}")

# Create task record
task_record = task_store.create(
    book_id=book_id,
    task_type="my_operation",
    payload_json=json.dumps(params),
    config_snapshot_json=config_snapshot,
)

# Admit for running
engine.admit(task_record.task_id)
```

**Handling Cancellation:**
```python
from context_aware_translation.workflow.tasks.handlers.base import CancelDispatchPolicy, CancelOutcome

class MyHandler:
    def cancel_dispatch_policy(self, record: TaskRecord, payload: object) -> CancelDispatchPolicy:
        # LOCAL_TERMINALIZE: immediately mark cancelled
        # REQUIRE_REMOTE_CONFIRMATION: wait for external system to confirm
        return CancelDispatchPolicy.LOCAL_TERMINALIZE

    def classify_cancel_outcome(self, record: TaskRecord, payload: object, provider_result: object) -> CancelOutcome:
        # Classify what happened after cancel was sent
        # CONFIRMED_CANCELLED, PROVIDER_TERMINAL_COMPLETED/FAILED, RETRYABLE_TRANSIENT, etc.
        return CancelOutcome.CONFIRMED_CANCELLED
```

**Document Scope Usage:**
```python
from context_aware_translation.workflow.tasks.claims import AllDocuments, SomeDocuments, NoDocuments, scopes_overlap

# Task that affects all documents in book
all_docs = AllDocuments(book_id="book_123")

# Task that affects specific documents
some_docs = SomeDocuments(book_id="book_123", doc_ids=frozenset([1, 2, 3]))

# Check if two scopes overlap (for conflict detection)
if scopes_overlap(all_docs, some_docs):
    print("Scopes overlap — potential conflict")
```

### Key Dependencies

**Internal:**
- `context_aware_translation.storage.task_store` - TaskStore, TaskRecord persistence
- `context_aware_translation.storage.book_manager` - BookManager for config snapshots and document metadata
- `context_aware_translation.workflow.service` - WorkflowService for domain operations
- `context_aware_translation.core.progress` - ProgressCallback, ProgressUpdate for progress reporting
- `context_aware_translation.documents` - Document type metadata and type checking

**External:**
- `json` - payload serialization
- `threading` - locking for per-book serialization
- `time` - monotonic clock for config snapshot probe cache TTL
- `logging` - event logging

### Handler Registration

Handlers must be registered with `EngineCore` before tasks can be executed. This typically happens in `main_window.py` during app initialization:

```python
from context_aware_translation.workflow.tasks.handlers.batch_translation import BatchTranslationHandler
from context_aware_translation.workflow.tasks.handlers.translation_text import TranslationTextHandler
# ... import all handlers

engine.register_handler(BatchTranslationHandler())
engine.register_handler(TranslationTextHandler())
# ... register all handlers
```

New handlers should be added to this registration list and their corresponding worker classes should be imported and available.

<!-- MANUAL: -->
