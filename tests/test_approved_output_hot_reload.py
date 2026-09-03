from __future__ import annotations

import inspect

import app


def test_approved_output_history_dependency_is_guarded_for_hot_reload() -> None:
    source = inspect.getsource(app.main)

    assert 'inspect.signature(render_approved_output).parameters' in source
    assert 'approved_output_kwargs["build_finished_generation_history_rows"]' in source
    assert "render_approved_output(**approved_output_kwargs)" in source
