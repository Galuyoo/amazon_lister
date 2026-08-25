from __future__ import annotations

import json
import re
from typing import Any

from services.listing_content_import import validate_listing_content_payload


SCHEMA_VERSION = 1
GROUP_TYPE = "christmas_project"
MEMBER_KEYS = ("tshirt", "sweatshirt", "hoodie")
REQUIRED_FIELDS = {"schema_version", "group_type", "members"}

_JSON_FENCE_PATTERN = re.compile(
    r"\A\s*```json\s*\r?\n(?P<json>.*?)\r?\n```\s*\Z",
    flags=re.IGNORECASE | re.DOTALL,
)


def parse_christmas_grouped_content_json(raw_text: str) -> dict[str, Any]:
    if not isinstance(raw_text, str) or not raw_text.strip():
        return _result(errors=["Raw input is empty."])

    text = raw_text.strip()
    fenced_match = _JSON_FENCE_PATTERN.fullmatch(text)
    if fenced_match:
        text = fenced_match.group("json").strip()

    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        message = exc.msg if isinstance(exc, json.JSONDecodeError) else str(exc)
        return _result(errors=[f"Malformed JSON: {message}"])

    return validate_christmas_grouped_content_payload(payload)


def validate_christmas_grouped_content_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _result(errors=["JSON root value must be an object."])

    errors: list[str] = []
    warnings: list[str] = []
    normalized_members: dict[str, dict[str, Any]] = {}

    for field_name in sorted(set(payload) - REQUIRED_FIELDS):
        errors.append(f"Unexpected top-level field: {field_name}.")
    for field_name in sorted(REQUIRED_FIELDS - set(payload)):
        errors.append(f"Missing required field: {field_name}.")

    if "schema_version" in payload:
        schema_version = payload["schema_version"]
        if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
            errors.append(f"schema_version must equal {SCHEMA_VERSION}.")
    if "group_type" in payload and payload["group_type"] != GROUP_TYPE:
        errors.append(f"group_type must equal '{GROUP_TYPE}'.")

    members = payload.get("members")
    if not isinstance(members, dict):
        if "members" in payload:
            errors.append("members must be an object.")
        return _result(members=normalized_members, errors=errors, warnings=warnings)

    member_keys = set(members)
    for member_key in sorted(member_keys - set(MEMBER_KEYS)):
        errors.append(f"Unknown member: {member_key}.")
    for member_key in MEMBER_KEYS:
        if member_key not in members:
            errors.append(f"Missing required member: {member_key}.")
            continue

        member_result = validate_listing_content_payload(members[member_key])
        errors.extend(f"{member_key}: {message}" for message in member_result["errors"])
        warnings.extend(f"{member_key}: {message}" for message in member_result["warnings"])
        if member_result["valid"]:
            normalized_members[member_key] = dict(member_result["content"])

    return _result(members=normalized_members, errors=errors, warnings=warnings)


def _result(
    *,
    members: dict[str, dict[str, Any]] | None = None,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    error_list = list(errors or [])
    return {
        "valid": not error_list,
        "members": dict(members or {}),
        "errors": error_list,
        "warnings": list(warnings or []),
    }
