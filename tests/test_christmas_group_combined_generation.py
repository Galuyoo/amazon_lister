from __future__ import annotations

import json
from pathlib import Path

import app
import pytest
from services.christmas_grouped_content_import import parse_christmas_grouped_content_json
from services.christmas_project_grouping import derive_christmas_group_members
from services.listing_memory import build_listing_memory_payload


ROOT = Path(__file__).parents[1]
SAMPLE_CONTENT_PATH = ROOT / "samples" / "christmas_grouped_listing_content_test.json"


def build_quality_safe_cp_payloads(profile: dict) -> list[dict]:
    content = parse_christmas_grouped_content_json(
        SAMPLE_CONTENT_PATH.read_text(encoding="utf-8")
    )["members"]
    payloads = []
    for member_key, parent_sku in (
        ("tshirt", "PRINT-CHRTST-T"),
        ("sweatshirt", "PRINT-CHRTST-S"),
        ("hoodie", "PRINT-CHRTST-H"),
    ):
        member = derive_christmas_group_members(profile)[member_key]
        design = member["designs"][0]
        colour = member["allowed_colours"][0]
        size = member["sizes_by_design"][design][0]
        payloads.append({
            **content[member_key],
            "parent_sku": parent_sku,
            "sku_decoration_code": "PRINT",
            "sku_listing_code": "CHRTST",
            "variation_theme": "SizeColor",
            "product_category": "apparel",
            "selected_variants": {
                "design": [design],
                "color": [colour],
                "size": [size],
            },
            "size_price_map": {f"{design}||{size}": 19.99},
            "parent_main_image_url": "https://example.test/parent.png",
            "color_image_map": {colour: "https://example.test/child.png"},
            "design_color_image_url_map": {},
        })
    return payloads


def load_cp_profile() -> dict:
    profile = json.loads(
        (ROOT / "templates" / "Special Projects" / "CP" / "config.json").read_text(
            encoding="utf-8"
        )
    )
    profile.update({
        "_slug": "CP",
        "_family_slug": "Special Projects",
        "_family_folder": str(ROOT / "templates" / "Special Projects"),
        "_folder": str(ROOT / "templates" / "Special Projects" / "CP"),
    })
    return profile


def test_cp_combined_generation_uses_three_separate_parent_skus(
    monkeypatch,
    tmp_path,
) -> None:
    profile = {
        "template_key": "CP",
        "parent_sku": "CP",
        "include_template_code_in_parent_sku": False,
    }

    specs = [
        ("tshirt", "TSHIRT", "PRINT-CHRTST-T"),
        ("sweatshirt", "SWEATSHIRT", "PRINT-CHRTST-S"),
        ("hoodie", "HOODIE", "PRINT-CHRTST-H"),
    ]

    items = []
    for member_key, legacy_suffix, _expected_parent in specs:
        items.append(
            {
                "folder_name": f"CHRTST-{legacy_suffix}",
                "profile": dict(profile),
                "listing_memory": {
                    "title": f"Christmas {member_key}",
                    "bullet_points": ["Bullet"] * 5,
                    "product_description": "Description " * 100,
                    "generic_keywords": "christmas clothing",
                    "selected_variants": {
                        "design": ["Example"],
                        "color": ["Black"],
                        "size": ["S"],
                    },
                    "size_price_map": {"S": 19.99},
                    "sku_decoration_code": "PRINT",
                    "sku_listing_code": f"CHRTST-{legacy_suffix}",
                    "manual_sku_listing_code": f"CHRTST-{legacy_suffix}",
                    "generated_sku_listing_code": "",
                    "quantity": 1,
                    "source_group": {
                        "group_type": "christmas_project",
                        "member_key": member_key,
                        "release_status": "released",
                    },
                },
            }
        )

    monkeypatch.setattr(
        app,
        "get_combined_workbook_group_identity",
        lambda _profile: ("cp",),
    )

    prepare_calls = []

    def fake_prepare_generation_payload(**kwargs):
        prepare_calls.append(kwargs)
        return {
            "errors": [],
            "payload": {
                "parent_sku": kwargs["parent_sku_override"],
                "selected_variants": dict(kwargs["selected_variants"]),
                "colors": list(
                    kwargs["selected_variants"].get("color", [])
                ),
                "parent_main_image_choice": kwargs.get(
                    "parent_main_image_choice",
                    "",
                ),
                "parent_main_image_url": kwargs.get(
                    "parent_main_image_url",
                    "",
                ),
            },
        }

    monkeypatch.setattr(
        app,
        "prepare_generation_payload",
        fake_prepare_generation_payload,
    )
    monkeypatch.setattr(
        app,
        "build_approved_folder_path",
        lambda _cfg, folder_name: f"/approved/{folder_name}",
    )
    monkeypatch.setattr(
        app,
        "get_cached_dropbox_overview",
        lambda _profile, _cfg: {},
    )
    monkeypatch.setattr(
        app,
        "resolve_folder_image_urls",
        lambda *args, **kwargs: (
            "https://example.test/main.png",
            [],
            {},
            {},
        ),
    )

    output_path = tmp_path / "cp-combined.xlsm"
    output_path.write_bytes(b"test")

    captured = {}

    def fake_build_combined_workbook(
        _profile,
        payloads,
        payload_profiles=None,
    ):
        captured["parents"] = [
            payload["parent_sku"]
            for payload in payloads
        ]
        return output_path, {"total_build": 0.0}

    monkeypatch.setattr(
        app,
        "build_combined_workbook",
        fake_build_combined_workbook,
    )

    result = app.generate_approved_listings_combined(items, {})

    expected = [
        "PRINT-CHRTST-T",
        "PRINT-CHRTST-S",
        "PRINT-CHRTST-H",
    ]

    assert [
        call["parent_sku_override"]
        for call in prepare_calls
    ] == expected
    assert captured["parents"] == expected
    assert result["status"] == "Success"
    assert result["output_path"] == str(output_path)


