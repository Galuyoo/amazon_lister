from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import PurePosixPath
from typing import Any

from services.christmas_project_grouping import (
    build_christmas_group_selected_variants,
    derive_christmas_group_members,
    partition_christmas_group_price_map,
)
from services.listing_content_import import validate_listing_content_payload
from services.listing_memory import MERCHANT_SHIPPING_GROUP_OPTIONS
from services.quality_checks import build_variant_combinations, find_oversized_child_titles
from services.staged_listing_tasks import validate_mpn


GROUP_SCHEMA_VERSION = 1
GROUP_TYPE = "christmas_project"
MEMBER_KEYS = ("tshirt", "sweatshirt", "hoodie")
GENERIC_TARGET_TEMPLATE_KEYS = {
    "tshirt": "GENERIC_SHIRTS",
    "sweatshirt": "GENERIC_SWEATSHIRTS",
    "hoodie": "GENERIC_HOODIES",
}
TSHIRT_KIDS_SIZE_MAP = {
    "2 YRS": "1Yr",
    "3/4 YRS": "3Yr",
    "5/6 YRS": "5Yr",
    "7/8 YRS": "7Yr",
    "9/10 YRS": "9Yr",
    "11/13 YRS": "11Yr",
}


def validate_christmas_group_submission(
    profile: dict[str, Any],
    source_memory: dict[str, Any],
    image_manifest: dict[str, Any],
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if str(profile.get("template_key", "") or "").strip().upper() != "CP":
        _add_error(errors, "profile.not_cp", "Grouped Christmas children must use the CP profile.")
    if str(source_memory.get("template_key", "") or "").strip().upper() != "CP":
        _add_error(errors, "source.not_cp", "Grouped Christmas source memory must use template_key CP.")

    try:
        members = derive_christmas_group_members(profile)
        expected_variants = build_christmas_group_selected_variants(profile)
    except ValueError as exc:
        _add_error(errors, "profile.invalid_grouping", str(exc))
        return _validation_result(errors, warnings)
    if set(members) != set(MEMBER_KEYS):
        _add_error(
            errors,
            "profile.member_keys",
            "CP grouped config must define exactly tshirt, sweatshirt, and hoodie.",
        )

    listing_group = source_memory.get("listing_group")
    if not isinstance(listing_group, dict):
        _add_error(errors, "group.missing", "listing_group must be an object.")
        return _validation_result(errors, warnings)

    if type(listing_group.get("schema_version")) is not int or listing_group.get("schema_version") != GROUP_SCHEMA_VERSION:
        _add_error(errors, "group.schema_version", "listing_group.schema_version must equal 1.")
    if listing_group.get("group_type") != GROUP_TYPE:
        _add_error(errors, "group.type", "listing_group.group_type must equal 'christmas_project'.")
    task_id = _text(listing_group.get("task_id"))
    if not task_id:
        _add_error(errors, "group.task_id", "listing_group.task_id is required.")

    grouped_members = listing_group.get("members")
    if not isinstance(grouped_members, dict):
        _add_error(errors, "group.members", "listing_group.members must be an object.")
        grouped_members = {}
    if set(grouped_members) != set(MEMBER_KEYS):
        _add_error(
            errors,
            "group.member_keys",
            "listing_group.members must contain exactly tshirt, sweatshirt, and hoodie.",
        )

    for member_key, definition in members.items():
        grouped_member = grouped_members.get(member_key)
        if not isinstance(grouped_member, dict):
            _add_error(errors, "member.missing", "Grouped member is missing.", member_key)
            continue
        if list(grouped_member.get("designs", [])) != list(definition["designs"]):
            _add_error(
                errors,
                "member.designs",
                f"Member designs must equal: {', '.join(definition['designs'])}.",
                member_key,
            )
        content = grouped_member.get("content")
        content_payload = {"schema_version": 1, **dict(content or {})} if isinstance(content, dict) else content
        content_result = validate_listing_content_payload(content_payload)
        for message in content_result.get("errors", []):
            _add_error(errors, "member.content", message, member_key)
        for message in content_result.get("warnings", []):
            _add_warning(warnings, "member.content", message, member_key)
        if content_result.get("valid"):
            oversized_titles = find_oversized_child_titles(
                profile,
                content_result["content"]["title"],
                _member_selected_variants(profile, definition),
            )
            if oversized_titles:
                longest_title, longest_length = max(
                    oversized_titles,
                    key=lambda item: item[1],
                )
                _add_error(
                    errors,
                    "member.child_title_length",
                    "Generated child titles must be 200 characters or fewer after garment, "
                    f"colour, and size prefixes. Longest is {longest_length}: {longest_title}",
                    member_key,
                )

    selected_variants = source_memory.get("selected_variants")
    if not isinstance(selected_variants, dict):
        _add_error(errors, "variants.missing", "selected_variants must be an object.")
    else:
        for dimension in ("design", "color", "size"):
            actual = list(selected_variants.get(dimension, []))
            expected = list(expected_variants.get(dimension, []))
            if len(actual) != len(set(actual)) or set(actual) != set(expected):
                _add_error(
                    errors,
                    f"variants.{dimension}",
                    f"Selected {dimension} values must match the configured grouped CP values.",
                )

    _validate_image_manifest(image_manifest, members, errors)
    _validate_prices(source_memory.get("size_price_map"), members, profile, errors)
    _validate_common_fields(profile, source_memory, members, errors)

    return _validation_result(errors, warnings)


def build_christmas_group_child_payload(
    profile: dict[str, Any],
    source_memory: dict[str, Any],
    image_manifest: dict[str, Any],
    member_key: str,
    target_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    members = derive_christmas_group_members(profile)
    if member_key not in members:
        raise ValueError(f"Unknown Christmas grouped member: {member_key}.")

    listing_group = source_memory["listing_group"]
    member = members[member_key]
    grouped_member = listing_group["members"][member_key]
    content = validate_listing_content_payload({
        "schema_version": 1,
        **dict(grouped_member["content"]),
    })["content"]
    materialization_profile = target_profile or profile
    selected_variants = _map_member_selected_variants(
        profile,
        member,
        member_key,
        materialization_profile,
    )
    price_map = partition_christmas_group_price_map(
        profile,
        source_memory.get("size_price_map", {}),
    )[member_key]
    price_map = _map_member_price_map(
        price_map,
        member_key,
        translate_tshirt_sizes=target_profile is not None,
    )
    child_identity = _build_child_identity(materialization_profile, source_memory, member)
    oversized_titles = find_oversized_child_titles(
        materialization_profile,
        content["title"],
        selected_variants,
    )
    if oversized_titles:
        longest_title, longest_length = max(oversized_titles, key=lambda item: item[1])
        raise ValueError(
            f"Christmas {member_key} target child title exceeds 200 characters "
            f"({longest_length}): {longest_title}"
        )
    member_manifest = image_manifest["members"][member_key]
    images_by_colour = {
        colour: member_manifest["images_by_colour"][colour]
        for colour in member["allowed_colours"]
    }

    child_payload = deepcopy(source_memory)
    child_payload.pop("listing_group", None)
    child_payload.pop("group_submission", None)
    child_payload.update({
        "template_label": materialization_profile.get(
            "label", materialization_profile.get("_slug", "")
        ),
        "template_slug": materialization_profile.get("_slug", ""),
        "template_key": materialization_profile.get("template_key", ""),
        "title": content["title"],
        "bullet_points": list(content["bullet_points"]),
        "product_description": content["product_description"],
        "generic_keywords": content["generic_keywords"],
        "selected_variants": selected_variants,
        "colors": list(selected_variants["color"]),
        "sizes": list(selected_variants["size"]),
        "size_price_map": price_map,
        **child_identity,
    })

    source_group = {
        "schema_version": GROUP_SCHEMA_VERSION,
        "group_type": GROUP_TYPE,
        "task_id": _text(listing_group.get("task_id")),
        "member_key": member_key,
        "source_mpn": _text(source_memory.get("mpn")),
        "source_listing_code": _text(source_memory.get("sku_listing_code")),
        "materialization_hash": "",
    }
    if target_profile is not None:
        child_payload["parent_sku_override"] = child_identity["parent_sku"]
    child_payload["source_group"] = source_group
    materialization_hash = compute_christmas_child_materialization_hash(
        child_payload,
        images_by_colour,
    )
    child_payload["source_group"]["materialization_hash"] = materialization_hash

    return {
        "member_key": member_key,
        "label": member["label"],
        "folder_suffix": member["folder_suffix"],
        "source_images_by_colour": images_by_colour,
        "source_image_files": list(images_by_colour.values()),
        "materialization_hash": materialization_hash,
        "payload": child_payload,
    }


def build_christmas_group_child_payloads(
    profile: dict[str, Any],
    source_memory: dict[str, Any],
    image_manifest: dict[str, Any],
) -> dict[str, Any]:
    preflight = validate_christmas_group_submission(profile, source_memory, image_manifest)
    if not preflight["valid"]:
        return {
            **preflight,
            "children": {},
        }

    target_profiles = _materialization_target_profiles(profile, source_memory)
    try:
        children = {
            member_key: build_christmas_group_child_payload(
                profile,
                source_memory,
                image_manifest,
                member_key,
                target_profiles.get(member_key) if target_profiles else None,
            )
            for member_key in MEMBER_KEYS
        }
    except ValueError as exc:
        return {
            "valid": False,
            "errors": [{"code": "target_profile.invalid", "message": str(exc)}],
            "warnings": list(preflight.get("warnings", [])),
            "children": {},
        }
    hashes = [child["materialization_hash"] for child in children.values()]
    if len(set(hashes)) != len(hashes):
        return {
            "valid": False,
            "errors": [{
                "code": "identity.hash_collision",
                "message": "Grouped child materialization identities are not unique.",
            }],
            "warnings": list(preflight["warnings"]),
            "children": {},
        }
    return {
        **preflight,
        "children": children,
    }


def compute_christmas_child_materialization_hash(
    child_payload: dict[str, Any],
    images_by_colour: dict[str, str],
) -> str:
    stable_material = build_christmas_child_materialization_projection(
        child_payload,
        images_by_colour,
    )
    serialized = json.dumps(
        stable_material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def build_christmas_child_materialization_projection(
    child_payload: dict[str, Any],
    images_by_colour: dict[str, str],
) -> dict[str, Any]:
    source_group = dict(child_payload.get("source_group", {}) or {})
    return {
        "template": {
            "template_label": _text(child_payload.get("template_label")),
            "template_key": _text(child_payload.get("template_key")),
            "template_slug": _text(child_payload.get("template_slug")),
        },
        "task_id": _text(source_group.get("task_id")),
        "member_key": _text(source_group.get("member_key")),
        "identity": {
            "mpn": _text(child_payload.get("mpn")),
            "sku_decoration_code": _text(child_payload.get("sku_decoration_code")),
            "manual_sku_listing_code": _text(child_payload.get("manual_sku_listing_code")),
            "generated_sku_listing_code": _text(child_payload.get("generated_sku_listing_code")),
            "sku_listing_code": _text(child_payload.get("sku_listing_code")),
            "base_parent_sku": _text(child_payload.get("base_parent_sku")),
            "parent_sku": _text(child_payload.get("parent_sku")),
            "original_finished_folder_name": _text(
                child_payload.get("original_finished_folder_name")
            ),
        },
        "selected_variants": deepcopy(child_payload.get("selected_variants", {})),
        "pricing": {
            "size_price_map": deepcopy(child_payload.get("size_price_map", {})),
            "price_input_mode": _text(child_payload.get("price_input_mode")),
            "use_same_price_for_all_sizes": bool(
                child_payload.get("use_same_price_for_all_sizes", False)
            ),
            "write_parent_starting_price": bool(
                child_payload.get("write_parent_starting_price", False)
            ),
        },
        "fulfillment": {
            "quantity": child_payload.get("quantity"),
            "handling_time_days": child_payload.get("handling_time_days"),
            "merchant_shipping_group_name": _text(
                child_payload.get("merchant_shipping_group_name")
            ),
        },
        "content": {
            "title": _text(child_payload.get("title")),
            "bullet_points": list(child_payload.get("bullet_points", []) or []),
            "product_description": _text(child_payload.get("product_description")),
            "generic_keywords": _text(child_payload.get("generic_keywords")),
        },
        "image_selection": {
            "parent_main_image_choice": _text(
                child_payload.get("parent_main_image_choice")
            ),
            "parent_main_image_url": _text(child_payload.get("parent_main_image_url")),
            "selected_parent_main_image_url": _text(
                child_payload.get("selected_parent_main_image_url")
            ),
        },
        "prepared_by": {
            "assets_prepared_by": _text(child_payload.get("assets_prepared_by")),
            "content_prepared_by": _text(child_payload.get("content_prepared_by")),
        },
        "image_filenames_by_colour": {
            colour: _filename(path)
            for colour, path in sorted(dict(images_by_colour or {}).items())
        },
    }


def _member_selected_variants(
    profile: dict[str, Any],
    member: dict[str, Any],
) -> dict[str, list[str]]:
    grouped_variants = build_christmas_group_selected_variants(profile)
    allowed_sizes = {
        size
        for sizes in member["sizes_by_design"].values()
        for size in sizes
    }
    return {
        "design": list(member["designs"]),
        "color": list(member["allowed_colours"]),
        "size": [size for size in grouped_variants["size"] if size in allowed_sizes],
    }


def _materialization_target_profiles(
    profile: dict[str, Any],
    source_memory: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    configured = profile.get("_group_target_profiles")
    if not isinstance(configured, dict):
        return {}
    ledger = source_memory.get("group_submission")
    if isinstance(ledger, dict) and ledger and ledger.get("materialization_mode") != "generic_profiles":
        return {}
    targets: dict[str, dict[str, Any]] = {}
    for member_key, expected_key in GENERIC_TARGET_TEMPLATE_KEYS.items():
        target = configured.get(member_key)
        if not isinstance(target, dict) or target.get("template_key") != expected_key:
            raise ValueError(
                f"Christmas {member_key} target profile must be {expected_key}."
            )
        targets[member_key] = target
    return targets


def _map_member_selected_variants(
    source_profile: dict[str, Any],
    member: dict[str, Any],
    member_key: str,
    target_profile: dict[str, Any],
) -> dict[str, list[str]]:
    selected = _member_selected_variants(source_profile, member)
    if member_key == "tshirt" and target_profile is not source_profile:
        selected["size"] = [TSHIRT_KIDS_SIZE_MAP.get(size, size) for size in selected["size"]]
    target_dimensions = {
        str(dimension.get("name", ""))
        for dimension in target_profile.get("variant_dimensions", [])
        if isinstance(dimension, dict)
    }
    if target_profile is not source_profile and target_dimensions != {"design", "color", "size"}:
        raise ValueError(f"Christmas {member_key} target variant dimensions are incompatible.")
    if target_profile is not source_profile:
        source_combinations = build_variant_combinations(
            source_profile,
            _member_selected_variants(source_profile, member),
        )
        expected = {
            (
                combination.get("design", ""),
                combination.get("color", ""),
                TSHIRT_KIDS_SIZE_MAP.get(combination.get("size", ""), combination.get("size", ""))
                if member_key == "tshirt"
                else combination.get("size", ""),
            )
            for combination in source_combinations
        }
        actual = {
            (
                combination.get("design", ""),
                combination.get("color", ""),
                combination.get("size", ""),
            )
            for combination in build_variant_combinations(target_profile, selected)
        }
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            details = []
            if missing:
                details.append(f"missing {len(missing)} combination(s)")
            if extra:
                details.append(f"unexpected {len(extra)} combination(s)")
            raise ValueError(
                f"Christmas {member_key} target profile does not exactly support the source variants: "
                + ", ".join(details)
                + "."
            )
    return selected


def _map_member_price_map(
    price_map: dict[str, Any],
    member_key: str,
    translate_tshirt_sizes: bool = True,
) -> dict[str, Any]:
    if member_key != "tshirt" or not translate_tshirt_sizes:
        return dict(price_map)
    translated: dict[str, Any] = {}
    for key, value in price_map.items():
        design, separator, size = str(key).partition("||")
        translated_size = TSHIRT_KIDS_SIZE_MAP.get(size, size)
        translated[f"{design}{separator}{translated_size}" if separator else design] = value
    return translated


def _build_child_identity(
    profile: dict[str, Any],
    source_memory: dict[str, Any],
    member: dict[str, Any],
) -> dict[str, str]:
    member_key = _text(member.get("key")).casefold()
    parent_suffix = {
        "tshirt": "T",
        "sweatshirt": "S",
        "hoodie": "H",
    }.get(member_key, "")
    if not parent_suffix:
        raise ValueError(f"Unsupported Christmas grouped member identity: {member_key}")

    source_listing_code = _sanitize_identity_part(
        source_memory.get("sku_listing_code")
    ).upper()
    decoration_code = _sanitize_identity_part(
        source_memory.get("sku_decoration_code")
    ).upper()

    parent_parts = [
        decoration_code,
        source_listing_code,
        parent_suffix,
    ]
    if bool(profile.get("include_template_code_in_parent_sku", True)):
        template_code = _sanitize_identity_part(
            profile.get("parent_sku")
            or profile.get("template_key")
            or profile.get("_slug")
            or "CP"
        ).upper()
        parent_parts.append(template_code)

    manual_code = _sanitize_identity_part(
        source_memory.get("manual_sku_listing_code")
    ).upper()
    generated_code = _sanitize_identity_part(
        source_memory.get("generated_sku_listing_code")
    ).upper()

    return {
        "manual_sku_listing_code": manual_code,
        "generated_sku_listing_code": generated_code,
        "sku_listing_code": source_listing_code,
        "base_parent_sku": _text(profile.get("parent_sku")),
        "parent_sku": "-".join(part for part in parent_parts if part),
    }


def _validate_image_manifest(
    image_manifest: Any,
    members: dict[str, dict[str, Any]],
    errors: list[dict[str, str]],
) -> None:
    if not isinstance(image_manifest, dict):
        _add_error(errors, "images.missing", "Grouped image manifest must be an object.")
        return
    if not image_manifest.get("valid"):
        _add_error(errors, "images.invalid", "Grouped image manifest is invalid.")
    if image_manifest.get("errors"):
        _add_error(errors, "images.reported_errors", "Grouped image manifest contains reported errors.")
    if not image_manifest.get("complete"):
        _add_error(errors, "images.incomplete", "Grouped image manifest is incomplete.")
    manifest_members = image_manifest.get("members")
    if not isinstance(manifest_members, dict):
        _add_error(errors, "images.members", "Grouped image manifest members are missing.")
        return
    for member_key, member in members.items():
        manifest_member = manifest_members.get(member_key)
        if not isinstance(manifest_member, dict):
            _add_error(errors, "images.member_missing", "Image manifest member is missing.", member_key)
            continue
        images_by_colour = manifest_member.get("images_by_colour")
        actual_colours = set(images_by_colour) if isinstance(images_by_colour, dict) else set()
        expected_colours = set(member["allowed_colours"])
        if actual_colours != expected_colours or any(
            not _text(path) for path in dict(images_by_colour or {}).values()
        ):
            _add_error(
                errors,
                "images.coverage",
                f"Image coverage must be {len(expected_colours)}/{len(expected_colours)} configured colours.",
                member_key,
            )


def _validate_prices(
    size_price_map: Any,
    members: dict[str, dict[str, Any]],
    profile: dict[str, Any],
    errors: list[dict[str, str]],
) -> None:
    if not isinstance(size_price_map, dict):
        _add_error(errors, "prices.missing", "size_price_map must be an object.")
        return
    partitioned = partition_christmas_group_price_map(profile, size_price_map)
    for member_key, member in members.items():
        member_prices = partitioned[member_key]
        for design in member["designs"]:
            for size in member["sizes_by_design"][design]:
                price_key = f"{design}||{size}"
                price = member_prices.get(price_key)
                if not _positive_finite_number(price):
                    _add_error(
                        errors,
                        "prices.required",
                        f"A positive exact price is required for {price_key}.",
                        member_key,
                    )


def _validate_common_fields(
    profile: dict[str, Any],
    source_memory: dict[str, Any],
    members: dict[str, dict[str, Any]],
    errors: list[dict[str, str]],
) -> None:
    for message in validate_mpn(source_memory.get("mpn")):
        _add_error(errors, "common.mpn", message)
    quantity = source_memory.get("quantity")
    if type(quantity) is not int or quantity <= 0:
        _add_error(errors, "common.quantity", "Quantity must be a positive integer.")
    shipping_group = _text(source_memory.get("merchant_shipping_group_name"))
    if shipping_group not in MERCHANT_SHIPPING_GROUP_OPTIONS:
        _add_error(errors, "common.shipping", "Merchant Shipping Group is not an allowed value.")
    if not _text(source_memory.get("sku_decoration_code")):
        _add_error(errors, "identity.decoration", "Decoration code is required.")
    if not _text(source_memory.get("sku_listing_code")):
        _add_error(errors, "identity.listing_code", "Listing/design code is required.")

    identities = [
        _build_child_identity(profile, source_memory, member)
        for member in members.values()
    ]
    listing_codes = [identity["sku_listing_code"] for identity in identities]
    parent_skus = [identity["parent_sku"] for identity in identities]
    if (
        any(not identity for identity in [*listing_codes, *parent_skus])
        or len(set(parent_skus)) != len(parent_skus)
    ):
        _add_error(
            errors,
            "identity.not_unique",
            "Three non-empty listing codes and three unique child parent SKUs are required.",
        )


def _validation_result(
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def _add_error(
    errors: list[dict[str, str]],
    code: str,
    message: str,
    member_key: str = "",
) -> None:
    error = {"code": code, "message": message}
    if member_key:
        error["member_key"] = member_key
    errors.append(error)


def _add_warning(
    warnings: list[dict[str, str]],
    code: str,
    message: str,
    member_key: str = "",
) -> None:
    warning = {"code": code, "message": message}
    if member_key:
        warning["member_key"] = member_key
    warnings.append(warning)


def _append_identity_suffix(value: Any, suffix: str) -> str:
    base = _sanitize_identity_part(value).upper()
    return f"{base}-{suffix}" if base else suffix


def _sanitize_identity_part(value: Any) -> str:
    safe = _text(value)
    for character in ['\\', '/', ':', '*', '?', '"', '<', '>', '|', ' ']:
        safe = safe.replace(character, "-")
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe.strip("-")


def _positive_finite_number(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _filename(path: Any) -> str:
    normalized = _text(path).replace("\\", "/")
    return PurePosixPath(normalized).name


def _text(value: Any) -> str:
    return str(value or "").strip()
