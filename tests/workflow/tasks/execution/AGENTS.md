<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# workflow/tasks/execution

## Purpose
Tests for batch translation execution pipeline including task orchestration and state management.

## Key Files
| File | Description |
|------|-------------|
| `test_batch_translation_executor.py` | Batch translation executor: task scheduling, execution ordering, result aggregation (28,148 lines) |

## For AI Agents

### Working In This Directory

#### Running Tests
```bash
# Run all tests in this directory
uv run pytest tests/workflow/tasks/execution/ -v

# Run specific test file
uv run pytest tests/workflow/tasks/execution/test_batch_translation_executor.py -v

# Run specific test
uv run pytest tests/workflow/tasks/execution/test_batch_translation_executor.py::test_function_name -v

# Run with coverage
uv run pytest tests/workflow/tasks/execution/ --cov=context_aware_translation.workflow
```

#### Testing Requirements

- **Async Support**: Executor is fully async; use `async def test_*()` syntax
- **Fixtures**: `temp_config`, `temp_db`, `temp_context_tree_db` from conftest
- **Mocking**: Mock LLM translation calls to avoid real API calls
- **Database**: Temporary SQLite DBs for document and context tree storage

#### Executor Testing Patterns

1. **Task Submission**: Verify executor accepts and queues translation tasks
2. **Execution Order**: Confirm tasks execute respecting priority and dependencies
3. **Progress Tracking**: Verify progress callbacks fired at correct intervals
4. **Result Aggregation**: Collected results match input tasks
5. **Error Handling**: Individual task failures do not stop batch execution
6. **Cancellation**: Graceful shutdown and resource cleanup on cancel request

#### Common Patterns
```python
from context_aware_translation.workflow.tasks.execution import BatchTranslationExecutor

executor = BatchTranslationExecutor(config=temp_config, db=temp_db)

# Submit tasks
task_ids = await executor.submit_batch(documents)

# Execute with progress tracking
results = await executor.execute(progress_callback=mock_callback)

# Verify results match input
assert len(results) == len(documents)
```

#### Key Considerations

- **Batch Size**: Default 5 chunks per LLM call (do not exceed 10 to avoid hallucinations)
- **Parallelism**: Executor may run multiple translation tasks concurrently; verify no resource conflicts
- **State Persistence**: Task state saved to database; verify recovery on restart
- **Timeout Handling**: Long-running translations should timeout gracefully

<!-- MANUAL: -->
