# Project Terms UX

## Scope

This note covers the **project-level Terms tab** only.

Goal: let users add project-wide term mappings manually and import them from JSON, so future translations stay consistent with an existing translation style.

## Summary

Keep this simple:

- add one toolbar button: `Add Terms`
- clicking it opens a small **floating draggable dialog**
- the dialog lets users enter `Term` and `Translation`
- `Import Terms` should support both:
  - the **existing structured glossary JSON format** as the recommended option
  - a simple flat JSON mapping like `{ "Term": "Translation" }`

## Toolbar

For the project-level Terms tab, add a new primary action:

- `Add Terms`

This should sit near `Import Terms` because both are dictionary-seeding actions.

No extra modes, tabs, or advanced setup are needed for v1.

## Add Terms Dialog

### Trigger

User clicks `Add Terms`.

### Presentation

Open a **floating draggable dialog** styled like the reference image:

- compact
- lightweight
- stays above the Terms view
- can be moved by dragging the title area
- dismissible with close button and `Esc`

This should feel like a quick utility window, not a full-page workflow.

### Title

Use English UI copy only.

Recommended title:

- `Add Terms`

### Content

The dialog contains a single entry row:

- `Term` input
- arrow label `=>`
- `Translation` input
- `Add` button

Example layout:

`[ Term ]  =>  [ Translation ]  [ Add ]`

Do not use Japanese/Chinese placeholder labels from the mockup. Use:

- placeholder: `Term`
- placeholder: `Translation`

### Behavior

When user clicks `Add`:

- both fields are required
- add the mapping into the project terms table
- clear both fields
- keep the dialog open for rapid repeated entry
- focus returns to the `Term` field

Keyboard behavior:

- `Tab` moves between fields and button
- `Enter` in `Translation` triggers `Add`
- `Esc` closes the dialog

### Validation

If `Term` is empty:

- show inline error: `Term is required.`

If `Translation` is empty:

- show inline error: `Translation is required.`

If the term already exists:

- update the existing row's translation
- show a light confirmation message such as:
  - `Updated existing term.`

This keeps the flow fast and avoids forcing users through a conflict dialog for every duplicate.

## Import Terms

### Supported Formats

`Import Terms` should accept **both** of these formats.

### 1. Existing structured format

Continue supporting the current glossary schema as the **recommended** import format.

Example:

```json
{
  "version": 1,
  "terms": [
    {
      "key": "ルフィ",
      "translated_name": "Luffy"
    }
  ]
}
```

### 2. Simple mapping format

Also support a flat JSON object:

```json
{
  "ルフィ": "Luffy",
  "ゾロ": "Zoro"
}
```

Rules for the flat format:

- keys must be strings
- values must be strings
- each pair means `term -> translation`

### Import Behavior

For the simple mapping format:

- create new terms when they do not exist
- update translation when the term already exists

For the existing glossary format:

- preserve current behavior unless explicitly changed during implementation

This keeps the recommended structured format in place while adding a simpler import path for basic needs.

### Success Feedback

After import, show a compact success message, for example:

- `Imported 42 terms.`

If useful, include added vs updated counts:

- `Imported 42 terms. Added 30, updated 12.`

## Export

No UX change is required for this step in this iteration.

If we later want symmetry, we can decide whether export should also support the flat mapping format. That does not need to block the current change.

## Implementation Notes

This UX implies:

- a new project-level `Add Terms` button
- a draggable add-terms dialog widget
- service support for creating or upserting a term directly from UI
- import parsing that can detect either:
  - current glossary JSON
  - flat term-to-translation JSON object

## Recommended v1

Implement only these pieces:

1. `Add Terms` button on project Terms
2. floating draggable dialog with `Term`, `=>`, `Translation`, `Add`
3. duplicate term updates existing translation
4. `Import Terms` supports both the recommended structured format and the flat JSON alternative

Anything beyond that can wait until we see real usage.
