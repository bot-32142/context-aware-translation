# Task 12: Project Setup Slice

## Goal

Implement project-level setup that selects target language, preset, and inherit/override behavior against app defaults.

## Execute

Start after Task 10. Can run in parallel with Task 11.

## Depends On

- [Task 01](01-foundation-contracts.md)
- [Task 02](02-foundation-services-composition.md)
- [Task 03](03-foundation-events-queue-contract.md)
- [Task 10](10-app-shell-navigation.md)

## Must Read

- [Setup UX](../../ux/phase1_setup.md)
- [UX architecture](../../ux/phase0/architecture.md)

## Current Code To Inspect

- current project/book configuration usage through `context_aware_translation/storage/book_manager.py`
- `context_aware_translation/config.py`
- current import/config/profile messaging in `context_aware_translation/ui/views/import_view.py`

## Scope

Implement `Project Setup`:
- target language
- project preset
- capability cards showing effective source
- inherit app defaults
- override for this project
- deep-link to App Setup when the global connection is missing
- advanced override section

Implementation note:
- In the first migrated version, the `Advanced` area may be informational only.
- Raw endpoint/model editing should remain in App Setup. Project Setup should
  focus on inherit-vs-override and capability selection.

## Acceptance Criteria

- project setup clearly distinguishes app defaults from project overrides
- UI uses application contracts, not config/profile storage directly
- saving project setup returns cleanly to the project shell
- capability cards and setup actions come from backend query state
- project setup refreshes via application invalidation + requery
- any project-level `Advanced` section must not reintroduce raw endpoint/model
  editing that belongs in App Setup
