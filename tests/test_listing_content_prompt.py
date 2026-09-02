from __future__ import annotations

import ast
from pathlib import Path

import pytest

from services.listing_content_prompt import (
    CANONICAL_PROMPT_PATH,
    load_amazon_listing_content_prompt,
    render_amazon_listing_content_prompt,
)
from ui import listing_content


def test_canonical_prompt_exists_and_contains_required_contract() -> None:
    assert CANONICAL_PROMPT_PATH.is_file()

    prompt = load_amazon_listing_content_prompt()
    prompt_lower = prompt.lower()
    for field_name in (
        "schema_version",
        "title",
        "bullet_points",
        "product_description",
        "generic_keywords",
    ):
        assert field_name in prompt

    assert "return only valid json" in prompt_lower
    assert "do not include any brand name" in prompt_lower
    assert "minimum 150 characters" in prompt_lower
    assert "maximum 200 characters" in prompt_lower
    assert "exactly 5 bullet points" in prompt_lower
    assert "minimum 1000 characters" in prompt_lower
    assert "maximum 2000 characters" in prompt_lower
    assert "maximum 249 utf-8 bytes" in prompt_lower
    assert "do not invent product facts" in prompt_lower
    assert "save it as a utf-8 json file" in prompt_lower
    assert "attach or provide that .json file" in prompt_lower
    assert "cannot create downloadable files" in prompt_lower
    assert "return only valid json" in prompt_lower
    assert "treat them as the primary source for the title's subject" in prompt_lower
    assert "base the title mainly on their product/design wording" in prompt_lower
    assert "reuse relevant customer search words and phrases from the notes" in prompt_lower
    assert "do not copy full sentences, instructions or irrelevant text" in prompt_lower


def test_normal_prompt_renderer_includes_context_and_download_filename() -> None:
    prompt = render_amazon_listing_content_prompt(
        "NORMAL-001",
        "Use only the visible festive artwork.",
        "NORMAL-001_amazon_listing_content.json",
    )

    assert "MPN (internal identifier only): NORMAL-001" in prompt
    assert "Use only the visible festive artwork." in prompt
    assert "NORMAL-001_amazon_listing_content.json" in prompt
    assert "do not add the MPN to the JSON object" in prompt


def test_prompt_loader_is_repository_relative() -> None:
    expected_path = (
        Path(__file__).resolve().parents[1]
        / "prompts"
        / "amazon_listing_content_chatgpt_prompt.txt"
    )

    assert CANONICAL_PROMPT_PATH == expected_path
    assert load_amazon_listing_content_prompt() == expected_path.read_text(encoding="utf-8")


def test_missing_prompt_file_has_a_catchable_read_error(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing-prompt.txt"

    with pytest.raises(OSError):
        load_amazon_listing_content_prompt(missing_path)


def test_missing_prompt_file_does_not_crash_prompt_ui(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeStreamlit:
        def __init__(self) -> None:
            self.errors: list[str] = []

        def markdown(self, _value: str) -> None:
            pass

        def caption(self, _value: str) -> None:
            pass

        def write(self, _value: str) -> None:
            pass

        def text_area(self, *_args, **_kwargs) -> str:
            return ""

        def error(self, value: str) -> None:
            self.errors.append(value)

        def download_button(self, *_args, **_kwargs) -> None:
            raise AssertionError("Download must not render when the prompt is unavailable.")

    fake_streamlit = FakeStreamlit()
    monkeypatch.setattr(listing_content, "st", fake_streamlit)
    monkeypatch.setattr(
        listing_content,
        "render_amazon_listing_content_prompt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("missing")),
    )

    listing_content.render_chatgpt_prompt_download(mpn="", sanitize_sku=lambda value: value)

    assert fake_streamlit.errors == ["The standard ChatGPT prompt is currently unavailable."]


def test_download_button_uses_canonical_prompt_and_stable_contract() -> None:
    module_path = Path(listing_content.__file__)
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    download = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "download_button"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "Download ChatGPT Prompt"
    )
    keywords = {keyword.arg: ast.unparse(keyword.value) for keyword in download.keywords}

    assert ast.literal_eval(download.args[0]) == "Download ChatGPT Prompt"
    assert keywords["data"] == "prompt_text"
    assert ast.literal_eval(keywords["file_name"]) == "amazon_listing_content_chatgpt_prompt.txt"
    assert ast.literal_eval(keywords["mime"]) == "text/plain"
    assert keywords["key"] == "AI_PROMPT_DOWNLOAD_KEY"
    assert listing_content.AI_PROMPT_DOWNLOAD_KEY == "listing_content_ai_prompt_download_btn"


def test_ui_loads_prompt_without_duplicating_canonical_instructions() -> None:
    module_source = Path(listing_content.__file__).read_text(encoding="utf-8")

    assert "render_amazon_listing_content_prompt(" in module_source
    assert "Do not invent materials, fabric composition" not in module_source
    assert "Return ONLY valid JSON" not in module_source
