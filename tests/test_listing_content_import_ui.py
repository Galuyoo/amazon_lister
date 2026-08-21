from __future__ import annotations

import ast
import inspect
from pathlib import Path

from ui import listing_content


EDITOR_KEYS = {
    "title": "content_title_input_v3",
    "description": "content_product_description_v3",
    "keywords": "content_generic_keywords_v3",
    "bullets": [f"content_bullet_{index}_v3" for index in range(1, 6)],
}


def valid_record(*, warnings: list[str] | None = None) -> dict[str, object]:
    return {
        "raw_text": "validated raw text",
        "result": {
            "valid": True,
            "content": {
                "schema_version": 1,
                "title": "Imported title",
                "bullet_points": [f"Imported bullet {index}" for index in range(1, 6)],
                "product_description": "Imported description",
                "generic_keywords": "imported search terms",
            },
            "errors": [],
            "warnings": list(warnings or []),
        },
    }


def apply_record(record: object, raw_text: str = "validated raw text"):
    state = {key: f"original {key}" for key in [
        EDITOR_KEYS["title"],
        EDITOR_KEYS["description"],
        EDITOR_KEYS["keywords"],
        *EDITOR_KEYS["bullets"],
    ]}
    sync_calls = []
    applied = listing_content.apply_validated_listing_content(
        record,
        raw_text,
        EDITOR_KEYS,
        state,
        lambda *values: sync_calls.append(values),
    )
    return applied, state, sync_calls


def test_import_ui_uses_parser_and_stable_widget_keys() -> None:
    module_path = Path(listing_content.__file__)
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "services.listing_content_import"
        for alias in node.names
    }

    assert "parse_listing_content_json" in imported
    assert listing_content.AI_JSON_INPUT_KEY == "listing_content_ai_json_input"
    assert listing_content.AI_VALIDATE_BUTTON_KEY == "listing_content_ai_validate_btn"
    assert listing_content.AI_APPLY_BUTTON_KEY == "listing_content_ai_apply_btn"
    assert listing_content.AI_VALIDATION_RESULT_KEY == "listing_content_ai_validation_result"


def test_valid_result_populates_all_existing_editor_keys_and_syncs_canonical_state() -> None:
    applied, state, sync_calls = apply_record(valid_record())

    assert applied is True
    assert state[EDITOR_KEYS["title"]] == "Imported title"
    assert [state[key] for key in EDITOR_KEYS["bullets"]] == [
        f"Imported bullet {index}" for index in range(1, 6)
    ]
    assert state[EDITOR_KEYS["description"]] == "Imported description"
    assert state[EDITOR_KEYS["keywords"]] == "imported search terms"
    assert sync_calls == [(
        "Imported title",
        [f"Imported bullet {index}" for index in range(1, 6)],
        "Imported description",
        "imported search terms",
    )]


def test_warnings_do_not_block_apply() -> None:
    applied, _, sync_calls = apply_record(valid_record(warnings=["Review this SEO warning."]))

    assert applied is True
    assert len(sync_calls) == 1


def test_invalid_result_does_not_alter_editor_content() -> None:
    record = {
        "raw_text": "validated raw text",
        "result": {"valid": False, "content": {}, "errors": ["Malformed JSON."], "warnings": []},
    }
    applied, state, sync_calls = apply_record(record)

    assert applied is False
    assert all(value.startswith("original ") for value in state.values())
    assert sync_calls == []


def test_validation_without_apply_has_no_editor_side_effects() -> None:
    record = valid_record()
    state = {EDITOR_KEYS["title"]: "Current title"}

    assert record["result"]["valid"] is True
    assert state == {EDITOR_KEYS["title"]: "Current title"}


def test_stale_validation_cannot_be_applied() -> None:
    applied, state, sync_calls = apply_record(valid_record(), raw_text="changed raw text")

    assert applied is False
    assert all(value.startswith("original ") for value in state.values())
    assert sync_calls == []


def test_apply_helper_has_no_workflow_save_dropbox_or_openai_dependency() -> None:
    source = inspect.getsource(listing_content.apply_validated_listing_content).lower()
    module_source = Path(listing_content.__file__).read_text(encoding="utf-8").lower()

    assert all(term not in source for term in ("dropbox", "save_listing", "submit", "workflow"))
    assert "import app" not in module_source
    assert "import openai" not in module_source
