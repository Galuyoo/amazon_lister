# Amazon Lister Roadmap: Epics, Sprints, and Scaling Plan

This document captures future improvements for the Amazon listing app. These items are not implemented yet. Use this roadmap to pick the next work safely, avoid short-term choices that block scaling, and keep the current warehouse workflow reliable while the product grows.

The current workflow remains:

```text
_stage -> ready -> approved -> finished
```

`listing_inputs.json` remains the compatibility format during the migration. Dropbox remains the operational storage layer until database-backed workflow state is planned, tested, and rolled out safely.

## Recommended Direction

- Keep Streamlit as the V1 operator/admin interface while the workflow is still changing quickly.
- Introduce a real database before trying to scale users heavily.
- Use Postgres, preferably Supabase Postgres for the first serious database version, because it gives Postgres, auth options, storage options, and Row Level Security in one platform.
- Keep `listing_inputs.json` as a compatibility/export format during migration, but gradually move canonical workflow state into the database.
- Add a backend layer later, likely FastAPI, once workbook generation, uploads, audits, or AI calls need background processing.
- Consider migrating from Streamlit to a proper web app only when the app needs stronger role UX, multi-user concurrency, subscriptions, customer portals, or more polished SaaS workflows.

## Epic 1: Template and Workbook Quality

### Goal

Make every template family and garment template dependable enough that Amazon upload problems are caught before operators generate files.

### Main Tasks

- Audit every template family and garment template.
- Verify workbook files, config metadata, browse node IDs, variation themes, size systems, colour lists, valid size/colour combinations, prices, image expectations, parent rows, country of origin, materials, product type fields, and required Amazon fields.
- Enrich workbook/template defaults where it improves upload quality and reduces Amazon warnings.
- Add template-level quality checks for SKU length, title length, missing prices, missing images, missing required fields, suspicious parent rows, invalid size systems, and known Amazon upload blockers.
- Record audit status in a template audit table or markdown file so weak templates are visible before use.

### Dependencies

- Existing template configs and workbook files must remain the source of truth until the database migration starts.
- Any config schema change needs backward compatibility or a migration note.

### Acceptance Criteria

- Every active template has a visible audit status.
- Known weak templates have clear notes and next actions.
- Review/generation blocks listings with hard failures before Amazon upload.
- Normal templates, kids templates, restaged folders, and special projects still generate correctly.

## Epic 2: Stage Folder Creation and Upload Intake

### Goal

Allow operators/admins to create a staged folder from the app instead of manually arranging Dropbox folders.

### Main Tasks

- Add an app flow to create a staged folder from selected template family and garment template.
- Support uploading an initial staged folder as a `.zip`.
- Extract ZIP contents into the configured Dropbox stage area.
- Validate structure before accepting it:
  - variant images
  - optional `resources` folder
  - optional or generated `listing_inputs.json`
  - expected colour/filename mappings
  - selected template metadata
- Auto-select the new staged folder after creation and continue through the normal workflow.
- Add clear validation messages when a staged folder is incomplete.

### Dependencies

- Dropbox storage remains the first target.
- Image mapping rules must stay compatible with existing normal-colour filenames and special project naming rules.

### Acceptance Criteria

- An operator can create a clean staged folder without manually building Dropbox folders.
- Uploaded ZIPs fail early if structure or filenames are wrong.
- The created folder enters the same workflow as manually staged folders.
- Existing staged folder selection and restage behavior keep working.

## Epic 3: Admin Task Intake

### Goal

Create listing tasks before operators start work, so the operator workflow is guided by an admin-approved brief.

### Main Tasks

- Add an admin-side task form.
- Capture MPN/listing code, template family, garment template or garment group, sizes, colours, prices, title/content notes, assets owner, due date, priority, status, and assigned operator.
- Show operators a task queue instead of relying only on folder names.
- Link each task to staged folder, review folder, approved folder, generated outputs, and finished history.
- Prefill product setup and listing content from the task where possible.
- Add task notes for edge cases, customer requirements, image status, and upload concerns.

### Dependencies

- Can start using the current Dropbox/JSON storage layer.
- Should be designed so the same task model can later move into Postgres.

### Acceptance Criteria

- A listing can start from an admin task instead of only from a staged folder.
- Operators can see assigned work and current status.
- Reviewers can trace a listing back to the original task brief.
- Task data is not lost when the folder moves through the workflow.

## Epic 4: AI-Assisted Content Preparation

### Goal

Use AI to speed up content creation while keeping humans in control of final listing quality.

### Main Tasks

- Create a strong prompt/spec for ChatGPT to generate structured listing JSON.
- The JSON should include title, bullets, description, search terms, garment details, colours, sizes, prices, MPN/listing code, and notes.
- First phase: manually use the prompt in ChatGPT and paste/import the JSON into the app.
- Later phase: call an API/server-side AI endpoint from the app to generate content directly.
- Allow extra context before generation, such as target audience, design theme, holiday/event, tone, garment type, compliance constraints, and marketplace notes.
- Add validation so AI output cannot bypass hard listing checks.

