# Staged Folder Smoke Fixtures

These local fixtures are Dropbox-shaped staged folders for manual regression checks.

## Visible Input Hydration

Folder:

`010FX6-UX4_visible-input-smoke`

Purpose:

- Verify `listing_inputs.json` loads into `Listing content`.
- Verify title, bullets, description, and search terms are visibly rendered in Streamlit inputs.
- Verify the duplicate-title-word warning still appears for a loaded title.

Manual check:

1. Copy or upload the folder into the configured Dropbox `_stage` folder.
2. Select it in `Product setup`.
3. Open `Listing content`.
4. Confirm the title input is visibly filled, not just counted by the validation text.
