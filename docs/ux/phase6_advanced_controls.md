# Phase 6: Advanced Controls

## Objective

Expose endpoint, model, routing, and diagnostic power without turning the app
back into an implementation-shaped tool console.

## User Problem

Power users need detailed control, but the product should not regress into the
old subsystem-first UI when advanced options are introduced.

## Scope

Phase 6 covers:
- advanced sections inside `App Setup` and `Project Setup`
- queue detail expansion
- advanced document rerun and diagnostic affordances
- advanced Terms import/export controls
- power-user visibility into routing and capability choices

Phase 6 does not redesign the shell itself. It layers onto the shell defined in
Phases 1 through 5.

## Core Principle

Advanced controls are an expansion of the same app, not a separate application
and not a global mode toggle.

## Screen-by-Screen Advanced Expansion

### App Setup

Reveal:
- exact endpoint/base URL
- model-level defaults
- per-capability routing edits
- custom provider definitions
- connection metadata and test details

### Project Setup

Reveal:
- project-specific routing overrides
- project-level model overrides where needed
- detailed capability source inspection
- more explicit override precedence explanation

### Work

Reveal:
- more granular actions
- advanced range targeting where safe
- force reruns
- power-user status detail

### Document Workspace

Reveal:
- more explicit rerun scopes
- richer OCR / translation diagnostics
- document-level force actions
- more operational detail around image processing

### Queue

Reveal:
- exact action type
- detailed stage text
- richer failure and blocker inspection
- more operational controls where appropriate

### Terms

Reveal:
- richer filters and metadata
- advanced import/export controls
- deeper term diagnostics

## Advanced-Control Rules

Default surfaces:
- never expose backend jargon as first-line UI
- prioritize guidance over control

Advanced sections:
- may expose technical terms when they add real control
- must still preserve the new top-level IA
- must not require users to navigate old subsystem tabs

## Component Design Package

Components that need dedicated design:
- advanced section pattern
- connection details panel
- routing override panel
- expanded queue detail view
- advanced action menus
- diagnostic drawers for document and Terms screens

## Required States

The design system must define:
- what is hidden by default
- what expands inline versus opens in a drawer
- what summary is still shown after an advanced override is applied
- what persists across projects vs app defaults

## Design Tasks

1. Define the advanced-control contract per screen.
2. Wireframe advanced expansions for App Setup, Project Setup, Work, Queue,
   Document Workspace, and Terms.
3. Define which advanced controls remain visible in context versus moving into
   panels.
4. Validate that advanced controls still feel like the same product.

## Acceptance Criteria

- Advanced controls give power users meaningful control.
- Default surfaces stay clean and teachable.
- Advanced sections do not feel like entering a different app.
- The new information architecture remains intact.
