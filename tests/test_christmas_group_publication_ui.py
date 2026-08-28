from __future__ import annotations

import json
import inspect
from pathlib import Path
from unittest.mock import Mock

import app
import pytest
from ui import listing_content


ROOT = Path(__file__).parents[1]


def load_cp_profile() -> dict:
    return json.loads(
        (ROOT / "templates" / "Special Projects" / "CP" / "config.json").read_text(
            encoding="utf-8"
        )
    )


def test_grouped_submission_button_summary_and_key_are_stable() -> None:
    source = inspect.getsource(listing_content.render_grouped_christmas_listing_content)
    assert 'st.subheader("Submit 3 listings for review")' in source
    assert '"Submit 3 listings for review"' in source
    assert '"Resume grouped submission"' in source
    assert 'key="grouped_christmas_submit_for_review_btn"' in source
    assert "submit_grouped_listing(" in source
    assert "st.rerun()" in source


def test_ready_queue_integration_hides_pending_but_keeps_released_and_ordinary(monkeypatch) -> None:
    items = [
        {"folder_name": "ordinary", "listing_memory": {}},
        {"folder_name": "pending", "listing_memory": {"source_group": {"group_type": "christmas_project", "release_status": "pending"}}},
        {"folder_name": "released", "listing_memory": {"source_group": {"group_type": "christmas_project", "release_status": "released"}}},
    ]
    build_queue = Mock(return_value=items)
    monkeypatch.setattr(app, "build_queue_items", build_queue)

    visible = app.build_ready_queue_items([], [], {})

    assert [item["folder_name"] for item in visible] == ["ordinary", "released"]


def test_normal_single_submit_implementation_remains_separate() -> None:
    source = inspect.getsource(app.main)
    assert "move_staged_dropbox_folder_to_ready(" in source
    renderer_source = inspect.getsource(listing_content.render_listing_content)
    assert "submit_grouped_listing=submit_grouped_listing" in renderer_source
    assert 'st.button("Submit for Review", width="stretch")' in renderer_source


def test_new_grouped_submit_injects_generic_targets_and_serializes_with_child_profile(
    monkeypatch,
) -> None:
    cp_profile = {"template_key": "CP", "label": "Christmas Project"}
    profiles = [
        cp_profile,
        {"template_key": "GENERIC_SHIRTS", "label": "Generic Shirts"},
        {"template_key": "GENERIC_SWEATSHIRTS", "label": "Generic Sweatshirts"},
        {"template_key": "GENERIC_HOODIES", "label": "Generic Hoodies"},
    ]
    saved = {}

    def publish(profile, **kwargs):
        assert {
            key: target["template_key"]
            for key, target in profile["_group_target_profiles"].items()
        } == {
            "tshirt": "GENERIC_SHIRTS",
            "sweatshirt": "GENERIC_SWEATSHIRTS",
            "hoodie": "GENERIC_HOODIES",
        }
        kwargs["storage"].save_memory(
            {"template_key": "GENERIC_SHIRTS", "title": "T-Shirt"},
            "/Amazon/ready/CHRTST-TSHIRT",
        )
        return {"success": False, "state": "blocked", "errors": []}

    monkeypatch.setattr(app, "path_exists_strict", Mock(return_value=False))
    monkeypatch.setattr(app, "publish_christmas_group", publish)
    monkeypatch.setattr(
        app,
        "save_listing_inputs_json_to_dropbox",
        lambda profile, payload, folder_path: saved.update({
            "profile": profile,
            "payload": payload,
            "folder_path": folder_path,
        }) or f"{folder_path}/listing_inputs.json",
    )

    app.submit_grouped_christmas_to_review(
        dropbox_cfg={
            "stage_root": "/Amazon/_stage",
            "ready_root": "/Amazon/ready",
            "grouped_preparation_root": "/Amazon/_prepare",
            "grouped_archive_root": "/Amazon/_archive",
        },
        staged_folder_name="CHRTST",
        profile=cp_profile,
        draft_payload={"template_key": "CP"},
        profiles=profiles,
    )

    assert saved["profile"]["template_key"] == "GENERIC_SHIRTS"
    assert saved["folder_path"] == "/Amazon/ready/CHRTST-TSHIRT"


