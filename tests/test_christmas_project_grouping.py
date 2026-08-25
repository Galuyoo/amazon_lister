from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

from services.christmas_project_grouping import (
    build_christmas_group_image_manifest,
    derive_christmas_group_members,
    parse_christmas_group_image_filename,
    validate_christmas_group_config,
)


ROOT = Path(__file__).parents[1]
CP_CONFIG_PATH = ROOT / "templates" / "Special Projects" / "CP" / "config.json"


def load_cp_profile() -> dict:
    return json.loads(CP_CONFIG_PATH.read_text(encoding="utf-8"))


def complete_image_paths() -> list[str]:
    return [
        *[f"/stage/T01 T02 {colour}.png" for colour in [
            "Black", "Navy", "Heather Grey", "Kelly Green", "Red", "Royal", "White"
        ]],
        *[f"/stage/S01 S02 {colour}.png" for colour in [
            "Black", "Navy", "Heather Grey", "Kelly Green", "Red", "Royal", "White"
        ]],
        "/stage/H01 H02 Black.png",
        "/stage/H01 H02 Navy.png",
    ]


def test_cp_grouped_config_exists_validates_and_has_exact_members() -> None:
    profile = load_cp_profile()

    assert validate_christmas_group_config(profile) == []
    assert [member["key"] for member in profile["grouped_listing"]["members"]] == [
        "tshirt", "sweatshirt", "hoodie"
    ]


def test_members_derive_codes_colours_and_sizes_from_existing_cp_maps() -> None:
    profile = load_cp_profile()
    members = derive_christmas_group_members(profile)

    assert list(members) == ["tshirt", "sweatshirt", "hoodie"]
    assert members["tshirt"]["garment_codes"] == ["T01", "T02"]
    assert members["sweatshirt"]["garment_codes"] == ["S01", "S02"]
    assert members["hoodie"]["garment_codes"] == ["H01", "H02"]
    assert members["tshirt"]["allowed_colours"] == profile["design_color_map"]["Adult T-Shirt"]
    assert members["sweatshirt"]["allowed_colours"] == profile["design_color_map"]["Adult Sweatshirt"]
    assert members["hoodie"]["allowed_colours"] == ["Black", "Navy"]
    assert members["tshirt"]["sizes_by_design"]["Adult T-Shirt"] == profile["design_size_map"]["Adult T-Shirt"]
    assert members["hoodie"]["sizes_by_design"]["Kids Hoodie"] == profile["design_size_map"]["Kids Hoodie"]


@pytest.mark.parametrize(
    ("filename", "member_key", "designs", "colour"),
    [
        ("T01 T02 Black.png", "tshirt", ["Adult T-Shirt", "Kids T-Shirt"], "Black"),
        ("T01 T02 Heather Grey.png", "tshirt", ["Adult T-Shirt", "Kids T-Shirt"], "Heather Grey"),
        ("S01 S02 Royal.png", "sweatshirt", ["Adult Sweatshirt", "Kids Sweatshirt"], "Royal"),
        ("H01 H02 Navy.png", "hoodie", ["Adult Hoodie", "Kids Hoodie"], "Navy"),
        (r"C:\stage\t01 t02 heather grey.JPEG", "tshirt", ["Adult T-Shirt", "Kids T-Shirt"], "Heather Grey"),
        ("/stage/h01 h02 BLACK.WEBP", "hoodie", ["Adult Hoodie", "Kids Hoodie"], "Black"),
    ],
)
def test_grouped_image_filename_parsing(
    filename: str,
    member_key: str,
    designs: list[str],
    colour: str,
) -> None:
    result = parse_christmas_group_image_filename(filename, load_cp_profile())

    assert result["valid"] is True
    assert result["ignored"] is False
    assert result["member_key"] == member_key
    assert result["designs"] == designs
    assert result["colour"] == colour


def test_manifest_ignores_non_images_and_unrelated_images() -> None:
    result = build_christmas_group_image_manifest(
        ["listing_inputs.json", "notes.txt", "main.png", "H01 H02 Black.png"],
        load_cp_profile(),
    )

    assert result["valid"] is True
    assert result["complete"] is False
    assert result["ignored_files"] == ["listing_inputs.json", "notes.txt", "main.png"]
    assert any("unrelated image" in warning for warning in result["warnings"])


@pytest.mark.parametrize(
    ("filename", "message"),
    [
        ("H01 H02 Red.png", "Unknown colour 'Red'"),
        ("T01 Black.png", "Incomplete or invalid garment-code sequence"),
        ("X01 X02 Black.png", "Unknown grouped garment-code prefix 'X01'"),
        ("H01 H02.png", "missing a colour"),
    ],
)
def test_invalid_grouped_image_names_are_reported(filename: str, message: str) -> None:
    result = parse_christmas_group_image_filename(filename, load_cp_profile())

    assert result["valid"] is False
    assert any(message in error for error in result["errors"])


