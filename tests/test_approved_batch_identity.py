from __future__ import annotations

from copy import deepcopy

from services.approved_batch_identity import assess_grouped_christmas_mpn_changes


def grouped_task(task_id: str, code: str) -> list[dict]:
    return [
        {
            "folder_name": f"folder-{task_id}-{member}",
            "listing_memory": {
                "template_key": template,
                "title": f"Title {member}",
                "sku_decoration_code": "PRINT",
                "mpn": code,
                "sku_listing_code": code,
                "parent_sku": f"PRINT-{code}-{suffix}",
                "parent_sku_override": f"PRINT-{code}-{suffix}",
                "source_group": {
                    "group_type": "christmas_project",
                    "task_id": task_id,
                    "member_key": member,
                },
            },
        }
        for member, suffix, template in [
            ("tshirt", "T", "GENERIC_SHIRTS"),
            ("sweatshirt", "S", "GENERIC_SWEATSHIRTS"),
            ("hoodie", "H", "GENERIC_HOODIES"),
        ]
    ]


def test_assessment_changes_one_complete_duplicate_task_with_same_length_code() -> None:
    items = grouped_task("task-a", "XMB") + grouped_task("task-b", "XMB")

    result = assess_grouped_christmas_mpn_changes(items)

    assert result["valid"] is True
    assert len(result["changes"]) == 3
    assert {row["task_id"] for row in result["changes"]} == {"task-b"}
    assert {row["old_listing_code"] for row in result["changes"]} == {"XMB"}
    new_codes = {row["new_listing_code"] for row in result["changes"]}
    assert len(new_codes) == 1
    new_code = next(iter(new_codes))
    assert len(new_code) == 3
    assert new_code != "XMB"
    assert {row["new_parent_sku"] for row in result["changes"]} == {
        f"PRINT-{new_code}-T",
        f"PRINT-{new_code}-S",
        f"PRINT-{new_code}-H",
    }


def test_assessment_is_deterministic_avoids_reserved_codes_and_does_not_mutate() -> None:
    items = grouped_task("task-a", "ABC") + grouped_task("task-b", "ABC")
    original = deepcopy(items)
    first = assess_grouped_christmas_mpn_changes(items)
    allocated = first["changes"][0]["new_listing_code"]
    second = assess_grouped_christmas_mpn_changes(items, reserved_listing_codes=[allocated])

    assert items == original
    assert first == assess_grouped_christmas_mpn_changes(items)
    assert second["changes"][0]["new_listing_code"] != allocated
    assert len(second["changes"][0]["new_listing_code"]) == 3


def test_assessment_changes_only_listing_code_segment_of_existing_parent_sku() -> None:
    items = grouped_task("task-a", "ABC") + grouped_task("task-b", "ABC")
    for item in items:
        if item["listing_memory"]["source_group"]["task_id"] == "task-b":
            suffix = item["listing_memory"]["parent_sku"].rsplit("-", 1)[-1]
            item["listing_memory"]["parent_sku"] = f"CUSTOM-ABC-{suffix}"
            item["listing_memory"]["parent_sku_override"] = f"CUSTOM-ABC-{suffix}"

    result = assess_grouped_christmas_mpn_changes(items)
    new_code = result["changes"][0]["new_listing_code"]

    assert {row["new_parent_sku"] for row in result["changes"]} == {
        f"CUSTOM-{new_code}-T",
        f"CUSTOM-{new_code}-S",
        f"CUSTOM-{new_code}-H",
    }


def test_assessment_rejects_incomplete_task_and_non_grouped_listing() -> None:
    incomplete = grouped_task("task-a", "ABC")[:2] + grouped_task("task-b", "ABC")
    result = assess_grouped_christmas_mpn_changes(incomplete)
    assert result["valid"] is False
    assert any("must include" in error for error in result["errors"])

    result = assess_grouped_christmas_mpn_changes([
        {"folder_name": "normal", "listing_memory": {"template_key": "GENERIC_SHIRTS"}}
    ])
    assert result["valid"] is False
    assert any("not a grouped Christmas" in error for error in result["errors"])
