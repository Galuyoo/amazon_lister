from __future__ import annotations

import inspect

import app


def test_grouped_christmas_provenance_wins_over_generic_template_identity() -> None:
    origin, member, task_id = app.classify_finished_listing_origin({
        "template_key": "GENERIC_SHIRTS",
        "source_group": {
            "group_type": "christmas_project",
            "member_key": "tshirt",
            "task_id": "task-xmas-1",
        },
    })

    assert origin == "Grouped Christmas"
    assert member == "T-Shirt"
    assert task_id == "task-xmas-1"


def test_genuine_generic_and_single_christmas_listings_remain_distinct() -> None:
    assert app.classify_finished_listing_origin({"template_key": "GENERIC_HOODIES"}) == (
        "Generic listing",
        "",
        "",
    )
    assert app.classify_finished_listing_origin({"template_key": "CP"}) == (
        "Christmas Project (single)",
        "",
        "",
    )


def test_finished_history_uses_saved_generation_and_group_metadata(monkeypatch) -> None:
    memories = {
        "/finished/PRINT-XMAS-T": {
            "template_key": "GENERIC_SHIRTS",
            "template_label": "Generic Shirts",
            "parent_sku": "PRINT-XMAS-T",
            "title": "Christmas T-Shirt",
            "source_group": {
                "group_type": "christmas_project",
                "member_key": "tshirt",
                "task_id": "task-xmas-1",
            },
            "generated_outputs": [{
                "created_at": "2026-09-02 14:05:10",
                "workbook_name": "PRINT-XMAS-T.xlsm",
            }],
        },
        "/finished/PRINT-GENERIC": {
            "template_key": "GENERIC_HOODIES",
            "template_label": "Generic Hoodies",
            "parent_sku": "PRINT-GENERIC",
            "title": "Generic Hoodie",
            "sku_manifest": {
                "created_at": "2026-09-01 10:30:00",
                "output_workbook_name": "PRINT-GENERIC.xlsm",
            },
        },
    }
    monkeypatch.setattr(app, "load_listing_memory_from_dropbox", lambda path: memories[path])
    monkeypatch.setattr(app, "find_profile_for_listing_memory", lambda _profiles, _memory: None)

    rows = app.build_finished_generation_history_rows(
        ["PRINT-GENERIC", "PRINT-XMAS-T"],
        [],
        {"finished_root": "/finished"},
    )

    assert [row["folder_name"] for row in rows] == ["PRINT-XMAS-T", "PRINT-GENERIC"]
    assert rows[0]["origin"] == "Grouped Christmas"
    assert rows[0]["christmas_member"] == "T-Shirt"
    assert rows[0]["history_group"] == "task-xmas-1"
    assert rows[0]["workbook"] == "PRINT-XMAS-T.xlsm"
    assert rows[1]["origin"] == "Generic listing"
    assert rows[1]["history_group"] == "2026-09-01 10:30"


def test_finished_history_reports_unreadable_memory_without_aborting(monkeypatch) -> None:
    monkeypatch.setattr(
        app,
        "load_listing_memory_from_dropbox",
        lambda _path: (_ for _ in ()).throw(RuntimeError("Dropbox unavailable")),
    )

    rows = app.build_finished_generation_history_rows(
        ["BROKEN"],
        [],
        {"finished_root": "/finished"},
    )

    assert rows[0]["folder_name"] == "BROKEN"
    assert rows[0]["origin"] == "Unknown"
    assert "Dropbox unavailable" in rows[0]["load_status"]


def test_finished_history_loader_is_read_only() -> None:
    source = inspect.getsource(app.build_finished_generation_history_rows)

    assert "load_listing_memory_from_dropbox(" in source
    assert "save_listing_inputs_json_to_dropbox(" not in source
    assert "move_dropbox_folder(" not in source
    assert "upload_" not in source