### Dependencies

- Needs stable listing JSON shape.
- Works best after admin task intake exists, because task notes become useful AI context.

### Acceptance Criteria

- AI can prepare structured content that imports cleanly into the app.
- Human review remains required before review/generation.
- Generated content passes existing quality checks or shows clear issues.
- AI output does not overwrite operator edits unexpectedly.

## Epic 5: Users, Roles, Sessions, and Database

### Goal

Move from session-heavy, Dropbox-only state toward a proper multi-user workflow with roles, auditability, and durable records.

### Main Tasks

- Add login and role checks.
- Separate admin, operator, reviewer, and approver views.
- Add profile-aware sidebar panels:
  - current user/profile
  - role and team
  - assigned task count
  - high-priority or blocked task count
  - admin notes/messages for the operator or team
  - quick links to assigned work
- Hide review/approval/admin actions from operators by default.
- Add workflow event logging for create, edit, submit, reject, approve, restage, generate, download, and finish actions.
- Introduce Postgres/Supabase schema for:
  - users
  - teams/workspaces
  - roles
  - profile settings
  - admin/operator notes
  - listing tasks
  - listing records
  - selected variants
  - prices
  - assets
  - generated outputs
  - template audit results
  - workflow events
  - AI generation requests
- Start with dual-write: keep Dropbox JSON compatibility while writing important state to the database.
- Add migration scripts, backup/export strategy, and rollback notes.

### Dependencies

- Auth and database design should be decided together.
- `listing_inputs.json` compatibility must remain until old folders can be migrated or archived safely.

### Acceptance Criteria

- Users only see actions appropriate to their role.
- Sidebar content is useful but quiet: identity, assigned work, and admin notes only.
- Operators can quickly see what is assigned to them without exposing review/approval tools.
- Key workflow actions are audit logged.
- New listings can be tracked in the database without breaking existing Dropbox-based folders.
- A listing can still be exported to or restored from `listing_inputs.json`.

## Epic 6: Scaling and SaaS Readiness

### Goal

Prepare the app to support multiple users, teams, and eventually paying customers.

### Main Tasks

- Add tenant/team/workspace separation.
- Add usage limits, billing/subscription planning, support tooling, logs, monitoring, backups, and deployment health checks.
- Add a storage abstraction so Dropbox can later be swapped or complemented with S3 or Supabase Storage.
- Extract long-running generation and upload work into background jobs.
- Define when to migrate from Streamlit to a React/Next.js frontend with a FastAPI backend.
- Plan customer onboarding, template library management, and team-level permissions.

### Dependencies

- Requires database-backed users, roles, and workflow records first.
- Billing should not be added until tenant isolation and audit logs are solid.

### Acceptance Criteria

- The product has a clear path to multi-customer use.
- Each team/customer can be isolated safely.
- Generated outputs and history are traceable per workspace.
- Migration away from Streamlit has defined triggers rather than being a vague rewrite.

## Sprint Plan

### Sprint 0: Stabilise Current Workflow

- Freeze risky feature additions.
- Confirm tab state, review reload, approved generation, finished/download behavior, CP split behavior, and restage paths.
- Add a smoke-test checklist for one normal shirt, one hoodie, one kids item, and one CP split listing.
- Fix any issue that causes data to disappear between stage, review, approval, generation, and finished history.

Acceptance: current warehouse workflow is reliable enough for daily use.

### Sprint 1: Template Audit Foundation

- Create a template audit checklist.
- Audit all existing template families and garment templates.
- Record missing/weak fields in a template audit table or markdown file.
- Add hard checks for SKU length, title length, missing prices, missing images, required Amazon fields, and parent row readiness.

Acceptance: every template has a visible quality status and known issues list.

### Sprint 2: Stage Folder Upload V1

- Add app flow to upload a ZIP and create a staged folder.
- Validate ZIP structure, images, resources, and listing metadata.
- Generate or update `listing_inputs.json`.
- Auto-select the new staged folder after upload.

Acceptance: an operator can create a clean staged folder without manually building Dropbox folders.

### Sprint 3: Admin Task Intake V1

- Add admin task form using the current storage layer first.
- Include MPN, garment/template, colours, sizes, prices, notes, content brief, priority, due date, and assignee.
- Show operators a task queue.
- Link task records to staged/review/approved/generated outputs.

Acceptance: listings can start from an admin task instead of only from a staged folder.

### Sprint 4: Auth, Roles, and Audit Trail

- Add login and role checks.
- Hide review/approval/admin actions from operators.
- Add workflow event logging.
- Add basic admin view for user/role mapping.
- Add first profile sidebar:
  - signed-in user
  - role/team
  - assigned task count
  - blocked/urgent task count
  - admin notes

