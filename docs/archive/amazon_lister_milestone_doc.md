# Amazon Lister - Technical Milestone Documentation

## Purpose
This document explains the current architecture, data flow, configuration model, and known limitations of the Amazon listing generator app after the latest milestone.

It is intended for the next developer who needs to maintain or extend the system without reverse-engineering the entire codebase.

---

## What this milestone introduced

This milestone changed the app from a simple template-driven workbook filler into a more structured listing pipeline with:

- permanent Dropbox asset finalization into `finished/`
- stable image-link generation for generated workbooks
- separation between reusable garment resources and design-specific staged assets
- dynamic variant-dimension support beyond simple color/size
- template-specific extra fields via config
- selected-combination previews in the UI
- combo image previews for design+color templates
- progress + timing instrumentation
- support for additional templates like UX4 and TC013 3-design towel

---

## High-level architecture

The app has four major layers:

1. Template configuration
2. Dropbox asset discovery and resolution
3. Workbook payload generation
4. Workbook writing into `.xlsm`

### 1) Template configuration
Each template lives under `templates/<folder>/config.json`.

These config files describe:

- product metadata
- variation theme
- color and size definitions
- optional dynamic variant dimensions
- SKU code maps
- optional extra workbook fields

### 2) Dropbox asset configuration
Dropbox resource mappings live in `config/dropbox_templates.json`.

This file defines:

- `stage_root`
- `finished_root`
- `resource_root`
- shared resource images
- per-template garment image maps
- optional design/color combo image maps

### 3) Runtime payload generation
When the user fills the UI and clicks Generate:

- the app validates title, bullets, price data, variant selection, and config completeness
- the selected staged Dropbox folder is moved into `finished/<unique>-<parent_sku>`
- Dropbox image URLs are resolved
- a payload dictionary is created and passed to workbook generation

### 4) Workbook writing
The app opens the `.xlsm` template, finds the header row, writes:

- one parent row
- one row per variant combination

then saves a generated workbook into `outputs/`.

---

## Dropbox model

The system now uses three distinct Dropbox areas.

### `_stage/`
Temporary design-specific image folders.

These are the images that change from one design/listing to another.

Example:

```text
_stage/
  towel-design-run-01/
    MAIN.png
    1.png
    2.jpg
```

These folders are selected in the UI and are only finalized when the user clicks Generate.

### `finished/`
Permanent finalized listing image folders.

When generation starts, the selected stage folder is moved into:

```text
finished/<unique_sku>-<parent_sku>/
```

Example:

```text
finished/AMZ260331133801-TC013/
```

This ensures old workbook image URLs continue to work even after staging contents change later.

### `1_Resources/`
Permanent shared reusable assets.

This contains:

- embroidery/shared examples
- reusable garment color images
- template-specific variant image folders
- optional design/color combination images

Example:

```text
1_Resources/
  EMB1.png
  EMB2.png
  EMB_FONTS.png
  UC502/
  UX4/
  TC013/
  TC013_3designs/
```

---

## Why the finished-folder flow exists

Originally, the app generated image links from staging/shared areas that could later be changed or overwritten.
That meant old exported workbooks could break because linked images were no longer stable.

The current solution is:

- design-specific assets start in `_stage/`
- on generation, they move into `finished/`
- the workbook uses links from `finished/`
- shared reusable garment assets still come from `1_Resources/`

This keeps the workflow fast while making workbook image links stable over time.

---

## Config model

## A. `templates/<name>/config.json`

This controls listing/business logic.

### Common fields
Typical keys include:

- `label`
- `template_key`
- `template_file`
- `parent_sku`
- `feed_product_type`
- `recommended_browse_nodes`
- `product_category`
- `brand_name`
- `manufacturer`
- `material_type`
- `style_name`
- `variation_theme`
- `condition_type`
- `item_type_name`
- `care_instructions`
- `theme`

### Legacy variant model
Older templates use:

- `colors`
- `sizes`
- `color_sku_map`
- `size_code_map`

This is still supported.

### Dynamic variant model
Newer templates can instead define:

```json
"variant_dimensions": [
  {
    "name": "color",
    "label": "Colours",
    "options": ["Black", "Navy"]
  },
  {
    "name": "design",
    "label": "Designs",
    "options": ["Design 1", "Design 2", "Design 3"]
  }
]
```

This allows non-size variants such as:

- color + design
- color + style
- future bag-type variation structures

### Extra fields
Templates can optionally define:

