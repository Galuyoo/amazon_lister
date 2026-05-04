# Amazon Lister - Current State

## Current milestone

The Amazon lister now supports a staged production workflow:

- `_stage` for incoming product folders
- `ready` for prepared listings with saved `listing_inputs.json`
- `finished` for generated/completed listings

The app currently supports:

- staged image mapping as the source of truth for variant images
- reusable garment support images from resource folders
- global support images
- template auto-detection from staged folder names and saved listing inputs
- saved listing inputs via `listing_inputs.json`
- restage/correction workflow
- preserving original finished folder/SKU identity after restage
- marking listings as ready
- ready queue generation
- generate selected ready listings
- generate all ready listings
- workbook downloads after generation
- worker/admin metadata:
  - assets_prepared_by
  - content_prepared_by
  - reviewed_by
  - prepared_at
  - reviewed_at

## Current UI state

The app currently has a 3-page Streamlit layout:

1. Product setup
2. Listing content
3. Review & generate

However, the 3-page structure caused active listing context drift between pages.

Observed issues included:

- active template/profile sometimes drifting after reruns
- Page 2 losing image/preflight context
- template/sidebar context disagreeing with staged folder contents
- image and variant state becoming difficult to keep aligned across separate pages

## Important workflow rule

The active staged folder and its `listing_inputs.json` should be treated as the source of truth for the active listing context whenever saved inputs exist.

The app should avoid recomputing the active listing context from multiple competing sources.

Important context fields:

- active staged folder
- active listing memory
- active profile/template
- selected variants
- price map
- parent main image choice
- resolved image state

## Next planned refactor

Replace the current 3-page radio/page model with one main workspace containing 3 tabs:

1. Product setup
   - folder workflow
   - template selection
   - readiness scanner
   - image review
   - product template details

2. Listing content
   - title
   - bullets
   - description
   - keywords
   - variants
   - pricing
   - quantity
   - check listing score
   - mark as ready

3. Review & output
   - current listing review/generate
   - ready queue
   - review panel
   - generate selected/all
   - downloads

## Refactor goal

The tab refactor should be layout/orchestration only.

Do not redesign business logic during the first tab refactor.

Preserve:

- existing widget keys
- existing staged -> ready -> finished workflow
- existing ready queue behavior
- existing generation logic
- existing restage identity preservation

## Reason for tab refactor

Setup and Listing content are tightly coupled and operate on one active listing session.

Tabs should keep the sections visually separate while reducing cross-page context drift.

The goal is:

- one active listing workspace
- one active product context
- three visual task tabs
- less reliance on page-to-page session reconstruction

## Future ideas

Later improvements can include:

- searchable generated listing archive
- re-download historical workbooks
- filter by template, worker, reviewer, date, status
- better admin approval workflow
- AI-assisted listing content and SEO optimization
- template creation/admin tooling for new product types
