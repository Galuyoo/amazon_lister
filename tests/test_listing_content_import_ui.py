from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

from ui import listing_content


EDITOR_KEYS = {
    "title": "content_title_input_v3",
    "description": "content_product_description_v3",
    "keywords": "content_generic_keywords_v3",
    "bullets": [f"content_bullet_{index}_v3" for index in range(1, 6)],
}


class UploadedFile:
    def __init__(self, content: bytes, name: str = "listing.json") -> None:
        self.name = name
        self._content = content

    def getvalue(self) -> bytes:
        return self._content


def valid_record(
    *,
    warnings: list[str] | None = None,
    source_identity: str | None = None,
) -> dict[str, object]:
    return {
        "raw_text": "validated raw text",
        **({"source_identity": source_identity} if source_identity is not None else {}),
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


def apply_record(
    record: object,
    raw_text: str = "validated raw text",
    source_identity: str | None = None,
):
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
        current_source_identity=source_identity,
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
    assert listing_content.AI_JSON_UPLOAD_KEY == "listing_content_ai_json_upload"


def test_json_uploader_accepts_only_json_and_has_stable_key() -> None:
    tree = ast.parse(Path(listing_content.__file__).read_text(encoding="utf-8"))
    uploader = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "file_uploader"
    )
    keywords = {keyword.arg: ast.unparse(keyword.value) for keyword in uploader.keywords}

    assert ast.literal_eval(uploader.args[0]) == "Upload JSON file"
    assert keywords["type"] == "['json']"
    assert keywords["key"] == "AI_JSON_UPLOAD_KEY"


def test_uploaded_utf8_json_uses_existing_parser_and_can_be_applied() -> None:
    payload = {
        "schema_version": 1,
        "title": "A" * 150,
        "bullet_points": ["B" * 150 for _ in range(5)],
        "product_description": "D" * 1000,
        "generic_keywords": "useful " * 20,
    }
    source = listing_content.resolve_listing_content_import_source(
        "ignored pasted text",
        UploadedFile(json.dumps(payload).encode("utf-8")),
    )
    result = listing_content.parse_listing_content_json(source["raw_text"])
    record = {
        "raw_text": source["raw_text"],
        "source_identity": source["source_identity"],
        "result": result,
    }
    state = {}
    sync_calls = []

    applied = listing_content.apply_validated_listing_content(
        record,
        source["raw_text"],
        EDITOR_KEYS,
        state,
        lambda *values: sync_calls.append(values),
        current_source_identity=source["source_identity"],
    )

    assert result["valid"] is True
    assert applied is True
    assert state[EDITOR_KEYS["title"]] == payload["title"]
    assert len([state[key] for key in EDITOR_KEYS["bullets"]]) == 5
    assert len(sync_calls) == 1


def test_uploaded_invalid_json_cannot_be_applied() -> None:
    source = listing_content.resolve_listing_content_import_source("", UploadedFile(b"{invalid"))
    result = listing_content.parse_listing_content_json(source["raw_text"])
    record = {
        "raw_text": source["raw_text"],
        "source_identity": source["source_identity"],
        "result": result,
    }

    applied, state, sync_calls = apply_record(
        record,
        raw_text=source["raw_text"],
        source_identity=source["source_identity"],
    )

    assert result["valid"] is False
    assert applied is False
    assert all(value.startswith("original ") for value in state.values())
    assert sync_calls == []


def test_invalid_utf8_upload_is_rejected_safely() -> None:
    source = listing_content.resolve_listing_content_import_source("", UploadedFile(b"\xff\xfe"))

    assert source["raw_text"] is None
    assert source["error"] == "The uploaded JSON file is not valid UTF-8 text."


def test_changing_uploaded_file_invalidates_validation() -> None:
    first_source = listing_content.resolve_listing_content_import_source("", UploadedFile(b"{}", "first.json"))
    second_source = listing_content.resolve_listing_content_import_source("", UploadedFile(b"{}", "second.json"))
    record = valid_record(source_identity=first_source["source_identity"])

    applied, state, sync_calls = apply_record(
        record,
        source_identity=second_source["source_identity"],
    )

    assert applied is False
    assert all(value.startswith("original ") for value in state.values())
    assert sync_calls == []


