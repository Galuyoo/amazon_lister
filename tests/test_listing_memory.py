from __future__ import annotations

import importlib
import json
import sys

from services.listing_memory import (
    DEFAULT_HANDLING_TIME_DAYS,
    DEFAULT_MERCHANT_SHIPPING_GROUP,
    DEFAULT_VARIANT_QUANTITY,
    MERCHANT_SHIPPING_GROUP_OPTIONS,
    build_listing_memory_payload,
    build_listing_memory_path,
    normalize_handling_time_days,
    normalize_merchant_shipping_group,
    normalize_variant_quantity,
)


def sample_profile() -> dict:
    return {
        "label": "Generic Shirts",
        "_slug": "generic-shirts",
        "template_key": "SHIRT_GENERIC",
    }


def sample_payload() -> dict:
    return {
        "title": "A test listing",
        "product_description": "Description",
        "generic_keywords": "keyword one keyword two",
        "bullet_points": ["Bullet 1", "Bullet 2"],
        "selected_variants": {"color": ["Red"], "size": ["M"]},
        "size_price_map": {"M": 12.99},
        "price_input_mode": "per_size",
        "use_same_price_for_all_sizes": True,
        "write_parent_starting_price": True,
        "sku_decoration_code": "PRINT",
        "manual_sku_listing_code": "MANUAL",
        "generated_sku_listing_code": "D12345",
        "sku_listing_code": "MANUAL",
        "base_parent_sku": "BASE-SKU",
        "parent_sku": "BASE-SKU-MANUAL",
        "quantity": "42",
        "handling_time_days": "3",
        "merchant_shipping_group_name": "Nationwide Prime",
        "assets_prepared_by": "Sal",
        "content_prepared_by": "Suleman",
        "reviewed_by": "Khalid",
        "prepared_at": "2026-08-20 10:00:00",
        "reviewed_at": "2026-08-20 10:10:00",
        "parent_main_image_choice": "Automatic (recommended)",
        "parent_main_image_url": "https://example.test/main.jpg",
    }


def test_normal_listing_memory_payload_preserves_standard_fields() -> None:
    memory = build_listing_memory_payload(sample_profile(), sample_payload())

    assert memory == {
        "template_label": "Generic Shirts",
        "template_slug": "generic-shirts",
        "template_key": "SHIRT_GENERIC",
        "title": "A test listing",
        "product_description": "Description",
        "generic_keywords": "keyword one keyword two",
        "bullet_points": ["Bullet 1", "Bullet 2"],
        "selected_variants": {"color": ["Red"], "size": ["M"]},
        "size_price_map": {"M": 12.99},
        "price_input_mode": "per_size",
        "use_same_price_for_all_sizes": True,
        "write_parent_starting_price": True,
        "sku_decoration_code": "PRINT",
        "manual_sku_listing_code": "MANUAL",
        "generated_sku_listing_code": "D12345",
        "sku_listing_code": "MANUAL",
        "base_parent_sku": "BASE-SKU",
        "parent_sku": "BASE-SKU-MANUAL",
        "quantity": 42,
        "handling_time_days": 3,
        "merchant_shipping_group_name": "Nationwide Prime",
        "assets_prepared_by": "Sal",
        "content_prepared_by": "Suleman",
        "reviewed_by": "Khalid",
        "prepared_at": "2026-08-20 10:00:00",
        "reviewed_at": "2026-08-20 10:10:00",
        "parent_main_image_choice": "Automatic (recommended)",
        "parent_main_image_url": "https://example.test/main.jpg",
    }


