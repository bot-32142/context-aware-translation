<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# dialogs

## Purpose
Dialog windows for creating and editing books, config profiles, and API endpoint profiles. Each dialog is a modal QDialog that handles validation, form layout, and database persistence.

## Key Files
| File | Description |
|------|-------------|
| `book_dialog.py` | Dialog for creating/editing books with profile selection or custom config override. Supports inline config editing via ConfigEditorWidget. |
| `config_profile_dialog.py` | Dialog for creating/editing config profiles with general metadata (name, description) and full YAML config editing. |
| `endpoint_profile_dialog.py` | Dialog for creating/editing API endpoint profiles (base URL, model, temperature, token limits, etc). Includes connection test worker. |

## For AI Agents
### Working In This Directory

**Dialog Lifecycle:**
- Each dialog is modal (blocks interaction with parent until closed via Accept/Reject)
- All forms validate on save and show QMessageBox warnings for validation errors
- Database persistence happens in `_on_save()` handlers
- Duplicate key errors (IntegrityError) are caught and reported to user

**Key Patterns:**
- Use `self.tr()` for all user-facing strings (i18n support)
- `BookDialog` and `ConfigProfileDialog` embed `ConfigEditorWidget` for YAML editing
- `EndpointProfileDialog` has inline spinners/checkboxes for token limits and test connection logic
- All dialogs support `changeEvent(LanguageChange)` for dynamic retranslation

**Form Validation:**
- Required fields: book name, profile name, endpoint name, base URL, model
- Custom JSON parsing for endpoint kwargs (with error messages)
- URL format validation (http:// or https://)
- ConfigEditorWidget provides its own config validation

**When Editing:**
- Dialogs pre-populate fields from passed model objects
- `BookDialog` shows custom config option if book has no profile_id
- `EndpointProfileDialog` shows read-only token usage labels when editing existing profile
- Both profile dialogs use CollapsibleSection for organized layout

### Common Gotchas
- `BookDialog` resizes on custom config toggle (DIALOG_WIDTH_NORMAL vs DIALOG_WIDTH_EXPANDED)
- `ConfigProfileDialog` wraps form in scroll area to handle small screens
- `EndpointProfileDialog` uses QThreadPool for non-blocking connection tests
- All dialogs inherit changeEvent handling for proper i18n

### Testing
- Test form submission with valid/invalid data
- Test database uniqueness constraints (duplicate names)
- Test validation error messages
- Test pre-population when editing existing records
- For endpoint dialog: test connection test worker signal handling

<!-- MANUAL: -->
