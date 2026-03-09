# Phase 1: Setup

## Objective

Make setup understandable for non-technical users without throwing away the
existing step-based config/profile backend.

This phase reframes setup as:
- `App Setup` for reusable connections and shared workflow profiles
- `Project Setup` for target language, preset, and choosing either a shared
  workflow profile or a project-specific workflow profile

This is a UX reframing over the current config-profile system, not a new setup
engine.

## User Problem

Today the user has to understand too much too early:
- which provider they want
- where credentials should live
- which models should be used for each workflow step
- whether a setting is app-wide or project-specific
- how raw config sections map to actual product behavior

The redesigned setup must answer only:
- what services the user already has
- what reusable connections are available
- which workflow profile will be used
- whether this project uses a shared profile or a project-specific profile

## Scope

Phase 1 covers:
- `App Setup` landing page
- provider-first setup wizard
- connection management
- capability testing as feedback only
- recommended workflow profile generation
- workflow profile editing
- `Project Setup` landing page
- shared-profile vs project-profile model
- advanced setup sections for custom endpoints and explicit model edits

Phase 1 does not cover:
- queue behavior
- document workspace design
- shared Terms design
- workflow execution UI outside setup
- backend storage redesign

## Core Model

### Reused backend model

The existing step-based config/profile backend remains the source of truth.

The UX reframes it as:
- **Connection**: saved provider credentials/settings
- **Workflow Profile**: user-facing wrapper over the existing step-based config payload
- **Shared Workflow Profile**: reusable app-level profile
- **Project-Specific Workflow Profile**: project-local profile derived from or independent of a shared profile

The wizard generates a concrete workflow profile. It does not introduce a new
routing abstraction.

### App Setup owns
- reusable service connections
- API keys and secrets
- known-provider defaults
- custom OpenAI-compatible base URLs
- shared workflow profiles
- step-level connection/model routing inside workflow profiles

### Project Setup owns
- target language
- project preset
- selected workflow profile
- optional project-specific workflow profile when needed

### Precedence

For each workflow step:
1. project-specific workflow profile
2. shared workflow profile
3. missing

## Capability Model

Setup still exposes capabilities, but capabilities are summary-only.

Required user-facing capabilities:
- `Translation`
- `Image text reading`
- `Image editing`

Optional secondary capability:
- `Reasoning and review`

Capabilities are used for:
- readiness summaries
- test feedback
- blocker messaging

Capabilities are not the primary editing surface.

Workflow profiles are used for:
- choosing which connection/model runs each step
- generating recommended defaults
- project-specific customization

## App Setup

### Purpose

`App Setup` is where users tell the app what services they have and manage the
shared setup reused across projects.

It should feel reusable and global:
- set it up once
- reuse it across projects
- edit only when connections or workflow profiles change

### Core Screen: App Setup Landing

Required areas:
- connection summary
- workflow profile summary
- lightweight capability summary
- `Run setup wizard` CTA
- `Add connection` CTA
- `Workflow profiles` section
- collapsed `Advanced` section for custom-provider details only

### Core Screen: Provider-First Wizard

The wizard should ask what the user already has, not how they want to design a
profile.

Wizard steps:
1. choose providers already available
2. enter API keys
3. test capabilities
4. review recommended workflow profile
5. save app setup

Wizard output:
- saved connections
- a concrete shared workflow profile with explicit step -> connection + model choices

### Provider Cards

Known providers should have dedicated cards:
- `Gemini`
- `OpenAI`
- `DeepSeek`
- `Anthropic`
- `OpenAI-compatible / Custom`

Rules:
- known providers ask for API key first
- known providers do not expose base URL in the normal flow
- known providers auto-pick concrete models by default
- custom provider exposes base URL and model fields
- provider cards may include small helper text about what each provider is good at

### Capability Testing

Tests must answer what the configured services can do, not only whether they are
reachable.

Test results should map to:
- `Translation`
- `Image text reading`
- `Image editing`
- `Reasoning and review` when relevant

This capability output is feedback and readiness only. It is not the main setup
editing UI.

### Recommended Workflow Profile

After testing, the app must generate a recommended workflow profile.

Example:
- `OCR / text extraction -> Gemini / gemini-3-flash-preview`
- `Build terms -> DeepSeek / deepseek-chat`
- `Summary / context building -> DeepSeek / deepseek-chat`
- `Term translation -> DeepSeek / deepseek-chat`
- `Translation review / reasoning -> OpenAI / gpt-4.1-mini`
- `Document translation -> OpenAI / gpt-4.1-mini`
- `Manga text detection -> Gemini / gemini-3-flash-preview`
- `Manga translation -> Gemini / gemini-3-flash-preview`
- `Image reinsertion -> Gemini / gemini-3.1-flash-image-preview`

