<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# handlers

## Purpose

Task handler implementations for each workflow operation type. Handlers implement the `TaskTypeHandler` protocol and provide task-specific logic for validation, scope/claims definition, worker construction, and cancellation handling. Standard interface enables extensible operation system.

## Key Files

| File | Description |
|------|-------------|
| `base.py` | Handler protocol definition (`TaskTypeHandler`). Defines interface all handlers must implement: `task_type`, `decode_payload()`, `scope()`, `claims()`, `can()`, `can_autorun()`, `validate_submit()`, `pre_delete()`, `build_worker()`, `validate_run()`, `cancel_dispatch_policy()`, `classify_cancel_outcome()`. Also defines `CancelDispatchPolicy` (LOCAL_TERMINALIZE vs REQUIRE_REMOTE_CONFIRMATION) and `CancelOutcome` enum. |
| `batch_translation.py` | Batch translation handler (`BatchTranslationHandler`). Implements multi-stage translation using Gemini batch API. Manages task transitions (queued → running → completed/failed), validates state, spawns batch executor worker. |
| `translation_text.py` | Text/document translation handler (`TranslationTextHandler`). Translates text documents (not manga). Uses batch translation ops for execution. Auto-runs on queued/paused status. |
| `translation_manga.py` | Manga translation handler (`TranslationMangaHandler`). Specialized handler for manga documents. Similar to text handler but uses manga-specific document type. |
| `glossary_extraction.py` | Glossary extraction handler (`GlossaryExtractionHandler`). Multi-pass term gleaning with OCR preflight validation. Checks for blocking OCR tasks. Uses `compute_glossary_preflight()` for state validation. |
| `glossary_translation.py` | Glossary translation handler (`GlossaryTranslationHandler`). Translates extracted glossary terms. No preflight checks. Simple operation on glossary store. |
| `glossary_review.py` | Glossary term review handler (`GlossaryReviewHandler`). Reviews extracted/translated terms. Allows voting on term translations and marking as verified. |
| `glossary_export.py` | Glossary export handler (`GlossaryExportHandler`). Exports glossary to structured formats (JSON, CSV, etc.). Works on glossary store only, not documents. |
| `chunk_retranslation.py` | Chunk retranslation handler (`ChunkRetranslationHandler`). Re-translates a single chunk on demand. Used for fixing translation errors on specific chunks. Targeted narrow operation. |

## For AI Agents

### Working In This Directory

**Handler Protocol:**
- All handlers implement `TaskTypeHandler` (can be runtime_checkable class or dataclass with methods)
- `task_type` identifies operation (e.g., "batch_translation", "glossary_extraction")
- Called by `EngineCore` at different lifecycle points
- Pure logic — no Qt or worker spawning directly (workers are spawned by engine via handler method)

**Standard Handler Methods:**

1. **`decode_payload(record: TaskRecord) -> dict[str, object]`**
   - Deserialize task parameters from `record.payload_json`
   - Used to access task-specific data throughout lifecycle

2. **`scope(record: TaskRecord, payload: object) -> DocumentScope`**
   - Define which documents this task affects
   - Return `AllDocuments`, `SomeDocuments`, or `NoDocuments`

3. **`claims(record: TaskRecord, payload: object) -> frozenset[ResourceClaim]`**
   - Define resource locks required (documents, glossary, embeddings, etc.)
   - Claims are checked against active claims to prevent conflicts

4. **`can(action: TaskAction, record: TaskRecord, payload: object, snapshot: ActionSnapshot) -> Decision`**
   - Check if user action (run/cancel/delete) is allowed
   - Return `Decision(allowed=True)` or `Decision(allowed=False, reason="...")`

5. **`can_autorun(record: TaskRecord, payload: object, snapshot: ActionSnapshot) -> Decision`**
   - Check if task should auto-start when admitted
   - Used by UI to auto-start suitable tasks (e.g., queued translation when no conflicts)

6. **`validate_submit(book_id: str, params: dict[str, object], deps: WorkerDeps) -> Decision`**
   - Validate parameters before task is created
   - Called before task record is created (early validation)
   - Check config snapshot availability, document existence, etc.

7. **`pre_delete(record: TaskRecord, payload: object, deps: WorkerDeps) -> list[str]`**
   - Cleanup hook before task is deleted
   - Return list of error/warning messages if deletion should be blocked
   - Empty list = deletion allowed

8. **`build_worker(action: TaskAction, record: TaskRecord, payload: object, deps: WorkerDeps) -> object`**
   - Construct worker instance for execution
   - Worker implements `Runnable` protocol (can be sync or async)
   - Called by engine just before worker execution

9. **`validate_run(record: TaskRecord, payload: object, deps: WorkerDeps) -> Decision`**
   - Final validation right before worker runs
   - Check preflight conditions (e.g., glossary blockers for glossary extraction)
   - Last chance to reject execution

10. **`cancel_dispatch_policy(record: TaskRecord, payload: object) -> CancelDispatchPolicy`**
    - Define cancellation behavior: LOCAL_TERMINALIZE or REQUIRE_REMOTE_CONFIRMATION
    - LOCAL: immediately mark task cancelled
    - REMOTE: wait for external system (e.g., batch job) to confirm

11. **`classify_cancel_outcome(record: TaskRecord, payload: object, provider_result: object) -> CancelOutcome`**
    - Classify what happened after cancel was sent
    - Outcomes: CONFIRMED_CANCELLED, PROVIDER_TERMINAL_COMPLETED/FAILED, RETRYABLE_TRANSIENT, INDETERMINATE_PROVIDER_RESPONSE

**Common Task Status Transitions:**
- Queued → Running (via `run` action)
- Running → Completed/Failed (worker finishes)
- Running → Cancel_Requested → Cancelling → Cancelled (via `cancel` action)
- Cancelled/Failed → Queued (via `run` action again, if rerunnable)

