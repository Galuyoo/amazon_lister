# Amazon Lister Regression Checklist

## Purpose

Use this checklist before merging any application change into staging.

## Non-negotiable rules

- listing_inputs.json remains the saved listing source of truth.
- Existing listing_inputs.json fields must not be removed or renamed without a migration plan.
- Older saved listings must continue to load.
- The workflow remains _stage -> ready -> approved -> finished.
- Denied listings must return safely from ready to _stage.
- Approved listings move to finished only after successful generation.
- Restaged finished listings must preserve their original folder and SKU identity.
- Workbook generation must not change during unrelated refactors.
- Secrets and credentials must never be committed.

## Before changing code

- [ ] Work on a branch rather than staging or main.
- [ ] Confirm the working tree is clean.
- [ ] Keep the task narrow.
- [ ] Know which files should change.
- [ ] Have a rollback path.

## Automated checks

```powershell
python -m compileall -q -x "(\.git|\.venv|venv|__pycache__|\.pytest_cache|\.history)" .
git diff --check
git status
```

## Manual smoke tests

- [ ] Streamlit starts successfully.
- [ ] A fresh listing defaults variant quantity to 100.
- [ ] Adult garment variants generate correctly.
- [ ] Generic Shirts adult sizes generate correctly.
- [ ] Generic Shirts kids sizes generate correctly.
- [ ] Every adult and kids child receives the selected quantity.
- [ ] One Size products generate correctly.
- [ ] Saved listing content reloads correctly.
- [ ] Submit for Review moves _stage to ready.
- [ ] Deny moves ready back to _stage.
- [ ] Approve moves ready to approved.
- [ ] Successful generation moves approved to finished.
- [ ] Failed generation does not move the listing to finished.
- [ ] Restaged listings preserve their original identity.

## Before committing

```powershell
git status
git diff --stat
git diff
git diff --check
```

Confirm that only intended files changed and no temporary files, workbooks, secrets, or unrelated formatting changes are included.

## Commit policy

- One clear purpose per commit.
- Compile and test before committing.
- Do not combine a refactor with a feature change.
- Keep every commit independently reversible.
