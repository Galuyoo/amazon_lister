from __future__ import annotations

from typing import Any, Callable

import streamlit as st


def render_listing_content(
    *,
    active_staged_folder_name: str,
    active_template_label: str,
    selected_parent_main_label: str,
    preview_parent_main_image_url: str,
    preview_color_image_map: dict[str, str],
    preview_design_color_image_url_map: dict[str, dict[str, str]],
    preview_other_images: list[str],
    image_mapping_status: str,
    image_mapping_detail: str,
    staged_folder_name: str | None,
    listing_memory: dict[str, Any],
    active_profile: dict[str, Any],
    profile: dict[str, Any],
    memory_fingerprint: str,
    CONTENT_EDITOR_KEYS: dict[str, Any],
    MERCHANT_SHIPPING_GROUP_OPTIONS: list[str],
    SKU_DECORATION_OPTIONS: list[str],
    WORKFLOW_ASSIGNEES: list[str],
    variant_dimensions: list[dict[str, Any]],
    selected_variants: dict[str, list[str]],
    colors_available: list[str],
    full_preview_color_image_map: dict[str, str],
    full_preview_design_color_image_url_map: dict[str, dict[str, str]],
    auto_apply_mapped_colors: bool,
    image_mapping_context_key: str,
    render_active_product_context: Callable[..., None],
    listing_memory_has_content: Callable[..., bool],
    apply_listing_memory_to_session: Callable[..., None],
    words_repeated_at_least: Callable[..., list[str]],
    find_forbidden_title_phrases_for_app: Callable[..., list[str]],
    sync_content_editor_to_canonical_state: Callable[..., None],
    trim_search_terms: Callable[..., str],
    normalize_merchant_shipping_group: Callable[..., str],
    selectbox_index_without_state_conflict: Callable[..., int],
    get_mapped_color_options: Callable[..., list[str]],
    apply_mapped_colors_to_widget_once: Callable[..., None],
    get_available_sizes_for_selected_colors: Callable[..., list[str]],
    normalize_multiselect_values: Callable[..., tuple[list[str], bool]],
    get_default_sku_decoration_code: Callable[..., str],
    sanitize_sku: Callable[..., str],
    get_or_create_generated_sku_listing_code: Callable[..., str],
    build_parent_sku_from_context: Callable[..., str],
    render_variant_combinations_preview: Callable[..., None],
    build_size_price_inputs: Callable[..., dict[str, float]],
) -> dict[str, Any]:
    render_active_product_context(
        active_staged_folder_name=active_staged_folder_name,
        active_template_label=active_template_label,
        selected_parent_main_label=selected_parent_main_label,
        preview_parent_main_image_url=preview_parent_main_image_url,
        preview_color_image_map=preview_color_image_map,
        preview_design_color_image_url_map=preview_design_color_image_url_map,
        preview_other_images=preview_other_images,
        image_mapping_status=image_mapping_status,
        image_mapping_detail=image_mapping_detail,
    )

    if staged_folder_name and listing_memory_has_content(listing_memory):
        fill_col, info_col = st.columns([1, 3])
        with fill_col:
            fill_from_json_clicked = st.button(
                "Fill fields from listing_inputs.json",
                key="fill_listing_content_from_json_btn",
                width="stretch",
                help="Use this when a restaged folder has saved content but the editable fields are blank.",
            )
        with info_col:
            st.caption(
                "Saved content is available for this staged folder. "
                "Click the button if the editable fields did not hydrate automatically."
            )

        if fill_from_json_clicked:
            apply_listing_memory_to_session(listing_memory, active_profile)
            current_memory_fingerprint = memory_fingerprint
            if current_memory_fingerprint:
                st.session_state["applied_listing_memory_key_v2"] = current_memory_fingerprint
                st.session_state["applied_listing_memory_widget_key_v2"] = current_memory_fingerprint
            st.success("Filled editable content fields from listing_inputs.json.")

    title = st.text_input(
        "Product title",
        key=CONTENT_EDITOR_KEYS["title"],
    )
    if st.session_state.get("show_header_debug", False):
        st.caption(f"Loaded title debug: {title or '[empty]'}")

    title_chars = len(title.strip())
    if title_chars < 150:
        st.caption(f"Title: {title_chars} chars - target 150 chars")
    else:
        st.caption(f"Title: {title_chars} chars - good")
    repeated_title_words = words_repeated_at_least(title, 3)
    if repeated_title_words:
        st.error(
            "Amazon may reject titles where one word appears 3+ times: "
            + ", ".join(repeated_title_words[:8])
        )
    forbidden_title_phrases = find_forbidden_title_phrases_for_app(title)
    if forbidden_title_phrases:
        st.error(
            "Amazon rejected phrase in title: "
            + ", ".join(forbidden_title_phrases)
        )

    st.subheader("Bullets")
    bullets = [
        st.text_input("Bullet 1", key=CONTENT_EDITOR_KEYS["bullets"][0]),
        st.text_input("Bullet 2", key=CONTENT_EDITOR_KEYS["bullets"][1]),
        st.text_input("Bullet 3", key=CONTENT_EDITOR_KEYS["bullets"][2]),
        st.text_input("Bullet 4", key=CONTENT_EDITOR_KEYS["bullets"][3]),
        st.text_input("Bullet 5", key=CONTENT_EDITOR_KEYS["bullets"][4]),
    ]

    for idx, bullet in enumerate(bullets, start=1):
        bullet_len = len(bullet.strip())
        if bullet_len < 150:
            st.caption(f"Bullet {idx}: {bullet_len} chars - target 150+")
        else:
            st.caption(f"Bullet {idx}: {bullet_len} chars - good")

    st.subheader("Description and search terms")
    product_description = st.text_area(
        "Product description",
        height=120,
        key=CONTENT_EDITOR_KEYS["description"],
    )

    description_chars = len(product_description.strip())
    if description_chars < 1000:
        st.caption(f"Description: {description_chars} chars - target 1000 to 2000")
    elif description_chars <= 2000:
        st.caption(f"Description: {description_chars} chars - good")
    else:
        st.error(f"Description: {description_chars} chars - must be under 2000")

    generic_keywords = st.text_area(
        "Search terms",
        height=100,
        key=CONTENT_EDITOR_KEYS["keywords"],
    )
    sync_content_editor_to_canonical_state(
        title,
        bullets,
        product_description,
        generic_keywords,
    )

    byte_count = len(generic_keywords.encode("utf-8"))
    max_bytes = 249

    if byte_count < max_bytes * 0.8:
        st.caption(f"{byte_count}/{max_bytes} bytes")
    elif byte_count <= max_bytes:
        st.warning(f"{byte_count}/{max_bytes} bytes (near limit)")
    else:
        st.error(f"{byte_count}/{max_bytes} bytes (too long)")

    trimmed_keywords = trim_search_terms(generic_keywords)
    if trimmed_keywords != generic_keywords.strip():
        st.warning("Search terms will be trimmed to fit Amazon limit:")
        st.code(trimmed_keywords)

    st.subheader("Fulfillment")
    fulfillment_col1, fulfillment_col2 = st.columns(2)
    with fulfillment_col1:
        handling_time_days = st.number_input(
            "Handling time",
            min_value=0,
            step=1,
            key="handling_time_days",
            help="Writes fulfillment lead time for child rows. Default is 2.",
        )
    with fulfillment_col2:
        current_shipping_group = normalize_merchant_shipping_group(
            st.session_state.get("merchant_shipping_group_name", "")
        )
        st.selectbox(
            "Merchant Shipping Group",
            MERCHANT_SHIPPING_GROUP_OPTIONS,
            index=selectbox_index_without_state_conflict(
                "merchant_shipping_group_name",
                MERCHANT_SHIPPING_GROUP_OPTIONS,
                current_shipping_group,
            ),
            key="merchant_shipping_group_name",
            help="Leave empty to skip this Amazon field.",
        )

    st.subheader("Variants")

    if variant_dimensions:
        selected_variants = {}
        for dim in variant_dimensions:
            dim_name = dim.get("name", "")
            dim_label = dim.get("label", dim_name.title())
            dim_options = dim.get("options", [])
            widget_key = f"variant_{dim_name}"
            if str(dim_name).strip().lower() in {"color", "colour"}:
                mapped_colors = get_mapped_color_options(
                    list(dim_options),
                    full_preview_color_image_map,
                    full_preview_design_color_image_url_map,
                )
                if auto_apply_mapped_colors:
                    apply_mapped_colors_to_widget_once(
                        widget_key,
                        mapped_colors,
                        image_mapping_context_key,
                        allow_replace_existing=True,
                    )
                action_cols = st.columns(3)
                if action_cols[0].button("All colours", key=f"{widget_key}_all", width="stretch"):
                    st.session_state[widget_key] = list(dim_options)
                    st.rerun()
                if action_cols[1].button("No colours", key=f"{widget_key}_none", width="stretch"):
                    st.session_state[widget_key] = []
                    st.rerun()
                if action_cols[2].button(
                    "Mapped colours",
                    key=f"{widget_key}_mapped",
                    width="stretch",
                    disabled=not bool(staged_folder_name),
                    help="Select only colours that have staged images mapped by filename.",
                ):
                    if mapped_colors:
                        st.session_state[widget_key] = list(mapped_colors)
                        st.rerun()
                    else:
                        st.session_state["apply_mapped_colours_widget_key"] = widget_key
                        st.session_state["scan_mapped_colours_now"] = True
                        st.rerun()

            selected_variants[dim_name] = st.multiselect(
                dim_label,
                dim_options,
                key=widget_key,
            )
    else:
        mapped_colors = get_mapped_color_options(
            list(colors_available),
            full_preview_color_image_map,
            full_preview_design_color_image_url_map,
        )
        if auto_apply_mapped_colors:
            apply_mapped_colors_to_widget_once(
                "selected_colours",
                mapped_colors,
                image_mapping_context_key,
                allow_replace_existing=True,
            )
        color_action_cols = st.columns(3)
        if color_action_cols[0].button("All colours", key="selected_colours_all", width="stretch"):
            st.session_state["selected_colours"] = list(colors_available)
            st.rerun()
        if color_action_cols[1].button("No colours", key="selected_colours_none", width="stretch"):
            st.session_state["selected_colours"] = []
            st.rerun()
        if color_action_cols[2].button(
            "Mapped colours",
            key="selected_colours_mapped",
            width="stretch",
            disabled=not bool(staged_folder_name),
            help="Select only colours that have staged images mapped by filename.",
        ):
            if mapped_colors:
                st.session_state["selected_colours"] = list(mapped_colors)
                st.rerun()
            else:
                st.session_state["apply_mapped_colours_widget_key"] = "selected_colours"
                st.session_state["scan_mapped_colours_now"] = True
                st.rerun()

        selected_colors = st.multiselect(
            "Colours",
            colors_available,
            key="selected_colours",
        )

        if profile.get("color_size_map"):
            st.caption("Some colours have restricted size availability. Only valid combinations will be generated.")

        available_sizes_for_selected_colors = get_available_sizes_for_selected_colors(
            profile,
            selected_colors,
        )
        normalized_sizes, should_set_sizes = normalize_multiselect_values(
            st.session_state.get("selected_sizes", []),
            available_sizes_for_selected_colors,
            selected_variants.get("size", available_sizes_for_selected_colors),
        )
        if should_set_sizes or "selected_sizes" not in st.session_state:
            st.session_state["selected_sizes"] = list(normalized_sizes)
        selected_sizes = st.multiselect(
            "Sizes",
            available_sizes_for_selected_colors,
            key="selected_sizes",
        )

        selected_variants = {
            "color": selected_colors,
            "size": selected_sizes,
        }

    st.subheader("SKU setup")
    default_sku_decoration_code = get_default_sku_decoration_code(profile, listing_memory)
    if "sku_decoration_choice" not in st.session_state:
        st.session_state["sku_decoration_choice"] = (
            default_sku_decoration_code
            if default_sku_decoration_code in SKU_DECORATION_OPTIONS
            else "Custom"
        )
    if "custom_sku_decoration_code" not in st.session_state:
        st.session_state["custom_sku_decoration_code"] = (
            ""
            if default_sku_decoration_code in SKU_DECORATION_OPTIONS
            else default_sku_decoration_code
        )

    sku_decoration_choice = st.selectbox(
        "Decoration code",
        SKU_DECORATION_OPTIONS,
        key="sku_decoration_choice",
    )
    if sku_decoration_choice == "Custom":
        custom_sku_decoration_code = st.text_input(
            "Custom decoration code",
            key="custom_sku_decoration_code",
        )
        sku_decoration_code = sanitize_sku(custom_sku_decoration_code).upper()
        if not sku_decoration_code:
            st.warning("Enter a custom SKU decoration code.")
    else:
        sku_decoration_code = sku_decoration_choice

    generated_sku_listing_code = get_or_create_generated_sku_listing_code(listing_memory)
    manual_sku_listing_code = st.text_input(
        "Listing/design code (optional)",
        key="manual_sku_listing_code",
        placeholder=generated_sku_listing_code,
        help="Leave blank to use the generated unique design identifier.",
    )
    manual_sku_listing_code = sanitize_sku(manual_sku_listing_code).upper()
    generated_sku_listing_code = sanitize_sku(generated_sku_listing_code).upper()
    sku_listing_code = manual_sku_listing_code or generated_sku_listing_code
    parent_sku_for_listing = build_parent_sku_from_context(
        profile,
        sku_decoration_code,
        sku_listing_code,
    )
    if manual_sku_listing_code:
        st.caption(f"Parent SKU: `{parent_sku_for_listing}`")
    else:
        st.caption(f"Generated listing code: `{generated_sku_listing_code}`")
        st.caption(f"Parent SKU: `{parent_sku_for_listing}`")

    with st.expander("Selected combinations preview", expanded=False):
        render_variant_combinations_preview(
            profile=profile,
            parent_sku=parent_sku_for_listing,
            selected_variants=selected_variants,
            base_title=title,
            sku_decoration_code=sku_decoration_code,
            sku_listing_code=sku_listing_code,
        )

    price_dimension_values = selected_variants.get("size", ["default"])
    size_price_map = build_size_price_inputs(
        price_dimension_values,
        saved_prices=listing_memory.get("size_price_map", {}),
        profile=profile,
        selected_variants=selected_variants,
    )
    st.session_state["current_size_price_map"] = dict(size_price_map)

    st.subheader("Inventory setup")
    quantity = st.number_input(
        "Quantity for all child variants",
        min_value=1,
        step=1,
        key="variant_quantity",
    )
    st.selectbox(
        "Content prepared by",
        WORKFLOW_ASSIGNEES,
        key="content_prepared_by",
    )

    st.caption("Check listing score to review quality before submitting the folder for review.")
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        score_clicked = st.button("Check listing score", width="stretch")
    with btn_col2:
        ready_clicked = st.button("Submit for Review", width="stretch")
    content_debug_container = st.container()
    content_preflight_container = st.container()
    content_action_result_container = st.container()

    return {
        "title": title,
        "bullets": bullets,
        "product_description": product_description,
        "generic_keywords": generic_keywords,
        "handling_time_days": handling_time_days,
        "selected_variants": selected_variants,
        "sku_decoration_code": sku_decoration_code,
        "manual_sku_listing_code": manual_sku_listing_code,
        "generated_sku_listing_code": generated_sku_listing_code,
        "sku_listing_code": sku_listing_code,
        "parent_sku_for_listing": parent_sku_for_listing,
        "size_price_map": size_price_map,
        "quantity": quantity,
        "score_clicked": score_clicked,
        "ready_clicked": ready_clicked,
        "content_debug_container": content_debug_container,
        "content_preflight_container": content_preflight_container,
        "content_action_result_container": content_action_result_container,
    }
