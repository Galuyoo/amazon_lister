from __future__ import annotations

import re
from collections import Counter
from typing import Any


SAFE_SKU_PART_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_sku_part(value: str) -> str:
    safe = SAFE_SKU_PART_PATTERN.sub("-", str(value or "").strip())
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe.strip("-")


def slugify_part(value: str) -> str:
    safe = str(value or "").strip().replace(" ", "-").replace("/", "-")
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe.strip("-")


def lookup_mapping(mapping: dict[str, Any], key: str) -> str:
    key = str(key or "")
    if key in mapping:
        return str(mapping[key] or "").strip()

    key_lower = key.lower()
    for candidate_key, candidate_value in mapping.items():
        if str(candidate_key).lower() == key_lower:
            return str(candidate_value or "").strip()

    return ""


def has_stock_reference(profile: dict[str, Any]) -> bool:
    return bool(str(profile.get("stock_reference_key", "") or "").strip())


def get_stock_reference(profile: dict[str, Any]) -> dict[str, Any]:
    reference = profile.get("_stock_reference", {})
    return dict(reference) if isinstance(reference, dict) and reference else {}


def is_strict_stock_ready(profile: dict[str, Any]) -> bool:
    reference = get_stock_reference(profile)
    if "strict_stock_ready" in reference:
        return bool(reference.get("strict_stock_ready"))
    if "strict" in reference:
        return bool(reference.get("strict"))
    return has_stock_reference(profile)


def build_variant_reference_key(
    reference: dict[str, Any],
    variant_values: dict[str, str],
) -> str:
    fields = reference.get("variant_key_fields", ["color", "size"])
    if not isinstance(fields, list) or not fields:
        fields = ["color", "size"]
    return "|".join(str(variant_values.get(str(field), "") or "") for field in fields)


def resolve_supplier_stock_key(
    profile: dict[str, Any],
    variant_values: dict[str, str],
) -> dict[str, str]:
    reference_key = str(profile.get("stock_reference_key", "") or "").strip()
    if not reference_key:
        return {
            "supplier": "",
            "supplier_stock_key": "",
            "supplier_stock_key_status": "legacy",
            "supplier_stock_key_reason": "No stock_reference_key is configured for this template.",
        }

    reference = get_stock_reference(profile)
    if not reference:
        return {
            "supplier": "",
            "supplier_stock_key": "",
            "supplier_stock_key_status": "missing",
            "supplier_stock_key_reason": f"Stock reference '{reference_key}' was not found in config/stock_references.json.",
        }

    supplier = str(reference.get("supplier", "") or "").strip().lower()
    variant_stock_key_map = reference.get("variant_stock_key_map", {})
    if not isinstance(variant_stock_key_map, dict) or not variant_stock_key_map:
        return {
            "supplier": supplier,
            "supplier_stock_key": "",
            "supplier_stock_key_status": "missing",
            "supplier_stock_key_reason": f"Stock reference '{reference_key}' has no variant_stock_key_map.",
        }

    variant_reference_key = build_variant_reference_key(reference, variant_values)
    supplier_stock_key = lookup_mapping(variant_stock_key_map, variant_reference_key)

    if supplier_stock_key:
        return {
            "supplier": supplier,
            "supplier_stock_key": supplier_stock_key,
            "supplier_stock_key_status": "resolved",
            "supplier_stock_key_reason": "",
        }

    return {
        "supplier": supplier,
        "supplier_stock_key": "",
        "supplier_stock_key_status": "missing",
        "supplier_stock_key_reason": (
            f"No supplier stock key mapped for '{variant_reference_key}' "
            f"in stock reference '{reference_key}'."
        ),
    }


def build_legacy_child_sku(
    profile: dict[str, Any],
    parent_sku: str,
    variant_values: dict[str, str],
) -> str:
    color_map = profile.get("color_sku_map", {})
    size_map = profile.get("size_code_map", {})
    design_map = profile.get("design_sku_map", {})

    color_map = color_map if isinstance(color_map, dict) else {}
    size_map = size_map if isinstance(size_map, dict) else {}
    design_map = design_map if isinstance(design_map, dict) else {}

    color_code = ""
    size_code = ""
    design_code = ""

    if "color" in variant_values:
        color_value = variant_values["color"]
        color_code = lookup_mapping(color_map, color_value) or slugify_part(color_value)

    if "size" in variant_values:
        size_value = variant_values["size"]
        size_code = lookup_mapping(size_map, size_value) or slugify_part(size_value)

    if "design" in variant_values:
        design_value = variant_values["design"]
        design_code = lookup_mapping(design_map, design_value) or slugify_part(design_value)

    parts: list[str] = []
    parent_sku = str(parent_sku or "")

    if color_code:
        if color_code.startswith(parent_sku):
            parts.append(color_code)
        else:
            parts.append(parent_sku)
            parts.append(color_code)
    else:
        parts.append(parent_sku)

    if size_code:
        parts.append(size_code)

    if design_code:
        parts.append(design_code)

    return "-".join(part for part in parts if part)


