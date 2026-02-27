<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# workflow/tasks

## Purpose
Tests for workflow task engine core, resource claims, and task lifecycle management with execution and handler subdirectories.

## Key Files
| File | Description |
|------|-------------|
| `test_claims.py` | Resource claim validation: allocation, deallocation, conflict detection (10,400 lines) |
| `test_engine_core.py` | Task engine core: lifecycle, state transitions, dependency resolution (10,353 lines) |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `execution/` | Task execution primitives (batch translation executor) |
| `handlers/` | Task handler implementations (translation, glossary, batch operations) |

## For AI Agents

### Working In This Directory

#### Running Tests
```bash
# Run all tests in this directory (including subdirectories)
uv run pytest tests/workflow/tasks/ -v

# Run specific subdirectory
uv run pytest tests/workflow/tasks/execution/ -v
uv run pytest tests/workflow/tasks/handlers/ -v

# Run specific test file
uv run pytest tests/workflow/tasks/test_claims.py -v

# Run specific test
uv run pytest tests/workflow/tasks/test_engine_core.py::test_function_name -v

# Run with coverage
uv run pytest tests/workflow/tasks/ --cov=context_aware_translation.workflow
```

#### Testing Requirements

- **Async Support**: Tasks are async; pytest-asyncio auto mode handles execution
- **Fixtures**: `temp_config`, `temp_db`, `temp_context_tree_db` from conftest
- **Mocking**: Mock LLM calls to avoid external API dependencies
- **Database**: Temporary SQLite DBs auto-created per test

#### Core Testing Patterns

1. **Resource Claims**: Create multiple tasks; verify non-overlapping resource allocation
2. **State Transitions**: Verify valid state paths (pending → running → complete)
3. **Dependency Resolution**: Task ordering respects input/output dependencies
4. **Error Propagation**: Failures in upstream tasks cancel downstream tasks
5. **Cancellation**: Verify cleanup on task cancellation

#### Common Patterns
```python
from context_aware_translation.workflow.tasks import TaskEngine, ResourceClaim

# Create task engine and submit tasks
engine = TaskEngine(config=temp_config, db=temp_db)
task_id = await engine.submit_task(task_spec)

# Verify resource claims
claim = engine.get_claim(task_id)
assert not claim.overlaps_with(other_claim)

# Test state transitions
await engine.run_task(task_id)
assert engine.get_task(task_id).state == TaskState.COMPLETE
```

### Task Handler Categories

Task handlers in `handlers/` subdirectory:
- **Batch operations**: `test_batch_translation_handler.py`, `test_glossary_export_handler.py`, `test_glossary_review_handler.py`
- **Content translation**: `test_translation_text_handler.py`, `test_translation_manga_handler.py`
- **Specialized**: `test_chunk_retranslation_handler.py`

<!-- MANUAL: -->