@pytest.mark.parametrize(
    ("member_key", "designs", "legacy_code", "expected_parent"),
    [
        ("tshirt", ["Adult T-Shirt", "Kids T-Shirt"], "CHRTST-TSHIRT", "PRINT-CHRTST-T"),
        ("sweatshirt", ["Adult Sweatshirt", "Kids Sweatshirt"], "CHRTST-SWEATSHIRT", "PRINT-CHRTST-S"),
        ("hoodie", ["Adult Hoodie", "Kids Hoodie"], "CHRTST-HOODIE", "PRINT-CHRTST-H"),
    ],
)
def test_historical_cp_child_identity_recovers_only_from_exact_saved_design_pair(
    member_key,
    designs,
    legacy_code,
    expected_parent,
) -> None:
    profile = load_cp_profile()
    memory = {
        "template_key": "CP",
        "selected_variants": {"design": designs},
        "sku_decoration_code": "PRINT",
        "sku_listing_code": legacy_code,
    }

    assert app.resolve_christmas_grouped_child_member_key(memory, profile) == member_key
    assert app.get_grouped_child_generation_parent_sku_override(memory, profile) == expected_parent
    assert expected_parent in app.build_output_workbook_name(profile, expected_parent)


def test_historical_identity_is_not_inferred_from_cp_template_or_partial_designs() -> None:
    profile = load_cp_profile()
    memory = {
        "template_key": "CP",
        "selected_variants": {"design": ["Adult T-Shirt"]},
        "sku_decoration_code": "PRINT",
        "sku_listing_code": "CHRTST-TSHIRT",
    }

    assert app.resolve_christmas_grouped_child_member_key(memory, profile) == ""
    assert app.get_grouped_child_generation_parent_sku_override(memory, profile) == ""


def test_ordinary_non_christmas_listing_keeps_normal_parent_behavior() -> None:
    profile = {
        "template_key": "GENERIC_SHIRTS",
        "parent_sku": "GS",
        "include_template_code_in_parent_sku": False,
    }
    memory = {
        "template_key": "GENERIC_SHIRTS",
        "selected_variants": {"design": ["Adult T-Shirt", "Kids T-Shirt"]},
        "sku_decoration_code": "PRINT",
        "sku_listing_code": "NORMAL-001",
    }

    assert app.resolve_christmas_grouped_child_member_key(memory, profile) == ""
    assert app.get_grouped_child_generation_parent_sku_override(memory, profile) == ""
    assert app.build_parent_sku_from_context(profile, "PRINT", "NORMAL-001") == "PRINT-NORMAL-001"


