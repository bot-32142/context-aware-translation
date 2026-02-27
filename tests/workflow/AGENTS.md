<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# workflow

## Purpose
Tests for workflow orchestration and service layer.

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| tasks | Task execution and handling tests |

## Key Files
| File | Description |
|------|-------------|
| test_session.py | Session lifecycle and state management |
| test_translator_import_path.py | Translation service import paths and initialization |
| test_translator_image_fetcher.py | Image fetching during translation |
| test_import_export.py | Document import and export operations |
| test_multi_document.py | Multi-document workflow handling |
| test_run_ocr.py | OCR execution workflow |
| test_ocr_required_for_translation.py | OCR requirement detection |
| test_service_bootstrap_lock.py | Service bootstrap locking |
| test_service_cancellation_semantics.py | Cancellation behavior and semantics |

## For AI Agents
### Working In This Directory
- Follow existing test patterns and naming conventions
- Use pytest fixtures from conftest.py
- Tests run in parallel (pytest-xdist)

<!-- MANUAL: -->
