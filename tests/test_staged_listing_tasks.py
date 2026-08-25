from __future__ import annotations

import importlib
import inspect
import sys
from unittest.mock import Mock

import pytest

from services.listing_memory import DEFAULT_HANDLING_TIME_DAYS, build_listing_memory_payload
from services.staged_listing_tasks import (
    build_staged_listing_task_payload,
    create_staged_listing_task,
    get_task_size_options,
    validate_mpn,
)


def profile() -> dict:
    return {
        "label": "UC301 Classic T-Shirt",
        "_slug": "uc301",
        "template_key": "UC301",
        "parent_sku": "UC301",
        "sizes": ["S", "M", "L"],
        "write_parent_starting_price": True,
    }


def valid_task_result(**overrides):
    values = {
        "profile": profile(),
        "mpn": "ADMIN-MPN-001",
        "price": 12.99,
        "quantity": 25,
        "merchant_shipping_group_name": "Nationwide Prime",
        "selected_sizes": ["S", "M", "L"],
        "sku_decoration_code": "PRINT",
        "manual_sku_listing_code": "DESIGN1",
        "generated_sku_listing_code": "D12345",
        "sku_listing_code": "DESIGN1",
        "base_parent_sku": "UC301",
        "parent_sku": "PRINT-DESIGN1-UC301",
        "assets_prepared_by": "Sal",
    }
    values.update(overrides)
    return build_staged_listing_task_payload(**values)


def test_valid_task_uses_existing_listing_memory_shape() -> None:
    result = valid_task_result()

    assert result["valid"] is True
    assert result["errors"] == []
    assert result["payload"] == {
        "mpn": "ADMIN-MPN-001",
        "title": "",
        "bullet_points": [],
        "product_description": "",
        "generic_keywords": "",
        "selected_variants": {"size": ["S", "M", "L"]},
        "size_price_map": {"S": 12.99, "M": 12.99, "L": 12.99},
        "price_input_mode": "",
        "use_same_price_for_all_sizes": True,
        "write_parent_starting_price": True,
        "quantity": 25,
        "handling_time_days": DEFAULT_HANDLING_TIME_DAYS,
        "merchant_shipping_group_name": "Nationwide Prime",
        "sku_decoration_code": "PRINT",
        "manual_sku_listing_code": "DESIGN1",
        "generated_sku_listing_code": "D12345",
        "sku_listing_code": "DESIGN1",
        "base_parent_sku": "UC301",
        "parent_sku": "PRINT-DESIGN1-UC301",
        "assets_prepared_by": "Sal",
    }

    memory = build_listing_memory_payload(profile(), result["payload"])
    assert memory["template_label"] == "UC301 Classic T-Shirt"
    assert memory["template_slug"] == "uc301"
    assert memory["template_key"] == "UC301"
    assert memory["mpn"] == "ADMIN-MPN-001"


@pytest.mark.parametrize("mpn", ["", "   ", "BAD/MPN", "BAD\\MPN", ".", "..", " BAD"])
def test_invalid_mpn_is_rejected_without_rewriting(mpn: str) -> None:
    result = valid_task_result(mpn=mpn)

    assert result["valid"] is False
    assert validate_mpn(mpn)
    assert result["payload"]["mpn"] == mpn


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"price": 0}, "Price must be greater than zero."),
        ({"price": -1}, "Price must be greater than zero."),
        ({"quantity": 0}, "Quantity must be greater than zero."),
        ({"selected_sizes": []}, "Select at least one size."),
        ({"selected_sizes": ["XL"]}, "Selected sizes must come from the selected garment template."),
        ({"merchant_shipping_group_name": "Unknown"}, "Merchant Shipping Group must use an existing allowed option."),
    ],
)
def test_task_field_validation(overrides: dict, message: str) -> None:
    result = valid_task_result(**overrides)

    assert result["valid"] is False
    assert message in result["errors"]