def test_generation_memory_round_trip_preserves_released_source_group_without_mutation() -> None:
    profile = load_cp_profile()
    source_group = {
        "schema_version": 1,
        "group_type": "christmas_project",
        "task_id": "task-chrtst-1",
        "member_key": "tshirt",
        "source_mpn": "CHRTST",
        "source_listing_code": "CHRTST",
        "materialization_hash": "abc123",
        "release_status": "released",
    }
    listing_memory = {"source_group": source_group}
    generation_payload = {"title": "Generated title"}

    app.preserve_grouped_child_generation_context(listing_memory, generation_payload)
    saved = build_listing_memory_payload(profile, generation_payload)

    assert saved["source_group"] == source_group
    assert saved["source_group"] is not source_group
    assert generation_payload["source_group"] is not source_group


def test_generate_approved_listing_persists_source_group_and_distinct_parent(
    monkeypatch,
    tmp_path,
) -> None:
    profile = load_cp_profile()
    source_group = {
        "schema_version": 1,
        "group_type": "christmas_project",
        "task_id": "task-chrtst-1",
        "member_key": "tshirt",
        "source_listing_code": "CHRTST",
        "materialization_hash": "hash-tshirt",
        "release_status": "released",
    }
    memory = {
        "template_key": "CP",
        "title": "Christmas T-Shirt",
        "bullet_points": ["Bullet"] * 5,
        "product_description": "Description " * 100,
        "generic_keywords": "christmas clothing",
        "selected_variants": {"design": ["Adult T-Shirt", "Kids T-Shirt"], "color": ["Black"], "size": ["S"]},
        "size_price_map": {"Adult T-Shirt||S": 19.99, "Kids T-Shirt||S": 14.99},
        "sku_decoration_code": "PRINT",
        "sku_listing_code": "CHRTST",
        "manual_sku_listing_code": "CHRTST",
        "quantity": 1,
        "source_group": source_group,
    }
    prepared = {}

    def prepare(**kwargs):
        prepared.update(kwargs)
        return {
            "errors": [],
            "payload": {
                "parent_sku": kwargs["parent_sku_override"],
                "selected_variants": dict(kwargs["selected_variants"]),
                "colors": ["Black"],
                "sku_decoration_code": kwargs["sku_decoration_code"],
                "sku_listing_code": kwargs["sku_listing_code"],
                "parent_main_image_choice": "",
                "selected_parent_main_image_url": "",
            },
        }

    class Workbook:
        def close(self):
            pass

    output_path = tmp_path / "PRINT-CHRTST-T_CP_amazon_listing.xlsm"
    output_path.write_bytes(b"workbook")
    saved = {}
    monkeypatch.setattr(app, "prepare_generation_payload", prepare)
    monkeypatch.setattr(app, "get_cached_dropbox_overview", lambda *_args: {})
    monkeypatch.setattr(app, "build_approved_folder_path", lambda *_args: "/approved/CHRTST-TSHIRT")
    monkeypatch.setattr(app, "resolve_template_path", lambda _profile: output_path)
    monkeypatch.setattr(app, "load_workbook", lambda *_args, **_kwargs: Workbook())
    monkeypatch.setattr(
        app,
        "resolve_folder_image_urls",
        lambda *_args, **_kwargs: ("https://example.test/main.png", [], {}, {}),
    )
    monkeypatch.setattr(
        app,
        "choose_finished_folder_target",
        lambda **_kwargs: ("EXISTING-FINISHED", "/finished/EXISTING-FINISHED"),
    )
    monkeypatch.setattr(app, "build_workbook", lambda *_args: (output_path, {"total_build": 0.0}))
    monkeypatch.setattr(
        app,
        "save_generated_artifacts_to_dropbox",
        lambda **_kwargs: {
            "workbook_dropbox_path": "/approved/CHRTST-TSHIRT/workbook.xlsm",
            "sku_manifest_dropbox_path": "/approved/CHRTST-TSHIRT/sku_manifest.json",
            "child_sku_count": 2,
            "missing_supplier_stock_key_count": 0,
        },
    )
    monkeypatch.setattr(app, "append_workflow_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        app,
        "save_listing_inputs_json_to_dropbox",
        lambda **kwargs: saved.update(kwargs) or "/approved/CHRTST-TSHIRT/listing_inputs.json",
    )

    result = app.generate_approved_listing(profile, memory, "CHRTST-TSHIRT", {})

    assert prepared["parent_sku_override"] == "PRINT-CHRTST-T"
    assert result["parent_sku"] == "PRINT-CHRTST-T"
    assert saved["payload"]["source_group"] == source_group
    assert saved["payload"]["source_group"] is not source_group


