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


def approved_grouped_task(task_id: str, code: str) -> list[dict]:
    return [
        {
            "folder_name": f"folder-{task_id}-{member}",
            "profile": {"template_key": template},
            "load_error": "",
            "listing_memory": {
                "title": f"Title {member}",
                "sku_decoration_code": "DEF",
                "mpn": code,
                "manual_sku_listing_code": code,
                "generated_sku_listing_code": code,
                "sku_listing_code": code,
                "parent_sku": f"DEF-{code}-{suffix}",
                "parent_sku_override": f"DEF-{code}-{suffix}",
                "source_group": {
                    "group_type": "christmas_project",
                    "task_id": task_id,
                    "member_key": member,
                    "source_mpn": code,
                    "source_listing_code": code,
                },
            },
        }
        for member, suffix, template in [
            ("tshirt", "T", "GENERIC_SHIRTS"),
            ("sweatshirt", "S", "GENERIC_SWEATSHIRTS"),
            ("hoodie", "H", "GENERIC_HOODIES"),
        ]
    ]


def test_assessed_mpn_changes_update_mpn_and_complete_sku_identity(monkeypatch) -> None:
    items = approved_grouped_task("task-a", "ABC") + approved_grouped_task("task-b", "ABC")
    approved_lookup = {item["folder_name"]: item for item in items}
    saved = []
    monkeypatch.setattr(
        app,
        "save_listing_inputs_json_to_dropbox",
        lambda **kwargs: saved.append(kwargs),
    )
    monkeypatch.setattr(app, "clear_cached_listing_memory", lambda *_args: None)

    assessment = app.assess_approved_grouped_christmas_mpn_changes(
        list(approved_lookup),
        approved_lookup,
    )
    changes = app.apply_assessed_grouped_christmas_mpn_changes(
        assessment,
        approved_lookup,
        {"approved_folder": "/Amazon/approved"},
    )

    assert len(changes) == 3
    assert len(saved) == 3
    new_code = changes[0]["new_listing_code"]
    assert len(new_code) == 3
    for change in changes:
        memory = approved_lookup[change["folder_name"]]["listing_memory"]
        assert memory["mpn"] == new_code
        assert memory["manual_sku_listing_code"] == new_code
        assert memory["generated_sku_listing_code"] == new_code
        assert memory["sku_listing_code"] == new_code
        assert memory["parent_sku"] == change["new_parent_sku"]
        assert memory["parent_sku_override"] == change["new_parent_sku"]
        assert memory["source_group"]["source_listing_code"] == "ABC"
        assert memory["identity_override"]["new_listing_code"] == new_code


def test_stale_mpn_assessment_is_rejected_before_writes(monkeypatch) -> None:
    items = approved_grouped_task("task-a", "ABC") + approved_grouped_task("task-b", "ABC")
    approved_lookup = {item["folder_name"]: item for item in items}
    assessment = app.assess_approved_grouped_christmas_mpn_changes(list(approved_lookup), approved_lookup)
    approved_lookup["folder-task-b-hoodie"]["listing_memory"]["sku_listing_code"] = "XYZ"
    saved = []
    monkeypatch.setattr(app, "save_listing_inputs_json_to_dropbox", lambda **kwargs: saved.append(kwargs))

    with pytest.raises(ValueError, match="changed after assessment"):
        app.apply_assessed_grouped_christmas_mpn_changes(assessment, approved_lookup, {})
    assert saved == []


