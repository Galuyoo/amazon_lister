from __future__ import annotations

import inspect

import app
from ui import product_setup


def test_zip_upload_invalidates_images_without_requesting_an_automatic_reload() -> None:
    source = inspect.getsource(app.render_stage_images_zip_upload)

    assert "clear_loaded_image_mapping_state(st.session_state)" in source
    assert 'st.session_state["load_image_mappings_now"] = True' not in source
    assert 'st.session_state["load_image_mappings_now"] = bool(uploaded_zip)' not in source


def test_image_mapping_invalidation_preserves_unrelated_session_state() -> None:
    state = {
        "load_image_mappings_now": True,
        "image_mappings_loaded_folder": "STAGED",
        "image_mappings_loaded_context": "context",
        "preview_image_cache": {"cached": True},
        "preview_image_mapping_cache": {"cached": True},
        "resolved_image_bundle_cache": {"cached": True},
        "listing_content_value": "keep me",
    }

    app.clear_loaded_image_mapping_state(state)

    assert state == {"listing_content_value": "keep me"}


def test_unloaded_product_setup_hides_image_review_content() -> None:
    source = inspect.getsource(product_setup.render_product_setup)

    unloaded_guard = source.index('    if image_mapping_status != "loaded":')
    loaded_panel = source.index(
        '        with st.expander("Dropbox image overview", expanded=True):',
        unloaded_guard,
    )

    assert unloaded_guard < loaded_panel
    assert "Images remain unloaded for faster editing." in source


def test_preview_dropbox_reads_are_conditional_on_loading_image_mappings() -> None:
    source = inspect.getsource(app.main)
    conditional = source.index("    if should_load_image_mappings:")
    preview_read = source.index(
        "        preview_image_data = get_cached_preview_image_data(",
        conditional,
    )

    assert conditional < preview_read
    assert "auto_apply_mapped_colors = False" in source
