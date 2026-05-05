# Current Project State - Amazon Lister

## Current Status

Amazon Lister is now the main listing workflow hub for preparing, reviewing, approving, and generating Amazon flat-file workbooks.

The repo is public and deployable through Streamlit Cloud. The app uses Dropbox as the operational state store and template/config files as the product generation system.

Current workflow:

    _stage -> ready -> approved -> finished

## Workflow Meaning

- `_stage`: worker prepares listing assets and listing content.
- `ready`: worker submitted the listing for admin review.
- `approved`: admin approved the listing for generation/listing.
- `finished`: workbook has been generated and the listing is completed.

## Current App Tabs

### Product setup

Used for:

- selecting staged/restaged folders
- template auto-detection
- reviewing folder/image setup
- checking staged-folder readiness
- restaging finished items for correction

### Listing content

Used for:

- title, bullets, description, and search terms
- variants, prices, and quantity
- listing score checks
- submitting a listing for admin review

### Review queue

Used for admin review of folders in `ready`.

Admins can:

- inspect listing content
- inspect images and quality
- approve for generation
- deny back to `_stage` with `_denied` suffix

### Approved output

Used for approved listings in `approved`.

Admins/output users can:

- review approved listings
- generate selected approved folders
- generate all approved folders
- download generated workbooks

## Source of Truth Rules

- `listing_inputs.json` is the saved listing state.
- If `listing_inputs.json` exists, it wins over folder auto-detection and stale Streamlit session state.
- Restaged/corrected finished items must preserve original finished folder/SKU identity.
- Dropbox queues represent workflow state.
- Generated workbook files are temporary unless downloaded or archived externally.
- Template configs define allowed variants, sizes, prices, and workbook mapping behavior.

## Recently Completed Milestones

- Added runtime `requirements.txt`.
- Refactored old page-style workflow into a tabbed Streamlit workspace.
- Fixed saved `listing_inputs.json` hydration.
- Fixed fresh-folder variant defaults.
- Fixed stale variant/session-state issues.
- Added Review queue and Approved output workflow.
- Added `_stage -> ready -> approved -> finished`.
- Added deny flow back to `_stage`.
- Fixed approved review image/quality resolution.
- Added queue refresh after folder moves.
- Added Streamlit secrets support.
- Cleaned public repo structure.
- Added staff docs and deployment checklist.
- Added approval workflow release notes.
- Added caching improvements for Dropbox/image reruns.

## Current Active Workstream

Current branch/workstream:

    perf/lazy-image-loading

Goal:

- Keep normal editing fast.
- Avoid resolving/loading Dropbox image mappings during simple text, price, assignee, or quantity edits.
- Load image mappings only when requested or when required for Submit/Approve/Generate.
- Keep image previews optional and off by default.
- Make review queue and approved output fast for large colour-count products.

## Known Pain Points

- Image-heavy products can still feel slow, especially high-colour-count items like beanies.
- Some image mapping work may still happen during normal reruns.
- There is not yet real worker/admin authentication.
- Admin-only tabs are not permission-gated yet.
- Generated workbooks are mostly download-based and should eventually be archived to Dropbox.
- Full audit/history is not yet formalized.
- Template onboarding is still developer/admin manual.
- Streamlit is good enough for the current V1, but role permissions, audit logs, locking, and background jobs may eventually require a stronger backend.

## Immediate Next Priorities

1. Finish lazy image loading/performance branch.
2. Add simple worker/admin role gate.
3. Archive generated workbooks into each listing folder in Dropbox.
4. Add `review_history.json` or equivalent audit trail.
5. Improve review UI/UX.
6. Add admin safeguards around approval and generation.
7. Later: template admin tools.
8. Later: AI-assisted listing content suggestions.
9. Later: database/backend migration only if Streamlit/Dropbox becomes limiting.

## Hard Rules for Future Changes

- Do not break `_stage -> ready -> approved -> finished`.
- Do not change workbook generation logic during UI/performance refactors.
- Do not change `listing_inputs.json` schema without a migration plan.
- Do not lose restaged finished identity reuse.
- Do not allow incomplete image mappings to silently generate bad workbooks.
- Do not commit secrets.
- Do not manually move Dropbox folders unless recovering from an issue.
- Keep changes narrow, testable, and branch-based.
- Keep `listing_inputs.json` as the source of truth when present.

## Manual Smoke Test Checklist

Before merging workflow changes:

1. Select a fresh staged folder.
2. Confirm template detection.
3. Confirm variants are selected.
4. Confirm listing content can be edited.
5. Submit for Review:
   - `_stage -> ready`
6. Review queue:
   - item appears
   - content loads
   - images/quality load when requested
7. Approve:
   - `ready -> approved`
8. Approved output:
   - item appears
   - generation works
   - download appears
   - `approved -> finished`
9. Restage finished item:
   - `finished -> _stage`
   - saved inputs hydrate
   - original finished identity is preserved
10. Deny ready item:
   - `ready -> _stage`
   - folder renamed with `_denied`
11. Hosted Streamlit smoke test:
   - app opens
   - Dropbox folders load
   - staged folder can be selected
   - listing score works
   - no secrets are exposed

## Fresh Chat Handoff Prompt

Use this when starting a new ChatGPT/Codex session:

    We are working on the public Galuyoo/amazon_lister repo. It is a Streamlit Amazon listing workflow hub using Dropbox folders and Amazon template configs. The current workflow is _stage -> ready -> approved -> finished. listing_inputs.json is the source of truth for saved listing state. The app has four tabs: Product setup, Listing content, Review queue, Approved output. The current priority is lazy image loading/performance because image-heavy products are slow and content edits can still trigger expensive Dropbox/image work. Do not break workbook generation, Dropbox move semantics, restage identity reuse, or the listing_inputs.json schema.
