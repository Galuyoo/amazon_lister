from __future__ import annotations

import copy
import importlib
import json
import sys

import pytest

from services.listing_content_import import (
    parse_listing_content_json,
    validate_listing_content_payload,
)


def valid_payload() -> dict:
    return {
        "schema_version": 1,
        "title": "A practical product title",
        "bullet_points": [f"Useful product bullet {index}" for index in range(1, 6)],
        "product_description": "A useful product description.",
        "generic_keywords": "useful product search terms",
    }


def high_quality_payload() -> dict:
    payload = valid_payload()
    payload["title"] = "Premium practical listing title " + " ".join(f"detail{index}" for index in range(1, 16))
    payload["bullet_points"] = [
        f"Feature {index} provides practical, detailed customer information " + "with clear product benefits. " * 5
        for index in range(1, 6)
    ]
    payload["product_description"] = "Detailed product information for customers. " * 30
    payload["generic_keywords"] = " ".join(f"term{index}" for index in range(20))
    return payload


def errors_for(payload: object) -> list[str]:
    return validate_listing_content_payload(payload)["errors"]


def test_valid_json() -> None:
    result = parse_listing_content_json(json.dumps(valid_payload()))
    assert result["valid"] is True
    assert result["content"]["schema_version"] == 1


def test_valid_json_surrounded_by_one_markdown_json_code_fence() -> None:
    raw = f"```json\n{json.dumps(valid_payload())}\n```"
    assert parse_listing_content_json(raw)["valid"] is True


def test_empty_raw_input() -> None:
    assert parse_listing_content_json("  ")["errors"] == ["Raw input is empty."]


def test_malformed_json() -> None:
    result = parse_listing_content_json('{"schema_version": 1')
    assert result["valid"] is False
    assert "Malformed JSON" in result["errors"][0]


def test_root_array_instead_of_object() -> None:
    assert errors_for([]) == ["JSON root value must be an object."]


def test_missing_schema_version() -> None:
    payload = valid_payload()
    del payload["schema_version"]
    assert any("schema_version" in error for error in errors_for(payload))


def test_wrong_schema_version() -> None:
    payload = valid_payload()
    payload["schema_version"] = 2
    assert "schema_version must equal 1." in errors_for(payload)


def test_missing_required_field() -> None:
    payload = valid_payload()
    del payload["title"]
    assert "Missing required field: title." in errors_for(payload)


def test_unexpected_top_level_field() -> None:
    payload = valid_payload()
    payload["sku"] = "FORBIDDEN"
    assert "Unexpected top-level field: sku." in errors_for(payload)


@pytest.mark.parametrize("field_name", ["title", "product_description", "generic_keywords"])
def test_string_field_wrong_type(field_name: str) -> None:
    payload = valid_payload()
    payload[field_name] = 123
    assert f"{field_name} must be a string." in errors_for(payload)


def test_bullet_points_wrong_type() -> None:
    payload = valid_payload()
    payload["bullet_points"] = "not a list"
    assert "bullet_points must be a list." in errors_for(payload)


def test_not_exactly_five_bullets() -> None:
    payload = valid_payload()
    payload["bullet_points"] = payload["bullet_points"][:4]
    assert "bullet_points must contain exactly 5 items." in errors_for(payload)


def test_non_string_bullet() -> None:
    payload = valid_payload()
    payload["bullet_points"][2] = 3
    assert "bullet_points item 3 must be a string." in errors_for(payload)


def test_whitespace_normalization() -> None:
    payload = valid_payload()
    payload.update({"title": "  Title  ", "product_description": "  Description  ", "generic_keywords": "  terms  "})
    payload["bullet_points"] = [f"  Bullet {index}  " for index in range(1, 6)]
    content = validate_listing_content_payload(payload)["content"]
    assert content["title"] == "Title"
    assert content["bullet_points"] == [f"Bullet {index}" for index in range(1, 6)]
    assert content["product_description"] == "Description"
    assert content["generic_keywords"] == "terms"