def test_optional_review_and_workflow_metadata_is_preserved_when_supplied() -> None:
    payload = sample_payload()
    payload.update(
        {
            "review_snapshot": {"status": "approved"},
            "workflow_events": [{"action": "approve", "to_state": "approved"}],
            "ignored_generations": [{"folder_name": "SKU-1"}],
            "generation_status": "generated",
            "ignored_at": "2026-08-20 11:00:00",
            "ignored_by": "Sal",
            "ignored_reason": "duplicate",
            "finished_folder_sku": "SKU-1",
            "pending_finished_folder_path": "/Finished/SKU-1",
        }
    )

    memory = build_listing_memory_payload(sample_profile(), payload)

    assert memory["review_snapshot"] == {"status": "approved"}
    assert memory["workflow_events"] == [{"action": "approve", "to_state": "approved"}]
    assert memory["ignored_generations"] == [{"folder_name": "SKU-1"}]
    assert memory["generation_status"] == "generated"
    assert memory["ignored_at"] == "2026-08-20 11:00:00"
    assert memory["ignored_by"] == "Sal"
    assert memory["ignored_reason"] == "duplicate"
    assert memory["finished_folder_sku"] == "SKU-1"
    assert memory["pending_finished_folder_path"] == "/Finished/SKU-1"


def test_original_finished_folder_name_is_preserved() -> None:
    payload = sample_payload()
    payload["original_finished_folder_name"] = "  OLD-FINISHED-SKU  "

    memory = build_listing_memory_payload(sample_profile(), payload)

    assert memory["original_finished_folder_name"] == "OLD-FINISHED-SKU"


def test_generated_outputs_and_sku_manifest_are_preserved() -> None:
    payload = sample_payload()
    payload["generated_outputs"] = [{"workbook": "listing.xlsx"}]
    payload["sku_manifest"] = {"parent": "BASE-SKU-MANUAL"}

    memory = build_listing_memory_payload(sample_profile(), payload)

    assert memory["generated_outputs"] == [{"workbook": "listing.xlsx"}]
    assert memory["sku_manifest"] == {"parent": "BASE-SKU-MANUAL"}


def test_optional_fields_currently_omitted_when_empty_remain_omitted() -> None:
    payload = sample_payload()
    payload.update(
        {
            "original_finished_folder_name": " ",
            "generation_status": "",
            "ignored_at": None,
            "ignored_by": [],
            "ignored_reason": {},
            "finished_folder_sku": "",
            "pending_finished_folder_path": "",
        }
    )

    memory = build_listing_memory_payload(sample_profile(), payload)

    for field_name in [
        "original_finished_folder_name",
        "generation_status",
        "ignored_at",
        "ignored_by",
        "ignored_reason",
        "finished_folder_sku",
        "pending_finished_folder_path",
    ]:
        assert field_name not in memory


def test_quantity_and_fulfillment_values_preserve_normalization_defaults() -> None:
    assert normalize_variant_quantity("0") == DEFAULT_VARIANT_QUANTITY
    assert normalize_variant_quantity("-5") == DEFAULT_VARIANT_QUANTITY
    assert normalize_variant_quantity("7") == 7
    assert normalize_handling_time_days("-3") == 0
    assert normalize_handling_time_days("bad") == DEFAULT_HANDLING_TIME_DAYS
    assert normalize_merchant_shipping_group(" Nationwide Prime ") == "Nationwide Prime"
    assert normalize_merchant_shipping_group("") == DEFAULT_MERCHANT_SHIPPING_GROUP
    assert normalize_merchant_shipping_group(None) == DEFAULT_MERCHANT_SHIPPING_GROUP
    assert normalize_merchant_shipping_group("Unknown group") == DEFAULT_MERCHANT_SHIPPING_GROUP
    assert "" not in MERCHANT_SHIPPING_GROUP_OPTIONS
    assert MERCHANT_SHIPPING_GROUP_OPTIONS[0] == DEFAULT_MERCHANT_SHIPPING_GROUP

    memory = build_listing_memory_payload(
        sample_profile(),
        {"quantity": "bad", "handling_time_days": "bad", "merchant_shipping_group_name": "Unknown group"},
    )

    assert memory["quantity"] == DEFAULT_VARIANT_QUANTITY
    assert memory["handling_time_days"] == DEFAULT_HANDLING_TIME_DAYS
    assert memory["merchant_shipping_group_name"] == DEFAULT_MERCHANT_SHIPPING_GROUP


