from __future__ import annotations

import json
import re
from typing import Any

from services.quality_checks import (
    find_forbidden_title_phrases,
    words_repeated_at_least,
)


SCHEMA_VERSION = 1
TITLE_RECOMMENDED_CHARS = 150
BULLET_RECOMMENDED_CHARS = 150
DESCRIPTION_RECOMMENDED_CHARS = 1000
DESCRIPTION_MAX_CHARS = 2000
GENERIC_KEYWORDS_RECOMMENDED_BYTES = 120
GENERIC_KEYWORDS_MAX_BYTES = 249

REQUIRED_FIELDS = {
    "schema_version",
    "title",
    "bullet_points",
    "product_description",
    "generic_keywords",
}

_JSON_FENCE_PATTERN = re.compile(
    r"\A\s*```json\s*\r?\n(?P<json>.*?)\r?\n```\s*\Z",
    flags=re.IGNORECASE | re.DOTALL,
)


def parse_listing_content_json(raw_text: str) -> dict[str, Any]:
    """Parse and validate untrusted listing-content JSON text."""
    if not isinstance(raw_text, str) or not raw_text.strip():
        return _result(errors=["Raw input is empty."])

    text = raw_text.strip()
    fenced_match = _JSON_FENCE_PATTERN.fullmatch(text)
    if fenced_match:
        text = fenced_match.group("json").strip()

    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        return _result(errors=[f"Malformed JSON: {exc.msg if isinstance(exc, json.JSONDecodeError) else str(exc)}"])

    return validate_listing_content_payload(payload)


def validate_listing_content_payload(payload: Any) -> dict[str, Any]:
    """Validate a decoded JSON value without mutating it."""
    if not isinstance(payload, dict):
        return _result(errors=["JSON root value must be an object."])

    errors: list[str] = []
    warnings: list[str] = []

    unexpected_fields = sorted(set(payload) - REQUIRED_FIELDS)
    for field_name in unexpected_fields:
        errors.append(f"Unexpected top-level field: {field_name}.")

    missing_fields = sorted(REQUIRED_FIELDS - set(payload))
    for field_name in missing_fields:
        errors.append(f"Missing required field: {field_name}.")

    if "schema_version" in payload:
        schema_version = payload["schema_version"]
        if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
            errors.append(f"schema_version must equal {SCHEMA_VERSION}.")

    string_fields = ("title", "product_description", "generic_keywords")
    for field_name in string_fields:
        if field_name in payload and not isinstance(payload[field_name], str):
            errors.append(f"{field_name} must be a string.")

    bullets = payload.get("bullet_points")
    bullets_are_strings = False
    if "bullet_points" in payload:
        if not isinstance(bullets, list):
            errors.append("bullet_points must be a list.")
        else:
            if len(bullets) != 5:
                errors.append("bullet_points must contain exactly 5 items.")
            non_string_indexes = [index for index, bullet in enumerate(bullets, start=1) if not isinstance(bullet, str)]
            for index in non_string_indexes:
                errors.append(f"bullet_points item {index} must be a string.")
            bullets_are_strings = not non_string_indexes

    fields_have_valid_types = all(isinstance(payload.get(field_name), str) for field_name in string_fields)
    can_normalize = not missing_fields and fields_have_valid_types and isinstance(bullets, list) and bullets_are_strings
    if not can_normalize:
        return _result(errors=errors, warnings=warnings)

    normalized = {
        "schema_version": SCHEMA_VERSION,
        "title": payload["title"].strip(),
        "bullet_points": [bullet.strip() for bullet in bullets],
        "product_description": payload["product_description"].strip(),
        "generic_keywords": payload["generic_keywords"].strip(),
    }

    title = normalized["title"]
    normalized_bullets = normalized["bullet_points"]
    description = normalized["product_description"]
    keywords = normalized["generic_keywords"]

    if not title:
        errors.append("title must not be empty after trimming whitespace.")
    for index, bullet in enumerate(normalized_bullets, start=1):
        if not bullet:
            errors.append(f"bullet_points item {index} must not be empty after trimming whitespace.")
    if not description:
        errors.append("product_description must not be empty after trimming whitespace.")
    if not keywords:
        errors.append("generic_keywords must not be empty after trimming whitespace.")

    if title:
        repeated_words = words_repeated_at_least(title, 3)
        if repeated_words:
            errors.append("Title repeats the same word at least 3 times: " + ", ".join(repeated_words) + ".")
        forbidden_phrases = find_forbidden_title_phrases(title)
        if forbidden_phrases:
            errors.append("Title contains forbidden Amazon phrase(s): " + ", ".join(forbidden_phrases) + ".")
        if len(title) > 200:
            errors.append("title must not exceed 200 characters.")
        if len(title) < TITLE_RECOMMENDED_CHARS:
            warnings.append(f"Title is below the recommended {TITLE_RECOMMENDED_CHARS}-character target.")

    for index, bullet in enumerate(normalized_bullets, start=1):
        if bullet and len(bullet) < BULLET_RECOMMENDED_CHARS:
            warnings.append(f"Bullet {index} is below the recommended {BULLET_RECOMMENDED_CHARS}-character target.")

    if description:
        if len(description) > DESCRIPTION_MAX_CHARS:
            errors.append(f"product_description must not exceed {DESCRIPTION_MAX_CHARS} characters.")
        elif len(description) < DESCRIPTION_RECOMMENDED_CHARS:
            warnings.append(
                f"Product description is below the recommended {DESCRIPTION_RECOMMENDED_CHARS}-character target."
            )

    if keywords:
        keyword_bytes = len(keywords.encode("utf-8"))
        if keyword_bytes > GENERIC_KEYWORDS_MAX_BYTES:
            errors.append(f"generic_keywords must not exceed {GENERIC_KEYWORDS_MAX_BYTES} UTF-8 bytes.")
        elif keyword_bytes < GENERIC_KEYWORDS_RECOMMENDED_BYTES:
            warnings.append(
                "Generic keywords use materially less than the available "
                f"{GENERIC_KEYWORDS_MAX_BYTES}-byte budget."
            )

    return _result(content=normalized if not errors else {}, errors=errors, warnings=warnings)


def _result(
    *,
    content: dict[str, Any] | None = None,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    error_list = list(errors or [])
    return {
        "valid": not error_list,
        "content": dict(content or {}),
        "errors": error_list,
        "warnings": list(warnings or []),
    }
