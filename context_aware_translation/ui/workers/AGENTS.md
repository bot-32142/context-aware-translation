<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# workers

## Purpose
Background QThread workers for async operations. Each worker wraps a workflow task handler or I/O operation for thread-safe execution. Workers emit signals for progress updates, completion, errors, and cancellation.

## Key Files
| File | Description |
|------|-------------|
| `base_worker.py` | Base QThread class with standard signals (progress, finished_success, cancelled, error) and error handling template. |
| `batch_task_overlap_guard.py` | Prevents duplicate batch tasks running concurrently (mutual exclusion). |
| `batch_translation_task_worker.py` | Worker for batch_translation workflow task. |
| `chunk_retranslation_task_worker.py` | Worker for chunk_retranslation task (re-translate specific chunks). |
| `export_worker.py` | Worker for exporting translations to files (formats: .json, .docx, etc). |
| `glossary_export_task_worker.py` | Worker for glossary_export workflow task. |
| `glossary_extraction_task_worker.py` | Worker for glossary_extraction task (gleaning and noise filtering). |
| `glossary_review_task_worker.py` | Worker for glossary_review task (human review and approval). |
| `glossary_translation_task_worker.py` | Worker for glossary_translation task. |
| `import_worker.py` | Worker for importing documents (read file, create document records). |
| `ocr_worker.py` | Worker for OCR (extract text from images). |
| `operation_tracker.py` | Tracks currently running operations per book/document (prevents overlapping work). |
| `translation_manga_task_worker.py` | Worker for translation_manga workflow task. |
| `translation_text_task_worker.py` | Worker for translation_text workflow task. |

## For AI Agents
### Working In This Directory

**Worker Architecture:**
- All task workers extend BaseWorker (which extends QThread)
- Workers run on background thread; UI remains responsive
- Workers emit standard signals: `progress(current, total, message)`, `finished_success(result)`, `cancelled()`, `error(message)`
- Worker execution wrapped in try/except; errors emit error signal
- Cancellation: check `_is_cancelled()` in loops, raise `OperationCancelledError` for cleanup

**Workflow Task Workers:**
- Wrap workflow handlers (from context_aware_translation.workflow.tasks.handlers)
- Call handler methods with WorkerDeps (LLM clients, storage, etc)
- Convert workflow progress events to Qt signals via `_emit_progress()`
- Handle task state transitions in handler (pending → running → completed)

**I/O Workers (import_worker, export_worker, ocr_worker):**
- No workflow task involvement
- Direct file I/O or API calls
- Emit progress for long operations
- Return result data via `finished_success` signal

**BaseWorker Template:**
```python
class MyWorker(BaseWorker):
    def _execute(self) -> None:
        # Subclass must implement
        # Check _is_cancelled() in loops
        # Emit progress: self.progress.emit(current, total, message)
        # On success: self.finished_success.emit(result)
        # Errors auto-caught and emit error signal
        pass
```

**Signal Handling in Views:**
- Connect worker signals to view methods:
  - `worker.progress.connect(view._on_progress)`
  - `worker.finished_success.connect(view._on_success)`
  - `worker.error.connect(view._on_error)`
  - `worker.cancelled.connect(view._on_cancelled)`
- Start worker: `worker.start()`
- Cancel worker: `worker.requestInterruption()` then `worker.wait()`

**Operation Tracking (OperationTracker / BatchTaskOverlapGuard):**
- `OperationTracker` maintains set of active document/task IDs
- Prevents multiple workers operating on same document concurrently
- Check before starting worker: `if tracker.has_operation(book_id, doc_id): return`
- Register on start: `tracker.register(task_id, book_id, doc_ids)`
- Deregister on completion: `tracker.deregister(task_id)`

**Sleep Inhibitor:**
- BaseWorker acquires system sleep lock during execution
- Prevents OS sleep during long operations
- Auto-released in finally block

**Task-Specific Workers:**

Task workers follow pattern:
1. Get task metadata from task store
2. Create handler instance with WorkerDeps
3. Call handler.execute() or similar
4. Monitor handler progress events → emit Qt signals
5. Update task status on completion

Glossary workers handle multi-phase workflows:
- Extraction: gleaning + noise filter
- Review: approve/reject terms
- Translation: call translator for approved terms

### Common Gotchas
- Workers must subclass BaseWorker, not QThread directly
- Always check `_is_cancelled()` in loops and before long operations
- Must call `self.progress.emit()` only from worker thread (Qt thread-safe)
- `finished_success.emit(result)` passes result data to connected slot
- Worker signals auto-disconnected on destroy; don't hold stale references
- Import/export workers may need temporary file cleanup
- OCR worker depends on OCR engine configuration (might fail if not configured)
- Task workers must handle edge cases: missing documents, empty chunks, etc

### Testing
- Test worker execution and signal emission
- Test progress updates with realistic data
- Test cancellation (requestInterruption → wait → verify cancelled signal)
- Test error handling and error signal emission
- Test operation tracking (prevent concurrent overlapping tasks)
- Test cleanup on success, error, and cancellation
- Test with invalid input (missing files, malformed configs)
- Verify no resource leaks (workers properly destroyed)

<!-- MANUAL: -->
