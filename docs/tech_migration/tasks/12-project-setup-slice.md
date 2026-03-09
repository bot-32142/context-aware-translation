# Task 12: Project Setup Slice

## Goal

Implement project-level setup that selects target language, preset, and either a shared workflow profile or a project-specific workflow profile.

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
- shared workflow profile selection
- project-specific workflow profile creation/editing
- deep-link to App Setup when the required shared connection or profile is missing
- advanced section for profile details only

Implementation note:
- In the first migrated version, the `Advanced` area may be informational only.
- Raw endpoint/model editing should remain in App Setup. Project Setup should
  focus on profile selection and project-specific profile editing.

## Acceptance Criteria

- project setup clearly distinguishes shared workflow profiles from project-specific workflow profiles
- UI uses application contracts, not config/profile storage directly
- saving project setup returns cleanly to the project shell
- setup actions come from backend query state
- project setup refreshes via application invalidation + requery
- capability status is summary-only, not the main editing surface
- any project-level `Advanced` section must not reintroduce raw endpoint/model
  editing that belongs in App Setup
