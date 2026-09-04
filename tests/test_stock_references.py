from __future__ import annotations

import json
from pathlib import Path

from services.stock_references import (
    build_clear_child_sku,
    build_size_sku_part,
    lookup_mapping,
    resolve_sku_decoration_code,
    sanitize_sku_part,
    slugify_part,
)
from services.quality_checks import build_variant_combinations


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


def test_print_templates_default_to_def_while_explicit_print_remains_compatible() -> None:
    assert resolve_sku_decoration_code({"label": "Printed T-Shirt"}) == "DEF"
    assert resolve_sku_decoration_code({"sku_decoration_code": "PRINT"}) == "PRINT"


def test_new_def_and_legacy_print_parent_prefixes_remain_authoritative() -> None:
    profile = load_profile("templates/SHIRT/Generic Shirts/config.json")
    variant = {"design": "Adult T-Shirt", "color": "Red", "size": "M"}

    assert build_clear_child_sku(profile, "DEF-NEW", variant) == "DEF-NEW-RED-M"
    assert build_clear_child_sku(profile, "PRINT-OLD", variant) == "PRINT-OLD-RED-M"


def test_generic_shirts_config_contract() -> None:
    profile = load_profile("templates/SHIRT/Generic Shirts/config.json")

    assert profile["design_sku_map"]["Adult T-Shirt"] == "T01"
    assert profile["design_sku_map"]["Kids T-Shirt"] == "T02"
    assert profile["color_sku_map"]["Red"] == "RED"
    assert profile["size_code_map"]["2Yr"] == "2Y"
    assert profile["size_code_map"]["11Yr"] == "11Y"
    assert profile["saved_variant_value_aliases"]["size"]["1-2 Years"] == "2Yr"


def test_uc301_first_kids_size_is_exactly_two_years() -> None:
    profile = load_profile("templates/SHIRT/UC301/config.json")

    assert "2 Years" in profile["sizes"]
    assert "1-2 Years" not in profile["sizes"]
    assert profile["size_code_map"]["2 Years"] == "2Y"
    assert profile["saved_variant_value_aliases"]["size"]["1-2 Years"] == "2 Years"


def test_generic_shirts_kids_child_sku_order() -> None:
    profile = load_profile("templates/SHIRT/Generic Shirts/config.json")

    sku = build_clear_child_sku(
        profile,
        "PRINT-IMBSE",
        {
            "design": "Kids T-Shirt",
            "color": "Red",
            "size": "2Yr",
        },
    )

    assert sku == "PRINT-IMBSE-RED-2Y"


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

    assert sku == "PRINT-IMBSE-RED-M"


def test_generic_hoodies_config_and_child_sku_codes() -> None:
    profile = load_profile("templates/HOODIE/Generic Hoodies/config.json")

    assert profile["design_sku_map"] == {
        "Adult Hoodie": "H01",
        "Kids Hoodie": "H02",
    }
    assert profile["design_size_map"]["Adult Hoodie"] == [
        "XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL", "5XL", "6XL"
    ]
    assert profile["design_size_map"]["Kids Hoodie"] == [
        "2 YRS", "3/4 YRS", "5/6 YRS", "7/8 YRS", "9/10 YRS", "11/13 YRS"
    ]
    assert "Brown" in profile["design_color_map"]["Adult Hoodie"]
    assert "Brown" not in profile["design_color_map"]["Kids Hoodie"]

    adult_sku = build_clear_child_sku(
        profile,
        "PRINT-IMBSE",
        {"design": "Adult Hoodie", "color": "Red", "size": "M"},
    )
    kids_sku = build_clear_child_sku(
        profile,
        "PRINT-IMBSE",
        {"design": "Kids Hoodie", "color": "Red", "size": "3/4 YRS"},
    )

    assert adult_sku == "PRINT-IMBSE-RED-M"
    assert kids_sku == "PRINT-IMBSE-RED-3Y"

    combinations = build_variant_combinations(
        profile,
        {
            "design": ["Adult Hoodie", "Kids Hoodie"],
            "color": profile["colors"],
            "size": profile["sizes"],
        },
    )
    assert len(combinations) == (22 * 10) + (21 * 6)
    assert {
        "design": "Kids Hoodie",
        "color": "Brown",
        "size": "3/4 YRS",
    } not in combinations