def test_optimized_christmas_generation_keeps_one_compatible_workbook_under_limit(monkeypatch, tmp_path) -> None:
    items = approved_grouped_task("task-a", "ABC") + approved_grouped_task("task-b", "XYZ")
    combined_calls = []
    persisted = []

    monkeypatch.setattr(
        app,
        "get_combined_workbook_group_identity",
        lambda _profile: ("shared-workbook",),
    )

    def generate_combined(chunk, _cfg):
        combined_calls.append([item["folder_name"] for item in chunk])
        output_path = tmp_path / f"combined-{len(combined_calls)}.xlsm"
        output_path.write_bytes(b"workbook")
        return {
            "folder_name": f"Combined {len(combined_calls)}",
            "status": "Success",
            "output_path": str(output_path),
            "output_name": output_path.name,
            "prepared_items": [
                {"item": item, "profile": item["profile"], "payload": {"parent_sku": item["listing_memory"]["parent_sku"]}}
                for item in chunk
            ],
        }

    def persist(prepared_item, output_path, dropbox_cfg, combined_listing_count):
        persisted.append((
            prepared_item["item"]["folder_name"],
            output_path.name,
            combined_listing_count,
        ))
        return {
            "folder_name": prepared_item["item"]["folder_name"],
            "approved_folder_name": prepared_item["item"]["folder_name"],
            "status": "Success",
        }

    monkeypatch.setattr(app, "generate_approved_listings_combined", generate_combined)
    monkeypatch.setattr(app, "persist_combined_chunk_listing_result", persist)
    monkeypatch.setattr(
        app,
        "generate_approved_listing",
        lambda **_kwargs: pytest.fail("six compatible listings should not use individual generation"),
    )
    monkeypatch.setattr(
        app,
        "move_successful_generation_results_to_finished",
        lambda **kwargs: (kwargs["results"], [{"status": "Success"} for _ in kwargs["results"]]),
    )

    results, move_results = app.generate_optimized_grouped_christmas_batch(items, [], {})

    assert len(combined_calls) == 1
    assert len(combined_calls[0]) == 6
    assert len(persisted) == 6
    assert {count for _folder, _output_name, count in persisted} == {6}
    assert len({output_name for _folder, output_name, _count in persisted}) == 1
    assert len(results) == 1
    assert len(move_results) == 6


def test_optimized_christmas_generation_splits_only_after_actual_file_exceeds_limit(
    monkeypatch,
    tmp_path,
) -> None:
    items = approved_grouped_task("task-a", "ABC") + approved_grouped_task("task-b", "XYZ")
    combined_sizes = []
    persisted_counts = []
    monkeypatch.setattr(app, "MAX_AMAZON_COMBINED_WORKBOOK_BYTES", 10)
    monkeypatch.setattr(app, "get_combined_workbook_group_identity", lambda _profile: ("shared",))

    def generate_combined(chunk, _cfg):
        combined_sizes.append(len(chunk))
        output_path = tmp_path / f"combined-{len(combined_sizes)}.xlsm"
        output_path.write_bytes(b"x" * (11 if len(chunk) > 3 else 5))
        return {
            "folder_name": f"Combined {len(combined_sizes)}",
            "status": "Success",
            "output_path": str(output_path),
            "output_name": output_path.name,
            "prepared_items": [
                {"item": item, "profile": item["profile"], "payload": {"parent_sku": item["listing_memory"]["parent_sku"]}}
                for item in chunk
            ],
        }

    def persist(prepared_item, output_path, dropbox_cfg, combined_listing_count):
        persisted_counts.append(combined_listing_count)
        return {
            "folder_name": prepared_item["item"]["folder_name"],
            "approved_folder_name": prepared_item["item"]["folder_name"],
            "status": "Success",
        }

    monkeypatch.setattr(app, "generate_approved_listings_combined", generate_combined)
    monkeypatch.setattr(app, "persist_combined_chunk_listing_result", persist)
    monkeypatch.setattr(
        app,
        "move_successful_generation_results_to_finished",
        lambda **kwargs: (kwargs["results"], [{"status": "Success"} for _ in kwargs["results"]]),
    )

    results, move_results = app.generate_optimized_grouped_christmas_batch(items, [], {})

    assert combined_sizes == [6, 3, 3]
    assert persisted_counts == [3, 3, 3, 3, 3, 3]
    assert len(results) == 2
    assert len(move_results) == 6
    assert not (tmp_path / "combined-1.xlsm").exists()


