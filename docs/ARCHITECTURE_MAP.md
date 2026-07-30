# Amazon Lister Architecture Map

## Purpose

This document records the current application structure and the boundaries that must be preserved while the project is gradually organised.

The immediate goal is a stable Streamlit V1 for worker preparation, admin review, workbook generation and recovery.

This is a map of the current system, not a proposal for a large rewrite.

## Current scale

- `app.py` contains approximately 11,148 lines.
- The project currently has 110 detected Streamlit session-state keys.
- All detected session-state keys are referenced from `app.py`.
- Product behaviour is driven by configured template families.
- Dropbox folders represent workflow state and asset storage.
- `listing_inputs.json` stores listing state and recovery data.

## Top-level runtime structure

| Location | Current responsibility |
| --- | --- |
| `app.py` | Streamlit UI, active listing context, workflow orchestration, pricing, image mapping, validation and workbook generation |
| `services/stock_references.py` | Supplier stock references, SKU segments, child SKU construction and SKU validation |
| `services/quality_checks.py` | Listing quality checks, validation combinations, title and content checks |
| `utils/dropbox_client.py` | Dropbox client creation, folder listing, moves, uploads, downloads and shared links |
| `utils/image_resolver.py` | Basic Dropbox image resolution |
| `tools/generate_stock_references.py` | Offline generation and comparison of supplier stock-reference mappings |
| `templates/` | Amazon template families, profiles, schemas and workbook files |
| `testing/` | Manual test fixtures and staged-folder test material |
| `docs/` | Workflow, deployment, operational and regression documentation |

## Configured template families

- BAG
- COAT
- HEADWEAR
- HOODIE
- SHIRT
- Special Projects
- TOWEL

## Main areas inside app.py

### Performance and loading diagnostics

The opening section records rerun causes, load events, timing summaries and debug state.

This area is operational support code and should remain separate from listing-generation rules.

### Template and profile loading

Profiles, schemas, workbook layouts, template paths and stock-reference configuration are loaded and validated here.

### Variant, size, price and SKU preparation

This includes:

- size normalisation,
- adult and kids size handling,
- variant combination generation,
- variant price keys and price maps,
- parent SKU construction,
- child SKU delegation,
- variant field preparation.

Some related validation functions also exist in `services/quality_checks.py`. These duplicated concepts are a future drift risk and should eventually share tested pure helpers.

### Listing context and saved memory

The active listing context includes:

- selected folder,
- selected template profile,
- selected variants,
- price map,
- listing content,
- quantity and handling defaults,
- SKU context,
- image context,
- workflow metadata.

`listing_inputs.json` must remain the saved source of truth whenever it exists.

### Dropbox workflow

The application currently supports:

- `_stage -> ready`,
- `ready -> approved`,
- `ready -> _stage` after denial,
- `approved -> ready` or `_stage` when returned,
- `approved -> finished` after successful generation,
- `finished -> approved` or review flow during correction and restaging.

These transitions are business-critical and must fail loudly and safely.

### Image resolution

Image handling includes folder inspection, ZIP uploads, colour-image inference, design-colour mappings, preview caches and final generation-safe resolution.

Preview loading may be lazy, but generation must still resolve required images before completion.

### Workbook generation

Workbook generation includes:

- parent-row writing,
- child-row writing,
- field aliases,
- apparel size fields,
- template validation,
- individual workbooks,
- combined workbooks,
- approved-listing generation,
- generated artifact upload.

This is the highest-risk application area and should not be reorganised until regression tests and fixture comparisons exist.

## Risk boundaries

### Highest risk

- Workbook row generation and Amazon field mapping.
- Dropbox folder moves and workflow state transitions.
- Restage identity and original SKU preservation.
- Listing-memory hydration and Streamlit session-state replacement.
- Image resolution required for final generation.

### Medium risk

- Variant combination generation.
- Adult, kids and One Size classification.
- Price-map normalisation.
- Parent and child SKU construction.
- Review editor state.

### Lower risk

- Documentation.
- Constants that preserve existing values.
- Pure text normalisation helpers.
- Pure formatting helpers.
- Read-only diagnostic scripts.
- Tests that do not modify production behaviour.

## Safe refactor order

1. Document current behaviour and regression scenarios.
2. Add automated tests around existing pure functions.
3. Centralise repeated constants and defaults without changing their values.
4. Extract small pure helpers with identical inputs and outputs.
5. Remove duplicated pure logic only after both paths have regression tests.
6. Extract listing-memory helpers while preserving the JSON schema.
7. Extract UI sections without changing widget keys or session-state behaviour.
8. Wrap workflow operations after transition tests exist.
9. Reorganise workbook generation last, using fixture workbook comparisons.

## Non-negotiable invariants

- `listing_inputs.json` remains the recovery source of truth.
- Existing JSON fields are not renamed or removed without migration support.
- Old listing files continue to load.
- `_stage -> ready -> approved -> finished` semantics remain intact.
- Denial safely returns the listing to `_stage`.
- Generation failure does not move a listing to `finished`.
- Restaged finished listings preserve their original folder and SKU identity.
- Restaged finished listings preserve their original identity.
- Workbook content does not change during unrelated refactors.
- Existing Streamlit widget keys are preserved during UI extraction.
- Secrets and `.env` files remain untracked.

## Commit policy

Each organisational change must:

- have one narrow purpose,
- be independently reversible,
- compile successfully,
- pass relevant automated checks,
- pass the applicable regression checklist,
- avoid combining a refactor with a feature change,
- avoid unrelated formatting changes.

## Intended future module boundaries

The following is a gradual destination rather than an immediate rewrite:

- `ui/` for Streamlit rendering sections.
- `domain/` for pure variant, size, pricing and listing rules.
- `services/` for Dropbox workflow, listing memory, images and SKUs.
- `generation/` for workbook-specific construction and field mapping.
- `tests/` for unit, workflow and workbook fixture tests.

No directory should be introduced until there is a small, tested extraction ready to move into it.