def test_duplicate_member_colour_image_is_an_error_without_overwriting_first_path() -> None:
    result = build_christmas_group_image_manifest(
        ["/first/H01 H02 Black.png", "/second/H01 H02 black.JPG"],
        load_cp_profile(),
    )

    assert result["valid"] is False
    assert result["complete"] is False
    assert result["members"]["hoodie"]["images_by_colour"] == {
        "Black": "/first/H01 H02 Black.png"
    }
    assert any("Duplicate grouped image mapping for hoodie / Black" in error for error in result["errors"])


def test_complete_manifest_is_valid_and_complete() -> None:
    result = build_christmas_group_image_manifest(complete_image_paths(), load_cp_profile())

    assert result["valid"] is True
    assert result["complete"] is True
    assert result["errors"] == []
    assert all(not member["missing_colours"] for member in result["members"].values())
    assert result["members"]["hoodie"]["images_by_colour"] == {
        "Black": "/stage/H01 H02 Black.png",
        "Navy": "/stage/H01 H02 Navy.png",
    }


def test_missing_expected_coverage_is_valid_but_incomplete_and_reported_per_member() -> None:
    paths = complete_image_paths()
    paths.remove("/stage/H01 H02 Navy.png")
    paths.remove("/stage/S01 S02 White.png")

    result = build_christmas_group_image_manifest(paths, load_cp_profile())

    assert result["valid"] is True
    assert result["complete"] is False
    assert result["members"]["hoodie"]["missing_colours"] == ["Navy"]
    assert result["members"]["sweatshirt"]["missing_colours"] == ["White"]
    assert result["members"]["tshirt"]["missing_colours"] == []


def test_duplicate_grouped_config_ownership_is_rejected() -> None:
    profile = load_cp_profile()
    duplicate = copy.deepcopy(profile["grouped_listing"]["members"][0])
    duplicate["key"] = "SHIRT-TWO"
    duplicate["label"] = "Second Shirt"
    duplicate["folder_suffix"] = "TSHIRT-TWO"
    profile["grouped_listing"]["members"].append(duplicate)

    errors = validate_christmas_group_config(profile)

    assert any("owned by both" in error for error in errors)
    assert any("same garment-code sequence" in error for error in errors)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda profile: profile.update({"grouped_listing": []}),
        lambda profile: profile["grouped_listing"].update({"schema_version": 2}),
        lambda profile: profile["grouped_listing"].update({"group_type": "other"}),
        lambda profile: profile["grouped_listing"].update({"members": []}),
        lambda profile: profile["grouped_listing"]["members"][1].update({"key": "TSHIRT"}),
        lambda profile: profile["grouped_listing"]["members"][1].update({"folder_suffix": "tshirt"}),
        lambda profile: profile["design_sku_map"].update({"Adult Hoodie": "T01", "Kids Hoodie": "T02"}),
        lambda profile: profile["design_color_map"].update({"Adult Hoodie": ["Black", "black"]}),
        lambda profile: profile["design_size_map"].pop("Kids Hoodie"),
    ],
)
def test_malformed_or_ambiguous_grouped_config_is_rejected(mutator) -> None:
    profile = load_cp_profile()
    mutator(profile)

    assert validate_christmas_group_config(profile)
    with pytest.raises(ValueError, match="Invalid Christmas grouped listing config"):
        derive_christmas_group_members(profile)


def test_service_does_not_mutate_profile_or_file_collection() -> None:
    profile = load_cp_profile()
    original_profile = copy.deepcopy(profile)
    paths = complete_image_paths()
    original_paths = list(paths)

    derive_christmas_group_members(profile)
    build_christmas_group_image_manifest(paths, profile)

    assert profile == original_profile
    assert paths == original_paths


def test_pure_module_imports_no_ui_dropbox_workbook_or_network_dependency() -> None:
    sys.modules.pop("services.christmas_project_grouping", None)
    before = set(sys.modules)
    module = importlib.import_module("services.christmas_project_grouping")
    imported = set(sys.modules) - before

    assert module.__name__ == "services.christmas_project_grouping"
    assert not any(name.startswith("streamlit") for name in imported)
    assert not any("dropbox" in name.lower() for name in imported)
    assert not any(name.startswith("openpyxl") for name in imported)
    assert not any(name.startswith(("requests", "httpx", "urllib3")) for name in imported)