def test_optimized_generation_blocks_duplicate_parent_skus_before_build(monkeypatch) -> None:
    items = approved_grouped_task("task-a", "ABC") + approved_grouped_task("task-b", "ABC")
    approved_lookup = {item["folder_name"]: item for item in items}
    monkeypatch.setattr(
        app,
        "generate_optimized_grouped_christmas_batch",
        lambda **_kwargs: pytest.fail("duplicate identities must be blocked before generation"),
    )

    results, move_results = app.generate_approved_output_batch(
        target_folders=list(approved_lookup),
        approved_lookup=approved_lookup,
        profiles=[],
        dropbox_cfg={},
        optimize_grouped_christmas=True,
    )

    assert move_results == []
    assert results[0]["status"] == "Failed"
    assert "assessment" in results[0]["folder_name"]


def test_daily_mpn_report_contains_finished_link_and_identity_changes(monkeypatch) -> None:
    monkeypatch.setattr(app, "format_workflow_timestamp", lambda: "2026-09-03 12:34:56")
    monkeypatch.setattr(app, "get_cached_dropbox_shared_link", lambda path: f"https://dropbox.test{path}")

    report = app.build_daily_mpn_change_report(
        applied_changes=[{
            "folder_name": "folder-task-b-tshirt",
            "task_id": "task-b",
            "member_key": "tshirt",
            "old_listing_code": "ABC",
            "new_listing_code": "X7Q",
            "old_parent_sku": "DEF-ABC-T",
            "new_parent_sku": "DEF-X7Q-T",
        }],
        move_results=[{
            "folder_name": "folder-task-b-tshirt",
            "status": "Success",
            "finished_folder_path": "/Amazon/finished/DEF-X7Q-T",
        }],
        generation_results=[{"status": "Success", "output_name": "batch.xlsm"}],
    )

    assert "ABC -> X7Q" in report
    assert "DEF-ABC-T -> DEF-X7Q-T" in report
    assert "/Amazon/finished/DEF-X7Q-T" in report
    assert "https://dropbox.test/Amazon/finished/DEF-X7Q-T" in report
    assert "batch.xlsm" in report


def test_approved_generation_ui_exposes_mpn_assessment_and_optimization_controls() -> None:
    source = Path(app.__file__).read_text(encoding="utf-8")

    assert '"Assess changes in MPN"' in source
    assert 'key="approved_queue_apply_mpn_assessment_btn"' in source
    assert 'key="approved_queue_optimize_christmas_batch"' in source


def test_sku_rule_assessment_previews_real_parent_and_child_lengths(monkeypatch) -> None:
    items = approved_grouped_task("task-a", "MPNLONG")
    approved_lookup = {item["folder_name"]: item for item in items}

    def length_report(_profile, parent_sku, _variants, **_kwargs):
        child = f"{parent_sku}-HEATHERGREY-11Y"
        return {
            "max_length": len(child),
            "longest": [{"sku": child, "length": len(child)}],
            "oversized": [child] if len(child) > app.MAX_AMAZON_SKU_LENGTH else [],
            "count": 1,
        }

    monkeypatch.setattr(app, "build_child_sku_length_report", length_report)
    assessment = app.assess_approved_sku_replacements(
        list(approved_lookup),
        approved_lookup,
        '"MPNLONG"=>"MPN"\n"DEF-"=>"D-"',
    )

    assert assessment["valid"] is True
    assert assessment["safe"] is True
    assert len(assessment["rows"]) == 3
    for row in assessment["rows"]:
        assert row["old_parent_sku"].startswith("DEF-MPNLONG-")
        assert row["new_parent_sku"].startswith("D-MPN-")
        assert row["new_listing_code"] == "MPN"
        assert row["new_decoration_code"] == "D"
        assert row["child_max_after"] < row["child_max_before"]


