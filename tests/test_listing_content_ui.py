from __future__ import annotations

import ast
import importlib
from pathlib import Path


WIDGET_METHODS = {
    "button",
    "multiselect",
    "number_input",
    "selectbox",
    "text_area",
    "text_input",
}


def _module_tree() -> tuple[object, ast.Module]:
    module = importlib.import_module("ui.listing_content")
    module_path = Path(module.__file__)
    return module, ast.parse(module_path.read_text(encoding="utf-8"))


def test_listing_content_ui_imports_without_app_dependency() -> None:
    module, tree = _module_tree()

    assert callable(module.render_listing_content)

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


def test_listing_content_widget_labels_and_keys_are_preserved() -> None:
    _, tree = _module_tree()
    renderer = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "render_listing_content"
    )
    widget_calls = []
    for call in sorted(
        (node for node in ast.walk(renderer) if isinstance(node, ast.Call)),
        key=lambda node: (node.lineno, node.col_offset),
    ):
        if not isinstance(call.func, ast.Attribute) or call.func.attr not in WIDGET_METHODS:
            continue
        label = ast.unparse(call.args[0]) if call.args else None
        key = next(
            (ast.unparse(keyword.value) for keyword in call.keywords if keyword.arg == "key"),
            None,
        )
        widget_calls.append((call.func.attr, label, key))

    assert widget_calls == [
        ("button", "'Fill fields from listing_inputs.json'", "'fill_listing_content_from_json_btn'"),
        ("text_input", "'Product title'", "CONTENT_EDITOR_KEYS['title']"),
        ("text_input", "'Bullet 1'", "CONTENT_EDITOR_KEYS['bullets'][0]"),
        ("text_input", "'Bullet 2'", "CONTENT_EDITOR_KEYS['bullets'][1]"),
        ("text_input", "'Bullet 3'", "CONTENT_EDITOR_KEYS['bullets'][2]"),
        ("text_input", "'Bullet 4'", "CONTENT_EDITOR_KEYS['bullets'][3]"),
        ("text_input", "'Bullet 5'", "CONTENT_EDITOR_KEYS['bullets'][4]"),
        ("text_area", "'Product description'", "CONTENT_EDITOR_KEYS['description']"),
        ("text_area", "'Search terms'", "CONTENT_EDITOR_KEYS['keywords']"),
        ("number_input", "'Handling time'", "'handling_time_days'"),
        ("selectbox", "'Merchant Shipping Group'", "'merchant_shipping_group_name'"),
        ("button", "'All colours'", "f'{widget_key}_all'"),
        ("button", "'No colours'", "f'{widget_key}_none'"),
        ("button", "'Mapped colours'", "f'{widget_key}_mapped'"),
        ("multiselect", "dim_label", "widget_key"),
        ("button", "'All colours'", "'selected_colours_all'"),
        ("button", "'No colours'", "'selected_colours_none'"),
        ("button", "'Mapped colours'", "'selected_colours_mapped'"),
        ("multiselect", "'Colours'", "'selected_colours'"),
        ("multiselect", "'Sizes'", "'selected_sizes'"),
        ("selectbox", "'Decoration code'", "'sku_decoration_choice'"),
        ("text_input", "'Custom decoration code'", "'custom_sku_decoration_code'"),
        ("text_input", "'Listing/design code (optional)'", "'manual_sku_listing_code'"),
        ("number_input", "'Quantity for all child variants'", "'variant_quantity'"),
        ("selectbox", "'Content prepared by'", "'content_prepared_by'"),
        ("button", "'Check listing score'", None),
        ("button", "'Submit for Review'", None),
    ]
