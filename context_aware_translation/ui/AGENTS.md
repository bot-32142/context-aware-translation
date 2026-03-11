<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# ui

## Purpose
PySide6-based GUI application providing book management, translation, glossary editing, and task monitoring. Implements sidebar navigation, stacked views, and reusable widgets on top of the Qt adapter layer in `../adapters/qt/`.

## Key Files

| File | Description |
|------|-------------|
| `main.py` | Application entry point: initializes QApplication, loads stylesheet, handles i18n setup, creates MainWindow. Executable via `cat-ui` command. |
| `main_window.py` | Main window: sidebar navigation with project management, stacked view switching, Qt adapter wiring, and signal routing. |
| `constants.py` | UI constants: window dimensions, sidebar width, language presets (50+ languages), table defaults. |
| `i18n.py` | Internationalization helpers: load_translation(), get_system_language(), i18n signal emission for retranslation on language change. |
| `sleep_inhibitor.py` | Reference-counted system sleep inhibitor: prevents idle sleep during long operations via platform-specific mechanisms (macOS: caffeinate, Windows: SetThreadExecutionState, Linux: systemd-inhibit). |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `resources/` | Static UI assets: icons, stylesheets (styles.qss), image resources. |
| `translations/` | i18n files: `zh_CN.ts` (source translations), `zh_CN.qm` (compiled translations). All user strings must be marked with self.tr() for inclusion. |
| `utils/` | UI utility functions: layout helpers, label factories, styling utilities. |
| `features/` | Main workspace surfaces: project shell, work, terms, setup, queue drawer, and document tabs. |
| `widgets/` | Reusable UI components: `progress_widget.py` (progress bars), `image_viewer.py` (image display), `collapsible_section.py` (collapsible UI sections). |

## For AI Agents

### Working In This Directory

**Internationalization (i18n):**
- All user-visible strings must wrap with `self.tr("string")` for Qt translation extraction
- Run `make lupdate` after adding/changing strings to update `zh_CN.ts`
- Add Chinese translations in `zh_CN.ts`, then compile with `lrelease`
- Supported languages: English (en), Simplified Chinese (zh_CN)

**UI Conventions:**
- Views inherit from `QWidget` with standardized layout setup via `QVBoxLayout`/`QHBoxLayout`
- Use `QSplitter` for resizable sections
- Use `QStackedWidget` for view switching
- Models derive from `QAbstractItemModel` or `QAbstractTableModel` for table/list integration

**Workers and Threading:**
- All long-running operations run in `QThread` subclasses under `../adapters/qt/workers/`
- Workers inherit from `BaseWorker` which provides `progress`, `finished_success`, `cancelled`, `error` signals
- Use `Signal.emit()` for cross-thread communication (Qt handles marshalling)
- Call `requestInterruption()` to cancel; workers check `isInterruptionRequested()` via `_raise_if_cancelled()`
- `SleepInhibitor.acquire()` / `.release()` in worker lifecycle to prevent system sleep

**Task Engine Integration:**
- `TaskEngine` (QObject in `../adapters/qt/task_engine.py`) is the Qt orchestration adapter
- Register task handlers via `engine.register_handler(handler)` for each workflow task type
- Handlers are registered in `main_window.py` for: BatchTranslation, GlossaryExtraction, GlossaryTranslation, GlossaryReview, GlossaryExport, ChunkRetranslation, TranslationText, TranslationManga
- Task state flows through `task_view_model_mapper.py` to display models for UI binding
- Signals: `tasks_changed`, `status_message`, `error_occurred`, `running_work_changed`

**Common Patterns:**
- Views use `@Slot()` decorator for Qt signal handlers
- Progress display via `ProgressWidget`
- Image review via `ImageViewer` (OCR/manga)

**mypy Exclusion:**
- UI code is excluded from mypy type checking (see `pyproject.toml`)
- Type hints are still recommended but not enforced

### Testing Requirements

- UI tests use `MagicMock` for Qt widgets (no actual event loop in most tests)
- Test files mirror this structure in `tests/ui/`
- Key test files: `test_translation_view.py`, `test_glossary_view.py`, `test_book_workspace_activity.py`, task worker tests
- Workers are tested via signal mocking in `tests/ui/workers/`
- Task engine is tested via Qt integration in `tests/ui/tasks/test_task_engine.py`

### Implementation Notes

**View Lifecycle:**
- Feature surfaces are created on demand from the main shell
- State is refreshed through application events plus requery

**Worker Lifecycle:**
- Worker instantiated with params
- `started` signal connected to slot
- `start()` called to run in QThread
- Monitors `finished_success`, `cancelled`, `error` signals
- Call `requestInterruption()` then `wait()` to clean shutdown

**Signal Flow:**
- User action → View slot → Worker task → Signal emission → View update
- Cross-thread communication via Qt's `QueuedConnection` (automatic in signal/slot)

## Dependencies

### Internal
- `context_aware_translation.workflow` - task handlers, execution engine, session management
- `context_aware_translation.storage` - BookManager, TaskStore, profile/endpoint management
- `context_aware_translation.config` - configuration models
- `context_aware_translation.llm` - LLMClient, token tracking
- `context_aware_translation.core` - progress tracking

### External
- `pyside6` - Qt6 bindings for Python (main UI framework)
- `PySide6.QtCore` - Core (signals, slots, threading, i18n)
- `PySide6.QtGui` - Graphics (colors, fonts, icons)
- `PySide6.QtWidgets` - Widgets (main UI components)

<!-- MANUAL: -->