def test_size_options_use_selected_profile_variant_dimension() -> None:
    dimension_profile = profile()
    dimension_profile["variant_dimensions"] = [
        {"name": "design", "options": ["Front", "Back"]},
        {"name": "size", "options": ["4 Years", "6 Years"]},
    ]

    assert get_task_size_options(dimension_profile) == ["4 Years", "6 Years"]
    assert get_task_size_options(profile()) == ["S", "M", "L"]


def test_successful_creation_creates_one_folder_and_writes_listing_inputs() -> None:
    payload = valid_task_result()["payload"]
    destination_exists = Mock(return_value=False)
    create_folder = Mock()
    save_memory = Mock(return_value="/Amazon/_stage/ADMIN-MPN-001/listing_inputs.json")

    result = create_staged_listing_task(
        profile=profile(),
        payload=payload,
        stage_root="/Amazon/_stage",
        destination_exists=destination_exists,
        create_folder=create_folder,
        save_listing_memory=save_memory,
    )

    assert result["status"] == "Success"
    assert result["folder_name"] == "ADMIN-MPN-001"
    destination_exists.assert_called_once_with("/Amazon/_stage/ADMIN-MPN-001")
    create_folder.assert_called_once_with("/Amazon/_stage/ADMIN-MPN-001")
    save_memory.assert_called_once_with(profile(), payload, "/Amazon/_stage/ADMIN-MPN-001")


def test_existing_destination_is_never_created_or_overwritten() -> None:
    create_folder = Mock()
    save_memory = Mock()

    result = create_staged_listing_task(
        profile=profile(),
        payload=valid_task_result()["payload"],
        stage_root="/Amazon/_stage",
        destination_exists=Mock(return_value=True),
        create_folder=create_folder,
        save_listing_memory=save_memory,
    )

    assert result["status"] == "Exists"
    create_folder.assert_not_called()
    save_memory.assert_not_called()


def test_exclusive_create_conflict_is_treated_as_existing_task() -> None:
    save_memory = Mock()
    result = create_staged_listing_task(
        profile=profile(),
        payload=valid_task_result()["payload"],
        stage_root="/Amazon/_stage",
        destination_exists=Mock(return_value=False),
        create_folder=Mock(side_effect=FileExistsError("conflict")),
        save_listing_memory=save_memory,
    )

    assert result["status"] == "Exists"
    save_memory.assert_not_called()


def test_folder_failure_does_not_write_listing_memory() -> None:
    save_memory = Mock()
    result = create_staged_listing_task(
        profile=profile(),
        payload=valid_task_result()["payload"],
        stage_root="/Amazon/_stage",
        destination_exists=Mock(return_value=False),
        create_folder=Mock(side_effect=RuntimeError("offline")),
        save_listing_memory=save_memory,
    )

    assert result["status"] == "Failed"
    assert result["folder_created"] is False
    save_memory.assert_not_called()


def test_memory_write_failure_is_reported_as_recoverable_partial_failure() -> None:
    result = create_staged_listing_task(
        profile=profile(),
        payload=valid_task_result()["payload"],
        stage_root="/Amazon/_stage",
        destination_exists=Mock(return_value=False),
        create_folder=Mock(),
        save_listing_memory=Mock(side_effect=RuntimeError("upload failed")),
    )

    assert result["status"] == "Partial failure"
    assert result["folder_created"] is True
    assert "left in place for recovery" in result["error"]


def test_task_service_has_no_workflow_generation_image_or_dropbox_dependency() -> None:
    source = inspect.getsource(create_staged_listing_task).lower()
    assert all(term not in source for term in (
        "move_dropbox_folder",
        "ready_root",
        "approved_root",
        "finished_root",
        "workbook",
        "image",
        "upload_binary",
    ))

    for module_name in list(sys.modules):
        if module_name == "services.staged_listing_tasks" or module_name.startswith("streamlit"):
            del sys.modules[module_name]
        if "dropbox" in module_name.lower():
            del sys.modules[module_name]
    importlib.import_module("services.staged_listing_tasks")
    assert not any(name.startswith("streamlit") for name in sys.modules)
    assert not any("dropbox" in name.lower() for name in sys.modules)
