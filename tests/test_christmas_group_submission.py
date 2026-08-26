from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

from services.christmas_group_submission import (
    build_christmas_group_child_payloads,
    compute_christmas_child_materialization_hash,
    validate_christmas_group_submission,
)
from services.christmas_grouped_content_import import parse_christmas_grouped_content_json
from services.christmas_project_grouping import (
    build_christmas_group_image_manifest,
    derive_christmas_group_members,
    is_grouped_christmas_memory,
    normalize_christmas_grouped_draft,
)
from services.listing_memory import build_listing_memory_payload
from services.staged_listing_tasks import build_grouped_christmas_staged_task_payload


ROOT = Path(__file__).parents[1]
CP_CONFIG_PATH = ROOT / "templates" / "Special Projects" / "CP" / "config.json"
SAMPLE_CONTENT_PATH = ROOT / "samples" / "christmas_grouped_listing_content_test.json"


def load_cp_profile() -> dict:
    profile = json.loads(CP_CONFIG_PATH.read_text(encoding="utf-8"))
    profile.update({"_slug": "CP", "_family_slug": "Special Projects"})
    return profile


def complete_image_paths() -> list[str]:
    common_colours = ["Black", "Navy", "Heather Grey", "Kelly Green", "Red", "Royal", "White"]
    return [
        *[f"/stage/T01 T02 {colour}.png" for colour in common_colours],
        *[f"/stage/S01 S02 {colour}.png" for colour in common_colours],
        "/stage/H01 H02 Black.png",
        "/stage/H01 H02 Navy.png",
    ]


def build_complete_source() -> tuple[dict, dict, dict]:
    profile = load_cp_profile()
    task_result = build_grouped_christmas_staged_task_payload(
        profile=profile,
        mpn="CHRTST",
        quantity=100,
        merchant_shipping_group_name="",
        sku_decoration_code="DTG",
        manual_sku_listing_code="",
        generated_sku_listing_code="D12345",
        sku_listing_code="D12345",
        base_parent_sku="CP",
        parent_sku="DTG-D12345",
        assets_prepared_by="Sal",
        task_id="task-chrtst-1",
    )
    assert task_result["valid"] is True
    source = task_result["payload"]
    content_result = parse_christmas_grouped_content_json(
        SAMPLE_CONTENT_PATH.read_text(encoding="utf-8")
    )
    assert content_result["valid"] is True
    source = normalize_christmas_grouped_draft(profile, source, content_result["members"])

    prices = {}
    for member in derive_christmas_group_members(profile).values():
        for design in member["designs"]:
            for size in member["sizes_by_design"][design]:
                prices[f"{design}||{size}"] = 10.0 + len(prices)
    source["size_price_map"] = prices
    source.update({
        "content_prepared_by": "Sal",
        "workflow_events": [{"action": "draft_saved"}],
        "review_snapshot": {"status": "draft"},
        "write_parent_starting_price": True,
    })
    source = build_listing_memory_payload(profile, source)
    manifest = build_christmas_group_image_manifest(complete_image_paths(), profile)
    assert manifest["valid"] is True and manifest["complete"] is True
    return profile, source, manifest


def error_codes(result: dict) -> set[str]:
    return {error["code"] for error in result["errors"]}


def test_complete_group_produces_exactly_three_ordinary_cp_children_without_mutation() -> None:
    profile, source, manifest = build_complete_source()
    original_profile = copy.deepcopy(profile)
    original_source = copy.deepcopy(source)
    original_manifest = copy.deepcopy(manifest)

    result = build_christmas_group_child_payloads(profile, source, manifest)

    assert result["valid"] is True
    assert list(result["children"]) == ["tshirt", "sweatshirt", "hoodie"]
    assert profile == original_profile
    assert source == original_source
    assert manifest == original_manifest
    for child in result["children"].values():
        payload = child["payload"]
        assert payload["template_key"] == "CP"
        assert payload["template_slug"] == "CP"
        assert "listing_group" not in payload
        assert is_grouped_christmas_memory(payload) is False