def test_sku_rule_apply_updates_saved_identity_and_rejects_stale_rules(monkeypatch) -> None:
    items = approved_grouped_task("task-a", "MPNLONG")
    approved_lookup = {item["folder_name"]: item for item in items}
    monkeypatch.setattr(
        app,
        "build_child_sku_length_report",
        lambda _profile, parent, _variants, **_kwargs: {
            "max_length": len(parent) + 2,
            "longest": [{"sku": f"{parent}-S", "length": len(parent) + 2}],
            "oversized": [],
            "count": 1,
        },
    )
    saved = []
    monkeypatch.setattr(app, "save_listing_inputs_json_to_dropbox", lambda **kwargs: saved.append(kwargs))
    monkeypatch.setattr(app, "clear_cached_listing_memory", lambda *_args: None)
    assessment = app.assess_approved_sku_replacements(
        list(approved_lookup), approved_lookup, "MPNLONG=>MPN"
    )

    applied = app.apply_assessed_sku_replacements(assessment, approved_lookup, {})

    assert len(applied) == 3
    assert len(saved) == 3
    assert {item["listing_memory"]["mpn"] for item in items} == {"MPN"}
    assert {item["listing_memory"]["sku_listing_code"] for item in items} == {"MPN"}
    assert all("-MPN-" in item["listing_memory"]["parent_sku"] for item in items)

    with pytest.raises(ValueError, match="changed after assessment"):
        app.apply_assessed_sku_replacements(assessment, approved_lookup, {})


def test_sku_rule_assessment_requires_all_christmas_members_for_mpn_change(monkeypatch) -> None:
    items = approved_grouped_task("task-a", "LONG")[:2]
    monkeypatch.setattr(
        app,
        "build_child_sku_length_report",
        lambda *_args, **_kwargs: {"max_length": 10, "longest": [], "oversized": [], "count": 1},
    )
    result = app.assess_approved_sku_replacements(
        [item["folder_name"] for item in items],
        {item["folder_name"]: item for item in items},
        "LONG=>X",
    )
    assert result["valid"] is False
    assert any("select T-Shirt, Sweatshirt, and Hoodie" in error for error in result["errors"])


def test_overlong_sku_replacement_remains_blocked(monkeypatch) -> None:
    items = approved_grouped_task("task-a", "LONG")
    approved_lookup = {item["folder_name"]: item for item in items}
    monkeypatch.setattr(
        app,
        "build_child_sku_length_report",
        lambda _profile, parent, _variants, **_kwargs: {
            "max_length": len(parent) + 20,
            "longest": [{"sku": f"{parent}-A-VERY-LONG-VARIANT", "length": len(parent) + 20}],
            "oversized": [f"{parent}-A-VERY-LONG-VARIANT"] if len(parent) + 20 > 30 else [],
            "count": 1,
        },
    )
    result = app.assess_approved_sku_replacements(
        list(approved_lookup), approved_lookup, "LONG=>STILLTOOLONG"
    )

    assert result["valid"] is True
    assert result["safe"] is False
    with pytest.raises(ValueError, match="within the SKU length limit"):
        app.apply_assessed_sku_replacements(result, approved_lookup, {})


def test_approved_generation_ui_exposes_sku_rule_preview_and_apply_controls() -> None:
    source = Path(app.__file__).read_text(encoding="utf-8")
    assert 'key="approved_queue_sku_replace_rules"' in source
    assert '"Assess SKU lengths / rules"' in source
    assert 'key="approved_queue_apply_sku_replace_rules_btn"' in source
    assert "Amazon/app seller SKU maximum" in source


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

    assert selected["size"] == ["2Yr", "11Yr"]
    assert prices == {
        "Kids T-Shirt||2Yr": 12.5,
        "Kids T-Shirt||11Yr": 14.5,
    }
    assert app.normalize_saved_variant_values_for_profile(profile, {
        "size": ["1Yr"],
    })["size"] == ["2Yr"]


@pytest.mark.parametrize(
    ("size", "expected_size", "expected_size_to", "expected_class"),
    [
        ("1Yr", "1 Year", "", "Age"),
        ("3Yr", "3 Years", "", "Age"),
        ("1-2 Years", "1 Year", "2 Years", "Age"),
        ("3/4 YRS", "3 Years", "4 Years", "Age"),
        ("5/6 YRS", "5 Years", "6 Years", "Age"),
        ("7/8 YRS", "7 Years", "8 Years", "Age"),
        ("9/10 YRS", "9 Years", "10 Years", "Age"),
        ("9/11 YRS", "9 Years", "11 Years", "Age"),
        ("11/13 YRS", "11 Years", "13 Years", "Age"),
        ("12/13 Years", "12 Years", "13 Years", "Age"),
        ("2XL", "XXL", "", "Alpha"),
    ],
)
def test_amazon_apparel_size_fields_use_template_values(
    size,
    expected_size,
    expected_size_to,
    expected_class,
) -> None:
    values = app.apply_apparel_size_fields({}, size, is_apparel=True)

    assert values["apparel_size"] == expected_size
    assert values["apparel_size_to"] == expected_size_to
    assert values["shirt_size"] == expected_size
    assert values["shirt_size_to"] == expected_size_to
    assert values["apparel_size_class"] == expected_class
    assert values["shirt_size_class"] == expected_class


