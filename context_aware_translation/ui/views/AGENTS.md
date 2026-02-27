<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# views

## Purpose
Main application views implementing the workspace, library, translation, glossary, and review UIs. Views coordinate user interaction with models, dialogs, workers, and task engine to drive translation workflows.

## Key Files
| File | Description |
|------|-------------|
| `book_workspace.py` | Main workspace container with tabbed interface. Hosts LibraryView, TranslationView, GlossaryView, ImportView, ExportView, etc. |
| `config_profile_view.py` | Config profile management UI. Table of profiles, create/edit/delete dialogs. |
| `endpoint_profile_view.py` | Endpoint profile management UI. Table of profiles with token usage, create/edit/delete dialogs. |
| `export_view.py` | Export UI for saving translations to files. Handles format selection and progress. |
| `glossary_view.py` | Glossary term editing UI. Table of terms, inline editing, deletion, and mass operations. |
| `import_view.py` | Document import UI. File selection, document type detection, metadata entry. |
| `library_view.py` | Book library browser. Table of books with sorting/filtering, create/edit/delete book dialogs. |
| `manga_review_widget.py` | Manga translation review UI. Side-by-side image and translation. |
| `ocr_review_view.py` | OCR results review. Table of extracted OCR elements with confidence scores. |
| `profile_view.py` | Base class for profile management views (config and endpoint profiles inherit). |
| `translation_view.py` | Main translation workflow UI. Chunk navigator, translation editor, progress tracker, review mode toggle. |

## For AI Agents
### Working In This Directory

**View Architecture:**
- Views inherit from QWidget and coordinate with BookManager, TaskEngine, and models
- Views emit signals for parent containers (e.g., `translation_completed`, `open_activity_requested`)
- Views create and show modal dialogs for CRUD operations
- Views use models (BookTableModel, ProfileModel, etc) as data sources for tables

**Key Patterns:**

**TranslationView (core translation UI):**
- Manages chunk-by-chunk translation workflow
- Two modes: progress view (live translation in progress) and review view (post-translation review)
- Emits task signals to TaskEngine for batch_translation, chunk_retranslation, etc
- Tracks open database connection to book.db and cleans up on close
- Shows progress strip with current/total chunks, failed items

**LibraryView:**
- Displays all books in a table via BookTableModel
- Create/Edit/Delete dialogs for book CRUD
- Double-click opens book in TranslationView

**GlossaryView:**
- Displays glossary terms in editable table
- Inline editing of term translations
- Delete button for individual terms or batch deletion
- May trigger glossary_extraction or glossary_review tasks

**ProfileViews (config and endpoint):**
- Tables of profiles with details
- Create/Edit/Delete dialogs
- Set default profile (config profiles only)
- Delete cascades properly (remove books referencing profile first)

**ImportView / ExportView:**
- ImportView: File picker → DocumentRepository → TaskEngine (submit batch_translation)
- ExportView: Format selector → export worker (write files to disk)

**View Lifecycle:**
1. `__init__()` - Set up UI, create models, connect signals
2. `show()` - Load initial data (often via model.refresh())
3. User interactions trigger dialogs, model mutations, task submissions
4. Signals from TaskEngine/workers update progress displays
5. `closeEvent()` - Cleanup database connections, stop workers

**Database Cleanup:**
- TranslationView opens book.db and holds reference to SQLiteBookDB
- Must close connection in closeEvent() or risk locked database
- GlossaryView and other views may also hold DatabaseRepository references

### Common Gotchas
- Views must check `hasattr()` before accessing optional task engine methods
- TaskEngine.submit() may fail preflighting; always check Decision result
- Database locks require proper resource cleanup (use context managers or explicit close)
- Models don't auto-refresh; call `model.refresh()` after mutations
- Modal dialogs should accept() or reject() to unblock parent view
- Progress tracking: normalize progress values before display (see task_view_model_mapper)

### Testing
- Test view initialization and model setup
- Test CRUD operations (create, edit, delete) with dialog flows
- Test task submission preflighting (decision validation)
- Test database cleanup on close (no locked database errors)
- Test signal emission for task progress updates
- Test view mode switching (e.g., progress ↔ review in TranslationView)
- Test with empty data sets and error conditions

<!-- MANUAL: -->