def test_building_memory_does_not_mutate_input_lists_or_dictionaries() -> None:
    payload = sample_payload()
    original_bullets = list(payload["bullet_points"])
    original_variants = dict(payload["selected_variants"])
    original_review_snapshot = {"status": "approved"}
    original_workflow_events = [{"action": "approve"}]
    payload["review_snapshot"] = original_review_snapshot
    payload["workflow_events"] = original_workflow_events

    memory = build_listing_memory_payload(sample_profile(), payload)
    memory["review_snapshot"]["status"] = "changed"
    memory["workflow_events"].append({"action": "finish"})

    assert payload["bullet_points"] == original_bullets
    assert payload["selected_variants"] == original_variants
    assert payload["review_snapshot"] == original_review_snapshot
    assert payload["workflow_events"] == original_workflow_events


def test_existing_single_listing_json_shape_remains_compatible() -> None:
    memory = build_listing_memory_payload(sample_profile(), sample_payload())
    loaded = json.loads(json.dumps(memory))

    assert loaded["template_slug"] == "generic-shirts"
    assert loaded["selected_variants"] == {"color": ["Red"], "size": ["M"]}
    assert build_listing_memory_path("/Stage/Folder") == "/Stage/Folder/listing_inputs.json"
    assert "listing_mode" not in loaded
    assert "group_items" not in loaded


def test_mpn_is_additive_and_preserved_exactly_when_present() -> None:
    payload = sample_payload()
    payload["mpn"] = "Admin MPN-001"

    memory = build_listing_memory_payload(sample_profile(), payload)

    assert memory["mpn"] == "Admin MPN-001"
    assert "mpn" not in build_listing_memory_payload(sample_profile(), sample_payload())


def test_source_group_is_additive_and_preserved_without_mutation() -> None:
    payload = sample_payload()
    payload["source_group"] = {
        "schema_version": 1,
        "group_type": "christmas_project",
        "task_id": "task-1",
        "member_key": "hoodie",
        "source_mpn": "CHRTST",
        "materialization_hash": "abc123",
    }

    memory = build_listing_memory_payload(sample_profile(), payload)

    assert memory["source_group"] == payload["source_group"]
    assert memory["source_group"] is not payload["source_group"]
    assert "source_group" not in build_listing_memory_payload(sample_profile(), sample_payload())


def test_group_submission_ledger_is_additive_and_preserved_without_mutation() -> None:
    payload = sample_payload()
    payload["listing_group"] = {
        "schema_version": 1,
        "group_type": "christmas_project",
        "task_id": "task-1",
        "members": {"hoodie": {"title": "Hoodie title"}},
    }
    payload["group_submission"] = {
        "schema_version": 1,
        "task_id": "task-1",
        "state": "publishing",
        "children": {"hoodie": {"status": "published_pending"}},
        "last_error": "",
    }

    memory = build_listing_memory_payload(sample_profile(), payload)

    assert memory["listing_group"] == payload["listing_group"]
    assert memory["listing_group"] is not payload["listing_group"]
    assert memory["group_submission"] == payload["group_submission"]
    assert memory["group_submission"] is not payload["group_submission"]
    assert "group_submission" not in build_listing_memory_payload(sample_profile(), sample_payload())


def test_importing_listing_memory_does_not_import_streamlit_or_dropbox() -> None:
    for module_name in list(sys.modules):
        if module_name == "services.listing_memory" or module_name.startswith("streamlit"):
            del sys.modules[module_name]
        if "dropbox" in module_name.lower() or module_name.startswith("utils.dropbox_client"):
            del sys.modules[module_name]

    importlib.import_module("services.listing_memory")

    assert not any(module_name.startswith("streamlit") for module_name in sys.modules)
    assert not any("dropbox" in module_name.lower() for module_name in sys.modules)