@pytest.mark.parametrize(
    ("field_name", "expected"),
    [
        ("title", "title must not be empty"),
        ("product_description", "product_description must not be empty"),
        ("generic_keywords", "generic_keywords must not be empty"),
    ],
)
def test_empty_normalized_string_field(field_name: str, expected: str) -> None:
    payload = valid_payload()
    payload[field_name] = " \t "
    assert any(expected in error for error in errors_for(payload))


def test_empty_normalized_bullet() -> None:
    payload = valid_payload()
    payload["bullet_points"][3] = "  "
    assert any("bullet_points item 4 must not be empty" in error for error in errors_for(payload))


def test_input_object_is_not_mutated_during_normalization() -> None:
    payload = valid_payload()
    payload["title"] = "  Title  "
    original = copy.deepcopy(payload)
    validate_listing_content_payload(payload)
    assert payload == original


def test_repeated_title_word_rejection() -> None:
    payload = valid_payload()
    payload["title"] = "Shirt shirt comfortable shirt"
    assert any("at least 3 times" in error for error in errors_for(payload))


def test_forbidden_title_phrase_rejection() -> None:
    payload = valid_payload()
    payload["title"] = "A thoughtful Mother's Day Gift for family"
    assert any("forbidden Amazon phrase" in error for error in errors_for(payload))


def test_description_over_2000_characters_rejection() -> None:
    payload = valid_payload()
    payload["product_description"] = "x" * 2001
    assert any("2000 characters" in error for error in errors_for(payload))


def test_search_terms_over_249_utf8_bytes_rejection() -> None:
    payload = valid_payload()
    payload["generic_keywords"] = "x" * 250
    assert any("249 UTF-8 bytes" in error for error in errors_for(payload))


def test_utf8_byte_check_uses_bytes_instead_of_character_count() -> None:
    payload = valid_payload()
    payload["generic_keywords"] = "é" * 125
    assert len(payload["generic_keywords"]) == 125
    assert len(payload["generic_keywords"].encode("utf-8")) == 250
    assert any("249 UTF-8 bytes" in error for error in errors_for(payload))


def test_short_title_produces_warning_but_remains_otherwise_valid() -> None:
    payload = high_quality_payload()
    payload["title"] = "Short useful title"
    result = validate_listing_content_payload(payload)
    assert result["valid"] is True
    assert any("Title is below" in warning for warning in result["warnings"])


def test_short_bullet_produces_warning_but_remains_otherwise_valid() -> None:
    payload = high_quality_payload()
    payload["bullet_points"][0] = "Short useful bullet"
    result = validate_listing_content_payload(payload)
    assert result["valid"] is True
    assert any("Bullet 1 is below" in warning for warning in result["warnings"])


def test_short_description_produces_warning_but_remains_otherwise_valid() -> None:
    payload = high_quality_payload()
    payload["product_description"] = "Short useful description"
    result = validate_listing_content_payload(payload)
    assert result["valid"] is True
    assert any("Product description is below" in warning for warning in result["warnings"])


def test_low_search_term_usage_produces_warning_but_remains_otherwise_valid() -> None:
    payload = high_quality_payload()
    payload["generic_keywords"] = "light search terms"
    result = validate_listing_content_payload(payload)
    assert result["valid"] is True
    assert any("materially less" in warning for warning in result["warnings"])


def test_valid_high_quality_content_returns_no_errors_or_warnings() -> None:
    result = validate_listing_content_payload(high_quality_payload())
    assert result["valid"] is True
    assert result["errors"] == []
    assert result["warnings"] == []


def test_import_does_not_load_forbidden_dependencies() -> None:
    forbidden = ("streamlit", "dropbox", "app")
    for module_name in list(sys.modules):
        if module_name == "services.listing_content_import" or module_name.startswith(forbidden):
            del sys.modules[module_name]

    importlib.import_module("services.listing_content_import")

    assert not any(name == "app" or name.startswith("app.") for name in sys.modules)
    assert not any(name.startswith("streamlit") for name in sys.modules)
    assert not any("dropbox" in name.lower() for name in sys.modules)
