from __future__ import annotations

import ast
import inspect
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from services.christmas_grouped_content_prompt import (
    CANONICAL_GROUPED_PROMPT_PATH,
    load_christmas_grouped_content_prompt,
    render_christmas_grouped_content_prompt,
)
from services.listing_content_prompt import load_amazon_listing_content_prompt
from ui import listing_content


def test_canonical_grouped_prompt_loads_from_repository() -> None:
    expected_path = (
        Path(__file__).resolve().parents[1]
        / "prompts"
        / "christmas_grouped_listing_content_chatgpt_prompt.txt"
    )

    assert CANONICAL_GROUPED_PROMPT_PATH == expected_path
    assert load_christmas_grouped_content_prompt() == expected_path.read_text(encoding="utf-8")


def test_renderer_includes_mpn_notes_and_safe_empty_notes() -> None:
    rendered = render_christmas_grouped_content_prompt("CHRTST", "Use the visible snowman design.")
    empty_notes = render_christmas_grouped_content_prompt("CHRTST", "  ")

    assert "MPN (internal identifier only): CHRTST" in rendered
    assert "Use the visible snowman design." in rendered
    assert "None provided" in empty_notes


def test_prompt_has_exact_grouped_output_contract() -> None:
    prompt = render_christmas_grouped_content_prompt("CHRTST").lower()

    assert "the mpn is internal context" in prompt
    assert "do not infer" in prompt
    assert "do not include the mpn in the output json" in prompt
    assert prompt.count('"tshirt": {') == 1
    assert prompt.count('"sweatshirt": {') == 1
    assert prompt.count('"hoodie": {') == 1
    assert '"schema_version": 1' in prompt
    assert '"group_type": "christmas_project"' in prompt
    assert "exactly 5 bullet points" in prompt
    assert "return only valid json" in prompt
    assert "do not include markdown code fences" in prompt
    assert "do not output prices, colours, sizes, skus, mpn, quantity, shipping" in prompt
    assert "no additional members" in prompt
    assert "must contain exactly these five fields and no others" in prompt
    assert "save it as a utf-8 json file" in prompt
    assert "attach or provide that .json file" in prompt
    assert "chrtst_christmas_grouped_listing_content.json" in prompt
    assert "cannot create downloadable files" in prompt
    assert "raw grouped object and as the only response" in prompt
    assert "maximum 150 characters for the base title" in prompt
    assert "never use the full amazon 200-character allowance" in prompt


def test_prompt_always_generates_all_three_from_one_representative_garment() -> None:
    prompt = render_christmas_grouped_content_prompt("CHRTST").lower()

    assert "regardless of which garment is visible" in prompt
    assert "always generate all three members" in prompt
    assert "never return only the garment family pictured" in prompt
    assert "a sweatshirt mockup must still produce t-shirt, sweatshirt and hoodie" in prompt


def test_prompt_keeps_colour_construction_age_and_personalisation_claims_separate() -> None:
    prompt = render_christmas_grouped_content_prompt("CHRTST").lower()

    assert "representative mockup is not the colour of the entire amazon listing" in prompt
    assert "keep grouped listing content colour-neutral by default" in prompt
    assert "do not output colour arrays or colour fields" in prompt
    assert "adult t-shirt and kids t-shirt" in prompt
    assert "do not make a whole member adult-only or kids-only" in prompt
    assert "do not transfer garment construction claims between families" in prompt
    assert "do not claim customisation or personalisation unless the optional notes explicitly" in prompt


def test_prompt_renderer_is_pure_and_has_no_openai_dependency() -> None:
    source = Path(inspect.getsourcefile(render_christmas_grouped_content_prompt)).read_text(
        encoding="utf-8"
    ).casefold()

    assert "streamlit" not in source
    assert "dropbox" not in source
    assert "openai" not in source


def test_grouped_prompt_ui_is_normal_operator_feature_and_dev_helper_stays_gated() -> None:
    source = inspect.getsource(listing_content.render_grouped_christmas_content_import)

    assert source.index("Download grouped ChatGPT prompt") < source.index("if dev_tools_enabled")
    assert 'if dev_tools_enabled and st.button(' in source
    assert "render_christmas_grouped_content_prompt" in source
    assert "save_grouped_draft" not in source
    assert "dropbox" not in source.casefold()


def test_grouped_prompt_download_has_stable_widget_contract() -> None:
    tree = ast.parse(Path(listing_content.__file__).read_text(encoding="utf-8"))
    download = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "download_button"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "Download grouped ChatGPT prompt"
    )
    keywords = {keyword.arg: ast.unparse(keyword.value) for keyword in download.keywords}

    assert keywords["data"] == "prompt_text"
    assert keywords["key"] == "GROUPED_PROMPT_DOWNLOAD_KEY"
    assert listing_content.GROUPED_PROMPT_NOTES_KEY == "grouped_christmas_prompt_notes"
    assert listing_content.GROUPED_PROMPT_DOWNLOAD_KEY == "grouped_christmas_prompt_download_btn"