```json
"extra_fields": {
  "Item Display Length": "50",
  "Unit of Measure (Per Unit Pricing)": "count",
  "Unit Count (Per Unit Pricing)": "1",
  "Item Length Longer Edge": "50",
  "Item Length Unit": "Centimetres",
  "Item Width Shorter Edge": "30",
  "Item Width Unit": "Centimetres"
}
```

These are written into both parent and child rows when present.

This is the framework for category-specific workbook requirements.
It should be preferred over hardcoding towel-specific or bag-specific fields in Python.

---

## B. `config/dropbox_templates.json`

This controls Dropbox asset lookup.

Top-level structure:

```json
{
  "stage_root": ".../_stage",
  "finished_root": ".../finished",
  "resource_root": ".../1_Resources",
  "general_resource_images": ["EMB1.png", "EMB2.png", "EMB_FONTS.png"],
  "templates": {
    "UX4": { ... },
    "TC013": { ... },
    "TC013_3designs": { ... }
  }
}
```

### Per-template block
A normal template block looks like:

```json
"UX4": {
  "variant_folder": "UX4",
  "main_image_map": {
    "Black": "UX4BK.jpg",
    "Navy": "UX4NY.jpg"
  }
}
```

### Combo-image template block
A design/color template can additionally define:

```json
"TC013_3designs": {
  "variant_folder": "TC013_3designs",
  "main_image_map": {
    "Black": "BK_D1.jpg",
    "Navy": "NV_D1.jpg"
  },
  "design_color_image_map": {
    "Black": {
      "Design 1": "BK_D1.jpg",
      "Design 2": "BK_D2.jpg",
      "Design 3": "BK_D3.jpg"
    },
    "Navy": {
      "Design 1": "NV_D1.jpg",
      "Design 2": "NV_D2.jpg",
      "Design 3": "NV_D3.jpg"
    }
  }
}
```

At the moment:

- `main_image_map` is used by actual workbook generation
- `design_color_image_map` is currently used for UI preview only

This is intentional because combo-image workbook writing is future work.

---

## Variant system

## Legacy mode
If a template does not define `variant_dimensions`, the app falls back to old behavior:

- select colors
- select sizes
- generate combinations from those two lists

This preserves backward compatibility for older garment configs.

## Dynamic mode
If `variant_dimensions` exists, the app renders one multiselect per dimension and builds all combinations using Cartesian product.

Example for TC013 3-design towel:

- colors: Black, Navy
- designs: Design 1, Design 2, Design 3

Generated combinations:

- Black / Design 1
- Black / Design 2
- Black / Design 3
- Navy / Design 1
- Navy / Design 2
- Navy / Design 3

---

## SKU generation

### Parent/finalized folder SKU
The final folder name is generated as:

```text
<unique_program_sku>-<parent_sku>
```

Example:

```text
AMZ260331133801-TC013
```

This unique+base approach ensures:

- uniqueness in `finished/`
- stable lookup later
- preservation of the business/product SKU

### Child SKU logic
Child SKUs are generated from:

- `parent_sku`
- `color_sku_map`
- `size_code_map`
- `design_sku_map`

The current implementation avoids doubling the parent prefix if `color_sku_map` already includes it.

Example for TC013 towel:

- parent `TC013`
- Black -> `TC013-BLK`
- Design 1 -> `D1`

Result:

```text
TC013-BLK-D1
```

---

## Image resolution behavior

## Parent images
Parent main image and other images are taken from the finalized `finished/<final_sku>/` folder.

Rules:

- `MAIN.*` is treated as the main image if present
- everything else becomes additional images in filename order
- if `MAIN.*` is missing, the first image becomes the main image

## Shared resource images
Additional shared images are taken from:

- `general_resource_images`

These are appended to other image URLs.

## Child main images
Current workbook child-image behavior is still color-based:

```python
image_url = data.get("color_image_map", {}).get(color_value, "")
```

So for TC013_3designs:

- all Black child rows currently use the same Black fallback image
- all Navy child rows use the same Navy fallback image

## Combo image preview
The UI now supports combo preview using `design_color_image_map`.
This is visible in the `Variant combinations` tab under Dropbox image overview.

This preview layer is working.

## Important limitation
Combo image preview does **not** yet feed workbook child `main_image_url` generation.
That is the next logical extension if design-specific child images are required in the workbook export.

---

## UI behavior

The main screen now includes:

- template selector
- selected staged Dropbox folder selector
- title, bullets, description, search terms
- dynamic variants section
- selected combinations preview table
- inventory controls
- Dropbox image overview with tabs