def test_uc503_standalone_profile_contract() -> None:
    profile = load_profile("templates/HOODIE/UC503/config.json")

    assert profile["sizes"] == [
        "2 YRS", "3/4 YRS", "5/6 YRS", "7/8 YRS", "9/10 YRS", "11/13 YRS"
    ]
    assert "Brown" not in profile["colors"]
    assert profile["brand_name"] == "Generic"
    assert "stock_reference_key" not in profile
    assert len(profile["colors"]) * len(profile["sizes"]) == 126


def test_generic_sweatshirts_config_and_child_sku_codes() -> None:
    profile = load_profile("templates/HOODIE/Generic Sweatshirts/config.json")

    assert profile["design_sku_map"] == {
        "Adult Sweatshirt": "S01",
        "Kids Sweatshirt": "S02",
    }
    assert profile["design_size_map"]["Adult Sweatshirt"] == [
        "XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL", "5XL", "6XL"
    ]
    assert profile["design_size_map"]["Kids Sweatshirt"] == [
        "2 YRS", "3/4 YRS", "5/6 YRS", "7/8 YRS", "9/10 YRS", "11/13 YRS"
    ]
    assert "Brown" not in profile["design_color_map"]["Adult Sweatshirt"]
    assert "Brown" in profile["design_color_map"]["Kids Sweatshirt"]
    assert "Charcoal" in profile["design_color_map"]["Adult Sweatshirt"]
    assert "Charcoal" not in profile["design_color_map"]["Kids Sweatshirt"]

    adult_sku = build_clear_child_sku(
        profile,
        "PRINT-IMBSE",
        {"design": "Adult Sweatshirt", "color": "Red", "size": "M"},
    )
    kids_sku = build_clear_child_sku(
        profile,
        "PRINT-IMBSE",
        {"design": "Kids Sweatshirt", "color": "Red", "size": "3/4 YRS"},
    )

    assert adult_sku == "PRINT-IMBSE-RED-M"
    assert kids_sku == "PRINT-IMBSE-RED-3Y"

    combinations = build_variant_combinations(
        profile,
        {
            "design": ["Adult Sweatshirt", "Kids Sweatshirt"],
            "color": profile["colors"],
            "size": profile["sizes"],
        },
    )
    assert len(combinations) == (16 * 10) + (13 * 6)
    assert {
        "design": "Adult Sweatshirt",
        "color": "Brown",
        "size": "M",
    } not in combinations
    assert {
        "design": "Kids Sweatshirt",
        "color": "Charcoal",
        "size": "3/4 YRS",
    } not in combinations


def test_generic_split_profiles_remain_sku_unique_without_design_codes() -> None:
    for relative_path in [
        "templates/SHIRT/Generic Shirts/config.json",
        "templates/HOODIE/Generic Sweatshirts/config.json",
        "templates/HOODIE/Generic Hoodies/config.json",
    ]:
        profile = load_profile(relative_path)
        dimensions = {
            str(dimension["name"]): list(dimension.get("options", []))
            for dimension in profile["variant_dimensions"]
        }
        combinations = build_variant_combinations(profile, dimensions)
        child_skus = [
            build_clear_child_sku(profile, "PRINT-XMDARTN-TARGET", combination)
            for combination in combinations
        ]

        assert len(child_skus) == len(set(child_skus))


def test_generic_christmas_targets_use_first_year_kids_size_tokens() -> None:
    expected = {
        "2 YRS": "2Y",
        "3/4 YRS": "3Y",
        "5/6 YRS": "5Y",
        "7/8 YRS": "7Y",
        "9/10 YRS": "9Y",
        "11/13 YRS": "11Y",
    }
    for relative_path in [
        "templates/HOODIE/Generic Sweatshirts/config.json",
        "templates/HOODIE/Generic Hoodies/config.json",
    ]:
        profile = load_profile(relative_path)

        assert {
            size: profile["size_code_map"][size]
            for size in expected
        } == expected


def test_design_code_remains_default_for_profiles_without_omit_flag() -> None:
    profile = {
        "sku_decoration_code": "PRINT",
        "design_sku_map": {"Kids T-Shirt": "T02"},
        "color_sku_map": {"Black": "BLAC"},
        "size_code_map": {"3Yr": "3Y"},
    }

    assert build_clear_child_sku(
        profile,
        "PRINT-XMDARTN",
        {"design": "Kids T-Shirt", "color": "Black", "size": "3Yr"},
    ) == "PRINT-XMDARTN-T02-BLAC-3Y"


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
