<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# models

## Purpose
Qt item/table models for data binding between SQLite database and UI views. Models implement QAbstractTableModel to enable Qt's MVC architecture with automatic view refresh on data changes.

## Key Files
| File | Description |
|------|-------------|
| `book_model.py` | QAbstractTableModel for books (columns: name, target language, progress, modified date). Maintains progress and config caches. |
| `endpoint_profile_model.py` | QAbstractTableModel for endpoint profiles. |
| `profile_model.py` | QAbstractTableModel for config profiles (columns: name, target language, description, is_default). |
| `term_model.py` | QAbstractTableModel for glossary terms in a specific book. Supports term editing and deletion. |

## For AI Agents
### Working In This Directory

**Model Architecture:**
- All models inherit from QAbstractTableModel
- Models wrap BookManager or database repos to fetch data
- `refresh()` method reloads data and emits signals for Qt views
- Internal ID-to-row mapping (`_id_to_row`) enables fast lookups by primary key

**Key Methods:**
- `rowCount()`, `columnCount()` - required for QAbstractTableModel
- `data(index, role)` - returns cell content based on column and data role
- `headerData(section, orientation, role)` - returns column headers
- `refresh()` - reload all data from storage layer

**Data Roles:**
- `Qt.DisplayRole` - visible text in cells
- `Qt.EditRole` - editable value
- `Qt.ToolTipRole` - hover tooltips
- `Qt.BackgroundRole` - cell background colors

**Model-Specific Details:**

`BookTableModel`:
- Column indices: COL_NAME, COL_TARGET_LANGUAGE, COL_PROGRESS, COL_MODIFIED
- Maintains `_progress_cache` and `_config_cache` to avoid repeated database hits
- Progress rendered as "X/Y" or percentage
- Modified date formatted human-readable

`ConfigProfileModel`:
- Column indices: COL_NAME, COL_TARGET_LANGUAGE, COL_DESCRIPTION, COL_DEFAULT
- Default profile marked with special icon or label
- Used in profile management views

`TermTableModel`:
- Columns typically: term, translation, part of speech, context
- Supports inline editing via Qt delegates
- Deletion via removeRow()

**Caching:**
- `_progress_cache` in BookTableModel avoids repeated progress calculations
- `_config_cache` avoids re-parsing config YAML
- Caches cleared on `refresh()`

### Common Gotchas
- Models don't auto-refresh on database changes; call `refresh()` explicitly when data changes
- ID-to-row mapping must be rebuilt on refresh (via `_build_id_index()`)
- Column indices are constants (COL_NAME, etc) to avoid magic numbers
- Empty parent parameter in index checks prevents crashes on nested models

### Testing
- Test rowCount/columnCount return correct values
- Test data(index, role) returns expected values for each column
- Test refresh() clears caches and rebuilds ID mapping
- Test with empty result sets
- Verify header data matches expected column names

<!-- MANUAL: -->
