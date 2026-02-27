<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# ui

## Purpose
Tests for PySide6 UI components using MagicMock (no Qt event loop).

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| tasks | Task engine UI tests |
| workers | Worker task implementation tests |

## Key Files
| File | Description |
|------|-------------|
| test_book_workspace_activity.py | Book workspace activity tracking |
| test_book_workspace_close_warning.py | Unsaved changes warnings on close |
| test_config_editor.py | Configuration editor UI |
| test_context_menu_selection.py | Context menu interactions |
| test_endpoint_profile_view.py | Endpoint profile management UI |
| test_export_view.py | Export dialog and workflow |
| test_glossary_view.py | Glossary viewer and editor |
| test_i18n_progress_messages.py | Internationalization of progress messages |
| test_image_viewer.py | Image viewing and navigation |
| test_import_view_controls.py | Import dialog controls |
| test_manga_review_widget_state.py | Manga review widget state management |
| test_ocr_review_empty_state.py | OCR review empty state UI |
| test_ocr_review_rerun.py | OCR review re-run functionality |
| test_progress_widget.py | Progress display widget |
| test_sleep_inhibitor.py | Sleep inhibitor during operations |
| test_task_activity_panel.py | Task activity panel UI |
| test_task_status_card.py | Task status card display |
| test_term_table_model.py | Glossary term table model |
| test_translation_no_legacy_workers.py | Translation view without legacy workers |
| test_translation_view_refresh.py | Translation view refresh behavior |
| test_translation_view_v2.py | Translation view v2 implementation |
| test_worker_cancellation_reporting.py | Worker cancellation reporting |
| test_worker_cleanup.py | Worker cleanup on shutdown |

## For AI Agents
### Working In This Directory
- Follow existing test patterns and naming conventions
- Use pytest fixtures from conftest.py
- Tests run in parallel (pytest-xdist)
- Tests use MagicMock for Qt components - no real event loop

<!-- MANUAL: -->
