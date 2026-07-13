from __future__ import annotations

from pathlib import Path
import shutil


APP_PATH = Path("app.py")
BACKUP_PATH = Path("app_before_auto_mapped_colours_delivery_fix.py")


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

    text = replace_once(
        text,
        '''        if is_variant_action_button:\n            # Streamlit buttons cannot be assigned through session_state.\n            st.session_state.pop(key, None)\n            continue\n''',
        '''        if is_variant_action_button:\n            # Leave button-owned state untouched so Streamlit can deliver the click.\n            continue\n''',
        "mapped-colour button click delivery",
    )

    text = replace_once(
        text,
        '''def merge_mapped_color_options(*color_groups: list[str]) -> list[str]:\n    merged: list[str] = []\n    for group in color_groups:\n        for color in list(group or []):\n            if color not in merged:\n                merged.append(color)\n    return merged\n\n\ndef build_lenient_image_maps(\n''',
        '''def merge_mapped_color_options(*color_groups: list[str]) -> list[str]:\n    merged: list[str] = []\n    for group in color_groups:\n        for color in list(group or []):\n            if color not in merged:\n                merged.append(color)\n    return merged\n\n\ndef auto_apply_mapped_colours_once(\n    widget_key: str,\n    mapped_colors: list[str],\n    staged_folder_name: str,\n    profile: dict[str, Any],\n    staged_preview_paths: list[str],\n) -> bool:\n    \"\"\"Apply filename-matched colours once per folder/template/file set.\n\n    Later manual colour edits are preserved until the folder, template, or staged\n    image filenames change. No image URLs or image bytes are loaded here.\n    \"\"\"\n    if not staged_folder_name or not mapped_colors:\n        return False\n\n    context = json.dumps(\n        {\n            \"folder\": staged_folder_name,\n            \"template\": profile.get(\"template_key\", profile.get(\"_slug\", \"\")),\n            \"widget\": widget_key,\n            \"files\": sorted(Path(str(path or \"\")).name for path in staged_preview_paths),\n        },\n        sort_keys=True,\n    )\n    context_key = f\"auto_mapped_colours_context::{widget_key}\"\n    if st.session_state.get(context_key) == context:\n        return False\n\n    st.session_state[widget_key] = list(mapped_colors)\n    st.session_state[context_key] = context\n    return True\n\n\ndef build_lenient_image_maps(\n''',
        "automatic mapped-colour helper",
    )

    variant_mapping_block = '''                    mapped_colors = merge_mapped_color_options(\n                        get_mapped_color_options(\n                            list(dim_options),\n                            full_preview_color_image_map,\n                            full_preview_design_color_image_url_map,\n                        ),\n                        get_mapped_color_options_from_filenames(\n                            list(dim_options),\n                            staged_preview_paths,\n                            template_key=str(dropbox_overview.get(\"template_key\", \"\") or profile.get(\"template_key\", \"\") or \"\"),\n                            main_image_map=dict(dropbox_overview.get(\"main_image_map\", {}) or {}),\n                            color_sku_map=dict(dropbox_overview.get(\"color_sku_map\", {}) or profile.get(\"color_sku_map\", {}) or {}),\n                        ),\n                    )\n'''
    text = replace_once(
        text,
        variant_mapping_block,
        variant_mapping_block + '''                    auto_apply_mapped_colours_once(\n                        widget_key,\n                        mapped_colors,\n                        staged_folder_name or \"\",\n                        profile,\n                        staged_preview_paths,\n                    )\n''',
        "variant automatic mapped-colour application",
    )

    standard_mapping_block = '''            mapped_colors = merge_mapped_color_options(\n                get_mapped_color_options(\n                    list(colors_available),\n                    full_preview_color_image_map,\n                    full_preview_design_color_image_url_map,\n                ),\n                get_mapped_color_options_from_filenames(\n                    list(colors_available),\n                    staged_preview_paths,\n                    template_key=str(dropbox_overview.get(\"template_key\", \"\") or profile.get(\"template_key\", \"\") or \"\"),\n                    main_image_map=dict(dropbox_overview.get(\"main_image_map\", {}) or {}),\n                    color_sku_map=dict(dropbox_overview.get(\"color_sku_map\", {}) or profile.get(\"color_sku_map\", {}) or {}),\n                ),\n            )\n'''
    text = replace_once(
        text,
        standard_mapping_block,
        standard_mapping_block + '''            auto_apply_mapped_colours_once(\n                \"selected_colours\",\n                mapped_colors,\n                staged_folder_name or \"\",\n                profile,\n                staged_preview_paths,\n            )\n''',
        "standard automatic mapped-colour application",
    )

    APP_PATH.write_text(text, encoding="utf-8")
    print(f"Patched {APP_PATH} successfully.")
    print(f"Backup written to {BACKUP_PATH}.")


if __name__ == "__main__":
    main()
