from __future__ import annotations

import math
from typing import Any, Callable

from services.listing_memory import (
    DEFAULT_HANDLING_TIME_DAYS,
    MERCHANT_SHIPPING_GROUP_OPTIONS,
)


def validate_mpn(mpn: Any) -> list[str]:
    if not isinstance(mpn, str) or not mpn.strip():
        return ["MPN is required."]
    if mpn != mpn.strip():
        return ["MPN must not start or end with whitespace."]
    if mpn in {".", ".."}:
        return ["MPN must be a Dropbox folder name, not a relative path."]
    if "/" in mpn or "\\" in mpn:
        return ["MPN must not contain path separators."]
    if any(ord(character) < 32 for character in mpn):
        return ["MPN must not contain control characters."]
    if len(mpn.encode("utf-8")) > 255:
        return ["MPN is too long for one Dropbox folder name."]
    return []


def get_task_size_options(profile: dict[str, Any]) -> list[str]:
    for dimension in profile.get("variant_dimensions", []):
        if str(dimension.get("name", "")).strip().lower() in {"size", "sizes"}:
            return list(dimension.get("options", []))
    return list(profile.get("sizes", []))


def build_staged_listing_task_payload(
    *,
    profile: dict[str, Any],
    mpn: Any,
    price: Any,
    quantity: Any,
    merchant_shipping_group_name: Any,
    selected_sizes: list[str],
    sku_decoration_code: str,
    manual_sku_listing_code: str,
    generated_sku_listing_code: str,
    sku_listing_code: str,
    base_parent_sku: str,
    parent_sku: str,
    assets_prepared_by: str = "",
) -> dict[str, Any]:
    errors = validate_mpn(mpn)
    available_sizes = get_task_size_options(profile)
    selected_sizes = list(selected_sizes or [])

    try:
        normalized_price = float(price)
    except (TypeError, ValueError):
        normalized_price = 0.0
    if not math.isfinite(normalized_price) or normalized_price <= 0:
        errors.append("Price must be greater than zero.")

    try:
        normalized_quantity = int(quantity)
    except (TypeError, ValueError):
        normalized_quantity = 0
    if isinstance(quantity, float) and not quantity.is_integer():
        normalized_quantity = 0
    if normalized_quantity <= 0:
        errors.append("Quantity must be greater than zero.")

    if not selected_sizes:
        errors.append("Select at least one size.")
    elif any(size not in available_sizes for size in selected_sizes):
        errors.append("Selected sizes must come from the selected garment template.")

    shipping_group = str(merchant_shipping_group_name or "").strip()
    if shipping_group not in MERCHANT_SHIPPING_GROUP_OPTIONS:
        errors.append("Merchant Shipping Group must use an existing allowed option.")

    if not str(sku_decoration_code or "").strip():
        errors.append("Decoration code is required.")
    if not str(sku_listing_code or "").strip():
        errors.append("A generated or manual listing/design code is required.")
    if not str(base_parent_sku or "").strip() or not str(parent_sku or "").strip():
        errors.append("The selected garment template cannot produce a parent SKU.")

    payload = {
        "mpn": mpn,
        "title": "",
        "bullet_points": [],
        "product_description": "",
        "generic_keywords": "",
        "selected_variants": {"size": list(selected_sizes)},
        "size_price_map": {size: normalized_price for size in selected_sizes},
        "price_input_mode": "",
        "use_same_price_for_all_sizes": True,
        "write_parent_starting_price": bool(profile.get("write_parent_starting_price", False)),
        "quantity": normalized_quantity,
        "handling_time_days": DEFAULT_HANDLING_TIME_DAYS,
        "merchant_shipping_group_name": shipping_group,
        "sku_decoration_code": str(sku_decoration_code or ""),
        "manual_sku_listing_code": str(manual_sku_listing_code or ""),
        "generated_sku_listing_code": str(generated_sku_listing_code or ""),
        "sku_listing_code": str(sku_listing_code or ""),
        "base_parent_sku": str(base_parent_sku or ""),
        "parent_sku": str(parent_sku or ""),
        "assets_prepared_by": str(assets_prepared_by or ""),
    }
    return {"valid": not errors, "errors": errors, "payload": payload}


def create_staged_listing_task(
    *,
    profile: dict[str, Any],
    payload: dict[str, Any],
    stage_root: str,
    destination_exists: Callable[[str], bool],
    create_folder: Callable[[str], None],
    save_listing_memory: Callable[[dict[str, Any], dict[str, Any], str], str],
) -> dict[str, Any]:
    mpn = payload.get("mpn")
    mpn_errors = validate_mpn(mpn)
    if mpn_errors:
        return {"status": "Failed", "error": mpn_errors[0], "folder_created": False}

    stage_root = str(stage_root or "").rstrip("/")
    if not stage_root:
        return {"status": "Failed", "error": "Dropbox stage_root is not configured.", "folder_created": False}

    folder_path = f"{stage_root}/{mpn}"
    try:
        if destination_exists(folder_path):
            return {
                "status": "Exists",
                "error": f"A staged task already exists for MPN {mpn}.",
                "folder_created": False,
                "folder_path": folder_path,
            }
    except Exception as exc:
        return {
            "status": "Failed",
            "error": f"Could not verify the staged task destination: {exc}",
            "folder_created": False,
            "folder_path": folder_path,
        }

    try:
        create_folder(folder_path)
    except FileExistsError:
        return {
            "status": "Exists",
            "error": f"A staged task already exists for MPN {mpn}.",
            "folder_created": False,
            "folder_path": folder_path,
        }
    except Exception as exc:
        return {
            "status": "Failed",
            "error": f"Could not create the staged task folder: {exc}",
            "folder_created": False,
            "folder_path": folder_path,
        }

    try:
        listing_memory_path = save_listing_memory(profile, payload, folder_path)
    except Exception as exc:
        return {
            "status": "Partial failure",
            "error": (
                f"The folder {folder_path} was created, but listing_inputs.json could not be written: {exc}. "
                "The folder was left in place for recovery."
            ),
            "folder_created": True,
            "folder_path": folder_path,
        }

    return {
        "status": "Success",
        "mpn": mpn,
        "folder_name": mpn,
        "folder_path": folder_path,
        "listing_memory_path": listing_memory_path,
        "folder_created": True,
    }
