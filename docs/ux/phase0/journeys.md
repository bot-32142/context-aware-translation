# Canonical User Journeys

These journeys define how the redesigned UX should behave. They are the source
of truth for later wireframes and visual design.

## Journey 1: First-Time User

Goal:
- get a non-technical user from an empty project to the first successful
  translation without opening advanced setup

Flow:
1. User creates or opens a project.
2. Project `Setup` checks whether required app-level connections exist.
3. If not, the app routes the user to `App Setup`.
4. User picks the services they already have, such as Gemini, OpenAI,
   DeepSeek, Anthropic, or a custom OpenAI-compatible endpoint.
5. User pastes API keys.
6. App tests capability coverage and shows a readiness summary.
7. App proposes a recommended workflow profile.
8. User accepts the recommended profile or edits it.
9. App saves reusable connections and the workflow profile, then returns the user to project `Setup`.
10. User selects target language and project preset.
11. User chooses a shared workflow profile or creates a project-specific profile.
12. App sends the user to `Work`.
13. Work shows imported documents or prompts for import.
14. User imports documents.
15. Work shows the current blocking row or next row action.
16. User presses the row action, such as `Open OCR`, `Open Terms`, or `Open`.
17. If the user needs document-specific detail, they open the document
    workspace.
18. When a document is ready, the user exports from the row or document
    workspace.

Success condition:
- the user reaches translated output without learning endpoint or model
  management first

## Journey 2: Returning User With Partial Progress

Goal:
- help the user resume exactly where the project is blocked or paused

Flow:
1. User opens project.
2. App lands on `Work`.
3. Work shows:
   - context frontier
   - current blockers
   - one primary action per row
4. If setup changed globally and the project is now incomplete, `Setup` is
   surfaced as the blocker target.
5. User either presses the current row action or opens a document workspace.
6. Queue drawer remains available for background visibility but is not required.

Success condition:
- the user does not need to inspect multiple screens to know what to do next

## Journey 3: App Setup Wizard

Goal:
- let a user go from raw provider credentials to a usable default app setup

Flow:
1. User opens `App Setup`.
2. User selects which providers they have.
3. Known providers ask for API key only.
4. Custom providers ask for base URL, API key, and model defaults.
5. User runs connection tests.
6. App reports capability coverage as feedback:
   - translation
   - image text reading
   - image editing
7. App proposes a recommended workflow profile.
8. User either:
   - accepts `Use recommended profile`
   - edits the workflow profile
   - opens `Advanced`
9. App saves reusable connections and workflow profiles, then returns the user to the previous destination.

Success condition:
- the user can set up services without manually designing a workflow profile from scratch

## Journey 4: Project Setup

Goal:
- let a project adopt a shared workflow profile quickly while still supporting
  project-specific customization

Flow:
1. User opens project `Setup`.
2. User sets target language.
3. User sets project preset.
4. Project Setup shows the selected workflow profile and a short summary of the
   workflow steps it covers.
5. User keeps the shared workflow profile, chooses `Use shared profile`, or chooses `Customize for this project`.
6. If the needed connection or profile does not exist, user opens `App Setup`.
7. User saves and returns to `Work`.

Success condition:
- users understand what is global, what is per-project, and which workflow profile will actually be used

## Journey 5: OCR Correction

Goal:
- let the user fix OCR issues without hidden expensive follow-up work

Flow:
1. User opens a document from `Work`.
2. User switches to `OCR`.
3. User edits the recognized text.
4. User presses `Save`.
5. App confirms save only.
6. App offers explicit next actions such as:
   - `Rerun this page`
   - `Return to Work`

Success condition:
- users understand that edits are saved, but translation is not silently rerun

## Journey 6: Terms Editing

Goal:
- allow users to curate key terms without unexpected project-wide side effects

Flow:
1. User opens top-level `Terms` or document `Terms`.
2. User edits, ignores, reviews, imports, or exports terms.
3. User saves the changes.
4. App confirms that existing translations are unchanged.

Success condition:
- users understand that term edits do not automatically rewrite prior work

## Journey 7: Explicit Retranslation

Goal:
- keep reruns scoped and trustworthy

Flow:
1. User opens a document from `Work`.
2. User switches to `Translation` and selects a chunk or page.
3. User presses `Retranslate`.
4. App confirms cost and scope.
5. App runs only the selected retranslation.
6. App returns updated content to the document workspace.

Success condition:
- users see retranslation as a local repair action, not a hidden workflow jump

## Journey 8: Image Reinsertion

Goal:
- make image text insertion understandable even when capabilities are missing

Flow:
1. User opens `Work` or document `Images`.
2. App shows whether image editing capability is configured.
3. If missing, CTA is `Fix setup`.
4. If available, CTA is `Put text back into images`.
5. User can run on the current item or pending items.
6. Results appear in the document workspace or on the Work row.

Success condition:
- users understand this is a separate, explicit stage with its own capability

## Journey 9: Export

Goal:
- make export feel like the final natural outcome, not a technical subsystem

Flow:
1. User opens `Work` or a document workspace.
2. App shows whether the current document is exportable.
3. If exporting from `Work`, the row-level `Export` action opens a small export
   dialog.
4. User selects output and format.
5. User exports.
6. App shows the output path.

Success condition:
- users understand what is exportable and why

## Screen Transition Rules

Default transitions:
- `Project Setup` -> `Work` after successful project configuration
- `Project Setup` -> `App Setup` when global connections are missing or need
  editing
- `App Setup` -> return to the calling destination after save
- `Work` -> document workspace when the user opens a document
- `Work` -> `Terms` when the user needs shared glossary curation
- document workspace -> `Work` after saves or retries unless the user stays in place
- `Queue` is always optional and non-primary

The app should not force users through every area in sequence. `Work` remains
the hub. `Terms`, document workspace, `Project Setup`, and `App Setup` are
purposeful drill-down destinations.

## Screen Map

App shell:
- `Projects`
- `App Setup`

Project shell:
- `Work`
- document workspace
- `Terms`
- `Setup`
- `Queue Drawer`

## Rejected UX Patterns

These patterns are intentionally not part of the redesign:
- queue-first home screen
- wizard-only runtime UI
- separate top-level tabs for every backend subsystem
- hidden automatic reruns after OCR or glossary edits
- arbitrary document selection as the default translation model
- a global Simple/Pro mode toggle for the whole product
