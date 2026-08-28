from __future__ import annotations

from unittest.mock import Mock

import app


DROPBOX_CONFIG = {
    "stage_root": "/Amazon/_stage",
    "grouped_archive_root": "/Amazon/_grouped_archive",
}


def grouped_memory() -> dict:
    return {
        "template_key": "CP",
        "mpn": "CHRTST",
        "listing_group": {
            "schema_version": 1,
            "group_type": "christmas_project",
            "task_id": "task-chrtst-1",
            "members": {
                "tshirt": {},
                "sweatshirt": {},
                "hoodie": {},
            },
        },
        "group_submission": {"state": "released"},
    }


def test_active_grouped_stage_memory_is_passed_through_unchanged() -> None:
    memory = grouped_memory()
    exists = Mock()
    load_fresh = Mock()

    result = app.resolve_active_staged_listing_memory(
        dropbox_cfg=DROPBOX_CONFIG,
        staged_folder_name="CHRTST",
        load_stage_memory=Mock(return_value=memory),
        destination_exists=exists,
        load_fresh_memory=load_fresh,
    )

    assert result == {"memory": memory, "location": "stage", "error": ""}
    assert result["memory"] is memory
    exists.assert_not_called()
    load_fresh.assert_not_called()


def test_missing_stage_loads_complete_authoritative_grouped_archive() -> None:
    memory = grouped_memory()
    exists = Mock(side_effect=lambda path: path.endswith("/_grouped_archive/CHRTST"))
    load_fresh = Mock(return_value=memory)

    result = app.resolve_active_staged_listing_memory(
        dropbox_cfg=DROPBOX_CONFIG,
        staged_folder_name="CHRTST",
        load_stage_memory=Mock(return_value={}),
        destination_exists=exists,
        load_fresh_memory=load_fresh,
    )

    assert result == {"memory": memory, "location": "archive", "error": ""}
    assert result["memory"] is memory
    load_fresh.assert_called_once_with("/Amazon/_grouped_archive/CHRTST")


def test_malformed_grouped_archive_fails_closed() -> None:
    malformed = {
        "template_key": "CP",
        "group_submission": {"state": "released"},
    }

    result = app.resolve_active_staged_listing_memory(
        dropbox_cfg=DROPBOX_CONFIG,
        staged_folder_name="CHRTST",
        load_stage_memory=Mock(return_value={}),
        destination_exists=Mock(side_effect=[False, True]),
        load_fresh_memory=Mock(return_value=malformed),
    )

    assert result["memory"] is malformed
    assert result["location"] == "archive"
    assert "Grouped Christmas state could not be loaded" in result["error"]


def test_missing_active_folder_fails_closed_without_inventing_grouped_state() -> None:
    result = app.resolve_active_staged_listing_memory(
        dropbox_cfg=DROPBOX_CONFIG,
        staged_folder_name="CHRTST",
        load_stage_memory=Mock(return_value={}),
        destination_exists=Mock(return_value=False),
        load_fresh_memory=Mock(),
    )

    assert result["memory"] == {}
    assert result["location"] == "missing"
    assert "no longer exists" in result["error"]


def test_existing_empty_stage_folder_does_not_force_grouped_mode_from_label() -> None:
    load_fresh = Mock()

    result = app.resolve_active_staged_listing_memory(
        dropbox_cfg=DROPBOX_CONFIG,
        staged_folder_name="CHRTST",
        load_stage_memory=Mock(return_value={}),
        destination_exists=Mock(return_value=True),
        load_fresh_memory=load_fresh,
    )

    assert result == {"memory": {}, "location": "stage", "error": ""}
    assert app.is_grouped_christmas_memory(result["memory"]) is False
    load_fresh.assert_not_called()


def test_stage_memory_read_failure_blocks_editing() -> None:
    result = app.resolve_active_staged_listing_memory(
        dropbox_cfg=DROPBOX_CONFIG,
        staged_folder_name="CHRTST",
        load_stage_memory=Mock(side_effect=RuntimeError("read failed")),
        destination_exists=Mock(return_value=True),
        load_fresh_memory=Mock(),
    )

    assert result["memory"] == {}
    assert result["location"] == "stage"
    assert "could not be loaded" in result["error"]


def test_missing_stage_can_recover_archive_after_cached_loader_error() -> None:
    memory = grouped_memory()

    result = app.resolve_active_staged_listing_memory(
        dropbox_cfg=DROPBOX_CONFIG,
        staged_folder_name="CHRTST",
        load_stage_memory=Mock(side_effect=FileNotFoundError("stage moved")),
        destination_exists=Mock(side_effect=[False, True]),
        load_fresh_memory=Mock(return_value=memory),
    )

    assert result == {"memory": memory, "location": "archive", "error": ""}
