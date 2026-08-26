from __future__ import annotations

import copy
import importlib
import inspect
import json
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from services.christmas_grouped_content_import import (
    parse_christmas_grouped_content_json,
    validate_christmas_grouped_content_payload,
)
from services.christmas_project_grouping import (
    build_christmas_group_image_manifest,
    initialize_christmas_listing_group,
)
from services.listing_content_import import validate_listing_content_payload
from services.runtime_flags import dev_tools_enabled
from ui.listing_content import (
    GROUPED_DRAFT_GROUP_KEY,
    apply_validated_grouped_christmas_content,
    get_grouped_christmas_content_widget_keys,
    render_grouped_christmas_content_import,
    resolve_listing_content_import_source,
)


ROOT = Path(__file__).parents[1]
SAMPLE_PATH = ROOT / "samples" / "christmas_grouped_listing_content_test.json"
CP_CONFIG_PATH = ROOT / "templates" / "Special Projects" / "CP" / "config.json"


def load_sample_text() -> str:
    return SAMPLE_PATH.read_text(encoding="utf-8")


def load_sample_payload() -> dict:
    return json.loads(load_sample_text())


def load_cp_profile() -> dict:
    return json.loads(CP_CONFIG_PATH.read_text(encoding="utf-8"))


def test_valid_grouped_json_parses_and_returns_normalized_members() -> None:
    result = parse_christmas_grouped_content_json(load_sample_text())

    assert result["valid"] is True
    assert list(result["members"]) == ["tshirt", "sweatshirt", "hoodie"]
    assert result["errors"] == []
    assert result["warnings"] == []
    assert result["members"]["tshirt"] == validate_listing_content_payload(
        load_sample_payload()["members"]["tshirt"]
    )["content"]


@pytest.mark.parametrize(
    ("mutator", "expected_error"),
    [
        (lambda payload: payload["members"].pop("hoodie"), "Missing required member: hoodie."),
        (lambda payload: payload["members"].update({"coat": payload["members"]["hoodie"]}), "Unknown member: coat."),
        (lambda payload: payload.update({"schema_version": 2}), "schema_version must equal 1."),
        (lambda payload: payload.update({"group_type": "other"}), "group_type must equal 'christmas_project'."),
    ],
)
def test_grouped_schema_requires_exact_members_and_identity(mutator, expected_error: str) -> None:
    payload = load_sample_payload()
    mutator(payload)

    result = validate_christmas_grouped_content_payload(payload)

    assert result["valid"] is False
    assert expected_error in result["errors"]


def test_malformed_member_uses_existing_validator_and_labels_errors() -> None:
    payload = load_sample_payload()
    payload["members"]["hoodie"]["title"] = "word " * 50
    expected_member_result = validate_listing_content_payload(payload["members"]["hoodie"])

    result = validate_christmas_grouped_content_payload(payload)

    assert expected_member_result["valid"] is False
    assert result["valid"] is False
    assert all(
        f"hoodie: {error}" in result["errors"]
        for error in expected_member_result["errors"]
    )


def test_grouped_parser_does_not_mutate_decoded_payload() -> None:
    payload = load_sample_payload()
    original = copy.deepcopy(payload)

    validate_christmas_grouped_content_payload(payload)

    assert payload == original


class UploadedJson:
    name = "christmas.json"

    def __init__(self, text: str):
        self._value = text.encode("utf-8")

    def getvalue(self) -> bytes:
        return self._value


def test_grouped_upload_and_paste_use_the_same_parser_input() -> None:
    raw_text = load_sample_text()
    pasted_source = resolve_listing_content_import_source(raw_text)
    uploaded_source = resolve_listing_content_import_source("ignored", UploadedJson(raw_text))

    assert parse_christmas_grouped_content_json(pasted_source["raw_text"])["valid"] is True
    assert parse_christmas_grouped_content_json(uploaded_source["raw_text"])["valid"] is True
    assert uploaded_source["source_label"] == "uploaded JSON file: christmas.json"


def test_stale_grouped_validation_cannot_apply() -> None:
    profile = load_cp_profile()
    listing_group = initialize_christmas_listing_group(profile, "task-1")
    raw_text = load_sample_text()
    source = resolve_listing_content_import_source(raw_text)
    record = {
        "raw_text": raw_text,
        "source_identity": source["source_identity"],
        "result": parse_christmas_grouped_content_json(raw_text),
    }

    assert apply_validated_grouped_christmas_content(
        validation_record=record,
        current_raw_text=raw_text + " ",
        current_source_identity=source["source_identity"],
        profile=profile,
        listing_group=listing_group,
        session_state={},
    ) is False


