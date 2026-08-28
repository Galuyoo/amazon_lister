from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path
from unittest.mock import Mock

from ui import product_setup


def test_product_setup_ui_imports_without_app_dependency() -> None:
    module = importlib.import_module("ui.product_setup")

    assert callable(module.render_product_setup_controls)
    assert callable(module.render_product_setup)

    module_path = Path(module.__file__)
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_modules.update(
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )

    assert "app" not in imported_modules


def test_product_setup_has_exact_folder_source_options() -> None:
    assert product_setup.FOLDER_SOURCE_OPTIONS == [
        "Use staged folder",
        "Restage finished folder",
        "Create staged folder",
    ]
    source = inspect.getsource(product_setup.render_product_setup_controls)
    assert 'if folder_source == "Use staged folder"' in source
    assert 'elif folder_source == "Restage finished folder"' in source
    assert "render_create_staged_listing_task_form(" in source


def test_create_task_form_has_stable_widgets_and_no_listing_content_key_changes() -> None:
    source = inspect.getsource(product_setup.render_create_staged_listing_task_form)
    expected_widget_contract = {
        '"Staging folder name"',
        'key="create_task_staged_folder_name"',
        '"create_task_price"',
        '"create_task_quantity"',
        '"create_task_shipping_group"',
        '"create_task_sizes"',
        '"create_task_sku_decoration_choice"',
        '"create_task_manual_sku_listing_code"',
        '"Create Listing Task"',
        '"Create Christmas Listing Task"',
        'key="create_staged_listing_task_btn"',
    }
    assert all(item in source for item in expected_widget_contract)
    assert "content_title_input_v3" not in source
    assert "content_bullet_1_v3" not in source
    assert '"Create grouped Christmas task"' not in source
    assert 'key="create_task_grouped_christmas"' not in source
    assert "is_christmas_project_profile(profile)" in source
    assert "Creates T-Shirt, Sweatshirt, and Hoodie listings." in source
    assert "build_grouped_christmas_staged_task_payload(" in source
    assert 'key="create_task_mpn"' not in source


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _CreateTaskStreamlit:
    def __init__(
        self,
        submit_clicked: bool = False,
        manual_listing_code: str = "D304VG",
    ) -> None:
        self.session_state = {}
        self.submit_clicked = submit_clicked
        self.manual_listing_code = manual_listing_code
        self.number_labels = []
        self.multiselect_labels = []
        self.submit_labels = []
        self.info_messages = []
        self.column_calls = 0
        self.errors = []
        self.captions = []

    def form(self, _key):
        return _Context()

    def text_input(self, label, **_kwargs):
        if label == "Staging folder name":
            return "TSTGP"
        if label == "Listing/design code (optional)":
            return self.manual_listing_code
        return ""

    def number_input(self, label, **_kwargs):
        self.number_labels.append(label)
        return 100 if label == "Quantity" else 12.99

    def selectbox(self, _label, options, **_kwargs):
        return options[0]

    def multiselect(self, label, options, **_kwargs):
        self.multiselect_labels.append(label)
        return list(options)

    def columns(self, count):
        self.column_calls += 1
        return [_Context() for _ in range(count)]

    def subheader(self, _value):
        pass

    def caption(self, value):
        self.captions.append(value)

    def info(self, value):
        self.info_messages.append(value)

    def form_submit_button(self, label, **_kwargs):
        self.submit_labels.append(label)
        return self.submit_clicked

    def error(self, value):
        self.errors.append(value)


def _render_create_form(
    profile,
    fake_streamlit,
    monkeypatch,
    create_listing_task=None,
) -> None:
    monkeypatch.setattr(product_setup, "st", fake_streamlit)
    product_setup.render_create_staged_listing_task_form(
        profile=profile,
        dropbox_cfg={},
        merchant_shipping_group_options=[""],
        sku_decoration_options=["PRINT", "Custom"],
        default_variant_quantity=100,
        get_default_sku_decoration_code=lambda _profile: "PRINT",
        sanitize_sku=lambda value: value,
        generate_unique_sku=lambda _length: "12345",
        get_default=lambda selected, key, fallback="": selected.get(key, fallback),
        build_parent_sku_from_context=lambda _profile, decoration, code: f"{decoration}-{code}",
        create_listing_task=create_listing_task or Mock(),
        refresh_cached_folder_names=Mock(),
        clear_cached_listing_memory=Mock(),
        clear_runtime_caches=Mock(),
        set_workflow_flash=Mock(),
    )


def test_cp_automatically_hides_ordinary_price_and_sizes_then_normal_restores_them(
    monkeypatch,
) -> None:
    fake_streamlit = _CreateTaskStreamlit()
    cp_profile = {"template_key": "CP", "label": "Christmas Project", "parent_sku": "CP"}
    normal_profile = {
        "template_key": "UC301",
        "label": "UC301",
        "parent_sku": "UC301",
        "sizes": ["S", "M"],
    }

    _render_create_form(cp_profile, fake_streamlit, monkeypatch)

    assert fake_streamlit.number_labels == ["Quantity"]
    assert fake_streamlit.multiselect_labels == []
    assert fake_streamlit.column_calls == 0
    assert fake_streamlit.submit_labels == ["Create Christmas Listing Task"]
    assert "Pricing is configured per garment and size" in fake_streamlit.info_messages[0]

    _render_create_form(normal_profile, fake_streamlit, monkeypatch)

    assert fake_streamlit.number_labels[-2:] == ["Price", "Quantity"]
    assert fake_streamlit.multiselect_labels == ["Sizes"]
    assert fake_streamlit.column_calls == 1
    assert fake_streamlit.submit_labels[-1] == "Create Listing Task"


