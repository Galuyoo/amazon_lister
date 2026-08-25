from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

from services.christmas_project_grouping import (
    build_christmas_group_selected_variants,
    initialize_christmas_listing_group,
    is_grouped_christmas_memory,
    normalize_christmas_grouped_draft,
    partition_christmas_group_price_map,
    validate_christmas_group_member_content,
)
from services.listing_memory import build_listing_memory_payload
from services.quality_checks import get_variant_price_from_map
from services.staged_listing_tasks import build_grouped_christmas_staged_task_payload
from ui.listing_content import (
    GROUPED_EDITOR_CONTEXT_KEY,
    GROUPED_PRICING_CONTEXT_KEY,
    get_grouped_christmas_content_widget_keys,
    initialize_grouped_christmas_editor_state,
)


ROOT = Path(__file__).parents[1]
CP_CONFIG_PATH = ROOT / "templates" / "Special Projects" / "CP" / "config.json"


def load_cp_profile() -> dict:
    profile = json.loads(CP_CONFIG_PATH.read_text(encoding="utf-8"))
    profile.update({
        "_slug": "CP",
        "_family_slug": "Special Projects",
    })
    return profile


def build_grouped_payload(task_id: str = "task-123") -> dict:
    result = build_grouped_christmas_staged_task_payload(
        profile=load_cp_profile(),
        mpn="CHRISTMAS-001",
        quantity=100,
        merchant_shipping_group_name="",
        sku_decoration_code="DTG",
        manual_sku_listing_code="",
        generated_sku_listing_code="D12345",
        sku_listing_code="D12345",
        base_parent_sku="CP",
        parent_sku="DTG-D12345-CP",
        assets_prepared_by="Sal",
        task_id=task_id,
    )
    assert result["valid"] is True
    return result["payload"]


def test_old_cp_memory_remains_non_grouped() -> None:
    memory = {
        "template_key": "CP",
        "selected_variants": {"design": ["Adult T-Shirt"], "size": ["M"]},
        "size_price_map": {"Adult T-Shirt||M": 12.99},
    }

    assert is_grouped_christmas_memory(memory) is False


def test_grouped_task_has_stable_identity_three_members_and_six_designs() -> None:
    profile = load_cp_profile()
    payload = build_grouped_payload()
    group = payload["listing_group"]

    assert is_grouped_christmas_memory(payload) is True
    assert group["task_id"] == "task-123"
    assert list(group["members"]) == ["tshirt", "sweatshirt", "hoodie"]
    assert payload["selected_variants"]["design"] == [
        "Adult T-Shirt",
        "Kids T-Shirt",
        "Adult Sweatshirt",
        "Kids Sweatshirt",
        "Adult Hoodie",
        "Kids Hoodie",
    ]
    assert payload["selected_variants"] == build_christmas_group_selected_variants(profile)

    normalized_again = normalize_christmas_grouped_draft(profile, payload, {})
    assert normalized_again["listing_group"]["task_id"] == "task-123"


def test_group_memory_derives_config_maps_instead_of_duplicating_them() -> None:
    group = build_grouped_payload()["listing_group"]

    for member in group["members"].values():
        assert set(member) == {"designs", "content"}
        assert "garment_codes" not in member
        assert "allowed_colours" not in member
        assert "sizes_by_design" not in member
        assert "size_price_map" not in member


def test_grouped_task_defaults_only_its_pricing_mode_to_clusters() -> None:
    payload = build_grouped_payload()

    assert payload["price_input_mode"] == "Use one price per cluster"
    assert payload["use_same_price_for_all_sizes"] is False
    assert payload["size_price_map"] == {}


def test_exact_price_map_partitions_by_member_and_never_by_colour() -> None:
    prices = {
        "Adult T-Shirt||M": 12.0,
        "Kids T-Shirt||5/6 YRS": 9.0,
        "Adult Sweatshirt||M": 18.0,
        "Kids Sweatshirt||5/6 YRS": 14.0,
        "Adult Hoodie||M": 22.0,
        "Kids Hoodie||5/6 YRS": 17.0,
        "adult hoodie||xl": 23.0,
        "Adult Hoodie||M||Black": 999.0,
    }

    partitioned = partition_christmas_group_price_map(load_cp_profile(), prices)

    assert partitioned == {
        "tshirt": {
            "Adult T-Shirt||M": 12.0,
            "Kids T-Shirt||5/6 YRS": 9.0,
        },
        "sweatshirt": {
            "Adult Sweatshirt||M": 18.0,
            "Kids Sweatshirt||5/6 YRS": 14.0,
        },
        "hoodie": {
            "Adult Hoodie||M": 22.0,
            "Adult Hoodie||XL": 23.0,
            "Kids Hoodie||5/6 YRS": 17.0,
        },
    }
    assert get_variant_price_from_map(prices, {"design": "Adult Hoodie", "size": "M", "color": "Navy"}) == 22.0


