# Deployment Checklist

## 1. Requirements Install Check

Run locally in a clean environment:

```bash
pip install -r requirements.txt
```

Confirm that the install succeeds without adding extra packages.

## 2. Secrets Setup

Required secrets:

- `DROPBOX_APP_KEY`
- `DROPBOX_APP_SECRET`
- `DROPBOX_REFRESH_TOKEN`

Sources:

- local example: `.env.example`
- cloud example: `.streamlit/secrets.toml.example`

Rules:

- never commit real secrets
- use the staff/shared Dropbox OAuth app credentials
- confirm the refresh token belongs to the correct Dropbox app

## 3. Streamlit Community Cloud Deployment Steps

1. Push the deployment branch.
2. Create the Streamlit Community Cloud app.
3. Set the entrypoint to `app.py`.
4. Add the required secrets in the app Secrets editor.
5. Deploy.
6. Watch the first boot logs for import or auth failures.

## 4. Smoke Test Checklist

After deployment, verify:

- app loads successfully
- Dropbox folders can be listed
- staged folder selection works
- saved `listing_inputs.json` hydrates the listing form
- template detection works
- `Check listing score` works
- `Submit for Review` works
- `Review & output` loads
- review queue renders
- approving a ready listing moves it to `approved`
- `Generate selected` works for one known-good approved listing
- a generated workbook can be downloaded

## 5. Rollback / Recovery Notes

If deployment fails:

1. revert the app in Streamlit Cloud to the previous known-good branch/commit
2. confirm secrets were not changed or removed
3. re-run the smoke test on the previous version

If runtime behavior is broken after deployment:

- stop staff from using `Generate all approved`
- test a single known-good staged item first
- verify Dropbox credentials and queue paths
- compare the deployed branch against the last known-good commit

## 6. First Staff Release Notes

Before first staff rollout:

- confirm at least one full `_stage -> ready -> approved -> finished` path in the deployed environment
- confirm restaging still preserves original finished identity
- confirm staff have the runbook: `docs/STAFF_RUNBOOK.md`