def test_apply_populates_all_namespaces_without_touching_unrelated_state() -> None:
    profile = load_cp_profile()
    listing_group = initialize_christmas_listing_group(profile, "task-1")
    raw_text = load_sample_text()
    source = resolve_listing_content_import_source(raw_text)
    result = parse_christmas_grouped_content_json(raw_text)
    record = {
        "raw_text": raw_text,
        "source_identity": source["source_identity"],
        "result": result,
    }
    state = {"unrelated_price": 44.5, "variant_quantity": 100}

    applied = apply_validated_grouped_christmas_content(
        validation_record=record,
        current_raw_text=raw_text,
        current_source_identity=source["source_identity"],
        profile=profile,
        listing_group=listing_group,
        session_state=state,
    )

    assert applied is True
    for member_key in ["tshirt", "sweatshirt", "hoodie"]:
        keys = get_grouped_christmas_content_widget_keys(member_key)
        assert state[keys["title"]] == result["members"][member_key]["title"]
        assert [state[key] for key in keys["bullets"]] == result["members"][member_key]["bullet_points"]
    assert state[get_grouped_christmas_content_widget_keys("tshirt")["title"]] != state[
        get_grouped_christmas_content_widget_keys("hoodie")["title"]
    ]
    assert state["unrelated_price"] == 44.5
    assert state["variant_quantity"] == 100
    assert state[GROUPED_DRAFT_GROUP_KEY]["members"]["sweatshirt"]["content"]["title"] == result[
        "members"
    ]["sweatshirt"]["title"]


def test_apply_path_has_no_save_move_or_dropbox_dependency() -> None:
    source = inspect.getsource(apply_validated_grouped_christmas_content).casefold()

    assert "dropbox" not in source
    assert "save_grouped_draft" not in source
    assert "move_" not in source


def test_dev_sample_uses_normal_parser_and_apply_path_and_is_explicitly_guarded() -> None:
    source = inspect.getsource(render_grouped_christmas_content_import)

    assert "parse_christmas_grouped_content_json" in source
    assert "apply_validated_grouped_christmas_content" in source
    assert 'if dev_tools_enabled and st.button(' in source
    assert '"Load test Christmas content"' in source
    assert parse_christmas_grouped_content_json(load_sample_text())["valid"] is True


def test_dev_tools_are_disabled_by_default_and_require_explicit_flag() -> None:
    assert dev_tools_enabled({}, {}) is False
    assert dev_tools_enabled({"AMAZON_LISTER_ENABLE_DEV_TOOLS": "true"}, {}) is True
    assert dev_tools_enabled({"AMAZON_LISTER_ENABLE_DEV_TOOLS": "false"}, {"ENABLE_DEV_TOOLS": True}) is False
    assert dev_tools_enabled({}, {"ENABLE_DEV_TOOLS": True}) is True


def test_grouped_import_apptest_hides_and_explicitly_enables_test_autofill() -> None:
    profile_path = CP_CONFIG_PATH.as_posix()
    sample_path = SAMPLE_PATH.as_posix()
    app_source = f"""
import json
from pathlib import Path
import streamlit as st
from services.christmas_project_grouping import initialize_christmas_listing_group
from ui.listing_content import render_grouped_christmas_content_import

profile = json.loads(Path(r'{profile_path}').read_text(encoding='utf-8'))
listing_group = initialize_christmas_listing_group(profile, 'apptest-task')
render_grouped_christmas_content_import(
    profile=profile,
    listing_group=listing_group,
    dev_tools_enabled=st.session_state.get('dev_enabled', False),
    load_grouped_test_json=lambda: Path(r'{sample_path}').read_text(encoding='utf-8'),
    mpn='CHRTST',
    sanitize_sku=lambda value: value,
)
"""
    app = AppTest.from_string(app_source).run(timeout=30)

    assert not any(button.label == "Load test Christmas content" for button in app.button)

    app.session_state["dev_enabled"] = True
    app.run(timeout=30)
    dev_button = next(button for button in app.button if button.label == "Load test Christmas content")
    dev_button.click().run(timeout=30)

    assert app.session_state[get_grouped_christmas_content_widget_keys("tshirt")["title"]].startswith(
        "TEST DATA ONLY"
    )
    assert app.session_state[get_grouped_christmas_content_widget_keys("hoodie")["title"]].startswith(
        "TEST DATA ONLY"
    )
    assert not app.exception


def test_grouped_parser_module_is_pure() -> None:
    sys.modules.pop("services.christmas_grouped_content_import", None)
    before = set(sys.modules)
    module = importlib.import_module("services.christmas_grouped_content_import")
    imported = set(sys.modules) - before

    assert module.__name__ == "services.christmas_grouped_content_import"
    assert not any(name.startswith("streamlit") for name in imported)
    assert not any("dropbox" in name.casefold() for name in imported)
    assert not any(name.startswith("openpyxl") for name in imported)
    assert not any(name.startswith(("requests", "httpx", "urllib3")) for name in imported)