Acceptance: admin/operator/reviewer responsibilities are separated and traceable.

### Sprint 4.5: Profile Sidebar and Operator Handoff

- Keep this after current bugs are stable and the task lister is live.
- Add profile-level settings for each operator/team.
- Show only useful sidebar context:
  - assigned tasks
  - admin notes
  - current role/team
  - quick filter to "my tasks"
- Let admins post short notes to one operator, one team, or all operators.
- Keep the main listing workflow in the main tabs; sidebar should support the workflow, not become another crowded control panel.

Acceptance: operators can open the app and immediately understand their assigned work and notes without needing Dropbox or manual messages.

### Sprint 5: Database Migration Foundation

- Introduce Postgres/Supabase schema for users, tasks, listing records, variants, prices, assets, generated outputs, and workflow events.
- Start dual-write for new listings.
- Keep Dropbox JSON compatibility.
- Add migration scripts and backup/export strategy.

Acceptance: new listings can be tracked in the database without breaking existing Dropbox-based folders.

### Sprint 6: AI Content Prep

- Finalise the listing JSON prompt/spec.
- Add import flow for AI-generated JSON.
- Later add direct AI generation behind an admin/reviewer action.
- Validate AI output before it can enter review.

Acceptance: AI can prepare structured content, but humans still approve before review/generation.

### Sprint 7: Backend and Background Jobs

- Extract workbook generation and heavier Dropbox operations behind service functions.
- Add FastAPI when app actions need stable endpoints or background processing.
- Start with simple background jobs.
- Move to a queue if generation becomes slow or concurrent.

Acceptance: long-running work no longer makes the Streamlit UI fragile.

### Sprint 8: SaaS Readiness and Migration Decision

- Add tenant/team model, billing plan, limits, logs, monitoring, backups, and support tools.
- Decide whether to stay on Streamlit or migrate to Next.js/React plus FastAPI.
- Define subscription/customer onboarding requirements.

Acceptance: the product has a clear path to multi-customer use.

## Technology Notes

### Database

Default direction: Supabase Postgres, with portable SQL so Neon/Postgres remains possible later.

Reasons:

- Postgres is mature and flexible for tasks, listings, audit events, prices, generated outputs, and tenant data.
- Supabase can provide auth/storage/RLS around Postgres if we want a faster V1.
- Neon remains a good Postgres hosting option if we prefer separating auth and database hosting.

### Auth

- Streamlit `st.login` can be considered for V1 OIDC login.
- Supabase Auth becomes stronger once database Row Level Security is central.
- Role mapping should support at least admin, operator, reviewer, and approver.

### Backend

- FastAPI is the likely backend when app actions need stable endpoints, background jobs, AI calls, or integrations.
- Keep business logic in reusable service modules so Streamlit and FastAPI can call the same code during migration.

### Background Jobs

- Start simple for light tasks.
- Use FastAPI background tasks only for short, non-critical work.
- Move to Redis/RQ, Celery, or a managed queue once workbook generation, image work, or Dropbox operations become slow or concurrent.

### Storage

- Keep Dropbox initially because it matches the current warehouse workflow.
- Introduce a `StorageService` abstraction before adding S3 or Supabase Storage.
- Generated workbooks should become downloadable history records, not one-time files that disappear from the UI.

### Frontend Migration Trigger

Stay on Streamlit until one or more of these become painful:

- complex admin/operator/reviewer permissions
- multi-user locking or real-time collaboration
- subscription/customer portal UX
- highly polished SaaS dashboards
- heavy custom UI that Streamlit cannot comfortably support

If those triggers appear, migrate to a React/Next.js frontend with FastAPI and Postgres behind it.

## Acceptance Criteria for This Roadmap Document

- The roadmap is grouped by epics and sprints.
- Each epic has goal, main tasks, dependencies, and acceptance criteria.
- The scaling section clearly explains Streamlit now, database next, backend later, and possible frontend migration.
- The plan respects the existing `_stage -> ready -> approved -> finished` workflow.
- The plan keeps `listing_inputs.json` compatibility during migration.
- Updating this document does not change app behavior.

## References

- Streamlit login/OIDC docs: https://docs.streamlit.io/develop/api-reference/user/st.login
- Supabase Row Level Security docs: https://supabase.com/docs/guides/database/postgres/row-level-security
- FastAPI background tasks docs: https://fastapi.tiangolo.com/tutorial/background-tasks/
- Neon Postgres pooling docs: https://neon.com/docs/connect/connection-pooling

## Working Principles

- Do not break the warehouse workflow while improving the product.
- Prefer config-driven behavior over one-off hard-coded fixes where reasonable.
- Preserve useful metadata at every workflow step.
- Keep operator work, admin review, generated outputs, template management, and audit history clearly separated.
- Treat `listing_inputs.json` as a stable bridge while database-backed workflow state is introduced.
- Make scaling choices gradually: reliability first, database second, backend third, SaaS polish later.
