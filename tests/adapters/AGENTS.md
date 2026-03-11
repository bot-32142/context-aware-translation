<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-26 -->

# adapters

## Purpose
Tests for adapter-layer boundaries such as file import/export and framework glue.

## Key Files
| File | Description |
|------|-------------|
| `files/test_glossary_io.py` | Glossary JSON import/export behavior against book and context-tree storage. |

## For AI Agents
### Working In This Directory
- Keep adapter tests focused on boundary translation behavior rather than pure storage CRUD
- Use temporary files and temporary SQLite databases for file-format tests

<!-- MANUAL: -->