@pytest.mark.parametrize(
    ("size", "expected_size", "expected_size_to"),
    [
        ("2Yr", "2 Years", ""),
        ("3Yr", "3 Years", "4 Years"),
        ("5Yr", "5 Years", "6 Years"),
        ("7Yr", "7 Years", "8 Years"),
        ("9Yr", "9 Years", "11 Years"),
        ("11Yr", "11 Years", "13 Years"),
    ],
)
def test_generic_shirt_compact_kids_sizes_restore_configured_ranges(
    size,
    expected_size,
    expected_size_to,
) -> None:
    profile = next(
        item
        for item in app.list_template_profiles()
        if item.get("template_key") == "GENERIC_SHIRTS"
    )

    values = app.apply_apparel_size_fields(
        {},
        size,
        is_apparel=True,
        profile=profile,
    )

    assert values["apparel_size"] == expected_size
    assert values["apparel_size_to"] == expected_size_to
    assert values["shirt_size"] == expected_size
    assert values["shirt_size_to"] == expected_size_to


@pytest.mark.parametrize(
    ("template_key", "size", "expected_size", "expected_size_to"),
    [
        ("GENERIC_SHIRTS", "2Yr", "2 Years", ""),
        ("UC301", "2 Years", "2 Years", ""),
        ("UC301", "9-11 Years", "9 Years", "11 Years"),
        ("CP", "11/13 YRS", "11 Years", "13 Years"),
    ],
)
def test_generic_uc301_and_special_projects_share_amazon_age_size_rules(
    template_key,
    size,
    expected_size,
    expected_size_to,
) -> None:
    profile = next(
        item
        for item in app.list_template_profiles()
        if item.get("template_key") == template_key
    )

    values = app.apply_apparel_size_fields(
        {
            "apparel_body_type": "Regular",
            "apparel_height_type": "Regular",
        },
        size,
        is_apparel=True,
        profile=profile,
    )

    assert values["apparel_size_system"] == "UK"
    assert values["apparel_size_class"] == "Age"
    assert values["apparel_size"] == expected_size
    assert values["apparel_size_to"] == expected_size_to
    assert values["shirt_size_system"] == "UK"
    assert values["shirt_size_class"] == "Age"
    assert values["shirt_size"] == expected_size
    assert values["shirt_size_to"] == expected_size_to
    assert values["apparel_body_type"] == ""
    assert values["apparel_height_type"] == ""
    assert values["shirt_body_type"] == "Regular"
    assert values["shirt_height_type"] == ""


@pytest.mark.parametrize("size", ["1Yr", "3/4 YRS", "11/13 YRS"])
def test_amazon_age_sizes_keep_only_required_shirt_body_type(size) -> None:
    values = app.apply_apparel_size_fields(
        {
            "apparel_body_type": "Regular",
            "shirt_body_type": "Regular",
            "apparel_height_type": "Regular",
            "shirt_height_type": "Regular",
        },
        size,
        is_apparel=True,
    )

    assert values["apparel_body_type"] == ""
    assert values["shirt_body_type"] == "Regular"
    assert values["apparel_height_type"] == ""
    assert values["shirt_height_type"] == ""


def test_amazon_alpha_sizes_keep_regular_body_and_height_types() -> None:
    values = app.apply_apparel_size_fields({}, "M", is_apparel=True)

    assert values["apparel_body_type"] == "Regular"
    assert values["shirt_body_type"] == "Regular"
    assert values["apparel_height_type"] == "Regular"
    assert values["shirt_height_type"] == "Regular"