**Glossary Extraction Specifics:**
- Must check glossary preflight before running
- Some document types (EPUB) can extract glossary without prior OCR
- Other types (scanned books) require OCR to complete first
- If blocked, `validate_run()` returns `Decision(allowed=False, reason="Blocking OCR tasks...")`

**Batch Translation Specifics:**
- Uses Gemini batch API for efficient large-scale translation
- Multi-stage: submit → poll → validate → fallback → apply
- Payload includes `payload_stage` dict tracking progress
- Supports both text and manga documents (via separate handlers)
- Can pause/resume between stages

### Common Patterns

**Minimal Handler Implementation:**
```python
from context_aware_translation.workflow.tasks.handlers.base import TaskTypeHandler, CancelDispatchPolicy, CancelOutcome
from context_aware_translation.workflow.tasks.claims import AllDocuments, ResourceClaim, ClaimMode
from context_aware_translation.workflow.tasks.models import Decision, TaskAction

class SimpleOperationHandler:
    task_type = "simple_operation"

    def decode_payload(self, record):
        import json
        return json.loads(record.payload_json)

    def scope(self, record, payload):
        return AllDocuments(book_id=record.book_id)

    def claims(self, record, payload):
        return frozenset([
            ResourceClaim("doc", record.book_id, "*", ClaimMode.WRITE_EXCLUSIVE)
        ])

    def can(self, action, record, payload, snapshot):
        if action == TaskAction.RUN and record.status == "queued":
            return Decision(allowed=True)
        return Decision(allowed=False, reason="Invalid state")

    def can_autorun(self, record, payload, snapshot):
        return Decision(allowed=record.status in ("queued", "paused"))

    def validate_submit(self, book_id, params, deps):
        # Check params are valid, book exists, etc.
        return Decision(allowed=True)

    def pre_delete(self, record, payload, deps):
        return []  # No cleanup needed

    def build_worker(self, action, record, payload, deps):
        # Return a Runnable worker object
        return MyOperationWorker(payload, deps)

    def validate_run(self, record, payload, deps):
        # Final preflight check
        return Decision(allowed=True)

    def cancel_dispatch_policy(self, record, payload):
        return CancelDispatchPolicy.LOCAL_TERMINALIZE

    def classify_cancel_outcome(self, record, payload, provider_result):
        return CancelOutcome.CONFIRMED_CANCELLED
```

**Preflight Validation with Glossary Blocking:**
```python
from context_aware_translation.workflow.tasks.glossary_preflight import compute_glossary_preflight

def validate_run(self, record, payload, deps):
    # Load document repo
    from context_aware_translation.storage.schema.book_db import SQLiteBookDB
    from context_aware_translation.storage.repositories.document_repository import DocumentRepository

    db = SQLiteBookDB(Path(...) / "book.db")
    doc_repo = DocumentRepository(db)

    # Check glossary preflight
    preflight = compute_glossary_preflight(
        pending_doc_ids=payload["document_ids"],
        selected_cutoff_doc_id=payload.get("cutoff_doc_id"),
        document_repo=doc_repo
    )

    if preflight.is_blocked:
        return Decision(
            allowed=False,
            reason=f"Blocked by OCR on docs {preflight.blocking_ocr_doc_ids}",
            args={"blocking_docs": preflight.blocking_ocr_doc_ids}
        )

    return Decision(allowed=True)
```

**Resource Claims for Glossary Operations:**
```python
def claims(self, record, payload):
    # Glossary operations claim glossary resource
    return frozenset([
        ResourceClaim("glossary", record.book_id, "default", ClaimMode.WRITE_EXCLUSIVE)
    ])

# Document-specific translation claims specific doc keys
def claims(self, record, payload):
    doc_ids = payload.get("document_ids", [])
    if not doc_ids:
        # Claim all docs
        return frozenset([
            ResourceClaim("doc", record.book_id, "*", ClaimMode.WRITE_EXCLUSIVE)
        ])
    else:
        # Claim specific docs
        claims = frozenset([
            ResourceClaim("doc", record.book_id, str(doc_id), ClaimMode.WRITE_EXCLUSIVE)
            for doc_id in doc_ids
        ])
        return claims
```

### Key Dependencies

**Internal:**
- `context_aware_translation.workflow.tasks.claims` - ResourceClaim, ClaimMode, DocumentScope, ClaimArbiter
- `context_aware_translation.workflow.tasks.models` - Task statuses, Decision, TaskAction
- `context_aware_translation.workflow.tasks.glossary_preflight` - Glossary preflight validation
- `context_aware_translation.workflow.tasks.execution.batch_translation_ops` - Batch operations utilities
- `context_aware_translation.storage.repositories.task_store` - TaskRecord interface
- `context_aware_translation.storage.library.book_manager` - BookManager for config snapshots
- `context_aware_translation.workflow.ops` - Workflow operation modules for domain operations

**External:**
- `json` - payload serialization
- `logging` - event logging

### Adding a New Handler

To add a new handler:

1. Create handler class in new file `my_operation.py` implementing `TaskTypeHandler` protocol
2. Import handler in `__init__.py` or at registration site
3. Register handler in `main_window.py` (or bootstrap): `engine.register_handler(MyOperationHandler())`
4. Create corresponding worker class (UI-specific or CLI-specific)
5. Update tests: `tests/workflow/tasks/handlers/test_my_operation_handler.py`

Example registration in main_window.py:
```python
from context_aware_translation.workflow.tasks.handlers.my_operation import MyOperationHandler

def _init_task_engine(self):
    # ... existing registrations ...
    self.engine.register_handler(MyOperationHandler())
```

<!-- MANUAL: -->