def test_uploaded_file_takes_precedence_and_paste_path_is_unchanged() -> None:
    upload_source = listing_content.resolve_listing_content_import_source(
        "pasted content",
        UploadedFile(b"uploaded content"),
    )
    paste_source = listing_content.resolve_listing_content_import_source("pasted content")

    assert upload_source["raw_text"] == "uploaded content"
    assert upload_source["source_label"].startswith("uploaded JSON file")
    assert paste_source["raw_text"] == "pasted content"
    assert paste_source["source_label"] == "pasted JSON"


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


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _ImportStreamlit:
    def __init__(self, raw_text: str, validation_record: dict) -> None:
        self.raw_text = raw_text
        self.session_state = {
            listing_content.AI_VALIDATION_RESULT_KEY: validation_record,
        }
        self.downloads: list[dict] = []

    def expander(self, *_args, **_kwargs):
        return _Context()

    def markdown(self, *_args, **_kwargs) -> None:
        pass

    def caption(self, *_args, **_kwargs) -> None:
        pass

    def write(self, *_args, **_kwargs) -> None:
        pass

    def text_area(self, label, *_args, **_kwargs):
        if label == "Optional notes":
            return "Temporary factual note"
        return self.raw_text

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


def test_normal_validated_download_uses_normalized_content_without_apply(
    monkeypatch,
) -> None:
    payload = {
        "schema_version": 1,
        "title": f"  {'A' * 150}  ",
        "bullet_points": [f"  {'B' * 150}  " for _ in range(5)],
        "product_description": f"  {'D' * 1000}  ",
        "generic_keywords": f"  {'keyword ' * 20}  ",
    }
    raw_text = json.dumps(payload)
    source = listing_content.resolve_listing_content_import_source(raw_text)
    result = listing_content.parse_listing_content_json(raw_text)
    validation_record = {
        "raw_text": raw_text,
        "source_identity": source["source_identity"],
        "result": result,
    }
    fake_streamlit = _ImportStreamlit(raw_text, validation_record)
    sync_calls = []
    monkeypatch.setattr(listing_content, "st", fake_streamlit)

    listing_content.render_ai_listing_content_import(
        content_editor_keys=EDITOR_KEYS,
        sync_content_editor_to_canonical_state=lambda *values: sync_calls.append(values),
        mpn="Bad / MPN",
        sanitize_sku=lambda value: value.replace(" / ", "-"),
    )

    validated = next(item for item in fake_streamlit.downloads if item["label"] == "Download validated JSON")
    assert json.loads(validated["data"]) == result["content"]
    assert validated["data"] != raw_text
    assert validated["file_name"] == "BAD-MPN_amazon_listing_content.json"
    assert validated["mime"] == "application/json"
    assert sync_calls == []
    assert fake_streamlit.session_state == {
        listing_content.AI_VALIDATION_RESULT_KEY: validation_record,
    }


def test_invalid_normal_json_has_no_validated_download(monkeypatch) -> None:
    raw_text = "{invalid"
    source = listing_content.resolve_listing_content_import_source(raw_text)
    validation_record = {
        "raw_text": raw_text,
        "source_identity": source["source_identity"],
        "result": listing_content.parse_listing_content_json(raw_text),
    }
    fake_streamlit = _ImportStreamlit(raw_text, validation_record)
    monkeypatch.setattr(listing_content, "st", fake_streamlit)

    listing_content.render_ai_listing_content_import(
        content_editor_keys=EDITOR_KEYS,
        sync_content_editor_to_canonical_state=lambda *_values: None,
        mpn="NORMAL-001",
        sanitize_sku=lambda value: value,
    )

    assert not any(item["label"] == "Download validated JSON" for item in fake_streamlit.downloads)