def test_finished_to_approved_restage_preserves_source_group_and_cp_profile(monkeypatch) -> None:
    cp_profile = load_cp_profile()
    generic_profile = {
        "template_key": "GENERIC_SHIRTS",
        "label": "Generic Shirts",
        "_slug": "Generic Shirts",
    }
    source_group = {
        "group_type": "christmas_project",
        "task_id": "task-chrtst-1",
        "member_key": "hoodie",
        "materialization_hash": "hash-hoodie",
        "release_status": "released",
    }
    finished_memory = {
        "template_key": "CP",
        "selected_variants": {"design": ["Adult Hoodie", "Kids Hoodie"]},
        "source_group": source_group,
    }
    saved = {}
    monkeypatch.setattr(
        app,
        "move_finished_dropbox_folder_to_approved",
        lambda **_kwargs: "/Amazon/approved/RESTAGED-CHRTST",
    )
    monkeypatch.setattr(app, "path_exists", lambda _path: True)
    monkeypatch.setattr(app, "load_listing_memory_from_dropbox", lambda _path: finished_memory)
    monkeypatch.setattr(
        app,
        "save_listing_inputs_json_to_dropbox",
        lambda **kwargs: saved.update(kwargs) or "/Amazon/approved/RESTAGED-CHRTST/listing_inputs.json",
    )

    result = app.restage_finished_listing_for_review(
        dropbox_cfg={"finished_root": "/Amazon/finished"},
        profiles=[generic_profile, cp_profile],
        fallback_profile=generic_profile,
        finished_folder_name="RANDOM-FINISHED-NAME",
        target_state="approved",
    )

    assert result["status"] == "Success"
    assert saved["profile"] is cp_profile
    assert saved["payload"]["source_group"] == source_group
    assert saved["payload"]["source_group"]["task_id"] == "task-chrtst-1"
    assert app.find_profile_for_listing_memory([generic_profile, cp_profile], saved["payload"]) is cp_profile


def test_cp_batch_builds_combined_before_moving_individual_folders(monkeypatch) -> None:
    profile = load_cp_profile()
    folder_names = ["CHRTST-TSHIRT", "CHRTST-SWEATSHIRT", "CHRTST-HOODIE"]
    approved_lookup = {
        folder_name: {
            "folder_name": folder_name,
            "profile": profile,
            "listing_memory": {"template_key": "CP", "title": folder_name},
            "load_error": "",
        }
        for folder_name in folder_names
    }
    events = []

    def generate_single(**kwargs):
        events.append(f"single:{kwargs['approved_folder_name']}")
        return {
            "folder_name": kwargs["approved_folder_name"],
            "approved_folder_name": kwargs["approved_folder_name"],
            "status": "Success",
        }

    def generate_combined(items, _cfg):
        events.append("combined")
        assert [item["folder_name"] for item in items] == folder_names
        return {"folder_name": "Combined workbook - CP", "status": "Success"}

    def move_results(*, results, profiles, dropbox_cfg):
        events.append("move")
        assert any(result["folder_name"].startswith("Combined workbook") for result in results)
        return results, []

    monkeypatch.setattr(app, "generate_approved_listing", generate_single)
    monkeypatch.setattr(app, "generate_approved_listings_combined", generate_combined)
    monkeypatch.setattr(app, "get_combined_workbook_group_identity", lambda _profile: ("cp",))
    monkeypatch.setattr(app, "move_successful_generation_results_to_finished", move_results)

    results, move_results_rows = app.generate_approved_output_batch(
        target_folders=folder_names,
        approved_lookup=approved_lookup,
        profiles=[profile],
        dropbox_cfg={},
    )

    assert events == [
        "single:CHRTST-TSHIRT",
        "single:CHRTST-SWEATSHIRT",
        "single:CHRTST-HOODIE",
        "combined",
        "move",
    ]
    assert len(results) == 4
    assert move_results_rows == []


