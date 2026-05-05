# Staff Runbook

## Purpose

This runbook explains how staff should use the Amazon Lister app during normal daily operation.

## Workflow Summary

The Dropbox queue flow is:

    _stage -> ready -> approved -> finished

Meaning:

- `_stage`: listing is being prepared.
- `ready`: listing has been submitted for admin review.
- `approved`: listing has been approved for generation/listing.
- `finished`: workbook has been generated and the listing is complete.

Do not move folders manually in Dropbox unless you are following a recovery step from an admin.

## What Each Tab Is For

### Product setup

Use this tab to:

- select the active staged folder
- restage a finished folder when a correction is needed
- confirm template detection
- check staged image setup
- review parent image and variant image mapping when needed

### Listing content

Use this tab to:

- complete title, bullets, description, and keywords
- confirm variants, prices, and quantity
- review listing score and blockers
- click `Submit for Review`

### Review queue

Use this tab to:

- review listings currently in `ready`
- inspect listing content before approval
- inspect images/quality when needed
- approve listings for generation
- deny listings back to `_stage` when they need correction

### Approved output

Use this tab to:

- review listings currently in `approved`
- generate selected approved listings
- generate all approved listings when appropriate
- download generated workbooks

## Standard Worker Workflow

1. Open the app.
2. Go to `Product setup`.
3. Select a folder from `_stage`.
4. Confirm the detected template and folder setup.
5. Go to `Listing content`.
6. Review or edit listing fields.
7. Run `Check listing score`.
8. Fix blockers if any appear.
9. Click `Submit for Review`.
10. Confirm the listing moved to `ready`.

## Standard Admin Review Workflow

1. Open the app.
2. Go to `Review queue`.
3. Select a ready listing.
4. Review:
   - overview
   - content
   - images if needed
   - quality/preflight results
5. Choose reviewer name.
6. Either:
   - click `Approve for generation`, or
   - deny/send back for correction.

If approved, the listing moves:

    ready -> approved

If denied, the listing moves:

    ready -> _stage

and is renamed with a `_denied` suffix.

## Standard Output Workflow

1. Go to `Approved output`.
2. Select one or more approved listings.
3. Generate selected approved listings, or generate all approved only when safe.
4. Download the generated workbook.
5. Confirm the folder moved:

    approved -> finished

## What Staff Should Not Touch

- Do not edit `.env`, `.streamlit/secrets.toml`, or cloud secrets unless you are the deployment owner.
- Do not change template JSON/config files.
- Do not move folders manually between `_stage`, `ready`, `approved`, and `finished` during normal use.
- Do not delete generated folders from Dropbox to retry a listing.
- Do not upload replacement template workbooks without approval.
- Do not generate all approved listings unless all approved items are safe to process.

## Image Loading Notes

Image-heavy products can be slow, especially products with many colours.

When lazy image loading is enabled:

- content fields may load before image mappings
- previews may be off by default
- image review may require clicking a load/review button
- `Reload images` should only be used when Dropbox assets changed

## Basic Troubleshooting

### Saved listing fields do not appear

- Re-select the staged folder.
- Confirm the folder contains `listing_inputs.json`.
- Confirm the file is named exactly `listing_inputs.json`.
- Check whether the sidebar says saved listing inputs were loaded.

### Template looks wrong

- Re-check the staged folder selection.
- Confirm the folder naming matches the expected product/template family.
- If the item was a correction, restage it again from the original finished folder.

### Images look missing

- Go back to `Product setup`.
- Use `Reload images`.
- Confirm the staged folder contains the expected images.
- Confirm the template family matches the product.
- Confirm variants are selected in `Listing content`.
- If image previews are off, enable image preview/loading before assuming images are missing.

### Submit for Review fails

- Run `Check listing score` again.
- Fix blockers shown in `Listing content`.
- Confirm Dropbox credentials are valid.
- Confirm the `_stage` folder still exists.

### Approval fails

- Confirm the item is still in `ready`.
- Refresh/reload the app.
- Try approving only one listing.
- Check whether image/quality blockers are present.

### Approved generation fails

- Review the item in `Approved output`.
- Check whether the review panel shows missing image or content issues.
- Retry a single approved listing before using `Generate all approved`.

## Escalation Notes

Escalate to the app owner if:

- Dropbox authentication fails
- folders are moving to the wrong queue
- generated workbooks are structurally incorrect
- template mapping is repeatedly wrong for a product family
- listings appear stuck between queues
- approved listings generate incomplete image mappings