def resolve_design_or_listing_code(
    profile: dict[str, Any],
    parent_sku: str,
    variant_values: dict[str, str],
) -> str:
    base_code = str(
        profile.get("design_or_listing_code")
        or profile.get("listing_code")
        or profile.get("sku_listing_code")
        or parent_sku
        or profile.get("template_key")
        or profile.get("_slug")
        or ""
    ).strip()

    design_value = str(variant_values.get("design", "") or "")
    if design_value:
        design_listing_code_map = profile.get("design_listing_code_map", {})
        design_listing_code_map = design_listing_code_map if isinstance(design_listing_code_map, dict) else {}
        explicit_design_code = lookup_mapping(design_listing_code_map, design_value)
        if explicit_design_code:
            return sanitize_sku_part(explicit_design_code)

        design_map = profile.get("design_sku_map", {})
        design_map = design_map if isinstance(design_map, dict) else {}
        design_code = lookup_mapping(design_map, design_value) or slugify_part(design_value)
        base_code = f"{base_code}-{design_code}" if base_code else design_code

    return sanitize_sku_part(base_code)


def build_child_sku_details(
    profile: dict[str, Any],
    parent_sku: str,
    variant_values: dict[str, str],
) -> dict[str, str]:
    legacy_sku = build_legacy_child_sku(profile, parent_sku, variant_values)
    design_or_listing_code = resolve_design_or_listing_code(profile, parent_sku, variant_values)
    stock_key_result = resolve_supplier_stock_key(profile, variant_values)
    supplier_stock_key = stock_key_result.get("supplier_stock_key", "")

    if not has_stock_reference(profile):
        amazon_seller_sku = legacy_sku
    elif supplier_stock_key:
        amazon_seller_sku = f"{design_or_listing_code}-{supplier_stock_key}" if design_or_listing_code else supplier_stock_key
    else:
        missing_suffix = sanitize_sku_part(legacy_sku) or "UNKNOWN"
        amazon_seller_sku = f"{design_or_listing_code}-MISSING-STOCK-KEY-{missing_suffix}"

    return {
        "amazon_seller_sku": amazon_seller_sku,
        "canonical_sku": amazon_seller_sku,
        "legacy_sku": legacy_sku,
        "supplier": stock_key_result.get("supplier", ""),
        "supplier_stock_key": supplier_stock_key,
        "supplier_stock_key_status": stock_key_result.get("supplier_stock_key_status", "missing"),
        "supplier_stock_key_reason": stock_key_result.get("supplier_stock_key_reason", ""),
        "design_or_listing_code": design_or_listing_code,
    }


def validate_stock_ready_skus(
    profile: dict[str, Any],
    parent_sku: str,
    variant_combos: list[dict[str, str]],
) -> dict[str, Any]:
    details = [
        build_child_sku_details(profile, parent_sku, variant_values)
        for variant_values in variant_combos
    ]

    sku_counts = Counter(row["amazon_seller_sku"] for row in details)
    duplicate_skus = sorted(sku for sku, count in sku_counts.items() if count > 1)
    missing_rows = [
        row for row in details
        if row.get("supplier_stock_key_status") == "missing"
    ]

    errors: list[str] = []
    warnings: list[str] = []

    if duplicate_skus:
        errors.append("Duplicate Amazon seller SKUs detected: " + ", ".join(duplicate_skus[:10]))

    if has_stock_reference(profile) and missing_rows:
        sample_reasons = []
        for row in missing_rows[:5]:
            reason = row.get("supplier_stock_key_reason", "")
            if reason and reason not in sample_reasons:
                sample_reasons.append(reason)
        message = (
            f"Missing supplier stock keys for {len(missing_rows)} child variant(s). "
            + " | ".join(sample_reasons)
        ).strip()
        if is_strict_stock_ready(profile):
            errors.append(message)
        else:
            warnings.append(message)

    return {
        "errors": errors,
        "warnings": warnings,
        "duplicate_skus": duplicate_skus,
        "missing_supplier_stock_key_count": len(missing_rows),
        "children": details,
    }
