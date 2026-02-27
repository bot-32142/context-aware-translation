<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# storage

## Purpose
Tests for SQLite storage layer.

## Key Files
| File | Description |
|------|-------------|
| test_book_db.py | Book database operations |
| test_book_manager.py | Book lifecycle management |
| test_context_tree_db.py | Context tree database persistence |
| test_document_repository.py | Document repository and access patterns |
| test_document_tables.py | Document table schema and operations |
| test_term_repository.py | Glossary term storage and retrieval |
| test_task_store.py | Task storage and state management |
| test_llm_batch_store.py | LLM batch request storage |
| test_translation_batch_task_store.py | Translation batch task storage |
| test_token_tracking.py | Token usage tracking storage |

## For AI Agents
### Working In This Directory
- Follow existing test patterns and naming conventions
- Use pytest fixtures from conftest.py
- Tests run in parallel (pytest-xdist)

<!-- MANUAL: -->
