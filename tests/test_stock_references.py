from __future__ import annotations

import json
from pathlib import Path

from services.stock_references import (
    build_clear_child_sku,
    build_size_sku_part,
    lookup_mapping,
    sanitize_sku_part,
    slugify_part,
)


ROOT = Path(__file__).resolve().parents[1]


def load_profile(relative_path: str) -> dict:
    path = ROOT / relative_path
    return json.loads(path.read_text(encoding="utf-8-sig"))


def test_sku_part_helpers() -> None:
    assert sanitize_sku_part(" PRINT / Red ") == "PRINT-Red"
    assert slugify_part("1 / 2 Years") == "1-2-Years"


def test_kids_size_tokens_are_shortened() -> None:
    expected = {
        "1-2 Years": "1Y",
        "3-4 Years": "3Y",
        "5-6 Years": "5Y",
        "7-8 Years": "7Y",
        "9-11 Years": "9Y",
        "12-13 Years": "12Y",
    }

    for size, token in expected.items():
        assert build_size_sku_part(size) == token


def test_mapping_lookup_is_case_insensitive() -> None:
    assert lookup_mapping({"Red": "RED"}, "red") == "RED"


def test_generic_shirts_config_contract() -> None:
    profile = load_profile("templates/SHIRT/Generic Shirts/config.json")

    assert profile["design_sku_map"]["Adult T-Shirt"] == "T01"
    assert profile["design_sku_map"]["Kids T-Shirt"] == "T02"
    assert profile["color_sku_map"]["Red"] == "RED"
    assert profile["size_code_map"]["1-2 Years"] == "1Y"
    assert profile["size_code_map"]["12-13 Years"] == "12Y"


def test_generic_shirts_kids_child_sku_order() -> None:
    profile = load_profile("templates/SHIRT/Generic Shirts/config.json")

    sku = build_clear_child_sku(
        profile,
        "PRINT-IMBSE",
        {
            "design": "Kids T-Shirt",
            "color": "Red",
            "size": "1-2 Years",
        },
    )

    assert sku == "PRINT-IMBSE-T02-RED-1Y"


def test_generic_shirts_adult_child_sku_order() -> None:
    profile = load_profile("templates/SHIRT/Generic Shirts/config.json")

    sku = build_clear_child_sku(
        profile,
        "PRINT-IMBSE",
        {
            "design": "Adult T-Shirt",
            "color": "Red",
            "size": "M",
        },
    )

    assert sku == "PRINT-IMBSE-T01-RED-M"


def test_uc301_red_child_sku_uses_red_token() -> None:
    profile = load_profile("templates/SHIRT/UC301/config.json")

    sku = build_clear_child_sku(
        profile,
        "PRINT-IMBSE-UC301",
        {
            "color": "Red",
            "size": "M",
        },
    )

    assert sku == "PRINT-IMBSE-UC301-RED-M"
    assert "REDD" not in sku


def test_classic_red_headwear_token_remains_redd() -> None:
    profile = load_profile("templates/HEADWEAR/BC045/config.json")

    assert profile["color_sku_map"]["Classic Red"] == "REDD"
