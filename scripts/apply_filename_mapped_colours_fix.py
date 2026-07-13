from __future__ import annotations

from pathlib import Path
import shutil


APP_PATH = Path("app.py")
BACKUP_PATH = Path("app_before_filename_mapped_colours_fix.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one {label} anchor, found {count}. "
            "The app may already be patched or may have changed."
        )
    return text.replace(old, new, 1)


def main() -> None:
    if not APP_PATH.exists():
        raise FileNotFoundError("Run this script from the repository root; app.py was not found.")

    text = APP_PATH.read_text(encoding="utf-8")
    shutil.copy2(APP_PATH, BACKUP_PATH)

    old_preservation = '''LISTING_WORKFLOW_PERSISTENT_WIDGET_PREFIXES = (\n    "bullet_",\n    "variant_",\n    "price_",\n    "cluster_price_",\n)\n\n\ndef preserve_listing_workflow_widget_state() -> None:\n    """Interrupt Streamlit cleanup for widgets hidden by the workflow segmented control."""\n    for key in list(st.session_state.keys()):\n        key_text = str(key)\n        if (\n            key_text in LISTING_WORKFLOW_PERSISTENT_WIDGET_KEYS\n            or key_text.startswith(LISTING_WORKFLOW_PERSISTENT_WIDGET_PREFIXES)\n        ):\n            st.session_state[key] = st.session_state[key]\n'''
    new_preservation = '''LISTING_WORKFLOW_PERSISTENT_WIDGET_PREFIXES = (\n    "bullet_",\n    "variant_",\n    "price_",\n    "cluster_price_",\n)\n\nLISTING_WORKFLOW_ACTION_WIDGET_SUFFIXES = (\n    "_all",\n    "_none",\n    "_mapped",\n)\n\n\ndef preserve_listing_workflow_widget_state() -> None:\n    """Interrupt Streamlit cleanup for value widgets hidden by the workflow control."""\n    for key in list(st.session_state.keys()):\n        key_text = str(key)\n        is_variant_action_button = (\n            key_text.startswith("variant_")\n            and key_text.endswith(LISTING_WORKFLOW_ACTION_WIDGET_SUFFIXES)\n        )\n        if is_variant_action_button:\n            # Streamlit buttons cannot be assigned through session_state.\n            st.session_state.pop(key, None)\n            continue\n        if (\n            key_text in LISTING_WORKFLOW_PERSISTENT_WIDGET_KEYS\n            or key_text.startswith(LISTING_WORKFLOW_PERSISTENT_WIDGET_PREFIXES)\n        ):\n            st.session_state[key] = st.session_state[key]\n'''
    text = replace_once(
        text,
        old_preservation,
        new_preservation,
        "workflow action-button exclusion",
    )

    old_helper_anchor = '''def get_mapped_color_options(\n    valid_colors: list[str],\n    color_image_map: dict[str, str],\n    design_color_image_url_map: dict[str, dict[str, str]],\n) -> list[str]:\n    valid_color_set = set(valid_colors)\n    mapped_colors: list[str] = []\n\n    for color in list(color_image_map.keys()) + list(design_color_image_url_map.keys()):\n        if color in valid_color_set and color not in mapped_colors:\n            mapped_colors.append(color)\n\n    return mapped_colors\n\n\ndef build_lenient_image_maps(\n'''
    new_helper_anchor = '''def get_mapped_color_options(\n    valid_colors: list[str],\n    color_image_map: dict[str, str],\n    design_color_image_url_map: dict[str, dict[str, str]],\n) -> list[str]:\n    valid_color_set = set(valid_colors)\n    mapped_colors: list[str] = []\n\n    for color in list(color_image_map.keys()) + list(design_color_image_url_map.keys()):\n        if color in valid_color_set and color not in mapped_colors:\n            mapped_colors.append(color)\n\n    return mapped_colors\n\n\ndef get_mapped_color_options_from_filenames(\n    valid_colors: list[str],\n    image_paths: list[str],\n    *,\n    template_key: str = "",\n    main_image_map: dict[str, str] | None = None,\n    color_sku_map: dict[str, str] | None = None,\n) -> list[str]:\n    """Match staged colours from filenames only; no image URL or image-byte loading."""\n    main_image_map = dict(main_image_map or {})\n    color_sku_map = dict(color_sku_map or {})\n\n    filename_rows: list[tuple[str, str, list[str]]] = []\n    for path in list(image_paths or []):\n        filename = Path(str(path or "")).name\n        if not filename or not is_image_file(filename):\n            continue\n        filename_rows.append((\n            filename.lower(),\n            normalize_image_match_key(filename),\n            tokenize_image_match_value(filename),\n        ))\n\n    mapped_colors: list[str] = []\n    for color in list(valid_colors or []):\n        configured_filename = str(main_image_map.get(color, "") or "")\n        color_code = str(color_sku_map.get(color, "") or "")\n        candidates = build_color_image_filename_candidates(\n            template_key,\n            color,\n            configured_filename,\n            color_code,\n        )\n        candidate_names = {candidate.lower() for candidate in candidates if candidate}\n        candidate_keys = {\n            normalize_image_match_key(candidate)\n            for candidate in candidates\n            if normalize_image_match_key(candidate)\n        }\n\n        exact_match = any(\n            filename_lower in candidate_names or filename_key in candidate_keys\n            for filename_lower, filename_key, _ in filename_rows\n        )\n        if exact_match:\n            mapped_colors.append(color)\n            continue\n\n        color_tokens = tokenize_image_match_value(color)\n        color_code_tokens = tokenize_image_match_value(color_code)\n        token_match = any(\n            contains_token_sequence(filename_tokens, color_tokens)\n            or (\n                bool(color_code_tokens)\n                and contains_token_sequence(filename_tokens, color_code_tokens)\n            )\n            for _, _, filename_tokens in filename_rows\n        )\n        if token_match:\n            mapped_colors.append(color)\n\n    return mapped_colors\n\n\ndef merge_mapped_color_options(*color_groups: list[str]) -> list[str]:\n    merged: list[str] = []\n    for group in color_groups:\n        for color in list(group or []):\n            if color not in merged:\n                merged.append(color)\n    return merged\n\n\ndef build_lenient_image_maps(\n'''
    text = replace_once(
        text,
        old_helper_anchor,
        new_helper_anchor,
        "filename mapped-colour helper",
    )

    old_variant_mapping = '''                    mapped_colors = get_mapped_color_options(\n                        list(dim_options),\n                        full_preview_color_image_map,\n                        full_preview_design_color_image_url_map,\n                    )\n'''
    new_variant_mapping = '''                    mapped_colors = merge_mapped_color_options(\n                        get_mapped_color_options(\n                            list(dim_options),\n                            full_preview_color_image_map,\n                            full_preview_design_color_image_url_map,\n                        ),\n                        get_mapped_color_options_from_filenames(\n                            list(dim_options),\n                            staged_preview_paths,\n                            template_key=str(dropbox_overview.get("template_key", "") or profile.get("template_key", "") or ""),\n                            main_image_map=dict(dropbox_overview.get("main_image_map", {}) or {}),\n                            color_sku_map=dict(dropbox_overview.get("color_sku_map", {}) or profile.get("color_sku_map", {}) or {}),\n                        ),\n                    )\n'''
    text = replace_once(
        text,
        old_variant_mapping,
        new_variant_mapping,
        "variant filename mapped-colour calculation",
    )

    old_standard_mapping = '''            mapped_colors = get_mapped_color_options(\n                list(colors_available),\n                full_preview_color_image_map,\n                full_preview_design_color_image_url_map,\n            )\n'''
    new_standard_mapping = '''            mapped_colors = merge_mapped_color_options(\n                get_mapped_color_options(\n                    list(colors_available),\n                    full_preview_color_image_map,\n                    full_preview_design_color_image_url_map,\n                ),\n                get_mapped_color_options_from_filenames(\n                    list(colors_available),\n                    staged_preview_paths,\n                    template_key=str(dropbox_overview.get("template_key", "") or profile.get("template_key", "") or ""),\n                    main_image_map=dict(dropbox_overview.get("main_image_map", {}) or {}),\n                    color_sku_map=dict(dropbox_overview.get("color_sku_map", {}) or profile.get("color_sku_map", {}) or {}),\n                ),\n            )\n'''
    text = replace_once(
        text,
        old_standard_mapping,
        new_standard_mapping,
        "standard filename mapped-colour calculation",
    )

    old_variant_fallback = '''                        else:\n                            st.session_state["apply_mapped_colours_widget_key"] = widget_key\n                            st.session_state["load_image_mappings_now"] = True\n                            if staged_folder_name:\n                                st.session_state["image_mappings_loaded_folder"] = staged_folder_name\n                                st.session_state["image_mappings_loaded_context"] = image_mapping_context_key\n                            st.rerun()\n'''
    new_variant_fallback = '''                        else:\n                            st.warning(\n                                "No configured colour matched the staged image filenames. "\n                                "Check the colour name/code in the filenames."\n                            )\n'''
    text = replace_once(
        text,
        old_variant_fallback,
        new_variant_fallback,
        "variant mapped-colour heavy-load fallback",
    )

    old_standard_fallback = '''                else:\n                    st.session_state["apply_mapped_colours_widget_key"] = "selected_colours"\n                    st.session_state["load_image_mappings_now"] = True\n                    if staged_folder_name:\n                        st.session_state["image_mappings_loaded_folder"] = staged_folder_name\n                        st.session_state["image_mappings_loaded_context"] = image_mapping_context_key\n                    st.rerun()\n'''
    new_standard_fallback = '''                else:\n                    st.warning(\n                        "No configured colour matched the staged image filenames. "\n                        "Check the colour name/code in the filenames."\n                    )\n'''
    text = replace_once(
        text,
        old_standard_fallback,
        new_standard_fallback,
        "standard mapped-colour heavy-load fallback",
    )

    APP_PATH.write_text(text, encoding="utf-8")
    print(f"Patched {APP_PATH} successfully.")
    print(f"Backup written to {BACKUP_PATH}.")


if __name__ == "__main__":
    main()