def test_child_variants_codes_colours_and_sizes_derive_from_cp_profile() -> None:
    profile, source, manifest = build_complete_source()
    children = build_christmas_group_child_payloads(profile, source, manifest)["children"]
    members = derive_christmas_group_members(profile)

    expected_codes = {
        "tshirt": ["T01", "T02"],
        "sweatshirt": ["S01", "S02"],
        "hoodie": ["H01", "H02"],
    }
    for member_key, child in children.items():
        variants = child["payload"]["selected_variants"]
        assert [profile["design_sku_map"][design] for design in variants["design"]] == expected_codes[member_key]
        assert variants["color"] == members[member_key]["allowed_colours"]
        for design in variants["design"]:
            assert set(members[member_key]["sizes_by_design"][design]).issubset(variants["size"])

    assert len(children["tshirt"]["payload"]["selected_variants"]["color"]) == 7
    assert len(children["sweatshirt"]["payload"]["selected_variants"]["color"]) == 7
    assert children["hoodie"]["payload"]["selected_variants"]["color"] == ["Black", "Navy"]


def test_member_content_is_promoted_only_to_its_matching_child() -> None:
    profile, source, manifest = build_complete_source()
    children = build_christmas_group_child_payloads(profile, source, manifest)["children"]

    for member_key, child in children.items():
        expected = source["listing_group"]["members"][member_key]["content"]
        payload = child["payload"]
        assert payload["title"] == expected["title"]
        assert payload["bullet_points"] == expected["bullet_points"]
        assert payload["product_description"] == expected["product_description"]
        assert payload["generic_keywords"] == expected["generic_keywords"]
    assert children["tshirt"]["payload"]["title"] != children["hoodie"]["payload"]["title"]


def test_exact_prices_partition_without_colour_keys_and_pricing_modes_are_preserved() -> None:
    profile, source, manifest = build_complete_source()
    children = build_christmas_group_child_payloads(profile, source, manifest)["children"]

    for member_key, child in children.items():
        payload = child["payload"]
        expected_designs = set(payload["selected_variants"]["design"])
        assert payload["size_price_map"]
        assert all(key.count("||") == 1 for key in payload["size_price_map"])
        assert all(key.split("||", 1)[0] in expected_designs for key in payload["size_price_map"])
        assert payload["price_input_mode"] == source["price_input_mode"]
        assert payload["use_same_price_for_all_sizes"] is source["use_same_price_for_all_sizes"]
        assert payload["write_parent_starting_price"] is True


def test_common_fields_workflow_metadata_and_internal_mpn_are_preserved() -> None:
    profile, source, manifest = build_complete_source()
    children = build_christmas_group_child_payloads(profile, source, manifest)["children"]

    for child in children.values():
        payload = child["payload"]
        assert payload["mpn"] == "CHRTST"
        assert payload["quantity"] == 100
        assert payload["merchant_shipping_group_name"] == ""
        assert payload["assets_prepared_by"] == "Sal"
        assert payload["workflow_events"] == [{"action": "draft_saved"}]
        assert payload["review_snapshot"] == {"status": "draft"}


def test_child_identity_and_source_group_provenance_are_unique_and_stable() -> None:
    profile, source, manifest = build_complete_source()
    first = build_christmas_group_child_payloads(profile, source, manifest)["children"]
    second = build_christmas_group_child_payloads(profile, source, manifest)["children"]

    assert [first[key]["payload"]["sku_listing_code"] for key in first] == [
        "D12345-TSHIRT",
        "D12345-SWEATSHIRT",
        "D12345-HOODIE",
    ]
    assert [first[key]["payload"]["parent_sku"] for key in first] == [
        "DTG-D12345-TSHIRT",
        "DTG-D12345-SWEATSHIRT",
        "DTG-D12345-HOODIE",
    ]
    for member_key, child in first.items():
        provenance = child["payload"]["source_group"]
        assert provenance == {
            "schema_version": 1,
            "group_type": "christmas_project",
            "task_id": "task-chrtst-1",
            "member_key": member_key,
            "source_mpn": "CHRTST",
            "materialization_hash": child["materialization_hash"],
        }
        assert child["materialization_hash"] == second[member_key]["materialization_hash"]


def test_existing_memory_serializer_preserves_source_group_additively() -> None:
    profile, source, manifest = build_complete_source()
    payload = build_christmas_group_child_payloads(profile, source, manifest)["children"]["tshirt"]["payload"]

    memory = build_listing_memory_payload(profile, payload)

    assert memory["source_group"] == payload["source_group"]
    assert memory["source_group"] is not payload["source_group"]
    ordinary_payload = {key: value for key, value in payload.items() if key != "source_group"}
    assert "source_group" not in build_listing_memory_payload(profile, ordinary_payload)


