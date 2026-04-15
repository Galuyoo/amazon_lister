# Amazon Listing Generator System

## Overview

Streamlit-based system for generating Amazon flat files (Excel) for
apparel and accessories. Includes: - Template-based listing generation -
Dropbox image integration - SKU automation - Variant generation
(size/color) - Multi-product family support (COAT, HEADWEAR, SHIRT,
HOODIE, TOWEL)

------------------------------------------------------------------------

## Core Concepts

### SKU Structure

`<UNIQUE>`{=html}-`<PRODUCT_CODE>`{=html}-`<COLOR_CODE>`{=html}-`<SIZE_CODE>`{=html}

Example: A7K92M-BC045-BKBR-ONE

### Product Categories

Only allowed: - apparel - accessory

### Variation System

-   SizeColor = standard
-   Some products use compound colors (e.g. Black/Red)

------------------------------------------------------------------------

## Template Structure

templates/ COAT/ HEADWEAR/ SHIRT/ HOODIE/ TOWEL/

Each template contains: - config.json - workbook (.xlsm or .xlsx)

------------------------------------------------------------------------

## Config Rules

-   colors MUST match dropbox_templates.json exactly
-   color_sku_map MUST match supplier codes
-   size_code_map must match Shopify logic
-   product_category must be "apparel" or "accessory"

------------------------------------------------------------------------

## Dropbox System

-   Images mapped via dropbox_templates.json
-   Naming pattern: `<PRODUCT_CODE>`{=html}`<COLOR_CODE>`{=html}.jpg

Example: R237XBKYE.jpg → Black/Yellow

------------------------------------------------------------------------

## Product Types

### Standard

-   Single color

### Dual Color

-   Black/Red style

### Customisation

-   Front only
-   Front & Back

------------------------------------------------------------------------

## Pricing

-   Per-size pricing supported
-   One-price-for-all option available
-   Stored in size_price_map

------------------------------------------------------------------------

## Constraints

-   Description must be \< 2000 chars
-   Titles SEO optimized
-   Only valid product_category values allowed

------------------------------------------------------------------------

## Future Improvements

-   Auto title generation
-   Auto bullet generation
-   Template abstraction
-   Multi-placement embroidery logic

------------------------------------------------------------------------

## Instructions for AI Assistants

-   Always respect SKU structure
-   Never change product_category values
-   Match config to dropbox_templates.json
-   Do not invent color codes
-   Prefer supplier data over assumptions