def locked_source_memory() -> dict:
    return {
        "template_key": "CP",
        "listing_group": {"task_id": "task-1", "group_type": "christmas_project"},
        "group_submission": {
            "schema_version": 1,
            "task_id": "task-1",
            "state": "failed",
            "children": {
                member: {
                    "destination_folder": f"CHRTST-{member.upper()}",
                    "materialization_hash": f"hash-{member}",
                    "status": "released",
                }
                for member in ("tshirt", "sweatshirt", "hoodie")
            },
            "last_error": "archive response lost",
        },
    }


def test_save_draft_is_blocked_service_side_after_publication_begins(monkeypatch) -> None:
    save_memory = Mock()
    monkeypatch.setattr(app, "load_listing_memory_from_dropbox_fresh", Mock(return_value=locked_source_memory()))
    monkeypatch.setattr(app, "save_listing_inputs_json_to_dropbox", save_memory)

    with pytest.raises(ValueError, match="locked against draft changes"):
        app.save_grouped_christmas_draft_to_dropbox(
            dropbox_cfg={"stage_root": "/Amazon/_stage"},
            staged_folder_name="CHRTST",
            profile={"template_key": "CP"},
            payload=locked_source_memory(),
        )

    save_memory.assert_not_called()


def test_save_draft_rejects_malformed_expected_grouped_payload_before_write(monkeypatch) -> None:
    save_memory = Mock()
    load_memory = Mock(side_effect=AssertionError("malformed payload must fail before loading"))
    monkeypatch.setattr(app, "load_listing_memory_from_dropbox_fresh", load_memory)
    monkeypatch.setattr(app, "save_listing_inputs_json_to_dropbox", save_memory)

    with pytest.raises(ValueError, match="Grouped Christmas draft memory is required"):
        app.save_grouped_christmas_draft_to_dropbox(
            dropbox_cfg={"stage_root": "/Amazon/_stage"},
            staged_folder_name="CHRTST",
            profile={"template_key": "CP"},
            payload={
                "template_key": "CP",
                "group_submission": {"state": "failed"},
            },
        )

    load_memory.assert_not_called()
    save_memory.assert_not_called()


def test_released_archive_failure_resumes_without_saving_stale_draft(monkeypatch) -> None:
    publish = Mock(return_value={"success": False, "state": "failed", "errors": []})
    save_draft = Mock(side_effect=AssertionError("locked source must not be saved as a draft"))
    monkeypatch.setattr(app, "path_exists_strict", Mock(return_value=True))
    monkeypatch.setattr(app, "load_listing_memory_from_dropbox_fresh", Mock(return_value=locked_source_memory()))
    monkeypatch.setattr(app, "save_grouped_christmas_draft_to_dropbox", save_draft)
    monkeypatch.setattr(app, "publish_christmas_group", publish)

    result = app.submit_grouped_christmas_to_review(
        dropbox_cfg={
            "stage_root": "/Amazon/_stage",
            "ready_root": "/Amazon/ready",
            "grouped_preparation_root": "/Amazon/_prepare",
            "grouped_archive_root": "/Amazon/_archive",
        },
        staged_folder_name="CHRTST",
        profile={"template_key": "CP"},
        draft_payload={**locked_source_memory(), "quantity": 999},
    )

    assert result["state"] == "failed"
    save_draft.assert_not_called()
    publish.assert_called_once()


