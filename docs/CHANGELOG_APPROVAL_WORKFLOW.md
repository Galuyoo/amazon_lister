# Approval Workflow Release Notes

## Summary

The Amazon Listing Generator has moved from a simple `_stage -> ready -> finished` workflow into a fuller staff/admin operations flow:

    _stage -> ready -> approved -> finished

This release separates worker preparation, admin review, admin approval, and final workbook generation.

---

## Workflow Changes

- Added a new `approved` queue between review and generation.
- Worker action changed from `Mark as Ready` to `Submit for Review`.
- `ready` now means “submitted for admin review,” not “ready to generate.”
- Admin can approve a ready listing, moving it from `ready` to `approved`.
- Workbook generation now runs from `approved`, not from `ready`.
- Finished-folder correction/reuse behavior was preserved, including original finished identity reuse.

---

## Review Queue

- Added a dedicated review queue for folders in `ready`.
- Each ready item can be opened in a review panel before approval.
- Review approval records:
  - `reviewed_by`
  - `reviewed_at`
- Added deny handling:
  - Reviewer can deny a ready listing.
  - Denied listing is moved back to `_stage`.
  - Folder is renamed to `<same_name>_denied`.
  - App reopens staged mode with that denied folder selected.

---

## Approved Output Queue

- Added a separate approved-output area for folders in `approved`.
- Supports:
  - reviewing approved listings
  - generating selected approved folders
  - generating all approved folders
- Approved generation moves folders from `approved` to `finished`.

---

## Top-Level UI

The old mixed `Review & output` area was split into separate top-level tabs:

    Product setup
    Listing content
    Review queue
    Approved output

This makes worker preparation, admin review, and final output generation visibly distinct.

---

## Review Panel

Added a more complete review panel for queue items, including:

- folder name
- template
- workflow metadata
- prepared/reviewed timestamps
- title
- bullets
- description
- keywords
- variants summary
- quantity/pricing summary
- image summary
- quality/preflight summary

The review panel keeps the internal tabs:

    Overview
    Content
    Images
    Quality

---

## Image Review

- Upgraded review images from mostly text to optional visual review.
- Parent image can render as a preview.
- Support images can render horizontally in order.
- Child variant images can render visually.
- Added `Show image previews`, off by default, to avoid slow review loads.
- Kept raw URL/details in an expander for debugging.

---

## Metadata Tracking

Added workflow staff fields:

- `assets_prepared_by`
- `content_prepared_by`
- `reviewed_by`

Added timestamps:

- `prepared_at`
- `reviewed_at`

These are persisted in `listing_inputs.json`, loaded back on reopen/restage/review, and used across the workflow.

---

## State and Context Reliability

- Added a normalized active-context layer in `main()`.
- Saved `listing_inputs.json` is now the authoritative source of template/profile context when present.
- Fixed template/profile drift across reruns.
- Improved hydration for restaged/saved listings.
- Fixed stale session-state problems for:
  - variants
  - pricing
  - image context
  - preflight context
- Fresh staged folders now recover valid variant defaults instead of keeping stale empty session state.

---

## Variant and Image State Fixes

- Centralized variant normalization helpers.
- Legacy color/size templates recover properly when session state contains empty or invalid colors.
- Fresh folders default to valid colours and sizes.
- Parent main image choice resets properly on new fresh contexts.
- Preflight uses resolved preview-side image state instead of recomputing conflicting image state.

---

## Performance and Rerun Behavior

- Added improved caching for:
  - Dropbox overview
  - preview image data
  - resolved image bundle
- Normal content edits no longer force unnecessary image recomputation, including:
  - title
  - bullets
  - assignees
  - prices
  - quantity
- `Reload images` remains the manual cache reset.
- Added lightweight debug timing under the troubleshooting toggle.

---

## Queue Refresh and Reruns

- Added cache clearing and safe reruns after folder transitions so queues refresh immediately after:
  - submit for review
  - approve
  - deny
  - generate approved
  - restage
- Added workflow flash messaging so success messages survive reruns.
- Fixed widget-state issues around folder selection by deferring selection resets to the next rerun when needed.

---

## Deployment and Operations Prep

- Added staff/public deployment documentation.
- Added Streamlit secrets example.
- Added dual Dropbox credential loading:
  - local `.env`
  - Streamlit Cloud `st.secrets`

---

## Known Remaining Gaps

- There is not yet true worker/admin authentication.
- Admin-only tabs are not yet permission-gated.
- Review image loading can still be heavy for large colour-count products.
- Generated workbooks are still primarily download-based; long-term archive storage should be added.
- Full audit/history tracking should be formalized later.
