# Staff Runbook

## Purpose

This runbook explains how staff should use the Amazon Lister app during normal daily operation.

## Workflow Summary

The Dropbox queue flow is:

`_stage -> ready -> finished`

Do not move folders manually in Dropbox unless you are following a recovery step from an admin.

## What Each Tab Is For

### Product setup

Use this tab to:

- select the active staged folder
- restage a finished folder when a correction is needed
- confirm template detection
- check staged image setup
- review parent image and variant image mapping

### Listing content

Use this tab to:

- complete title, bullets, description, and keywords
- confirm variants, prices, and quantity
- review listing score and blockers
- click `Mark as Ready`

### Review & output

Use this tab to:

- review listings currently in `ready`
- inspect the review panel before generation
- generate selected ready listings
- generate all ready listings when appropriate
- download generated workbooks

## Standard Staff Workflow

1. Open the app.
2. Go to `Product setup`.
3. Select a folder from `_stage`.
4. Confirm the detected template and image context.
5. Go to `Listing content`.
6. Review or edit listing fields.
7. Run `Check listing score`.
8. Fix blockers if any appear.
9. Click `Mark as Ready`.
10. Go to `Review & output`.
11. Review the ready listing.
12. Generate the workbook from the ready queue section.
13. Download the workbook if needed.

## What Staff Should Not Touch

- Do not edit `.env`, `.streamlit/secrets.toml`, or cloud secrets unless you are the deployment owner.
- Do not change template JSON/config files.
- Do not move folders manually between `_stage`, `ready`, and `finished` during normal use.
- Do not delete generated folders from Dropbox to ?retry? a listing.
- Do not upload replacement template workbooks without approval.

## Basic Troubleshooting

### Saved listing fields do not appear

- Re-select the staged folder.
- Confirm the folder actually contains `listing_inputs.json`.
- Check whether the sidebar shows that saved listing inputs were loaded.

### Template looks wrong

- Re-check the staged folder selection.
- Confirm the folder naming matches the expected product/template family.
- If the item was a correction, restage it again from the original finished folder.

### Images look missing

- Go back to `Product setup`.
- Use `Reload images`.
- Confirm the staged folder contains the expected images.
- Confirm the template family matches the product.

### Mark as Ready fails

- Run `Check listing score` again.
- Fix blockers shown in `Listing content`.
- Confirm Dropbox credentials are valid and the `_stage` folder still exists.

### Ready generation fails

- Review the ready item in `Review & output`.
- Check whether the review panel shows missing image or content issues.
- Retry a single ready listing before using `Generate all ready`.

## Escalation Notes

Escalate to the app owner if:

- Dropbox authentication fails
- folders are moving to the wrong queue
- generated workbooks are structurally incorrect
- template mapping is repeatedly wrong for a product family
