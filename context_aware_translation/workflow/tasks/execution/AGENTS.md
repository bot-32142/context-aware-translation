<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# execution

## Purpose

Batch translation execution pipeline for processing large translation jobs through Gemini batch API. Implements multi-stage execution (submission, polling, validation, fallback) with progress tracking, cancellation support, and error recovery.

## Key Files

| File | Description |
|------|-------------|
| `batch_translation_executor.py` | Batch translation executor (`BatchTranslationExecutor`). Main async entry point for executing batch translation tasks. Manages stage transitions, polling loop, cancellation, and result application. Tracks phases (prepare, translation_submit, translation_poll, polish_submit, polish_poll, apply, done) with fallback handling. |
| `batch_translation_ops.py` | Batch translation operations and utilities. Helper functions: `decode_task_payload()`, `ensure_payload_prepared()`, `new_payload_stage()`, `new_stage_state()`, `run_translation_stage()`, `run_polish_stage()`, `apply_results()`, `is_item_translation_success()`. Shared by executor and handlers. |

## For AI Agents

### Working In This Directory

**Batch Translation Pipeline:**
- Multi-stage execution: prepare → translation_submit → translation_poll → translation_validate → translation_fallback → polish_submit → polish_poll → polish_validate → polish_fallback → apply → done
- Each stage modifies task payload with progress state (items processed, results, errors)
- Translation stage: submit items to Gemini batch API, poll for completion, validate results, apply fallback for failures
- Polish stage (optional): optional secondary refinement pass with same flow
- Apply: persist translated chunks to document store

**Config Snapshot and Restoration:**
- On task creation, a config snapshot is captured and stored in task record
- When executor runs, config snapshot is loaded and used to initialize WorkflowService
- Snapshot includes all LLM configs, strategies, and parameters — ensures consistent behavior even if app config changes

**Progress Tracking:**
- Task payload includes `payload_stage` dict: items_processed, items_total, results, errors
- Progress callback updated after each batch poll iteration
- Cancellation checked between iterations

**Cancellation Handling:**
- Two modes: LOCAL_TERMINALIZE (immediate cancellation) and REQUIRE_REMOTE_CONFIRMATION (wait for batch job)
- For LOCAL_TERMINALIZE: just mark cancelled
- For REQUIRE_REMOTE_CONFIRMATION: attempt to cancel batch job with provider, classify outcome

**Fallback Logic:**
- If item fails translation, fallback rule applies based on config:
  - For text: use original text or empty string
  - For manga: typically empty (image-only context)
- Fallback items still marked as processed to avoid infinite loops

### Common Patterns

**Running Batch Translation:**
```python
from context_aware_translation.workflow.tasks.execution.batch_translation_executor import (
    BatchTranslationExecutor,
)

executor = BatchTranslationExecutor(
    task_record=task_record,
    payload=payload,  # dict with document_ids, translation_config, etc.
    create_workflow_session=create_workflow_session,
    task_store=task_store,
    notify_task_changed=notify_changed,
    progress_callback=on_progress,
    cancel_check=lambda: cancel_flag.get("cancelled", False),
)

result = await executor.execute()
# result is final task status
```

**Payload Structure:**
```python
payload = {
    "document_ids": [1, 2, 3],
    "config_snapshot_json": "...",
    "payload_stage": {
        "items_processed": 10,
        "items_total": 100,
        "results": {...},  # per-item results
        "errors": [...]    # per-item errors
    }
}
```

**Stage Transition:**
```python
from context_aware_translation.workflow.tasks.execution.batch_translation_ops import (
    new_payload_stage,
)

# Create new stage state with reset counters
new_payload = new_payload_stage(
    old_payload,
    stage_name="polish_submit",
    items_total=100
)
```

### Key Dependencies

**Internal:**
- `context_aware_translation.workflow.ops` - Workflow operation modules for batch translation operations
- `context_aware_translation.storage.task_store` - TaskStore, TaskRecord persistence
- `context_aware_translation.storage.llm_batch_store` - LLMBatchStore for batch job persistence
- `context_aware_translation.llm.batch_jobs` - GeminiBatchJobGateway for Gemini API
- `context_aware_translation.core.progress` - ProgressCallback for progress reporting
- `context_aware_translation.core.cancellation` - OperationCancelledError for cancellation handling
- `context_aware_translation.config` - TranslatorBatchConfig, TranslatorConfig

**External:**
- `asyncio` - async/await for batch polling loop
- `httpx` - HTTP client (for Gemini API via batch gateway)
- `json` - payload serialization

### Polling Loop Strategy

The executor implements a robust polling loop:

1. **Submission Phase**: Send batch request to Gemini, store job ID, transition to polling phase
2. **Polling Phase**: Poll batch job status every 10 seconds (DEFAULT_TASK_POLL_INTERVAL_SEC)
3. **Active States**: Continue polling if state in (QUEUED, PENDING, RUNNING, UPDATING, PAUSED, CANCELLING)
4. **Terminal States**: Stop polling and move to validation (SUCCEEDED, FAILED, EXPIRED, CANCELLED)
5. **Transient Errors**: Retry with exponential backoff (network errors, timeouts)
6. **Cancellation**: If cancel requested, attempt to cancel batch job (if REQUIRE_REMOTE_CONFIRMATION) or terminate immediately

<!-- MANUAL: -->