def test_age_size_normalization_keeps_only_required_shirt_body_type_alias() -> None:
    aliases = app.get_field_aliases({})
    values = app.prepare_row_values(
        {},
        aliases,
        {"apparel_body_type": "Regular", "apparel_height_type": "Regular"},
    )

    values = app.finalize_apparel_size_fields(
        values,
        "3/4 YRS",
        is_apparel=True,
        profile={},
        field_aliases=aliases,
    )

    assert values["shirt_body_type"] == "Regular"
    for field in ["apparel_body_type", "tops_body_type", "outerwear_body_type"]:
        assert values[field] == ""
    for field in ["apparel_height_type", *aliases["apparel_height_type"]]:
        assert values[field] == ""


@pytest.mark.parametrize(
    ("template_key", "size"),
    [
        ("GENERIC_SHIRTS", "2Yr"),
        ("GENERIC_HOODIES", "2 YRS"),
        ("UC301", "2 Years"),
        ("CP", "2 YRS"),
    ],
)
def test_kids_shirt_and_hoodie_rows_finalize_with_regular_shirt_body_type(
    template_key,
    size,
) -> None:
    profile = next(
        item
        for item in app.list_template_profiles()
        if item.get("template_key") == template_key
    )
    aliases = app.get_field_aliases(profile)

    values = app.finalize_apparel_size_fields(
        app.prepare_row_values({}, aliases, app.get_extra_child_fields(profile)),
        size,
        is_apparel=True,
        profile=profile,
        field_aliases=aliases,
    )

    assert values["apparel_body_type"] == ""
    assert values["shirt_body_type"] == "Regular"
    assert values["shirt_height_type"] == ""


@pytest.mark.parametrize(
    ("design", "size", "expected_price"),
    [
        ("Adult T-Shirt", "S", 11.99),
        ("Adult T-Shirt", "2XL", 11.99),
        ("Adult T-Shirt", "3XL", 13.99),
        ("Adult T-Shirt", "4XL", 13.99),
        ("Kids T-Shirt", "5/6 YRS", 9.99),
        ("Adult Sweatshirt", "S", 19.99),
        ("Adult Sweatshirt", "4XL", 21.99),
        ("Kids Sweatshirt", "5/6 YRS", 18.99),
        ("Adult Hoodie", "S", 21.99),
        ("Adult Hoodie", "4XL", 23.99),
        ("Kids Hoodie", "5/6 YRS", 19.99),
    ],
)
def test_cp_design_size_defaults_use_configured_prices(
    design,
    size,
    expected_price,
) -> None:
    profile = load_cp_profile()

    assert app.get_default_price_for_size(
        profile,
        size,
        design=design,
    ) == expected_price


def test_saved_cp_design_size_price_wins_over_profile_default() -> None:
    profile = load_cp_profile()

    assert app.get_default_price_for_size(
        profile,
        "M",
        {"Adult Hoodie||M": 27.49},
        design="Adult Hoodie",
    ) == 27.49


@pytest.mark.parametrize(
    ("template_key", "parent_sku", "variant", "expected_sku"),
    [
        (
            "GENERIC_SHIRTS",
            "PRINT-XMDARTN-T",
            {"design": "Kids T-Shirt", "color": "Black", "size": "3Yr"},
            "PRINT-XMDARTN-T-BLAC-3Y",
        ),
        (
            "GENERIC_SWEATSHIRTS",
            "PRINT-XMDARTN-S",
            {"design": "Kids Sweatshirt", "color": "Black", "size": "3/4 YRS"},
            "PRINT-XMDARTN-S-BLAC-3Y",
        ),
        (
            "GENERIC_HOODIES",
            "PRINT-XMDARTN-H",
            {"design": "Kids Hoodie", "color": "Black", "size": "3/4 YRS"},
            "PRINT-XMDARTN-H-BLAC-3Y",
        ),
    ],
)
def test_christmas_target_child_skus_omit_redundant_design_code(
    template_key,
    parent_sku,
    variant,
    expected_sku,
) -> None:
    profile = next(
        item for item in app.list_template_profiles()
        if item.get("template_key") == template_key
    )

    assert app.build_child_sku(profile, parent_sku, variant) == expected_sku


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