def test_successful_release_and_archive_clears_only_old_staged_context(monkeypatch) -> None:
    state = {
        "staged_folder_select": "CHRTST",
        "active_staged_folder_select": "CHRTST",
        "pending_staged_folder_selection_on_rerun": "CHRTST",
        "clear_staged_folder_selection_on_rerun": True,
        "last_loaded_listing_memory_folder": "/Amazon/_stage/CHRTST",
        "last_detected_template_folder": "CHRTST",
        "applied_listing_memory_key_v2": "old-memory",
        "applied_listing_memory_widget_key_v2": "old-widget-memory",
        "initialized_listing_context_key": "old-context",
        "last_loaded_listing_memory_signature": "CHRTST|CP",
        "image_mappings_loaded_folder": "CHRTST",
        "image_mappings_loaded_context": "old-images",
        "grouped_christmas_editor_context": "old-editor",
        "grouped_christmas_pricing_context": "old-pricing",
        "grouped_christmas_draft_listing_group": {"task_id": "task-1"},
        "grouped_christmas_tshirt_title": "Old title",
        "grouped_christmas_image_manifest_task-1": {"valid": True},
        "cluster_price_adult": 12.99,
        "price_M": 12.99,
        "size_cluster_price_standard": 12.99,
        "current_size_price_map": {"M": 12.99},
        "design_size_pricing_mode": "Use one price per cluster",
        "use_same_price_for_all_sizes": False,
        "shared_price_all_sizes": 12.99,
        "known_grouped_source_folders": ["OTHER", "CHRTST"],
        "dropbox_folder_list_cache": {
            "stage": {"folder_names": ["CHRTST", "OTHER"]},
            "ready": {"folder_names": ["READY"]},
        },
        "dropbox_folder_load_errors": {"stage": "old error"},
        "listing_memory_cache": {
            "/Amazon/_stage/CHRTST": {"listing_group": {}},
        },
        "preview_image_mapping_cache": {"key": "old-images"},
        "unrelated_operator_preference": "keep-me",
    }
    monkeypatch.setattr(app.st, "session_state", state)

    app.clear_grouped_publication_active_context(
        staged_folder_name="CHRTST",
        source_folder_path="/Amazon/_stage/CHRTST",
        archive_path="/Amazon/_grouped_archive/CHRTST",
    )

    assert state["staged_folder_select"] is None
    assert state["active_staged_folder_select"] == ""
    assert state["last_loaded_listing_memory_folder"] == ""
    assert "stage" not in state["dropbox_folder_list_cache"]
    assert state["dropbox_folder_list_cache"]["ready"]["folder_names"] == ["READY"]
    assert "stage" not in state["dropbox_folder_load_errors"]
    assert "listing_memory_cache" not in state
    assert "preview_image_mapping_cache" not in state
    assert state["known_grouped_source_folders"] == ["OTHER"]
    assert state["unrelated_operator_preference"] == "keep-me"

    cleared_keys = {
        "pending_staged_folder_selection_on_rerun",
        "clear_staged_folder_selection_on_rerun",
        "last_detected_template_folder",
        "applied_listing_memory_key_v2",
        "applied_listing_memory_widget_key_v2",
        "initialized_listing_context_key",
        "last_loaded_listing_memory_signature",
        "image_mappings_loaded_folder",
        "image_mappings_loaded_context",
        "grouped_christmas_editor_context",
        "grouped_christmas_pricing_context",
        "grouped_christmas_draft_listing_group",
        "grouped_christmas_tshirt_title",
        "grouped_christmas_image_manifest_task-1",
        "cluster_price_adult",
        "price_M",
        "size_cluster_price_standard",
        "current_size_price_map",
        "design_size_pricing_mode",
        "use_same_price_for_all_sizes",
        "shared_price_all_sizes",
    }
    assert cleared_keys.isdisjoint(state)


def test_submit_clears_context_only_after_verified_release_and_archive(monkeypatch) -> None:
    cleanup = Mock()
    monkeypatch.setattr(app, "path_exists_strict", Mock(return_value=False))
    monkeypatch.setattr(app, "clear_grouped_publication_active_context", cleanup)
    monkeypatch.setattr(
        app,
        "publish_christmas_group",
        Mock(return_value={
            "success": True,
            "state": "released",
            "archive_path": "/Amazon/_grouped_archive/CHRTST",
            "errors": [],
        }),
    )

    result = app.submit_grouped_christmas_to_review(
        dropbox_cfg={
            "stage_root": "/Amazon/_stage",
            "ready_root": "/Amazon/ready",
            "grouped_preparation_root": "/Amazon/_prepare",
            "grouped_archive_root": "/Amazon/_grouped_archive",
        },
        staged_folder_name="CHRTST",
        profile={"template_key": "CP"},
        draft_payload=locked_source_memory(),
    )

    assert result["success"] is True
    cleanup.assert_called_once_with(
        staged_folder_name="CHRTST",
        source_folder_path="/Amazon/_stage/CHRTST",
        archive_path="/Amazon/_grouped_archive/CHRTST",
    )


