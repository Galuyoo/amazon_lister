from __future__ import annotations

import hashlib
import json
import string
from typing import Any, Iterable


CHRISTMAS_MEMBER_SUFFIXES = {
    "tshirt": "T",
    "sweatshirt": "S",
    "hoodie": "H",
}
SAFE_CODE_ALPHABET = string.ascii_uppercase + string.digits


def _clean_code(value: Any) -> str:
    return "".join(
        character
        for character in str(value or "").strip().upper()
        if character in SAFE_CODE_ALPHABET
    )


def _current_listing_code(memory: dict[str, Any]) -> str:
    identity_override = memory.get("identity_override")
    if isinstance(identity_override, dict):
        overridden = _clean_code(identity_override.get("new_listing_code"))
        if overridden:
            return overridden
    return _clean_code(
        memory.get("sku_listing_code")
        or memory.get("mpn")
        or memory.get("generated_sku_listing_code")
    )


def _candidate_code(task_id: str, old_code: str, attempt: int) -> str:
    digest = hashlib.shake_256(
        f"{task_id}|{old_code}|{attempt}".encode("utf-8")
    ).digest(len(old_code))
    return "".join(
        SAFE_CODE_ALPHABET[byte % len(SAFE_CODE_ALPHABET)]
        for byte in digest[:len(old_code)]
    )


def _replace_parent_listing_code(
    parent_sku: str,
    old_code: str,
    new_code: str,
    decoration_code: str,
    member_key: str,
) -> str:
    parent_parts = str(parent_sku or "").split("-")
    matching_indexes = [
        index
        for index, part in enumerate(parent_parts)
        if part.casefold() == old_code.casefold()
    ]
    if len(matching_indexes) == 1:
        parent_parts[matching_indexes[0]] = new_code
        return "-".join(parent_parts)

    suffix = CHRISTMAS_MEMBER_SUFFIXES[member_key]
    return "-".join(part for part in [decoration_code, new_code, suffix] if part)


def _assessment_fingerprint(items: list[dict[str, Any]]) -> str:
    identity_rows = [
        {
            "folder_name": str(item.get("folder_name", "") or ""),
            "task_id": str(item.get("task_id", "") or ""),
            "member_key": str(item.get("member_key", "") or ""),
            "listing_code": str(item.get("listing_code", "") or ""),
            "parent_sku": str(item.get("parent_sku", "") or ""),
        }
        for item in items
    ]
    encoded = json.dumps(identity_rows, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def assess_grouped_christmas_mpn_changes(
    selected_items: Iterable[dict[str, Any]],
    reserved_listing_codes: Iterable[str] = (),
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    normalized_items: list[dict[str, Any]] = []

    for item in selected_items:
        folder_name = str(item.get("folder_name", "") or "").strip()
        memory = item.get("listing_memory")
        memory = memory if isinstance(memory, dict) else {}
        source_group = memory.get("source_group")
        source_group = source_group if isinstance(source_group, dict) else {}
        if str(source_group.get("group_type", "") or "").strip().casefold() != "christmas_project":
            errors.append(f"{folder_name or 'Unknown folder'} is not a grouped Christmas listing.")
            continue

        task_id = str(source_group.get("task_id", "") or "").strip()
        member_key = str(source_group.get("member_key", "") or "").strip().casefold()
        listing_code = _current_listing_code(memory)
        if not task_id:
            errors.append(f"{folder_name or 'Unknown folder'} has no Christmas task ID.")
        if member_key not in CHRISTMAS_MEMBER_SUFFIXES:
            errors.append(f"{folder_name or 'Unknown folder'} has an invalid Christmas member.")
        if not listing_code:
            errors.append(f"{folder_name or 'Unknown folder'} has no usable MPN/design code.")
        normalized_items.append({
            "folder_name": folder_name,
            "task_id": task_id,
            "member_key": member_key,
            "listing_code": listing_code,
            "parent_sku": str(memory.get("parent_sku_override") or memory.get("parent_sku") or "").strip(),
            "sku_decoration_code": _clean_code(memory.get("sku_decoration_code")),
            "title": str(memory.get("title", "") or "").strip(),
            "template_key": str(memory.get("template_key", "") or "").strip(),
        })

    normalized_items.sort(key=lambda row: (row["task_id"], row["member_key"], row["folder_name"]))
    fingerprint = _assessment_fingerprint(normalized_items)
    if errors:
        return {
            "valid": False,
            "fingerprint": fingerprint,
            "changes": [],
            "errors": errors,
            "warnings": warnings,
        }

    tasks: dict[str, list[dict[str, Any]]] = {}
    for item in normalized_items:
        tasks.setdefault(item["task_id"], []).append(item)

    expected_members = set(CHRISTMAS_MEMBER_SUFFIXES)
    for task_id, task_items in tasks.items():
        members = [item["member_key"] for item in task_items]
        if len(members) != len(set(members)):
            errors.append(f"Christmas task {task_id} contains duplicate garment members.")
        if set(members) != expected_members:
            missing = sorted(expected_members - set(members))
            errors.append(
                f"Christmas task {task_id} must include T-Shirt, Sweatshirt, and Hoodie"
                + (f"; missing: {', '.join(missing)}." if missing else ".")
            )
        task_codes = {item["listing_code"] for item in task_items}
        if len(task_codes) != 1:
            errors.append(f"Christmas task {task_id} does not use one shared MPN/design code.")

    if errors:
        return {
            "valid": False,
            "fingerprint": fingerprint,
            "changes": [],
            "errors": errors,
            "warnings": warnings,
        }

    tasks_by_code: dict[str, list[str]] = {}
    for task_id, task_items in tasks.items():
        tasks_by_code.setdefault(task_items[0]["listing_code"], []).append(task_id)

    used_codes = {
        _clean_code(code)
        for code in reserved_listing_codes
        if _clean_code(code)
    }
    used_codes.update(tasks_by_code)
    changes: list[dict[str, Any]] = []

    for old_code, task_ids in sorted(tasks_by_code.items()):
        if len(task_ids) < 2:
            continue
        if len(old_code) < 2:
            errors.append(
                f"Duplicate code {old_code!r} is too short for a safe same-length automatic replacement."
            )
            continue

        keeper_task_id = sorted(task_ids)[0]
        warnings.append(f"Christmas task {keeper_task_id} keeps duplicate code {old_code}.")
        for task_id in sorted(task_ids)[1:]:
            new_code = ""
            for attempt in range(10000):
                candidate = _candidate_code(task_id, old_code, attempt)
                if candidate != old_code and candidate not in used_codes:
                    new_code = candidate
                    break
            if not new_code:
                errors.append(
                    f"Could not allocate a unique {len(old_code)}-character code for task {task_id}."
                )
                continue
            used_codes.add(new_code)

            for item in tasks[task_id]:
                new_parent_sku = _replace_parent_listing_code(
                    item["parent_sku"],
                    old_code,
                    new_code,
                    item["sku_decoration_code"],
                    item["member_key"],
                )
                changes.append({
                    **item,
                    "old_listing_code": old_code,
                    "new_listing_code": new_code,
                    "old_parent_sku": item["parent_sku"],
                    "new_parent_sku": new_parent_sku,
                    "code_length": len(old_code),
                })

    return {
        "valid": not errors,
        "fingerprint": fingerprint,
        "changes": changes,
        "errors": errors,
        "warnings": warnings,
    }