def test_cp_submit_automatically_uses_grouped_payload_builder_without_price(
    monkeypatch,
) -> None:
    fake_streamlit = _CreateTaskStreamlit(submit_clicked=True)
    grouped_payload = {
        "staged_folder_name": "TSTGP",
        "mpn": "D304VG",
        "sku_listing_code": "D304VG",
        "listing_group": {"group_type": "christmas_project"},
        "size_price_map": {},
    }
    grouped_builder = Mock(return_value={
        "valid": True,
        "errors": [],
        "payload": grouped_payload,
    })
    ordinary_builder = Mock(side_effect=AssertionError("ordinary builder must not run for CP"))
    create_listing_task = Mock(return_value={"status": "Failed", "error": "test stop"})
    monkeypatch.setattr(
        product_setup,
        "build_grouped_christmas_staged_task_payload",
        grouped_builder,
    )
    monkeypatch.setattr(
        product_setup,
        "build_staged_listing_task_payload",
        ordinary_builder,
    )

    _render_create_form(
        {"template_key": "CP", "label": "Christmas Project", "parent_sku": "CP"},
        fake_streamlit,
        monkeypatch,
        create_listing_task=create_listing_task,
    )

    grouped_builder.assert_called_once()
    assert "price" not in grouped_builder.call_args.kwargs
    assert grouped_builder.call_args.kwargs["staged_folder_name"] == "TSTGP"
    assert grouped_builder.call_args.kwargs["mpn"] == "D304VG"
    assert grouped_builder.call_args.kwargs["sku_listing_code"] == "D304VG"
    ordinary_builder.assert_not_called()
    create_listing_task.assert_called_once()
    assert create_listing_task.call_args.kwargs["payload"] is grouped_payload
    assert create_listing_task.call_args.kwargs["staged_folder_name"] == "TSTGP"
    assert "MPN: `D304VG`" in fake_streamlit.captions
    assert any("PRINT-D304VG-T" in caption for caption in fake_streamlit.captions)


def test_blank_manual_code_uses_generated_code_for_new_mpn_without_changing_folder(
    monkeypatch,
) -> None:
    fake_streamlit = _CreateTaskStreamlit(
        submit_clicked=True,
        manual_listing_code="",
    )
    ordinary_payload = {
        "staged_folder_name": "TSTGP",
        "mpn": "D12345",
        "sku_listing_code": "D12345",
    }
    ordinary_builder = Mock(return_value={
        "valid": True,
        "errors": [],
        "payload": ordinary_payload,
    })
    create_listing_task = Mock(return_value={"status": "Failed", "error": "test stop"})
    monkeypatch.setattr(
        product_setup,
        "build_staged_listing_task_payload",
        ordinary_builder,
    )

    _render_create_form(
        {
            "template_key": "UC301",
            "label": "UC301",
            "parent_sku": "UC301",
            "sizes": ["S", "M"],
        },
        fake_streamlit,
        monkeypatch,
        create_listing_task=create_listing_task,
    )

    assert ordinary_builder.call_args.kwargs["staged_folder_name"] == "TSTGP"
    assert ordinary_builder.call_args.kwargs["mpn"] == "D12345"
    assert ordinary_builder.call_args.kwargs["sku_listing_code"] == "D12345"
    assert ordinary_builder.call_args.kwargs["generated_sku_listing_code"] == "D12345"
    assert create_listing_task.call_args.kwargs["staged_folder_name"] == "TSTGP"
    assert "MPN: `D12345`" in fake_streamlit.captions


def test_task_sku_context_reuses_passed_existing_helpers() -> None:
    sanitize_calls = []
    parent_calls = []

    def sanitize(value: str) -> str:
        sanitize_calls.append(value)
        return value.replace(" ", "-")

    def build_parent(profile, decoration, listing_code):
        parent_calls.append((profile, decoration, listing_code))
        return f"{decoration}-{listing_code}-UC301"

    profile = {"parent_sku": "UC301"}
    result = product_setup.resolve_staged_task_sku_context(
        profile=profile,
        decoration_choice="Custom",
        custom_decoration_code="custom print",
        manual_listing_code="design one",
        generated_listing_code="D12345",
        sanitize_sku=sanitize,
        get_default=lambda selected_profile, key, default: selected_profile.get(key, default),
        build_parent_sku_from_context=build_parent,
    )

    assert sanitize_calls == ["custom print", "design one", "D12345"]
    assert parent_calls == [(profile, "CUSTOM-PRINT", "DESIGN-ONE")]
    assert result["parent_sku"] == "CUSTOM-PRINT-DESIGN-ONE-UC301"


def test_successful_task_refreshes_caches_and_selects_new_staged_folder() -> None:
    state = {}
    refresh = Mock()
    clear_memory = Mock()
    clear_runtime = Mock()
    flash = Mock()
    result = {
        "folder_name": "ADMIN-MPN-001",
        "folder_path": "/Amazon/_stage/ADMIN-MPN-001",
        "listing_memory_path": "/Amazon/_stage/ADMIN-MPN-001/listing_inputs.json",
    }

    product_setup.apply_created_task_ui_state(
        result=result,
        session_state=state,
        refresh_cached_folder_names=refresh,
        clear_cached_listing_memory=clear_memory,
        clear_runtime_caches=clear_runtime,
        set_workflow_flash=flash,
    )

    refresh.assert_called_once_with("stage")
    clear_memory.assert_called_once_with("/Amazon/_stage/ADMIN-MPN-001")
    clear_runtime.assert_called_once_with()
    assert state["stage_folder_list_loaded"] is True
    assert state["auto_switch_to_staged"] is True
    assert state["pending_staged_folder_selection_on_rerun"] == "ADMIN-MPN-001"
    flash.assert_called_once()
