<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# core

## Purpose
Tests for core engine components: context tree, strategies, extraction, progress.

## Key Files
| File | Description |
|------|-------------|
| test_context_tree.py | Context tree node building and hierarchy |
| test_context_tree_registry.py | Context tree registry and persistence |
| test_context_extractor.py | Document content extraction into context tree |
| test_context_manager.py | Context manager strategy and filtering |
| test_translation_context_manager_strategy_api.py | Translation context manager strategy API |
| test_manga_document_handler.py | Manga-specific context extraction |
| test_models.py | Core model validation and behavior |
| test_noise_filtering_pipeline.py | Noise filtering in extraction pipeline |
| test-terms.json | Test fixture for glossary terms |
| expected_batching_output.json | Expected output for batching tests |

## For AI Agents
### Working In This Directory
- Follow existing test patterns and naming conventions
- Use pytest fixtures from conftest.py
- Tests run in parallel (pytest-xdist)

<!-- MANUAL: -->
