# Amazon Lister - Project Update

## Current milestone
This milestone upgrades the app from a basic workbook generator into a more reliable listing-production workflow.

## What was added

### 1. Finished-to-stage recovery flow
A finished Dropbox folder can now be moved back into stage and reused in the normal workflow.
This makes it possible to redo incorrect listings without manual Dropbox operations.

### 2. Listing memory persistence
The app now saves listing inputs into `listing_inputs.json` inside the finalized Dropbox folder.

Saved data includes:
- title
- bullets
- product description
- search terms
- selected variants
- price map
- quantity
- template metadata
- extra fields used in generation

When a finished folder is moved back to stage, the app can reload those saved inputs and repopulate the form.

### 3. Streamlit session-state recovery support
Saved listing inputs are now applied back into `st.session_state` when a staged folder with `listing_inputs.json` is selected.
This allows previously used listing data to refill the UI instead of requiring manual re-entry.

### 4. Separate listing score workflow
The app now provides a dedicated **Check listing score** button before workbook generation.

This allows users to:
- review listing quality first
- see blockers and warnings
- avoid moving Dropbox assets before checking quality

### 5. Preflight quality validation
A preflight validation layer was added before generation.

It currently evaluates:
- missing required content
- selected variant completeness
- price validity
- parent/child structure validity
- image coverage
- duplicate or weak listing content
- internal quality score breakdown

Outputs include:
- validation errors
- quality blockers
- warnings
- internal score

### 6. Improved preflight architecture
Preflight logic was cleaned up so the app now uses:
- `build_preflight_report(...)`
- `render_listing_score_result(...)`

This reduces duplicate code and makes the quality layer easier to extend.

### 7. Improved image-resolution handling
Preview scoring now resolves actual image URLs from the selected staged folder and template resource mappings, instead of scoring against empty image fields.

This fixed false image blocker results during score checks.

### 8. Cleaner folder-image utilities
Folder image handling was generalized:
- generic folder image splitting
- generic folder image URL resolution
- clearer naming for reusable image helpers

### 9. Safer generation payload flow
Generation now starts from the validated preview payload and then injects:
- finalized SKU
- finalized parent main image
- finalized other images
- finalized color image map
- finalized design/color image map

This keeps preflight and generation aligned while still using the final finished-folder assets.

## Operational impact

The app now supports a much stronger production workflow:

1. select a staged folder
2. load previous inputs if available
3. review staged assets
4. check listing score
5. fix issues before generation
6. generate workbook
7. save listing memory with finished Dropbox assets
8. re-stage later if correction is needed

## Why this matters
This milestone moves the app closer to a scalable listing-production system rather than a one-pass CSV/XLSM generator.

Main gains:
- less repetitive work
- safer recovery
- stronger operational confidence
- better quality control before generation
- cleaner base for future template growth

## Current templates in active focus
The current templates being stabilized are:
- UC612
- UC502
- UX4
- TC013

The current strategy is to stabilize workflow and listing quality on these templates before broader expansion, while still allowing new template onboarding when required by real pending listings.

## Recommended next steps

### Short-term
- process more listings using the current stable flow
- collect repeated quality issues from real usage
- refine blocker and warning rules based on real listing outcomes

### Medium-term
- add template-specific quality rules
- save a structured listing quality report alongside `listing_inputs.json`
- move more service logic out of `app.py`

### Long-term
- standardize template onboarding
- make new template setup safer and faster
- strengthen the system as a scalable listing-production platform

## Notes
Generated operational files should stay out of Git where appropriate.
Recommended `.gitignore` coverage includes:
- `outputs/`
- generated workbooks
- local-only generated artifacts