def test_saved_member_content_and_pricing_mode_replace_stale_grouped_state() -> None:
    profile = load_cp_profile()
    memory = build_grouped_payload()
    memory["price_input_mode"] = "Manual price by garment/size"
    memory["size_price_map"] = {"Adult Hoodie||M": 31.5}
    memory["listing_group"]["members"]["hoodie"]["content"] = {
        "title": "Saved hoodie title",
        "bullet_points": ["One", "Two", "Three", "Four", "Five"],
        "product_description": "Saved description",
        "generic_keywords": "saved keywords",
    }
    hoodie_keys = get_grouped_christmas_content_widget_keys("hoodie")
    state = {
        hoodie_keys["title"]: "Stale title",
        "design_size_pricing_mode": "Use one price for all",
        "price_Adult-Hoodie-M": 1.0,
        "cluster_price_Adult-Hoodie_Adult-XS-2XL": 2.0,
    }

    initialize_grouped_christmas_editor_state(
        profile=profile,
        listing_memory=memory,
        session_state=state,
    )

    assert state[hoodie_keys["title"]] == "Saved hoodie title"
    assert [state[key] for key in hoodie_keys["bullets"]] == ["One", "Two", "Three", "Four", "Five"]
    assert state["design_size_pricing_mode"] == "Manual price by garment/size"
    assert "price_Adult-Hoodie-M" not in state
    assert "cluster_price_Adult-Hoodie_Adult-XS-2XL" not in state
    assert state[GROUPED_EDITOR_CONTEXT_KEY]
    assert state[GROUPED_PRICING_CONTEXT_KEY]


def test_member_content_is_independent_and_normalization_does_not_mutate_inputs() -> None:
    profile = load_cp_profile()
    payload = build_grouped_payload()
    original = copy.deepcopy(payload)
    contents = {
        "tshirt": {
            "title": "T-Shirt title",
            "bullet_points": ["T1", "T2", "T3", "T4", "T5"],
            "product_description": "T-Shirt description",
            "generic_keywords": "tshirt words",
        },
        "hoodie": {
            "title": "Hoodie title",
            "bullet_points": ["H1", "H2", "H3", "H4", "H5"],
            "product_description": "Hoodie description",
            "generic_keywords": "hoodie words",
        },
    }

    normalized = normalize_christmas_grouped_draft(profile, payload, contents)

    assert payload == original
    assert normalized["listing_group"]["members"]["tshirt"]["content"]["title"] == "T-Shirt title"
    assert normalized["listing_group"]["members"]["hoodie"]["content"]["title"] == "Hoodie title"
    assert normalized["listing_group"]["members"]["sweatshirt"]["content"]["title"] == ""
    assert validate_christmas_group_member_content(contents["tshirt"]) == []


def test_listing_memory_preserves_group_and_existing_metadata() -> None:
    profile = load_cp_profile()
    payload = build_grouped_payload()
    payload["workflow_events"] = [{"action": "created"}]
    payload["review_snapshot"] = {"status": "draft"}

    memory = build_listing_memory_payload(profile, payload)

    assert memory["listing_group"] == payload["listing_group"]
    assert memory["listing_group"] is not payload["listing_group"]
    assert memory["workflow_events"] == [{"action": "created"}]
    assert memory["review_snapshot"] == {"status": "draft"}


def test_grouped_draft_save_implementation_has_no_folder_move() -> None:
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "save_grouped_christmas_draft_to_dropbox"
    )
    function_source = ast.get_source_segment(source, function) or ""

    assert "save_listing_inputs_json_to_dropbox" in function_source
    assert "move_dropbox_folder" not in function_source
    assert "move_staged_dropbox_folder_to_ready" not in function_source


def test_grouped_submit_guard_precedes_existing_ready_move_and_normal_memory_is_allowed() -> None:
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    guard = "if ready_clicked and is_grouped_christmas_memory(listing_memory):"
    ready_move = "ready_folder_path = move_staged_dropbox_folder_to_ready("

    assert guard in source
    assert source.index(guard) < source.index(ready_move)
    assert is_grouped_christmas_memory({"template_key": "CP"}) is False