def test_combined_group_identity_error_is_reported_not_hidden(monkeypatch) -> None:
    item = {
        "folder_name": "BROKEN",
        "profile": {"template_key": "CP"},
        "listing_memory": {"template_key": "CP"},
        "load_error": "",
    }
    monkeypatch.setattr(app, "generate_approved_listing", lambda **_kwargs: {"status": "Failed"})
    monkeypatch.setattr(
        app,
        "get_combined_workbook_group_identity",
        lambda _profile: (_ for _ in ()).throw(ValueError("template path is invalid")),
    )
    monkeypatch.setattr(
        app,
        "move_successful_generation_results_to_finished",
        lambda **kwargs: (kwargs["results"], []),
    )

    results, _ = app.generate_approved_output_batch(
        target_folders=["BROKEN", "BROKEN-2"],
        approved_lookup={"BROKEN": item, "BROKEN-2": {**item, "folder_name": "BROKEN-2"}},
        profiles=[],
        dropbox_cfg={},
    )

    skipped = next(result for result in results if result.get("status") == "Skipped")
    assert "template path is invalid" in skipped["message"]


def test_combined_workbook_writes_three_distinct_parent_rows(monkeypatch, tmp_path) -> None:
    template_path = tmp_path / "template.xlsm"
    template_path.write_bytes(b"template")
    profile = {
        "template_key": "CP",
        "_slug": "CP",
        "_family_slug": "Special Projects",
        "_folder": str(tmp_path),
        "template_file": template_path.name,
    }
    parents = ["PRINT-CHRTST-T", "PRINT-CHRTST-S", "PRINT-CHRTST-H"]
    payloads = [
        {
            "parent_sku": parent,
            "template_key": "CP",
            "sku_decoration_code": "PRINT",
            "sku_listing_code": "CHRTST",
            "selected_variants": {"size": ["S"]},
        }
        for parent in parents
    ]
    written = []

    class Workbook:
        def __getitem__(self, _name):
            return object()

        def save(self, path):
            Path(path).write_bytes(b"combined")

        def close(self):
            pass

    monkeypatch.setattr(app, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(app, "load_workbook", lambda *_args, **_kwargs: Workbook())
    monkeypatch.setattr(app, "build_header_map", lambda *_args: {})
    monkeypatch.setattr(app, "validate_listing_quality", lambda *_args: {"blockers": []})
    monkeypatch.setattr(app, "validate_stock_ready_payload", lambda *_args: {"errors": []})
    monkeypatch.setattr(app, "build_variant_combinations", lambda *_args: [{"size": "S"}])
    monkeypatch.setattr(
        app,
        "build_child_sku_details",
        lambda _profile, parent_sku, _combo: {"amazon_seller_sku": f"{parent_sku}-S"},
    )
    monkeypatch.setattr(app, "get_dynamic_profile_fields", lambda *_args: {})

    def write_rows(_ws, _headers, _profile, payload, **kwargs):
        written.append((payload["parent_sku"], kwargs["parent_row"]))
        return {"variants_written": 1, "next_row": kwargs["parent_row"] + 2}

    monkeypatch.setattr(app, "write_listing_rows_to_workbook", write_rows)

    output_path, timings = app.build_combined_workbook(profile, payloads, [profile] * 3)

    assert [parent for parent, _row in written] == parents
    assert len({row for _parent, row in written}) == 3
    assert output_path.exists()
    assert timings["combined_listing_count"] == 3.0


def test_combined_workbook_accepts_quality_safe_cp_titles(monkeypatch, tmp_path) -> None:
    profile = load_cp_profile()
    payloads = build_quality_safe_cp_payloads(profile)
    written_parents = []

    class Workbook:
        def __getitem__(self, _name):
            return object()

        def save(self, path):
            Path(path).write_bytes(b"combined")

        def close(self):
            pass

    monkeypatch.setattr(app, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(app, "load_workbook", lambda *_args, **_kwargs: Workbook())
    monkeypatch.setattr(app, "build_header_map", lambda *_args: {})
    monkeypatch.setattr(app, "validate_stock_ready_payload", lambda *_args: {"errors": []})
    monkeypatch.setattr(app, "get_dynamic_profile_fields", lambda *_args: {})

    def write_rows(_ws, _headers, _profile, payload, **kwargs):
        written_parents.append(payload["parent_sku"])
        return {"variants_written": 1, "next_row": kwargs["parent_row"] + 2}

    monkeypatch.setattr(app, "write_listing_rows_to_workbook", write_rows)

    output_path, _timings = app.build_combined_workbook(
        profile,
        payloads,
        [profile] * 3,
    )

    assert written_parents == [
        "PRINT-CHRTST-T",
        "PRINT-CHRTST-S",
        "PRINT-CHRTST-H",
    ]
    assert output_path.exists()


def test_individual_and_combined_quality_reject_same_real_child_title(
    monkeypatch,
) -> None:
    profile = load_cp_profile()
    payload = build_quality_safe_cp_payloads(profile)[0]
    payload["title"] = (
        "Merry Christmas T-Shirt for Adults and Kids, Festive Holiday Graphic with Holly, "
        "Candy Canes, Baubles, Gifts, Snowflakes and Christmas Tree for Seasonal Family Outfits"
    )
    variants = payload["selected_variants"] = {
        "design": ["Kids T-Shirt"],
        "color": ["Heather Grey"],
        "size": ["11/13 YRS"],
    }
    payload["size_price_map"] = {"Kids T-Shirt||11/13 YRS": 19.99}

    monkeypatch.setattr(app, "validate_template_file", lambda *_args: [])
    monkeypatch.setattr(app, "validate_stock_ready_payload", lambda *_args: {"errors": [], "warnings": []})

    individual = app.prepare_generation_payload(
        profile=profile,
        title=payload["title"],
        bullets=payload["bullet_points"],
        product_description=payload["product_description"],
        generic_keywords=payload["generic_keywords"],
        selected_variants=variants,
        size_price_map=payload["size_price_map"],
        sku_decoration_code="PRINT",
        sku_listing_code="CHRTST",
        manual_sku_listing_code="CHRTST",
        generated_sku_listing_code="",
        quantity=100,
        staged_folder_name="CP-TITLE-CHECK",
    )
    combined_quality = app.validate_listing_quality(profile, payload)

    assert any("Amazon titles must be 200 characters or fewer" in error for error in individual["errors"])
    assert any("Generated child titles exceed Amazon's 200 character limit" in blocker for blocker in combined_quality["blockers"])
    assert "210 chars" in "; ".join(individual["errors"])
    assert "210 chars" in "; ".join(combined_quality["blockers"])


def test_ordinary_non_christmas_child_title_output_is_unchanged() -> None:
    profile = {"size_display_prefix_by_design": {"Adult T-Shirt": "Adult T-Shirt"}}
    variant = {"design": "Adult T-Shirt", "color": "Black", "size": "M"}

    assert app.build_child_item_name("Ordinary listing", variant, profile) == (
        "Adult T-Shirt, Black, M, Ordinary listing"
    )


def test_generic_shirts_historical_size_values_normalize_without_losing_prices() -> None:
    profiles = app.list_template_profiles()
    profile = next(
        item for item in profiles if item.get("template_key") == "GENERIC_SHIRTS"
    )
    selected = app.normalize_saved_variant_values_for_profile(profile, {
        "design": ["Kids T-Shirt"],
        "color": ["Black"],
        "size": ["1-2 Years", "12-13 Years"],
    })
    prices = app.normalize_saved_price_map_for_profile(profile, {
        "Kids T-Shirt||1-2 Years": 12.5,
        "Kids T-Shirt||12-13 Years": 14.5,
    })

    assert selected["size"] == ["1Yr", "11Yr"]
    assert prices == {
        "Kids T-Shirt||1Yr": 12.5,
        "Kids T-Shirt||11Yr": 14.5,
    }


def test_new_christmas_targets_use_normal_workbook_compatibility_groups() -> None:
    profiles = app.list_template_profiles()
    by_key = {profile.get("template_key"): profile for profile in profiles}

    shirt_identity = app.get_combined_workbook_group_identity(by_key["GENERIC_SHIRTS"])
    sweatshirt_identity = app.get_combined_workbook_group_identity(
        by_key["GENERIC_SWEATSHIRTS"]
    )
    hoodie_identity = app.get_combined_workbook_group_identity(by_key["GENERIC_HOODIES"])

    assert shirt_identity != sweatshirt_identity
    assert sweatshirt_identity == hoodie_identity


@pytest.mark.parametrize(
    ("template_key", "filename", "colour", "designs"),
    [
        ("GENERIC_SHIRTS", "T01 T02 Heather Grey.png", "Heather Grey", ["Adult T-Shirt", "Kids T-Shirt"]),
        ("GENERIC_SWEATSHIRTS", "S01 S02 Royal.png", "Royal", ["Adult Sweatshirt", "Kids Sweatshirt"]),
        ("GENERIC_HOODIES", "H01 H02 Navy.png", "Navy", ["Adult Hoodie", "Kids Hoodie"]),
    ],
)
def test_grouped_image_names_resolve_through_ordinary_target_profile_inference(
    template_key,
    filename,
    colour,
    designs,
) -> None:
    profile = next(
        item for item in app.list_template_profiles()
        if item.get("template_key") == template_key
    )

    result = app.infer_design_color_image_path_map_from_paths(
        profile,
        [f"/ready/{filename}"],
        [colour],
        designs,
    )

    assert set(result[colour]) == set(designs)
    assert set(result[colour].values()) == {f"/ready/{filename}"}


def test_explicit_saved_parent_override_wins_for_generic_grouped_child() -> None:
    profile = {
        "template_key": "GENERIC_SHIRTS",
        "include_template_code_in_parent_sku": False,
    }
    memory = {
        "template_key": "GENERIC_SHIRTS",
        "parent_sku_override": "PRINT-CHRTST-T",
        "source_group": {
            "group_type": "christmas_project",
            "member_key": "tshirt",
        },
    }

    assert app.get_listing_generation_parent_sku_override(memory, profile) == (
        "PRINT-CHRTST-T"
    )
    assert app.build_review_parent_sku(memory, profile, "PRINT", "CHRTST") == (
        "PRINT-CHRTST-T"
    )


def test_combined_workbook_duplicate_parent_protection_remains_active(monkeypatch, tmp_path) -> None:
    template_path = tmp_path / "template.xlsm"
    template_path.write_bytes(b"template")
    profile = {
        "template_key": "CP",
        "_folder": str(tmp_path),
        "template_file": template_path.name,
    }
    payload = {
        "parent_sku": "PRINT-CHRTST-T",
        "selected_variants": {},
    }
    monkeypatch.setattr(app, "validate_listing_quality", lambda *_args: {"blockers": []})
    monkeypatch.setattr(app, "validate_stock_ready_payload", lambda *_args: {"errors": []})

    with pytest.raises(ValueError, match="Duplicate parent SKUs"):
        app.build_combined_workbook(profile, [payload, dict(payload)], [profile, profile])


def test_combined_workbook_duplicate_child_protection_remains_active(monkeypatch, tmp_path) -> None:
    template_path = tmp_path / "template.xlsm"
    template_path.write_bytes(b"template")
    profile = {
        "template_key": "CP",
        "_folder": str(tmp_path),
        "template_file": template_path.name,
    }
    payloads = [
        {"parent_sku": "PRINT-CHRTST-T", "selected_variants": {"size": ["S"]}},
        {"parent_sku": "PRINT-CHRTST-S", "selected_variants": {"size": ["S"]}},
    ]
    monkeypatch.setattr(app, "validate_listing_quality", lambda *_args: {"blockers": []})
    monkeypatch.setattr(app, "validate_stock_ready_payload", lambda *_args: {"errors": []})
    monkeypatch.setattr(app, "build_variant_combinations", lambda *_args: [{"size": "S"}])
    monkeypatch.setattr(
        app,
        "build_child_sku_details",
        lambda *_args: {"amazon_seller_sku": "DUPLICATE-CHILD"},
    )

    with pytest.raises(ValueError, match="Duplicate child SKUs"):
        app.build_combined_workbook(profile, payloads, [profile, profile])
