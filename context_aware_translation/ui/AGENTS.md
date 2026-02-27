<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# ui

## Purpose
PySide6-based GUI application providing book management, translation, glossary editing, and task monitoring. Implements sidebar navigation, stacked views, background workers for async operations, and Qt task engine integration for workflow orchestration.

## Key Files

| File | Description |
|------|-------------|
| `main.py` | Application entry point: initializes QApplication, loads stylesheet, handles i18n setup, creates MainWindow. Executable via `cat-ui` command. |
| `main_window.py` | Main window: sidebar navigation with book/profile management, stacked view switching, TaskEngine setup, handler registration for all workflow tasks, signal routing. |
| `constants.py` | UI constants: window dimensions, sidebar width, language presets (50+ languages), table defaults. |
| `i18n.py` | Internationalization helpers: load_translation(), get_system_language(), i18n signal emission for retranslation on language change. |
| `sleep_inhibitor.py` | Reference-counted system sleep inhibitor: prevents idle sleep during long operations via platform-specific mechanisms (macOS: caffeinate, Windows: SetThreadExecutionState, Linux: systemd-inhibit). |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `dialogs/` | Dialog windows: `book_dialog.py` (new/edit book), `config_profile_dialog.py` (config management), `endpoint_profile_dialog.py` (API endpoint configuration). |
| `models/` | Qt data models: `book_model.py`, `term_model.py`, `profile_model.py`, `endpoint_profile_model.py` for QTableWidget/QListWidget integration. |
| `resources/` | Static UI assets: icons, stylesheets (styles.qss), image resources. |
| `tasks/` | Qt task engine integration: `qt_task_engine.py` (QObject orchestrator), `task_view_model_mapper.py` (task state to UI model), `task_view_models.py` (display models), `task_console.py` (task output display). |
| `translations/` | i18n files: `zh_CN.ts` (source translations), `zh_CN.qm` (compiled translations). All user strings must be marked with self.tr() for inclusion. |
| `utils/` | UI utility functions: layout helpers, label factories, styling utilities. |
| `views/` | Main workspace views: `book_workspace.py` (container for open book), `translation_view.py` (translation editor/monitor), `glossary_view.py` (glossary management), `library_view.py` (book library), `profile_view.py` (config/profile management), `ocr_review_view.py` (OCR result review), `manga_review_widget.py` (manga translation review), plus import/export views. |
| `widgets/` | Reusable UI components: `task_status_card.py` (task status display), `task_activity_panel.py` (active task list with progress), `progress_widget.py` (progress bars), `config_editor.py` (nested config editing), `image_viewer.py` (image display), `language_dropdown.py` (language selector), `collapsible_section.py` (collapsible UI sections), OCR/manga-specific widgets. |
| `workers/` | Background QThread workers for async operations: `base_worker.py` (QThread base with signal/error handling), task workers (`translation_text_task_worker.py`, `translation_manga_task_worker.py`, `batch_translation_task_worker.py`, `glossary_extraction_task_worker.py`, `glossary_translation_task_worker.py`, `glossary_review_task_worker.py`, `glossary_export_task_worker.py`, `chunk_retranslation_task_worker.py`), utility workers (`import_worker.py`, `export_worker.py`, `ocr_worker.py`), plus `batch_task_overlap_guard.py` and `operation_tracker.py` for worker coordination. |

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
- All long-running operations run in `QThread` subclasses (workers in `workers/`)
- Workers inherit from `BaseWorker` which provides `progress`, `finished_success`, `cancelled`, `error` signals
- Use `Signal.emit()` for cross-thread communication (Qt handles marshalling)
- Call `requestInterruption()` to cancel; workers check `isInterruptionRequested()` via `_raise_if_cancelled()`
- `SleepInhibitor.acquire()` / `.release()` in worker lifecycle to prevent system sleep

**Task Engine Integration:**
- `TaskEngine` (QObject in `tasks/qt_task_engine.py`) is the UI orchestrator
- Register task handlers via `engine.register_handler(handler)` for each workflow task type
- Handlers are registered in `main_window.py` for: BatchTranslation, GlossaryExtraction, GlossaryTranslation, GlossaryReview, GlossaryExport, ChunkRetranslation, TranslationText, TranslationManga
- Task state flows through `task_view_model_mapper.py` to display models for UI binding
- Signals: `tasks_changed`, `status_message`, `error_occurred`, `running_work_changed`

**Common Patterns:**
- Views use `@Slot()` decorator for Qt signal handlers
- Config dialogs use nested editors via `ConfigEditor` widget
- Task monitoring via `TaskStatusCard` (single task) and `TaskActivityPanel` (task list)
- Progress display via `ProgressWidget`
- Image review via `ImageViewer` (OCR/manga)

**mypy Exclusion:**
- UI code is excluded from mypy type checking (see `pyproject.toml`)
- Type hints are still recommended but not enforced

### Testing Requirements

- UI tests use `MagicMock` for Qt widgets (no actual event loop in most tests)
- Test files mirror this structure in `tests/ui/`
- Key test files: `test_translation_view.py`, `test_glossary_view.py`, `test_book_workspace_activity.py`, task worker tests
- Workers tested via signal mocking: `test_translation_text_task_worker.py`, `test_glossary_export_task_worker.py`, etc.
- Task engine tested via core integration: `test_qt_task_engine.py`

### Implementation Notes

**View Lifecycle:**
- Views created on-demand when selected in sidebar
- Views destroyed/recreated on book switch via `close_requested` signal
- State persisted in `BookManager` / `TaskStore`

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
