from __future__ import annotations

import ast
import importlib
from pathlib import Path


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
