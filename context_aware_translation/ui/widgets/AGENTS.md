<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# widgets

## Purpose
Reusable UI components used across views. Widgets encapsulate common patterns (collapsible sections, config editing, image display, progress tracking) for consistent and maintainable UI code.

## Key Files
| File | Description |
|------|-------------|
| `collapsible_section.py` | Collapsible header with toggle button and content widget. Used in dialogs for organized layout. |
| `config_editor.py` | YAML config editor with collapsible sections for all config groups (extractor, translator, OCR, etc). |
| `image_viewer.py` | Image display widget with zoom, pan, and annotation support (used in OCR/manga review). |
| `language_dropdown.py` | Language selector dropdown (ISO 639-1 codes). Searchable. |
| `ocr_element_card.py` | Individual OCR extracted element card showing text, confidence, and bounding box. |
| `ocr_element_list.py` | List/grid of OCR element cards with selection and batch operations. |
| `progress_widget.py` | Progress bar or circular progress display with percentage/count labels. |
| `task_activity_panel.py` | Activity panel showing live task status overview (running tasks, recent completions). |
| `task_status_card.py` | Individual task status card (title, progress bar, cancel button). |

## For AI Agents
### Working In This Directory

**Widget Design Principles:**
- Widgets are reusable, stateless (or minimal state) components
- Widgets emit signals for parent views to handle, not direct UI updates
- Widgets accept data via constructor or setter methods
- Widgets validate input and emit `validation_error` signal on failure

**Key Patterns:**

**ConfigEditorWidget (config_editor.py):**
- Combines multiple CollapsibleSection widgets for each config group
- Loads config dict and creates appropriate spinners, dropdowns, checkboxes
- `get_config()` returns validated YAML-compatible dict
- `set_config(config: dict)` populates fields from dict
- `validate()` returns error message or None

**CollapsibleSection:**
- Header with toggle button, content area
- Used in dialogs for organizational grouping
- Emits `toggled(bool)` signal on click

**LanguageDropdown:**
- Dropdown of ISO 639-1 language codes
- Searchable (type to filter)
- Emits `language_changed(code)` signal

**OCRElementCard:**
- Displays extracted text, confidence score, position
- Click to select/highlight
- Emits `selected` and `clicked` signals

**OCRElementList:**
- Container for multiple OCRElementCard widgets
- Scroll area or grid layout
- Supports multi-select for batch operations
- Emits `selection_changed(list[card_ids])` signal

**ProgressWidget:**
- Visual progress bar or circular progress
- Shows percentage or "X/Y items" label
- Optional indeterminate state for unknown progress
- Updates via `set_progress(current, total)` method

**TaskStatusCard:**
- Title, status icon, progress bar, cancel button
- Shows task ID, phase, error if present
- Emits `cancel_requested(task_id)` signal
- Auto-updates via connected signals from TaskEngine

**TaskActivityPanel:**
- Overview of all running tasks (compact view)
- Recent completions and failures
- Click to open detailed task view
- Emits `task_selected(task_id)` signal

### Common Gotchas
- Signals must be connected in parent view; widgets don't update parent directly
- ConfigEditorWidget expects config dict structure matching schema (see config.py)
- OCRElementCard bounding box requires pixel coordinates (not normalized)
- ProgressWidget with total=0 should show indeterminate/N/A state
- LanguageDropdown may be empty if no language data available
- TaskStatusCard.cancel_button visibility depends on task status (don't show for completed/failed)

### Testing
- Test widget initialization with various data states
- Test signal emissions on user interaction
- Test validation and error handling
- Test config round-trip (set_config → get_config)
- Test progress updates with edge cases (0, partial, 100%)
- Test collapsible expand/collapse toggle
- Test OCR element selection and multi-select
- Verify layout doesn't break with long text or many items

<!-- MANUAL: -->
