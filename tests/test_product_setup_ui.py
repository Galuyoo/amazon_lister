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
        'st.text_input("MPN", key="create_task_mpn")',
        '"create_task_price"',
        '"create_task_quantity"',
        '"create_task_shipping_group"',
        '"create_task_sizes"',
        '"create_task_sku_decoration_choice"',
        '"create_task_manual_sku_listing_code"',
        '"Create Listing Task"',
        'key="create_staged_listing_task_btn"',
    }
    assert all(item in source for item in expected_widget_contract)
    assert "content_title_input_v3" not in source
    assert "content_bullet_1_v3" not in source


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
