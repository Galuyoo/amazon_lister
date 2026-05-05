# Next Steps

## Current Active Workstream

Performance and lazy image loading.

Branch:

    perf/lazy-image-loading

Goal:

- Keep normal editing fast.
- Avoid resolving/loading Dropbox image mappings during simple text, price, assignee, or quantity edits.
- Load image mappings only when requested or when required for Submit/Approve/Generate.
- Keep image previews optional and off by default.
- Make review queue and approved output usable for high-colour-count products.

## Current Workflow

The app now uses:

    _stage -> ready -> approved -> finished

Meaning:

- `_stage`: worker prepares listing.
- `ready`: submitted for admin review.
- `approved`: admin approved for generation.
- `finished`: workbook generated/completed.

## Immediate Priorities

### 1. Finish lazy image loading

Target behavior:

- Selecting a folder should be fast.
- Editing text fields should be fast.
- Changing assignees should be fast.
- Changing prices/quantity should be fast.
- Images should not resolve unless needed.
- Image previews should be optional and off by default.
- Submit/Approve/Generate may force image validation if needed for safety.

### 2. Add simple role gate

Minimum version:

- Worker mode:
  - Product setup
  - Listing content
  - Submit for Review

- Admin mode:
  - Review queue
  - Approve/Deny
  - Approved output
  - Generate approved

This can start as a simple Streamlit secrets/password or role selector. Full auth can come later.

### 3. Archive generated workbooks to Dropbox

Current generated workbook files are temporary unless downloaded.

Future behavior:

- Save generated workbooks into the listing folder.
- Example:

    finished/<listing-folder>/generated/<timestamp>_amazon_listing.xlsm

Benefits:

- re-download later
- audit trail
- safer staff operation

### 4. Add workflow history/audit

Add a history file per listing, such as:

    review_history.json

Track:

- submitted for review
- approved
- denied
- generated
- restaged
- timestamps
- staff member

### 5. Improve Review UI/UX

Ideas:

- faster lightweight review cards
- load image review only when requested
- run full quality check only when requested
- clearer blockers/warnings
- better approved output download history

### 6. Template admin tools

Future admin workflow:

- add new template family
- upload workbook/config
- validate config
- validate Dropbox image mapping
- generate sample workbook
- approve template

Not a priority until staff workflow is stable.

### 7. AI-assisted listing content

Future AI features:

- title suggestions
- bullet suggestions
- description suggestions
- keyword suggestions
- listing quality improvements
- SEO warnings

Not a priority until workflow/audit/permissions are stable.

### 8. Database/backend migration

Do not migrate prematurely.

A database becomes useful when we need:

- real user accounts
- permissions
- audit history
- search/filtering
- concurrent editing/locking
- background jobs
- queue dashboards
- stronger output archive

For V1, Streamlit + Dropbox remains acceptable.

## Hard Rules

- Do not break `_stage -> ready -> approved -> finished`.
- Do not change workbook generation logic during UI/performance refactors.
- Do not change `listing_inputs.json` schema without a migration plan.
- Preserve restage identity reuse.
- Keep Dropbox destructive operations guarded and clear.
- Do not commit secrets.
- Keep changes narrow and testable.