def test_grouped_download_uses_grouped_payload_and_mpn_filename(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Context:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state = {}
            self.download: dict = {}

        def expander(self, *_args, **_kwargs):
            return Context()

        def markdown(self, *_args, **_kwargs) -> None:
            pass

        def caption(self, *_args, **_kwargs) -> None:
            pass

        def write(self, *_args, **_kwargs) -> None:
            pass

        def text_area(self, label, *_args, **_kwargs):
            return "Visible snowman artwork." if label == "Optional notes" else ""

        def download_button(self, label, **kwargs) -> None:
            self.download = {"label": label, **kwargs}

        def button(self, *_args, **_kwargs) -> bool:
            return False

        def file_uploader(self, *_args, **_kwargs):
            return None

    fake_streamlit = FakeStreamlit()
    monkeypatch.setattr(listing_content, "st", fake_streamlit)

    listing_content.render_grouped_christmas_content_import(
        profile={},
        listing_group={},
        dev_tools_enabled=False,
        load_grouped_test_json=lambda: "",
        mpn="CHRTST",
        sanitize_sku=lambda value: value,
    )

    assert fake_streamlit.download["file_name"] == "CHRTST_christmas_grouped_chatgpt_prompt.txt"
    assert '"group_type": "christmas_project"' in fake_streamlit.download["data"]
    assert '"tshirt": {' in fake_streamlit.download["data"]
    assert '"sweatshirt": {' in fake_streamlit.download["data"]
    assert '"hoodie": {' in fake_streamlit.download["data"]
    assert fake_streamlit.download["data"] != load_amazon_listing_content_prompt()


def test_empty_input_errors_require_an_explicit_validation_attempt() -> None:
    source = inspect.getsource(listing_content.render_grouped_christmas_content_import)

    guard = "if not st.session_state.get(GROUPED_VALIDATION_ATTEMPTED_KEY, False):"
    assert guard in source
    assert source.index(guard) < source.index('result = validation_record.get("result", {})')


def test_grouped_prompt_download_is_visible_and_empty_input_is_quiet() -> None:
    root = Path(__file__).resolve().parents[1]
    profile_path = (root / "templates" / "Special Projects" / "CP" / "config.json").as_posix()
    sample_path = (root / "samples" / "christmas_grouped_listing_content_test.json").as_posix()
    app_source = f"""
import json
from pathlib import Path
from services.christmas_project_grouping import initialize_christmas_listing_group
from ui.listing_content import render_grouped_christmas_content_import

profile = json.loads(Path(r'{profile_path}').read_text(encoding='utf-8'))
render_grouped_christmas_content_import(
    profile=profile,
    listing_group=initialize_christmas_listing_group(profile, 'prompt-test'),
    dev_tools_enabled=False,
    load_grouped_test_json=lambda: Path(r'{sample_path}').read_text(encoding='utf-8'),
    mpn='CHRTST',
    sanitize_sku=lambda value: value,
)
"""

    app = AppTest.from_string(app_source).run(timeout=30)

    assert not app.exception
    assert any(button.label == "Download grouped ChatGPT prompt" for button in app.get("download_button"))
    assert not any(button.label == "Load test Christmas content" for button in app.button)
    assert not any("Raw input is empty." in error.value for error in app.error)


def _render_listing_content_kwargs(listing_memory: dict, profile: dict) -> dict:
    signature = inspect.signature(listing_content.render_listing_content)
    kwargs = {name: Mock() for name in signature.parameters}
    kwargs.update({
        "active_staged_folder_name": "CHRTST" if listing_memory else "",
        "active_template_label": "Christmas Project",
        "selected_parent_main_label": "",
        "preview_parent_main_image_url": "",
        "preview_color_image_map": {},
        "preview_design_color_image_url_map": {},
        "preview_other_images": [],
        "image_mapping_status": "",
        "image_mapping_detail": "",
        "staged_folder_name": "CHRTST" if listing_memory else None,
        "listing_memory": listing_memory,
        "active_profile": profile,
        "profile": profile,
        "memory_fingerprint": "",
        "grouped_state_load_error": "",
        "listing_memory_location": "stage",
        "CONTENT_EDITOR_KEYS": {},
        "MERCHANT_SHIPPING_GROUP_OPTIONS": [],
        "SKU_DECORATION_OPTIONS": [],
        "WORKFLOW_ASSIGNEES": [],
        "variant_dimensions": [],
        "selected_variants": {},
        "colors_available": [],
        "full_preview_color_image_map": {},
        "full_preview_design_color_image_url_map": {},
        "auto_apply_mapped_colors": False,
        "image_mapping_context_key": "",
        "dev_tools_enabled": False,
    })
    return kwargs


def test_grouped_saved_memory_routes_only_to_grouped_prompt_ui(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = {"template_key": "CP"}
    memory = {
        "mpn": "CHRTST",
        "listing_group": {"group_type": "christmas_project"},
    }
    grouped_result = {"route": "grouped"}
    grouped_renderer = Mock(return_value=grouped_result)
    ordinary_renderer = Mock(side_effect=AssertionError("ordinary importer must not render"))
    monkeypatch.setattr(listing_content, "render_grouped_christmas_listing_content", grouped_renderer)
    monkeypatch.setattr(listing_content, "render_ai_listing_content_import", ordinary_renderer)

    result = listing_content.render_listing_content(
        **_render_listing_content_kwargs(memory, profile)
    )

    assert result == grouped_result
    assert grouped_renderer.call_args.kwargs["listing_memory"] is memory
    ordinary_renderer.assert_not_called()


def test_group_submission_does_not_disable_grouped_routing(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = {"template_key": "CP"}
    memory = {
        "mpn": "CHRTST",
        "listing_group": {"group_type": "christmas_project"},
        "group_submission": {"state": "released"},
    }
    grouped_renderer = Mock(return_value={"route": "grouped"})
    monkeypatch.setattr(listing_content, "render_grouped_christmas_listing_content", grouped_renderer)
    monkeypatch.setattr(
        listing_content,
        "render_ai_listing_content_import",
        Mock(side_effect=AssertionError("ordinary importer must not render")),
    )

    result = listing_content.render_listing_content(
        **_render_listing_content_kwargs(memory, profile)
    )

    assert result == {"route": "grouped"}
    assert grouped_renderer.call_args.kwargs["listing_memory"] is memory


def test_expected_grouped_state_load_error_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = {"template_key": "CP"}
    grouped_renderer = Mock(side_effect=AssertionError("malformed grouped state must not render"))
    ordinary_renderer = Mock(side_effect=AssertionError("ordinary importer must not render"))
    error = Mock()
    monkeypatch.setattr(listing_content.st, "error", error)
    monkeypatch.setattr(listing_content, "render_grouped_christmas_listing_content", grouped_renderer)
    monkeypatch.setattr(listing_content, "render_ai_listing_content_import", ordinary_renderer)
    kwargs = _render_listing_content_kwargs({}, profile)
    kwargs["grouped_state_load_error"] = "Grouped Christmas state could not be loaded."

    result = listing_content.render_listing_content(**kwargs)

    assert result["ready_clicked"] is False
    assert result["score_clicked"] is False
    error.assert_called_once_with("Grouped Christmas state could not be loaded.")
    grouped_renderer.assert_not_called()
    ordinary_renderer.assert_not_called()


def test_archived_grouped_memory_is_not_described_as_active_staged_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = {"template_key": "CP"}
    memory = {
        "mpn": "CHRTST",
        "listing_group": {"group_type": "christmas_project"},
        "group_submission": {"state": "released"},
    }
    active_context = Mock()
    grouped_renderer = Mock(return_value={"route": "archived"})
    monkeypatch.setattr(listing_content, "render_grouped_christmas_listing_content", grouped_renderer)
    kwargs = _render_listing_content_kwargs(memory, profile)
    kwargs["listing_memory_location"] = "archive"
    kwargs["render_active_product_context"] = active_context

    result = listing_content.render_listing_content(**kwargs)

    assert result == {"route": "archived"}
    assert active_context.call_args.kwargs["active_staged_folder_name"] == ""
    assert grouped_renderer.call_args.kwargs["listing_memory_location"] == "archive"


def test_cp_without_grouped_memory_keeps_legacy_importer_with_clear_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = {"template_key": "CP"}
    notice = Mock()

    class LegacyRouteReached(Exception):
        pass

    monkeypatch.setattr(listing_content.st, "info", notice)
    monkeypatch.setattr(
        listing_content,
        "render_grouped_christmas_listing_content",
        Mock(side_effect=AssertionError("grouped importer must not render")),
    )
    monkeypatch.setattr(
        listing_content,
        "render_ai_listing_content_import",
        Mock(side_effect=LegacyRouteReached),
    )

    with pytest.raises(LegacyRouteReached):
        listing_content.render_listing_content(
            **_render_listing_content_kwargs({}, profile)
        )

    notice.assert_called_once_with(
        "This is the standard single-listing content importer. Select a grouped Christmas "
        "staged task to generate T-Shirt, Sweatshirt and Hoodie content together."
    )
