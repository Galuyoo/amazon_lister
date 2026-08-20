from __future__ import annotations

import ast
import importlib
from pathlib import Path


WIDGET_METHODS = {
    "button",
    "form_submit_button",
    "multiselect",
    "radio",
    "selectbox",
    "text_input",
}


def _module_tree() -> tuple[object, ast.Module]:
    module = importlib.import_module("ui.approved_output")
    module_path = Path(module.__file__)
    return module, ast.parse(module_path.read_text(encoding="utf-8"))


def _renderer(tree: ast.Module) -> ast.FunctionDef:
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "render_approved_output"
    )


def test_approved_output_ui_imports_without_app_dependency() -> None:
    module, tree = _module_tree()

    assert callable(module.render_approved_output)

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


def test_approved_output_widget_labels_and_keys_are_preserved() -> None:
    _, tree = _module_tree()
    widget_calls = []
    for call in sorted(
        (node for node in ast.walk(_renderer(tree)) if isinstance(node, ast.Call)),
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
        ("multiselect", "'Select finished folders'", "'finished_output_restage_selected'"),
        ("radio", "'Bring back to'", "'finished_output_return_destination'"),
        ("form_submit_button", "'Bring selected finished folders back'", None),
        (
            "multiselect",
            "'Select finished generations to ignore'",
            "'finished_output_ignore_selected'",
        ),
        ("text_input", "'Reason'", "'finished_output_ignore_reason'"),
        ("selectbox", "'Marked by'", "'finished_output_ignore_by'"),
        ("form_submit_button", "'Mark selected generation(s) ignored'", None),
        ("button", "'Load / refresh approved output'", "'load_approved_output_tab_btn'"),
    ]


def test_approved_output_form_and_session_state_keys_are_preserved() -> None:
    _, tree = _module_tree()
    renderer = _renderer(tree)
    form_keys = []
    session_state_keys: set[str] = set()

    for node in ast.walk(renderer):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "st"
            and node.func.attr == "form"
        ):
            form_keys.append(ast.unparse(node.args[0]))
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            value = node.value
            if isinstance(value, ast.Attribute) and value.attr == "session_state":
                session_state_keys.add(node.slice.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            value = node.func.value
            if (
                isinstance(value, ast.Attribute)
                and value.attr == "session_state"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                session_state_keys.add(node.args[0].value)

    assert sorted(form_keys) == [
        "'finished_output_ignore_form'",
        "'finished_output_restaging_form'",
    ]
    assert session_state_keys == {
        "active_perf_action_label",
        "approved_output_tab_loaded",
        "approved_queue_items_cache",
        "finished_ignore_results",
        "finished_output_ignore_selected",
        "finished_output_restage_selected",
        "finished_restage_results",
        "pending_perf_action_label",
    }


def test_approved_output_workflow_implementations_remain_in_app() -> None:
    _, ui_tree = _module_tree()
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app_tree = ast.parse(app_path.read_text(encoding="utf-8"))
    implementation_names = {
        "build_combined_workbook",
        "generate_approved_listing",
        "generate_approved_listings_combined",
        "mark_finished_generation_ignored",
        "move_successful_generation_results_to_finished",
        "render_approved_queue_view",
        "restage_finished_listing_for_review",
        "save_generated_artifacts_to_dropbox",
    }
    ui_function_names = {
        node.name for node in ui_tree.body if isinstance(node, ast.FunctionDef)
    }
    app_function_names = {
        node.name for node in app_tree.body if isinstance(node, ast.FunctionDef)
    }

    assert ui_function_names.isdisjoint(implementation_names)
    assert implementation_names <= app_function_names