### Selected combinations preview
This preview shows the currently selected variant combinations and their computed child SKUs.

### Dropbox image overview tabs
The overview includes:

- Staged images
- Shared resources
- Colour variants
- Variant combinations

For `TC013_3designs`, the `Variant combinations` tab shows the six design/color images from `design_color_image_map`.

---

## Generation flow

When the user clicks **Generate workbook**:

1. Validate required text inputs
2. Validate bullets
3. Validate price inputs
4. Validate selected variants
5. Validate template parent SKU presence
6. Build a pre-validation payload
7. Validate payload structure
8. Finalize/move the selected stage folder into `finished/`
9. Resolve Dropbox image URLs
10. Build the workbook payload
11. Load `.xlsm`
12. Write parent row
13. Write child rows
14. Save workbook to `outputs/`

---

## Progress and timing instrumentation

The app now shows:

- a progress bar
- live text status
- a performance breakdown after generation

Tracked sections:

- move staged folder
- resolve Dropbox image URLs
- build workbook
- load workbook
- write parent row
- write child rows
- save workbook

This was added because large macro-enabled workbooks were observed to be slow, and the instrumentation showed workbook writing/saving as a major bottleneck.

---

## Performance notes

The current code includes a `Copy row styles` toggle in the sidebar.

Reason:

- `copy_row_format()` is expensive on large `.xlsm` files
- this can be a major contributor to slow generation

If performance becomes an issue again, compare timings with:

- `Copy row styles = True`
- `Copy row styles = False`

Likely future optimization area:

- reduce style copying cost
- minimize workbook save overhead
- optionally cache more Dropbox link resolutions

---

## Validation behavior

The app currently validates:

- parent SKU presence
- required payload fields
- product category
- variation theme
- quantity and pricing
- selected variant dimensions

### Supported variation themes
The validation currently allows:

- `SizeColor`
- `Colour & Style`
- empty string

If a future template requires another workbook-specific variation theme, the validation set must be extended.

---

## Template-specific extra fields strategy

The app now supports template-driven `extra_fields`.

This is the preferred approach for category-specific columns such as:

- towels
- bags
- future non-apparel products

### Why this matters
Without this, category-specific workbook fields would require hardcoded logic in Python.
That quickly becomes brittle.

### Current rule
If a field is required only for certain template types, add it to that template’s `config.json` under `extra_fields`.

### Important caution
The keys in `extra_fields` must match the workbook header names exactly.

---

## Current known limitations

1. Combo image preview is implemented, but workbook child rows still use color-only fallback images.
2. `design_color_image_map` is currently preview-only metadata.
3. Variation theme validation is intentionally narrow and may need expanding for future product categories.
4. Some template fields still reflect generic assumptions unless overridden by config.
5. The workbook writer still attempts a broad field set and silently ignores headers that do not exist unless debug is enabled.

---

## Recommended next development steps

### Highest-value next step
Feed `design_color_image_map` into child workbook image generation so each child row gets the correct design/color image.

### Other good next steps
- move exact header-name discovery into a cleaner inspection workflow
- add per-template required-field linting
- reduce workbook write time on heavy `.xlsm` files
- add a template QA checklist to validate config completeness before generation
- optionally add branch-safe Git export or milestone snapshot automation

---

## Practical onboarding notes for the next developer

If you are adding a new template:

1. Create `templates/<folder>/config.json`
2. Add `template_key`
3. Add workbook metadata
4. Add `colors` / `sizes` or `variant_dimensions`
5. Add SKU maps
6. Add any `extra_fields`
7. Add a matching block in `config/dropbox_templates.json`
8. Add garment resource images into `1_Resources/<variant_folder>/`
9. Test preview tabs first
10. Test generation with a real staged folder

If you are adding a new category with extra workbook columns:

- do not hardcode in Python first
- try `extra_fields` in the template config
- only add Python logic if the field behavior is dynamic rather than static

If you are extending image behavior:

- check whether the need is preview-only or workbook-export behavior
- keep preview and export logic conceptually separate unless they intentionally share a resolver

---

## Summary

This milestone established a solid config-driven foundation:

- stable finished-folder image flow
- reusable resource mapping
- dynamic variant dimensions
- extra-fields framework
- selected combinations preview
- combo image preview support
- performance visibility

The system is now much more maintainable than the original color/size-only workbook filler, while still remaining backward compatible with older templates.

The one major remaining gap is full combo-image export into child workbook rows.