def test_image_files_partition_7_7_2_without_duplication_per_design() -> None:
    profile, source, manifest = build_complete_source()
    children = build_christmas_group_child_payloads(profile, source, manifest)["children"]

    assert len(children["tshirt"]["source_image_files"]) == 7
    assert len(children["sweatshirt"]["source_image_files"]) == 7
    assert children["hoodie"]["source_images_by_colour"] == {
        "Black": "/stage/H01 H02 Black.png",
        "Navy": "/stage/H01 H02 Navy.png",
    }
    assert len(children["hoodie"]["source_image_files"]) == 2


def test_meaningful_content_and_price_changes_change_materialization_hash() -> None:
    profile, source, manifest = build_complete_source()
    child = build_christmas_group_child_payloads(profile, source, manifest)["children"]["hoodie"]
    payload = copy.deepcopy(child["payload"])
    images = child["source_images_by_colour"]
    original_hash = child["materialization_hash"]

    payload["title"] += " changed"
    assert compute_christmas_child_materialization_hash(payload, images) != original_hash
    payload = copy.deepcopy(child["payload"])
    first_price_key = next(iter(payload["size_price_map"]))
    payload["size_price_map"][first_price_key] += 1
    assert compute_christmas_child_materialization_hash(payload, images) != original_hash


def test_incomplete_or_invalid_images_block_preflight_without_children() -> None:
    profile, source, _manifest = build_complete_source()
    incomplete = build_christmas_group_image_manifest(complete_image_paths()[:-1], profile)

    result = build_christmas_group_child_payloads(profile, source, incomplete)

    assert result["valid"] is False
    assert result["children"] == {}
    assert {"images.incomplete", "images.coverage"}.issubset(error_codes(result))


def test_missing_member_content_and_required_price_block_preflight() -> None:
    profile, source, manifest = build_complete_source()
    source["listing_group"]["members"]["tshirt"]["content"]["title"] = ""
    source["size_price_map"].pop("Adult Hoodie||M")

    result = validate_christmas_group_submission(profile, source, manifest)

    assert result["valid"] is False
    assert {"member.content", "prices.required"}.issubset(error_codes(result))
    assert any(error.get("member_key") == "tshirt" for error in result["errors"])
    assert any("Adult Hoodie||M" in error["message"] for error in result["errors"])


def test_invalid_profile_variants_common_fields_and_identity_are_structured_errors() -> None:
    profile, source, manifest = build_complete_source()
    profile["template_key"] = "GENERIC_SHIRTS"
    source["template_key"] = "GENERIC_SHIRTS"
    source["selected_variants"]["color"].remove("White")
    source["quantity"] = 0
    source["merchant_shipping_group_name"] = "Unknown"
    source["sku_listing_code"] = ""

    result = validate_christmas_group_submission(profile, source, manifest)

    assert {
        "profile.not_cp",
        "source.not_cp",
        "variants.color",
        "common.quantity",
        "common.shipping",
        "identity.listing_code",
    }.issubset(error_codes(result))


def test_grouped_config_must_define_exactly_the_three_supported_members() -> None:
    profile, source, manifest = build_complete_source()
    profile["grouped_listing"]["members"] = profile["grouped_listing"]["members"][:-1]

    result = validate_christmas_group_submission(profile, source, manifest)

    assert result["valid"] is False
    assert "profile.member_keys" in error_codes(result)


def test_legacy_ordinary_listing_and_existing_grouped_source_remain_unchanged() -> None:
    profile, source, manifest = build_complete_source()
    ordinary = {"template_key": "CP", "title": "Legacy listing"}
    original_ordinary = copy.deepcopy(ordinary)
    original_source = copy.deepcopy(source)

    ordinary_result = build_christmas_group_child_payloads(profile, ordinary, manifest)
    grouped_result = build_christmas_group_child_payloads(profile, source, manifest)

    assert ordinary_result["valid"] is False
    assert ordinary == original_ordinary
    assert grouped_result["valid"] is True
    assert source == original_source


def test_submission_service_imports_no_streamlit_dropbox_openpyxl_or_network_clients() -> None:
    sys.modules.pop("services.christmas_group_submission", None)
    before = set(sys.modules)
    module = importlib.import_module("services.christmas_group_submission")
    imported = set(sys.modules) - before

    assert module.__name__ == "services.christmas_group_submission"
    assert not any(name.startswith("streamlit") for name in imported)
    assert not any("dropbox" in name.casefold() for name in imported)
    assert not any(name.startswith("openpyxl") for name in imported)
    assert not any(name.startswith(("requests", "httpx", "urllib3")) for name in imported)
