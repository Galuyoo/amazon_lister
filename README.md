# Amazon Listing Generator System

Streamlit app for preparing and generating Amazon flat-file workbooks from Dropbox-managed listing folders.

## What This App Does

The app supports a staff workflow built around three Dropbox queues:

- `_stage`: work in progress listings
- `ready`: listings approved for workbook generation
- `finished`: completed listings that already generated outputs

The main workspace is organized into three tabs:

1. `Product setup`
2. `Listing content`
3. `Review & output`

Saved `listing_inputs.json` data is used as the source of truth whenever a staged or ready folder already has saved listing context.

## Runtime Requirements

- Python 3.11+
- Dropbox OAuth app credentials
- Access to the configured Dropbox folders referenced by `config/dropbox_templates.json`

Install runtime dependencies with:

```bash
pip install -r requirements.txt
```

## Local Setup

1. Create a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create a local `.env` file from `.env.example`.
4. Fill in the required Dropbox values:

- `DROPBOX_APP_KEY`
- `DROPBOX_APP_SECRET`
- `DROPBOX_REFRESH_TOKEN`

5. Start the app:

```bash
streamlit run app.py
```

## Streamlit Community Cloud Setup

This repo is prepared for first staff deployment on Streamlit Community Cloud.

### Required secrets

Add these secrets in the Streamlit app settings using the same names shown in `.streamlit/secrets.toml.example`:

```toml
DROPBOX_APP_KEY = "..."
DROPBOX_APP_SECRET = "..."
DROPBOX_REFRESH_TOKEN = "..."
```

Notes:

- Do not commit real secrets.
- Use Dropbox OAuth refresh-token credentials for the shared staff app.
- Keep local `.env` and cloud secrets values aligned.

### Deployment steps

1. Push the repo branch you want to deploy.
2. Create a new app in Streamlit Community Cloud.
3. Point the app to this repo and `app.py` as the entrypoint.
4. Add the Dropbox secrets in the app Secrets editor.
5. Deploy and run the smoke tests listed in `docs/DEPLOYMENT_CHECKLIST.md`.

## Staff Workflow

### 1. Product setup

Use this tab to:

- choose the staged folder or restage a finished folder
- confirm template detection and template selection
- review staged images
- check staged-folder readiness

### 2. Listing content

Use this tab to:

- confirm title, bullets, description, and keywords
- confirm variants, prices, and quantity
- run `Check listing score`
- click `Mark as Ready` when the listing is complete

### 3. Review & output

Use this tab to:

- review ready listings
- inspect the review panel
- generate selected ready folders
- generate all ready folders when appropriate

## Dropbox Queue Expectations

- `_stage` contains listings still being prepared.
- `ready` contains listings that passed content review and are waiting for workbook generation.
- `finished` contains completed listings after generation.

Staff should not manually move folders between these queues in Dropbox. Use the app workflow instead.

## Additional Docs

- Staff workflow: `docs/STAFF_RUNBOOK.md`
- Deployment steps: `docs/DEPLOYMENT_CHECKLIST.md`
- Current app notes: `docs/CURRENT_STATE.md`
