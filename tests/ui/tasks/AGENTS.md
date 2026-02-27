<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# ui/tasks

## Purpose
Tests for Qt task engine integration layer including console UI, async task execution, and view model mapping.

## Key Files
| File | Description |
|------|-------------|
| `test_task_console.py` | Qt console task engine UI: message rendering, layout management, real-time status updates (14,664 lines) |
| `test_task_engine.py` | Core async task engine: lifecycle, state transitions, cancellation, resource claims (13,460 lines) |
| `test_task_view_model_mapper.py` | ViewModel binding: task state to Qt models, dependency tracking, update propagation (5,847 lines) |

## For AI Agents

### Working In This Directory

#### Running Tests
```bash
# Run all tests in this directory
uv run pytest tests/ui/tasks/ -v

# Run specific test file
uv run pytest tests/ui/tasks/test_task_engine.py -v

# Run specific test
uv run pytest tests/ui/tasks/test_task_engine.py::test_function_name -v

# Run without parallelism (for debugging Qt issues)
uv run pytest tests/ui/tasks/ -n 0 -v
```

#### Testing Requirements

- **PySide6 Required**: Tests skip gracefully if PySide6 not installed
- **Qt Initialization**: Each test module auto-initializes QApplication singleton
- **Async Support**: pytest-asyncio in auto mode; no `@pytest.mark.asyncio` needed
- **Fixtures**: Uses `temp_config`, `temp_db`, and Qt mocks from parent conftest

#### UI Testing Patterns

1. **Task Engine**: Mock LLM responses; verify task execution, state transitions, error handling
2. **Console Rendering**: Mock QTextEdit; verify message formatting and layout
3. **ViewModel Binding**: Create dummy tasks; verify model updates reflect task state changes
4. **Async Coordination**: Test concurrent task execution and resource claim conflicts

#### Common Imports
```python
from PySide6.QtWidgets import QApplication, QTextEdit
from context_aware_translation.ui.tasks import TaskEngine, TaskConsole, TaskViewModelMapper
from unittest.mock import MagicMock, patch
```

<!-- MANUAL: -->
