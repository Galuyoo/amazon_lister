# Amazon Listing Generator System

Streamlit app for preparing, reviewing, approving, and generating Amazon flat-file workbooks from Dropbox-managed listing folders.

Amazon Lister is now the main listing workflow hub for product listing operations. It connects Dropbox folder queues, template configs, listing metadata, image mappings, review checks, and Amazon workbook generation into one workflow.

## Current Workflow

The current Dropbox queue flow is:

    _stage -> ready -> approved -> finished

Meaning:

- `_stage`: worker prepares listing assets and listing content.
- `ready`: worker submitted the listing for admin review.
- `approved`: admin approved the listing for generation/listing.
- `finished`: workbook has been generated and the listing is completed.

Saved `listing_inputs.json` data is the source of truth whenever a staged, ready, approved, or restaged folder already has saved listing context.

## Main App Tabs

The main workspace is organized into four tabs:

1. `Product setup`
   - select staged/restaged folders
   - auto-detect templates
   - review folder/image setup
   - restage finished items for correction

2. `Listing content`
   - edit title, bullets, description, and keywords
   - select variants, prices, and quantity
   - check listing score
   - submit the listing for admin review

3. `Review queue`
   - review folders submitted to `ready`
   - approve listings for generation
   - deny listings back to `_stage` with a `_denied` suffix

4. `Approved output`
   - review approved listings
   - generate selected approved folders
   - generate all approved folders
   - download generated workbooks

## Runtime Requirements

- Python 3.11+
- Dropbox OAuth app credentials
- Access to the configured Dropbox folders referenced by `config/dropbox_templates.json`
- Dropbox queue roots configured for `_stage`, `ready`, `approved`, and `finished`

Install runtime dependencies with:

    pip install -r requirements.txt

## Local Setup

1. Create and activate a virtual environment.
2. Install dependencies:

    pip install -r requirements.txt

3. Create a local `.env` file from `.env.example`.
4. Fill in the required Dropbox values:

- `DROPBOX_APP_KEY`
- `DROPBOX_APP_SECRET`
- `DROPBOX_REFRESH_TOKEN`

5. Start the app:

    streamlit run app.py

## Streamlit Community Cloud Setup

This repo is prepared for staff deployment on Streamlit Community Cloud.

### Required secrets

Add these secrets in the Streamlit app settings using the same names shown in `.streamlit/secrets.toml.example`:

    DROPBOX_APP_KEY = "..."
    DROPBOX_APP_SECRET = "..."
    DROPBOX_REFRESH_TOKEN = "..."

Notes:

- Do not commit real secrets.
- Use Dropbox OAuth refresh-token credentials for the shared staff app.
- Keep local `.env` and cloud secret values aligned.

### Deployment steps

1. Push the repo branch you want to deploy.
2. Create a new app in Streamlit Community Cloud.
3. Point the app to this repo and `app.py` as the entrypoint.
4. Add the Dropbox secrets in the app Secrets editor.
5. Deploy and run the smoke tests listed in `docs/DEPLOYMENT_CHECKLIST.md`.

## Repository Structure

    amazon_lister/
    ├── app.py                       # Main Streamlit app entrypoint
    ├── requirements.txt             # Runtime dependencies
    ├── config/                      # Dropbox/template mapping config
    ├── templates/                   # Amazon flat-file template families and garment configs
    ├── services/                    # Listing quality and workflow support logic
    ├── utils/                       # Dropbox and image helper utilities
    ├── docs/                        # Staff docs, deployment notes, changelogs, and handoff docs
    ├── .streamlit/                  # Streamlit deployment example config
    └── tools/legacy/                # Older helper scripts not used by the main runtime

The production app starts from:

    streamlit run app.py

## Generated Outputs

Generated workbook files are written locally to `outputs/` during runtime.

`outputs/` is intentionally ignored by Git and should be treated as temporary working storage. Staff should download generated workbooks immediately after generation or archive them externally.

A hosted Streamlit app can create files during runtime, but those files are not committed back to GitHub and may not survive app restarts or redeployments.

Future work should archive generated workbooks into the relevant Dropbox listing folder so approved/finished outputs can be downloaded again later.

## Staff Workflow Summary

1. Worker adds product assets/content in `_stage`.
2. Worker uses `Product setup` and `Listing content`.
3. Worker clicks `Submit for Review`.
4. Folder moves `_stage -> ready`.
5. Admin reviews the listing in `Review queue`.
6. Admin either:
   - approves it, moving `ready -> approved`, or
   - denies it, moving it back to `_stage` with `_denied` suffix.
7. Approved listings are generated from `Approved output`.
8. Generation moves folders `approved -> finished`.

Staff should not manually move folders between Dropbox queues during normal operation.

## Documentation

- Current project handoff: `docs/CURRENT_STATE.md`
- Staff workflow: `docs/STAFF_RUNBOOK.md`
- Deployment checklist: `docs/DEPLOYMENT_CHECKLIST.md`
- Approval workflow release notes: `docs/CHANGELOG_APPROVAL_WORKFLOW.md`
- Archived project notes: `docs/archive/`

## Legacy and Archive Files

Historical project notes are stored in:

    docs/archive/

Older helper scripts and early development workbooks are stored in:

    tools/legacy/

These files are kept for reference only and are not part of the main Streamlit runtime.

## Current Priority

The current active workstream is performance and lazy image loading.

Goal:

- Keep normal editing fast.
- Avoid resolving/loading Dropbox image mappings during simple text, price, assignee, or quantity edits.
- Load image mappings only when requested or when required for Submit/Approve/Generate.
- Keep image previews optional and off by default.
