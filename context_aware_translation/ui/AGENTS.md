<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# ui

## Purpose
PySide6-based GUI application providing book management, translation, glossary editing, and task monitoring. App, project, document, queue, and settings chrome now run through hybrid QML hosts, while remaining feature behavior continues to live in QWidget panes and Qt adapter integrations where parity work is still in progress.

## Key Files

| File | Description |
|------|-------------|
| `main.py` | Application entry point: initializes QApplication, loads stylesheet, handles i18n setup, creates MainWindow. Executable via `cat-ui` command. |
| `main_window.py` | Main window composition root: application context wiring, window lifetime, top-level status handling, and shell-host orchestration. |
| `constants.py` | UI constants: window dimensions, language presets (50+ languages), table defaults, and shared shell sizing values. |
| `i18n.py` | Internationalization helpers: load_translation(), get_system_language(), i18n signal emission for retranslation on language change. |
| `sleep_inhibitor.py` | Reference-counted system sleep inhibitor: prevents idle sleep during long operations via platform-specific mechanisms (macOS: caffeinate, Windows: SetThreadExecutionState, Linux: systemd-inhibit). |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `resources/` | Static UI assets: icons, stylesheets (styles.qss), image resources. |
| `qml/` | QML shell/dialog chrome for app, project, document, queue, and settings surfaces. |
| `viewmodels/` | QObject-backed QML-facing state and route models. |
| `shell_hosts/` | Hybrid QQuickWidget/QWidget hosts for shell chrome and dialog containers. |
| `translations/` | i18n files: `zh_CN.ts` (source translations), `zh_CN.qm` (compiled translations). All user strings must be marked with self.tr() for inclusion. |
| `utils/` | UI utility functions: layout helpers, label factories, styling utilities. |
| `features/` | Main workspace panes and dialogs: library, work, terms, app/project settings panes, queue drawer, and document sections hosted inside shell chrome. |
| `widgets/` | Reusable UI components: `progress_widget.py` (progress bars), `image_viewer.py` (image display). |

## For AI Agents

### Working In This Directory

**Internationalization (i18n):**
- All user-visible strings must wrap with `self.tr("string")` for Qt translation extraction
- Run `make lupdate` after adding/changing strings to update `zh_CN.ts`
- Add Chinese translations in `zh_CN.ts`, then compile with `lrelease`
- Supported languages: English (en), Simplified Chinese (zh_CN)

**UI Conventions:**
- QML shell chrome talks only to QObject viewmodels backed by `application.services` and contracts
- Feature panes still commonly inherit from `QWidget` with standardized layout setup via `QVBoxLayout`/`QHBoxLayout`
- Use `QSplitter` for resizable sections where existing pane behavior still needs it
- Use `QStackedWidget` inside hosts/panes where local content switching is still widget-managed
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
- App/project/document shells are created through `ui/shell_hosts/` and should own chrome/routing only
- Hosted feature panes are created on demand from the main shell/session managers
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
- `superqt` - supplemental Qt widgets used for collapsible sections and other higher-level components
- `PySide6.QtCore` - Core (signals, slots, threading, i18n)
- `PySide6.QtGui` - Graphics (colors, fonts, icons)
- `PySide6.QtWidgets` - Widgets (main UI components)
- `PySide6.QtQuickWidgets` - hybrid QML shell hosting inside widget-based windows

<!-- MANUAL: -->