@pytest.mark.parametrize(
    "publication_result",
    [
        {"success": False, "state": "failed", "errors": []},
        {"success": False, "state": "blocked", "errors": []},
        {"success": True, "state": "publishing", "archive_path": "/archive/CHRTST", "errors": []},
        {"success": True, "state": "released", "archive_path": "", "errors": []},
    ],
)
def test_interrupted_or_unverified_publication_retains_resume_context(
    monkeypatch,
    publication_result,
) -> None:
    cleanup = Mock()
    state = {
        "active_staged_folder_select": "CHRTST",
        "grouped_christmas_editor_context": "resume-context",
    }
    monkeypatch.setattr(app.st, "session_state", state)
    monkeypatch.setattr(app, "path_exists_strict", Mock(return_value=False))
    monkeypatch.setattr(app, "clear_grouped_publication_active_context", cleanup)
    monkeypatch.setattr(app, "publish_christmas_group", Mock(return_value=publication_result))

    app.submit_grouped_christmas_to_review(
        dropbox_cfg={
            "stage_root": "/Amazon/_stage",
            "ready_root": "/Amazon/ready",
            "grouped_preparation_root": "/Amazon/_prepare",
            "grouped_archive_root": "/Amazon/_grouped_archive",
        },
        staged_folder_name="CHRTST",
        profile={"template_key": "CP"},
        draft_payload=locked_source_memory(),
    )

    cleanup.assert_not_called()
    assert state["active_staged_folder_select"] == "CHRTST"
    assert state["grouped_christmas_editor_context"] == "resume-context"


def test_archived_released_source_is_read_only_without_save_or_submit(monkeypatch) -> None:
    class Context:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state = {}
            self.messages: list[str] = []
            self.button = Mock(return_value=False)

        def subheader(self, value, **_kwargs):
            self.messages.append(str(value))

        def caption(self, value, **_kwargs):
            self.messages.append(str(value))

        def markdown(self, value, **_kwargs):
            self.messages.append(str(value))

        def write(self, value, **_kwargs):
            self.messages.append(str(value))

        def info(self, value, **_kwargs):
            self.messages.append(str(value))

        def columns(self, count, **_kwargs):
            return [Context() for _ in range(count)]

        def container(self):
            return Context()

    fake_streamlit = FakeStreamlit()
    save_draft = Mock()
    submit = Mock()
    monkeypatch.setattr(listing_content, "st", fake_streamlit)
    monkeypatch.setattr(
        listing_content,
        "initialize_grouped_christmas_editor_state",
        Mock(side_effect=AssertionError("archived source must not initialize editors")),
    )

    archived_memory = locked_source_memory() | {"mpn": "CHRTST"}
    archived_memory["group_submission"] = {
        **archived_memory["group_submission"],
        "state": "released",
    }
    result = listing_content.render_grouped_christmas_listing_content(
        staged_folder_name="CHRTST",
        listing_memory_location="archive",
        listing_memory=archived_memory,
        profile=load_cp_profile(),
        merchant_shipping_group_options=[],
        sku_decoration_options=[],
        workflow_assignees=[],
        normalize_merchant_shipping_group=Mock(),
        selectbox_index_without_state_conflict=Mock(),
        get_default_sku_decoration_code=Mock(),
        sanitize_sku=Mock(),
        get_or_create_generated_sku_listing_code=Mock(),
        build_parent_sku_from_context=Mock(),
        build_size_price_inputs=Mock(),
        load_grouped_image_manifest=Mock(),
        save_grouped_draft=save_draft,
        submit_grouped_listing=submit,
        dev_tools_enabled=False,
        load_grouped_test_json=Mock(),
    )

    assert result["ready_clicked"] is False
    assert "Archived grouped source: CHRTST" in fake_streamlit.messages
    assert "Publication status: Released" in fake_streamlit.messages
    assert any("read-only" in message for message in fake_streamlit.messages)
    fake_streamlit.button.assert_not_called()
    save_draft.assert_not_called()
    submit.assert_not_called()
