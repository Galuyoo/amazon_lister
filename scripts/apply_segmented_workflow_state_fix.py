from __future__ import annotations

from pathlib import Path
import shutil


APP_PATH = Path("app.py")
BACKUP_PATH = Path("app_before_segmented_workflow_state_fix.py")


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
        '''def initialize_listing_context_defaults(profile: dict[str, Any]) -> None:\n''',
        '''LISTING_WORKFLOW_PERSISTENT_WIDGET_KEYS = {\n    "folder_source_mode",\n    "staged_folder_select",\n    "finished_folder_select",\n    "template_family_select",\n    "listing_template_select",\n    "assets_prepared_by",\n    "title_input",\n    "product_description",\n    "generic_keywords",\n    "handling_time_days",\n    "merchant_shipping_group_name",\n    "selected_colours",\n    "selected_sizes",\n    "sku_decoration_choice",\n    "custom_sku_decoration_code",\n    "manual_sku_listing_code",\n    "generated_sku_listing_code",\n    "variant_quantity",\n    "content_prepared_by",\n    "use_same_price_for_all_sizes",\n    "shared_price_all_sizes",\n    "design_size_pricing_mode",\n    "parent_main_image_choice",\n    "use_resource_fallback_images",\n}\n\nLISTING_WORKFLOW_PERSISTENT_WIDGET_PREFIXES = (\n    "bullet_",\n    "variant_",\n    "price_",\n    "cluster_price_",\n)\n\n\ndef preserve_listing_workflow_widget_state() -> None:\n    """Interrupt Streamlit cleanup for widgets hidden by the workflow segmented control."""\n    for key in list(st.session_state.keys()):\n        key_text = str(key)\n        if (\n            key_text in LISTING_WORKFLOW_PERSISTENT_WIDGET_KEYS\n            or key_text.startswith(LISTING_WORKFLOW_PERSISTENT_WIDGET_PREFIXES)\n        ):\n            st.session_state[key] = st.session_state[key]\n\n\ndef get_required_listing_editor_state_keys(profile: dict[str, Any]) -> list[str]:\n    required_keys = [\n        "title_input",\n        "bullet_1",\n        "bullet_2",\n        "bullet_3",\n        "bullet_4",\n        "bullet_5",\n        "product_description",\n        "generic_keywords",\n        "handling_time_days",\n        "merchant_shipping_group_name",\n        "sku_decoration_choice",\n        "custom_sku_decoration_code",\n        "manual_sku_listing_code",\n        "generated_sku_listing_code",\n        "variant_quantity",\n        "parent_main_image_choice",\n    ]\n\n    variant_dimensions = list(profile.get("variant_dimensions", []) or [])\n    if variant_dimensions:\n        required_keys.extend(\n            f"variant_{str(dim.get('name', '') or '').strip()}"\n            for dim in variant_dimensions\n            if str(dim.get("name", "") or "").strip()\n        )\n    else:\n        required_keys.extend(["selected_colours", "selected_sizes"])\n\n    return required_keys\n\n\ndef has_complete_listing_editor_state(profile: dict[str, Any]) -> bool:\n    return all(\n        key in st.session_state\n        for key in get_required_listing_editor_state_keys(profile)\n    )\n\n\ndef initialize_listing_context_defaults(profile: dict[str, Any]) -> None:\n''',
        "listing workflow state helpers",
    )

    text = replace_once(
        text,
        '''def main() -> None:\n    st.set_page_config(page_title="Amazon Listing Generator", layout="wide")\n''',
        '''def main() -> None:\n    st.set_page_config(page_title="Amazon Listing Generator", layout="wide")\n    preserve_listing_workflow_widget_state()\n''',
        "main workflow state preservation call",
    )

    text = replace_once(
        text,
        '''        should_apply_memory = applied_memory_key != memory_fingerprint\n''',
        '''        should_apply_memory = (\n            applied_memory_key != memory_fingerprint\n            or not has_complete_listing_editor_state(active_profile)\n        )\n''',
        "saved listing memory rehydration guard",
    )

    text = replace_once(
        text,
        '''        if initialized_context_key != listing_context_key:\n            initialize_listing_context_defaults(active_profile)\n''',
        '''        if (\n            initialized_context_key != listing_context_key\n            or not has_complete_listing_editor_state(active_profile)\n        ):\n            initialize_listing_context_defaults(active_profile)\n''',
        "new listing default rehydration guard",
    )

    APP_PATH.write_text(text, encoding="utf-8")
    print(f"Patched {APP_PATH} successfully.")
    print(f"Backup written to {BACKUP_PATH}.")


if __name__ == "__main__":
    main()