The user should then choose one of:
- `Use recommended profile`
- `Edit workflow profile`
- `Advanced`

### Workflow Profile Editor

Workflow profiles are the main advanced-friendly setup surface.

The editor should use the existing real step map, not a capability map.

Required rows:
- `Extractor`
- `Summarizer`
- `Glossary translator`
- `Translator`
- `Reviewer`
- `OCR`
- `Image reembedding`
- `Manga translator`
- `Translator batch`

Required columns:
- `Step`
- `Connection`
- `Model`

Rules:
- known providers auto-fill concrete models when a row is first generated
- users may change connection and model manually if needed
- custom providers may require explicit model entry
- profiles should be named and reusable
- no extra source / override / auto-manual columns should be shown

### Advanced in App Setup

Advanced should be collapsed by default.

It may reveal:
- custom provider endpoint/base URL
- custom provider model names
- connection metadata
- workflow-profile details that are not needed in the default view

Known providers should not expose raw endpoint editing in the normal flow.

## Project Setup

### Purpose

`Project Setup` answers:
- what language this project targets
- which quality preset it uses
- which workflow profile this project uses

### Core Screen: Project Setup Landing

Required areas:
- target language
- project preset
- selected workflow profile
- project-ready summary
- `Use shared profile` affordance
- `Customize for this project` affordance
- `Edit project profile` affordance when a project-specific profile exists
- `Open App Setup` deep link when a required shared connection or profile is missing
- collapsed `Advanced` section

### Project Setup Profile Selection

The primary control is workflow profile selection.

Project Setup should show:
- selected shared workflow profile
- short summary of what that profile covers
- target language
- preset
- CTA:
  - `Use shared profile`
  - `Customize for this project`
  - `Edit project profile`
  - `Open App Setup`

### Project-Specific Profile

If a project needs different step routing, the user should be able to create a
project-specific workflow profile by copying the selected shared profile and
editing it.

Rules:
- default behavior is use a shared workflow profile
- project-specific customization is explicit
- project-specific profiles remain editable from Project Setup
- the UI should avoid the word `override` on the main surface
- project-specific profiles still use the same step table as shared profiles

### Project Setup Interaction Rules

- default behavior is use a shared workflow profile
- project-specific customization is opt-in
- project setup should not expose raw endpoint editing by default
- if the needed connection or shared profile does not exist globally, route the
  user to `App Setup`
- saving project setup returns the user to `Work`

## Interaction Rules

- provider choice comes before endpoint/model choice
- known-provider setup is key-first, not endpoint-first
- default setup should auto-pick concrete models for known providers
- the app must always explain whether a missing piece is app-level or
  project-level
- setup should not imply that every project needs a project-specific profile
- advanced sections should expand in place, not switch the entire app into a
  different mode

## Component Design Package

Components that need dedicated design:
- app setup landing shell
- provider card
- provider selection grid
- API key entry panel
- connection test result row
- workflow profile summary card
- workflow profile routing table
- project setup shell
- profile selector
- customize-for-project control
- advanced setup section
- success / failure state panels

## Required States

App Setup needs at least:
- no connections
- one known provider configured
- mixed providers configured
- capability coverage partial
- fully ready
- custom provider configured
- test failed
- recommended workflow profile generated
- shared workflow profile list with at least one imported legacy profile

Project Setup needs at least:
- shared profile available
- no shared profile available
- project uses shared profile
- project uses project-specific profile
- project blocked by missing setup
- project fully ready

## Design Tasks

1. Wireframe the `App Setup` landing page.
2. Wireframe the provider-first wizard.
3. Define the provider card states.
4. Define capability testing copy and result states.
5. Define the workflow profile summary and routing table.
6. Wireframe the `Project Setup` page.
7. Define shared-profile vs project-profile interactions.
8. Define the advanced setup sections for custom endpoints and explicit model edits.
9. Prototype the first-run flow from project -> app setup wizard -> project setup -> work.

## Acceptance Criteria

- A user can set up common providers without learning endpoints first.
- A user can understand what the app can and cannot do from capability tests.
- App-wide connections and shared workflow profiles are visibly distinct from
  project choices.
- The app can generate a recommended workflow profile from supplied providers.
- Project Setup clearly supports either a shared workflow profile or a project-specific workflow profile.
- Advanced endpoint/model management exists, but does not block normal setup.
- The spec makes clear that this is a UX reframing over the existing config-profile backend.
