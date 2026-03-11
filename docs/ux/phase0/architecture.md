# UX Architecture

## Objective

Redesign the app from a tool-tab UI into a guided translation workspace without
changing the ordered-document, context-tree, or task-engine model underneath.

The product should present the workflow users actually have:
- an app owns reusable service connections and shared workflow profiles
- a `Project` contains an ordered stack of `Documents`
- earlier documents shape later context
- users move the stack forward through explicit actions
- concurrency and conflicts exist, but they stay secondary UI

## Locked Product Model

User-facing nouns:
- `Project`: current `book`
- `Document`: current ordered document unit
- `Context Frontier`: the furthest document whose OCR/context state is valid for
  downstream work
- `Terms`: the shared glossary for the current project
- `App Settings`: reusable service connections, shared workflow profiles, and
  the provider-first setup wizard, opened as an app-level dialog
- `Project Settings`: target language, preset, and workflow profile selection,
  opened as a project-level dialog
- `Action`: a user-triggered operation such as reading text, building terms,
  translating, reinserting text, or exporting
- `Issue`: something that needs attention, such as a blocker or failed action

Not user-facing on default surfaces:
- task types
- handler names
- resource claims
- endpoint terminology
- context-tree implementation details
- model-level configuration

## Shell Model

The redesign has one app shell plus nested project and document surfaces.

### App Shell

Purpose:
- let users create or open projects
- host app-level actions and status
- open `App Settings` without leaving the current shell context

Primary app surface:
- `Projects`

Secondary app surfaces:
- `App Settings` dialog
- `Queue Drawer`

There is no global left sidebar.

### Project Shell

Purpose:
- let users process one ordered document stack
- expose the shared `Terms` surface for that project
- open project-scoped settings and queue actions without adding extra primary routes

Primary project routes:
- `Work`
- `Terms`

Secondary project surfaces:
- `Project Settings` dialog
- `Queue Drawer`

There is no project-level left sidebar and no `Setup` route.

### Document Workspace

This is a nested surface under `Work`.

Purpose:
- hold document-scoped tools in one place
- keep OCR, Terms, Translation, Images, and Export close to the current document

Local document navigation:
- `OCR`
- `Terms`
- `Translation`
- `Images`
- `Export`

There is no document `Overview` section in the current shell model.

## Screen Roles

### Projects

This is outside the project shell.

Purpose:
- list existing projects
- create a new project
- open a project
- surface when app settings are incomplete before the user enters a project

### App Settings

This is an app-level dialog, not a shell destination.

Purpose:
- create and edit reusable service connections
- run a provider-first setup wizard
- generate a recommended workflow profile from available providers
- let users edit shared workflow profiles when needed
- expose raw endpoint controls only for custom providers or explicit advanced edits

### Work

This is the default project home screen.

Purpose:
- show the ordered document stack
- show the context frontier
- show what is blocked
- let each document row surface one primary action
- let users open a document workspace for detailed work

Core elements:
- project header
- context / blocker strip
- ordered document list
- row-level primary actions

The row action should usually route the user into the correct document section
rather than directly executing work.

### Document Workspace

This is a nested surface under `Work`.

Purpose:
- hold document-scoped tools in one place
- keep OCR, Terms, Translation, Images, and Export close to the current document

### Terms

This is the only shared glossary surface inside a project.

Purpose:
- provide the canonical project-wide terms table
- support shared term review, translation, filtering, import, and export
- stay visually close to the current table UI

Document `Terms` is a filtered view of this same data, not a separate glossary.

### Project Settings

This is a project-level dialog launched from the project shell gear action or
from blocker CTAs.

Purpose:
- choose target language and project preset
- choose which workflow profile the project uses
- optionally customize a project-specific workflow profile when needed
- deep-link to `App Settings` when shared connections are missing or insufficient

### Queue Drawer

This is the concurrency and task-monitoring surface.

Purpose:
- show running, queued, blocked, failed, and completed actions
- support retry/cancel/delete
- explain blocking reasons without requiring users to understand engine internals

The queue drawer is always secondary. It must never become the default shell.

## Complexity Control Model

There is no global Simple/Pro mode for the entire product.

Instead:
- `Work`, `Terms`, and document workspace keep one stable UX model
- app/project settings carry most setup-specific complexity
- advanced controls appear as collapsible sections, drawers, or detail panels
- default surfaces stay plain-language and low-noise

Advanced controls are allowed when they add real control, especially in:
- `App Settings`
- `Project Settings`
- queue details
- document-level rerun and diagnostics panels

## Setup Implementation Principle

Settings are a UX reframing over the existing step-based config/profile backend.

The backend model stays the same in substance:
- saved provider connections
- saved step-based config payloads
- shared profiles and project-specific config

The UX renames and organizes that model as:
- `Connections`
- `Workflow Profiles`
- `Project Settings` choosing a shared profile or a project-specific profile

The setup wizard generates a concrete saved workflow profile. It does not create
a separate routing abstraction.

## Setup Model

### App Settings own
- reusable provider connections
- API keys and secrets
- known-provider defaults
- custom base URLs
- shared workflow profiles
- step-level connection and model routing inside workflow profiles

### Project Settings own
- target language
- project quality preset
- selected workflow profile
- optional project-specific workflow profile when necessary

### Precedence rule

For each workflow step:
1. project-specific workflow profile
2. shared workflow profile
3. missing

## Core Interaction Rules

These behaviors are fixed and must be reflected clearly in the UX.

- Document order is canonical.
- The context frontier is visible and user-readable.
- OCR is always explicit-user-run.
- Manga translation is always explicit-user-run.
- Build Terms is explicit.
- `Build Terms` is owned by document `Terms`.
- Term edits do not auto-trigger translation.
- OCR edits do not auto-trigger translation.
- Image reinsertion is always explicit.
- Expensive downstream work is never silently scheduled after manual edits.
- Users must always see why work is blocked.
- Setup must distinguish clearly between app-level and project-level changes.

## Action Hierarchy

The app should favor explicit, scoped actions over global wizard-like controls.

Primary project actions are row- or document-scoped:
- `Open`
- `Open OCR`
- `Open Terms`
- `Open Translation`
- `Open Images`
- `Export`

Shared terms actions:
- `Translate pending`
- `Review`
- `Filter noise`
- `Import`
- `Export`

Settings actions:
- `Open App Settings`
- `Use recommended profile`
- `Use shared profile`
- `Open Project Settings`
