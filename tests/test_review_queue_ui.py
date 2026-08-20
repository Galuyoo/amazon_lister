from __future__ import annotations

import ast
import importlib
from pathlib import Path


def _module_tree() -> tuple[object, ast.Module]:
    module = importlib.import_module("ui.review_queue")
    module_path = Path(module.__file__)
    return module, ast.parse(module_path.read_text(encoding="utf-8"))


def test_review_queue_ui_imports_without_app_dependency() -> None:
    module, tree = _module_tree()

    assert callable(module.render_review_queue)

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


def test_review_queue_widget_labels_and_keys_are_preserved() -> None:
    _, tree = _module_tree()
    renderer = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "render_review_queue"
    )
    streamlit_calls = []
    for call in sorted(
        (node for node in ast.walk(renderer) if isinstance(node, ast.Call)),
        key=lambda node: (node.lineno, node.col_offset),
    ):
        if not (
            isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "st"
        ):
            continue
        label = ast.unparse(call.args[0]) if call.args else None
        key = next(
            (ast.unparse(keyword.value) for keyword in call.keywords if keyword.arg == "key"),
            None,
        )
        streamlit_calls.append((call.func.attr, label, key))

    assert streamlit_calls == [
        ("caption", "'Review ready listings and approve them for generation.'", None),
        ("columns", "[1, 3]", None),
        ("button", "'Load / refresh review queue'", "'load_review_queue_tab_btn'"),
        (
            "info",
            "'Review queue is not loaded yet. Click Load / refresh review queue when you need admin review.'",
            None,
        ),
    ]


def test_review_queue_session_state_keys_are_preserved() -> None:
    _, tree = _module_tree()
    renderer = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "render_review_queue"
    )
    session_state_keys: set[str] = set()

    for node in ast.walk(renderer):
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

    assert session_state_keys == {
        "active_perf_action_label",
        "ready_queue_items_cache",
        "review_queue_tab_loaded",
    }