def test_real_sixteen_image_manifest_is_complete_without_unsupported_hoodie_colours() -> None:
    tshirt_colours = ["Black", "Navy", "Heather Grey", "Kelly Green", "Red", "Royal", "White"]
    sweatshirt_colours = list(tshirt_colours)
    paths = [
        *[f"T01 T02 {colour}.png" for colour in tshirt_colours],
        *[f"S01 S02 {colour}.png" for colour in sweatshirt_colours],
        "H01 H02 Black.png",
        "H01 H02 Navy.png",
    ]

    manifest = build_christmas_group_image_manifest(paths, load_cp_profile())

    assert manifest["valid"] is True
    assert manifest["complete"] is True
    assert len(manifest["members"]["tshirt"]["images_by_colour"]) == 7
    assert len(manifest["members"]["sweatshirt"]["images_by_colour"]) == 7
    assert len(manifest["members"]["hoodie"]["images_by_colour"]) == 2
    assert manifest["members"]["hoodie"]["missing_colours"] == []
    assert manifest["members"]["hoodie"]["allowed_colours"] == ["Black", "Navy"]


def test_grouped_validated_download_uses_normalized_members_without_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Context:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeStreamlit:
        def __init__(self, raw_text: str, validation_record: dict) -> None:
            self.raw_text = raw_text
            self.session_state = {
                "grouped_christmas_validation_attempted": True,
                "grouped_christmas_validation_result": validation_record,
            }
            self.downloads: list[dict] = []

        def expander(self, *_args, **_kwargs):
            return Context()

        def markdown(self, *_args, **_kwargs) -> None:
            pass

        def caption(self, *_args, **_kwargs) -> None:
            pass

        def write(self, *_args, **_kwargs) -> None:
            pass

        def text_area(self, label, *_args, **_kwargs):
            return "Temporary note" if label == "Optional notes" else self.raw_text

        def file_uploader(self, *_args, **_kwargs):
            return None

        def button(self, *_args, **_kwargs) -> bool:
            return False

        def download_button(self, label, **kwargs) -> None:
            self.downloads.append({"label": label, **kwargs})

        def error(self, *_args, **_kwargs) -> None:
            pass

        def warning(self, *_args, **_kwargs) -> None:
            pass

        def success(self, *_args, **_kwargs) -> None:
            pass

    raw_text = load_sample_text()
    source = resolve_listing_content_import_source(raw_text)
    result = parse_christmas_grouped_content_json(raw_text)
    validation_record = {
        "raw_text": raw_text,
        "source_identity": source["source_identity"],
        "result": result,
    }
    fake_streamlit = FakeStreamlit(raw_text, validation_record)
    monkeypatch.setattr("ui.listing_content.st", fake_streamlit)

    render_grouped_christmas_content_import(
        profile=load_cp_profile(),
        listing_group=initialize_christmas_listing_group(load_cp_profile(), "task-1"),
        dev_tools_enabled=False,
        load_grouped_test_json=load_sample_text,
        mpn="Bad / MPN",
        sanitize_sku=lambda value: value.replace(" / ", "-"),
    )

    validated = next(item for item in fake_streamlit.downloads if item["label"] == "Download validated JSON")
    assert json.loads(validated["data"]) == {
        "schema_version": 1,
        "group_type": "christmas_project",
        "members": result["members"],
    }
    assert validated["file_name"] == "BAD-MPN_christmas_grouped_listing_content.json"
    assert validated["mime"] == "application/json"
    assert GROUPED_DRAFT_GROUP_KEY not in fake_streamlit.session_state


def test_invalid_grouped_json_has_no_validated_download(monkeypatch: pytest.MonkeyPatch) -> None:
    class Context:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeStreamlit:
        def __init__(self) -> None:
            raw_text = "{invalid"
            source = resolve_listing_content_import_source(raw_text)
            self.raw_text = raw_text
            self.session_state = {
                "grouped_christmas_validation_attempted": True,
                "grouped_christmas_validation_result": {
                    "raw_text": raw_text,
                    "source_identity": source["source_identity"],
                    "result": parse_christmas_grouped_content_json(raw_text),
                },
            }
            self.downloads: list[dict] = []

        def expander(self, *_args, **_kwargs):
            return Context()

        def markdown(self, *_args, **_kwargs) -> None:
            pass

        def caption(self, *_args, **_kwargs) -> None:
            pass

        def write(self, *_args, **_kwargs) -> None:
            pass

        def text_area(self, label, *_args, **_kwargs):
            return "" if label == "Optional notes" else self.raw_text

        def file_uploader(self, *_args, **_kwargs):
            return None

        def button(self, *_args, **_kwargs) -> bool:
            return False

        def download_button(self, label, **kwargs) -> None:
            self.downloads.append({"label": label, **kwargs})

        def error(self, *_args, **_kwargs) -> None:
            pass

        def warning(self, *_args, **_kwargs) -> None:
            pass

    fake_streamlit = FakeStreamlit()
    monkeypatch.setattr("ui.listing_content.st", fake_streamlit)

    render_grouped_christmas_content_import(
        profile=load_cp_profile(),
        listing_group=initialize_christmas_listing_group(load_cp_profile(), "task-1"),
        dev_tools_enabled=False,
        load_grouped_test_json=load_sample_text,
        mpn="CHRTST",
        sanitize_sku=lambda value: value,
    )

    assert not any(item["label"] == "Download validated JSON" for item in fake_streamlit.downloads)
