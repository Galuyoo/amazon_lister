# Stock-Ready Amazon Manifests

Amazon Lister does not fetch supplier stock and does not update Amazon inventory.
Its job is to generate listings, Amazon workbooks, finished folders, and `sku_manifest.json`.

The separate stock updater service should read finished-folder `sku_manifest.json` files and use those immutable mappings for Amazon inventory feeds.

## SKU Contract

For templates with a stock reference, child seller SKUs are generated as:

```text
<design_or_listing_code>-<supplier_stock_key>
```

`supplier_stock_key` must be the exact stock lookup key from the supplier reference data.
By default, `design_or_listing_code` comes from the listing parent SKU used at generation time, which is the finished-folder identity and is preserved during restage/regeneration. Templates can override it with `design_or_listing_code`, `listing_code`, or per-design `design_listing_code_map` when a more specific design code is available.

- Uneek stock updater lookup: `ItemNo -> Stock`
- Ralawise stock updater lookup: `SKU -> free`

The stock updater must trust `sku_manifest.json`. It should not recalculate Amazon seller SKUs from template config.

## Amazon Lister Scope

Amazon Lister only:

- resolves `supplier_stock_key` from explicit local stock reference JSON
- writes `amazon_seller_sku`, `supplier`, `supplier_stock_key`, `supplier_stock_key_status`, `design_or_listing_code`, and `variant_values` into `sku_manifest.json`
- blocks duplicate `amazon_seller_sku`
- blocks missing supplier stock keys when `strict_stock_ready` is enabled

Amazon Lister does not:

- call Uneek or Ralawise stock APIs
- build live stock levels
- upload Amazon inventory updates
- call Amazon SP-API

## Configuring A Garment

Add a `stock_reference_key` to the garment/template config:

```json
{
  "template_key": "UC106",
  "parent_sku": "UC106",
  "stock_reference_key": "UC106"
}
```

Then add an explicit reference in `config/stock_references.json`:

```json
{
  "references": {
    "UC106": {
      "supplier": "uneek",
      "strict_stock_ready": true,
      "variant_key_fields": ["color", "size"],
      "variant_stock_key_map": {
        "Black|S": "106BKSM",
        "Black|M": "106BKMD"
      }
    }
  }
}
```

For Ralawise, use the exact `SKU` values from its stock/catalog data:

```json
{
  "references": {
    "RALAWISE_EXAMPLE": {
      "supplier": "ralawise",
      "strict_stock_ready": true,
      "variant_key_fields": ["color", "size"],
      "variant_stock_key_map": {
        "Black|S": "26BROANTH"
      }
    }
  }
}
```

Do not infer Ralawise stock keys from colour or size names unless a separate verified catalog mapping exists.

## Manual Test

1. Choose a template with `stock_reference_key`, such as `UC106`.
2. Select a small set of variants, for example Black S and Black M.
3. Open selected combinations preview.
4. Confirm child SKUs contain the exact supplier stock keys, for example `...-106BKSM` and `...-106BKMD`.
5. Generate a test finished folder.
6. Confirm the workbook child `item_sku` values match the previewed Amazon seller SKUs.
7. Confirm `sku_manifest.json` contains `supplier_stock_key`, `supplier_stock_key_status`, `supplier`, `design_or_listing_code`, and `variant_values` for each child.
8. Temporarily remove a mapping in `config/stock_references.json` and confirm strict mode blocks generation before workbook output.
