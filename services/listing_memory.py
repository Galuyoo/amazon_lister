from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_HANDLING_TIME_DAYS = 2
DEFAULT_VARIANT_QUANTITY = 100
MERCHANT_SHIPPING_GROUP_OPTIONS = [
    "",
    "Migrated TemplateDEFAULT",
    "Nationwide Prime",
    "INSTOCK Template",
    "Template",
]


def build_listing_memory_path(folder_path: str) -> str:
    return f"{folder_path.rstrip('/')}/listing_inputs.json"


def normalize_handling_time_days(value: Any, default: int = DEFAULT_HANDLING_TIME_DAYS) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    return max(0, normalized)


def normalize_variant_quantity(value: Any, default: int = DEFAULT_VARIANT_QUANTITY) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    return normalized if normalized > 0 else default


def normalize_merchant_shipping_group(value: Any) -> str:
    group = str(value or "").strip()
    return group if group in MERCHANT_SHIPPING_GROUP_OPTIONS else ""


def build_listing_memory_payload(profile: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    memory_payload = {
        "template_label": profile.get("label", profile.get("_slug", "")),
        "template_slug": profile.get("_slug", ""),
        "template_key": profile.get("template_key", ""),
        "title": payload.get("title", ""),
        "product_description": payload.get("product_description", ""),
        "generic_keywords": payload.get("generic_keywords", ""),
        "bullet_points": payload.get("bullet_points", []),
        "selected_variants": payload.get("selected_variants", {}),
        "size_price_map": payload.get("size_price_map", {}),
        "price_input_mode": payload.get("price_input_mode", ""),
        "use_same_price_for_all_sizes": payload.get("use_same_price_for_all_sizes", False),
        "write_parent_starting_price": payload.get("write_parent_starting_price", False),
        "sku_decoration_code": payload.get("sku_decoration_code", ""),
        "manual_sku_listing_code": payload.get("manual_sku_listing_code", ""),
        "generated_sku_listing_code": payload.get("generated_sku_listing_code", ""),
        "sku_listing_code": payload.get("sku_listing_code", ""),
        "base_parent_sku": payload.get("base_parent_sku", ""),
        "parent_sku": payload.get("parent_sku", ""),
        "quantity": normalize_variant_quantity(payload.get("quantity", DEFAULT_VARIANT_QUANTITY)),
        "handling_time_days": normalize_handling_time_days(payload.get("handling_time_days", DEFAULT_HANDLING_TIME_DAYS)),
        "merchant_shipping_group_name": normalize_merchant_shipping_group(payload.get("merchant_shipping_group_name", "")),
        "assets_prepared_by": payload.get("assets_prepared_by", ""),
        "content_prepared_by": payload.get("content_prepared_by", ""),
        "reviewed_by": payload.get("reviewed_by", ""),
        "prepared_at": payload.get("prepared_at", ""),
        "reviewed_at": payload.get("reviewed_at", ""),
        "parent_main_image_choice": payload.get("parent_main_image_choice", ""),
        "parent_main_image_url": payload.get("parent_main_image_url", ""),
    }

    if "mpn" in payload:
        memory_payload["mpn"] = payload.get("mpn")

    staged_folder_name = str(payload.get("staged_folder_name", "") or "").strip()
    if staged_folder_name:
        memory_payload["staged_folder_name"] = staged_folder_name

    if isinstance(payload.get("listing_group"), dict):
        memory_payload["listing_group"] = deepcopy(payload.get("listing_group", {}))

    if isinstance(payload.get("source_group"), dict):
        memory_payload["source_group"] = deepcopy(payload.get("source_group", {}))

    if isinstance(payload.get("group_submission"), dict):
        memory_payload["group_submission"] = deepcopy(payload.get("group_submission", {}))

    parent_sku_override = str(payload.get("parent_sku_override", "") or "").strip()
    if parent_sku_override:
        memory_payload["parent_sku_override"] = parent_sku_override

    original_finished_folder_name = str(payload.get("original_finished_folder_name", "")).strip()
    if original_finished_folder_name:
        memory_payload["original_finished_folder_name"] = original_finished_folder_name

    # Additive metadata for review/dashboard use. Old listing_inputs.json files remain valid.
    if isinstance(payload.get("review_snapshot"), dict):
        memory_payload["review_snapshot"] = dict(payload.get("review_snapshot", {}))

    if isinstance(payload.get("workflow_events"), list):
        memory_payload["workflow_events"] = list(payload.get("workflow_events", []))

    if isinstance(payload.get("sku_manifest"), dict):
        memory_payload["sku_manifest"] = dict(payload.get("sku_manifest", {}))

    if isinstance(payload.get("generated_outputs"), list):
        memory_payload["generated_outputs"] = list(payload.get("generated_outputs", []))

    if isinstance(payload.get("ignored_generations"), list):
        memory_payload["ignored_generations"] = list(payload.get("ignored_generations", []))

    for field_name in [
        "generation_status",
        "ignored_at",
        "ignored_by",
        "ignored_reason",
        "finished_folder_sku",
        "pending_finished_folder_path",
    ]:
        if payload.get(field_name) not in (None, "", [], {}):
            memory_payload[field_name] = payload.get(field_name, "")

    return memory_payload
