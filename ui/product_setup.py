from __future__ import annotations

from typing import Any, Callable

import streamlit as st

from services.staged_listing_tasks import (
    build_grouped_christmas_staged_task_payload,
    build_staged_listing_task_payload,
    get_task_size_options,
    is_christmas_project_profile,
)


FOLDER_SOURCE_OPTIONS = [
    "Use staged folder",
    "Restage finished folder",
    "Create staged folder",
]

CREATE_TASK_WIDGET_KEYS = [
    "create_task_staged_folder_name",
    "create_task_price",
    "create_task_quantity",
    "create_task_shipping_group",
    "create_task_sizes",
    "create_task_sku_decoration_choice",
    "create_task_custom_sku_decoration_code",
    "create_task_manual_sku_listing_code",
    "create_task_generated_sku_listing_code",
    "create_task_profile_key",
]


def resolve_staged_task_sku_context(
    *,
    profile: dict[str, Any],
    decoration_choice: str,
    custom_decoration_code: str,
    manual_listing_code: str,
    generated_listing_code: str,
    sanitize_sku: Callable[[str], str],
    get_default: Callable[..., Any],
    build_parent_sku_from_context: Callable[[dict[str, Any], str, str], str],
) -> dict[str, str]:
    sku_decoration_code = sanitize_sku(
        custom_decoration_code if decoration_choice == "Custom" else decoration_choice
    ).upper()
    manual_sku_listing_code = sanitize_sku(manual_listing_code).upper()
    generated_sku_listing_code = sanitize_sku(generated_listing_code).upper()
    sku_listing_code = manual_sku_listing_code or generated_sku_listing_code
    return {
        "sku_decoration_code": sku_decoration_code,
        "manual_sku_listing_code": manual_sku_listing_code,
        "generated_sku_listing_code": generated_sku_listing_code,
        "sku_listing_code": sku_listing_code,
        "base_parent_sku": str(get_default(profile, "parent_sku", "")).strip(),
        "parent_sku": build_parent_sku_from_context(
            profile,
            sku_decoration_code,
            sku_listing_code,
        ),
    }


def apply_created_task_ui_state(
    *,
    result: dict[str, Any],
    session_state: Any,
    refresh_cached_folder_names: Callable[..., None],
    clear_cached_listing_memory: Callable[..., None],
    clear_runtime_caches: Callable[..., None],
    set_workflow_flash: Callable[..., None],
) -> None:
    folder_name = result["folder_name"]
    refresh_cached_folder_names("stage")
    clear_cached_listing_memory(result.get("folder_path", ""))
    clear_runtime_caches()
    session_state["stage_folder_list_loaded"] = True
    session_state["auto_switch_to_staged"] = True
    session_state["pending_staged_folder_selection_on_rerun"] = folder_name
    session_state["reset_create_task_form_on_rerun"] = True
    session_state["pending_perf_action_label"] = "create staged listing task"
    set_workflow_flash(
        "success",
        f"Created listing task: {folder_name}",
        f"Saved listing inputs to {result.get('listing_memory_path', '')}.",
    )


def render_create_staged_listing_task_form(
    *,
    profile: dict[str, Any],
    dropbox_cfg: dict[str, Any],
    merchant_shipping_group_options: list[str],
    sku_decoration_options: list[str],
    default_variant_quantity: int,
    get_default_sku_decoration_code: Callable[..., str],
    sanitize_sku: Callable[[str], str],
    generate_unique_sku: Callable[[int], str],
    get_default: Callable[..., Any],
    build_parent_sku_from_context: Callable[[dict[str, Any], str, str], str],
    create_listing_task: Callable[..., dict[str, Any]],
    refresh_cached_folder_names: Callable[..., None],
    clear_cached_listing_memory: Callable[..., None],
    clear_runtime_caches: Callable[..., None],
    set_workflow_flash: Callable[..., None],
) -> None:
    if st.session_state.pop("reset_create_task_form_on_rerun", False):
        for key in CREATE_TASK_WIDGET_KEYS:
            st.session_state.pop(key, None)

    profile_key = str(profile.get("template_key") or profile.get("_slug") or "")
    if st.session_state.get("create_task_profile_key") != profile_key:
        for key in [
            "create_task_sizes",
            "create_task_sku_decoration_choice",
            "create_task_custom_sku_decoration_code",
        ]:
            st.session_state.pop(key, None)
        st.session_state["create_task_profile_key"] = profile_key

    default_decoration_code = get_default_sku_decoration_code(profile)
    st.session_state.setdefault(
        "create_task_sku_decoration_choice",
        default_decoration_code if default_decoration_code in sku_decoration_options else "Custom",
    )
    st.session_state.setdefault(
        "create_task_custom_sku_decoration_code",
        "" if default_decoration_code in sku_decoration_options else default_decoration_code,
    )
    st.session_state.setdefault(
        "create_task_generated_sku_listing_code",
        f"D{generate_unique_sku(5)}",
    )
    st.session_state.setdefault("create_task_quantity", default_variant_quantity)

    grouped_christmas = is_christmas_project_profile(profile)
    size_options = [] if grouped_christmas else get_task_size_options(profile)

    with st.form("create_staged_listing_task_form"):
        staged_folder_name = st.text_input(
            "Staging folder name",
            key="create_task_staged_folder_name",
        )
        if grouped_christmas:
            quantity = st.number_input(
                "Quantity",
                min_value=0,
                step=1,
                key="create_task_quantity",
            )
            st.info(
                "Creates T-Shirt, Sweatshirt, and Hoodie listings. Pricing is configured "
                "per garment and size in Listing Content."
            )
        else:
            price_col, quantity_col = st.columns(2)
            with price_col:
                price = st.number_input(
                    "Price",
                    min_value=0.0,
                    step=0.01,
                    format="%.2f",
                    key="create_task_price",
                )
            with quantity_col:
                quantity = st.number_input(
                    "Quantity",
                    min_value=0,
                    step=1,
                    key="create_task_quantity",
                )
        merchant_shipping_group_name = st.selectbox(
            "Merchant Shipping Group",
            merchant_shipping_group_options,
            key="create_task_shipping_group",
            help="Leave empty to skip this Amazon field.",
        )
        if not grouped_christmas:
            selected_sizes = st.multiselect(
                "Sizes",
                size_options,
                key="create_task_sizes",
            )

        st.subheader("SKU setup")
        decoration_choice = st.selectbox(
            "Decoration code",
            sku_decoration_options,
            key="create_task_sku_decoration_choice",
        )
        custom_decoration_code = ""
        if decoration_choice == "Custom":
            custom_decoration_code = st.text_input(
                "Custom decoration code",
                key="create_task_custom_sku_decoration_code",
            )
        manual_listing_code = st.text_input(
            "Listing/design code (optional)",
            key="create_task_manual_sku_listing_code",
            placeholder=st.session_state["create_task_generated_sku_listing_code"],
            help="Leave blank to use the generated unique design identifier.",
        )

        sku_context = resolve_staged_task_sku_context(
            profile=profile,
            decoration_choice=decoration_choice,
            custom_decoration_code=custom_decoration_code,
            manual_listing_code=manual_listing_code,
            generated_listing_code=st.session_state["create_task_generated_sku_listing_code"],
            sanitize_sku=sanitize_sku,
            get_default=get_default,
            build_parent_sku_from_context=build_parent_sku_from_context,
        )
        if manual_listing_code:
            st.caption(f"MPN: `{sku_context['sku_listing_code']}`")
            st.caption(f"Parent SKU: `{sku_context['parent_sku']}`")
        else:
            st.caption(f"Generated listing code: `{sku_context['generated_sku_listing_code']}`")
            st.caption(f"MPN: `{sku_context['sku_listing_code']}`")
            st.caption(f"Parent SKU: `{sku_context['parent_sku']}`")
        if grouped_christmas and sku_context["sku_decoration_code"] and sku_context["sku_listing_code"]:
            grouped_parent_base = (
                f"{sku_context['sku_decoration_code']}-{sku_context['sku_listing_code']}"
            )
            st.caption(
                "Will create parents: "
                f"`{grouped_parent_base}-T`, `{grouped_parent_base}-S`, `{grouped_parent_base}-H`"
            )

        create_clicked = st.form_submit_button(
            "Create Christmas Listing Task" if grouped_christmas else "Create Listing Task",
            key="create_staged_listing_task_btn",
            width="stretch",
        )

    if not create_clicked:
        return

    if grouped_christmas:
        task_result = build_grouped_christmas_staged_task_payload(
            profile=profile,
            staged_folder_name=staged_folder_name,
            mpn=sku_context["sku_listing_code"],
            quantity=quantity,
            merchant_shipping_group_name=merchant_shipping_group_name,
            assets_prepared_by=st.session_state.get("assets_prepared_by", ""),
            **sku_context,
        )
    else:
        task_result = build_staged_listing_task_payload(
            profile=profile,
            staged_folder_name=staged_folder_name,
            mpn=sku_context["sku_listing_code"],
            price=price,
            quantity=quantity,
            merchant_shipping_group_name=merchant_shipping_group_name,
            selected_sizes=selected_sizes,
            assets_prepared_by=st.session_state.get("assets_prepared_by", ""),
            **sku_context,
        )
    if not task_result["valid"]:
        for error in task_result["errors"]:
            st.error(error)
        return

    result = create_listing_task(
        profile=profile,
        payload=task_result["payload"],
        staged_folder_name=staged_folder_name,
        dropbox_cfg=dropbox_cfg,
    )
    if result.get("status") != "Success":
        if result.get("status") == "Partial failure":
            refresh_cached_folder_names("stage")
            st.session_state["stage_folder_list_loaded"] = True
        st.error(result.get("error") or "Could not create the staged listing task.")
        return

    apply_created_task_ui_state(
        result=result,
        session_state=st.session_state,
        refresh_cached_folder_names=refresh_cached_folder_names,
        clear_cached_listing_memory=clear_cached_listing_memory,
        clear_runtime_caches=clear_runtime_caches,
        set_workflow_flash=set_workflow_flash,
    )
    st.rerun()


def render_product_setup_controls(
    *,
    staged_folder_names: list[str],
    finished_folder_names: list[str],
    finished_root: str,
    dropbox_cfg: dict[str, Any],
    profiles: list[dict[str, Any]],
    profile: dict[str, Any],
    families: list[str],
    family_labels: list[str],
    detection_message: str,
    detection_level: str,
    selected_family: str,
    selected_label: str,
    workflow_assignees: list[str],
    selectbox_index_without_state_conflict: Callable[..., int],
    get_cached_folder_names: Callable[..., list[str]],
    refresh_cached_folder_names: Callable[..., None],
    clear_cached_listing_memory: Callable[..., None],
    clear_runtime_caches: Callable[..., None],
    restage_finished_listing_for_review: Callable[..., dict[str, Any]],
    set_workflow_flash: Callable[..., None],
    reset_restaged_selection_state: Callable[..., None],
    list_folder_names: Callable[[str], list[str]],
    scan_staged_folder_readiness: Callable[..., dict[str, Any]],
    merchant_shipping_group_options: list[str],
    sku_decoration_options: list[str],
    default_variant_quantity: int,
    get_default_sku_decoration_code: Callable[..., str],
    sanitize_sku: Callable[[str], str],
    generate_unique_sku: Callable[[int], str],
    get_default: Callable[..., Any],
    build_parent_sku_from_context: Callable[[dict[str, Any], str, str], str],
    create_listing_task: Callable[..., dict[str, Any]],
) -> tuple[str, str | None, str | None]:
    staged_folder_name = None
    selected_finished_folder = None
    show_create_task_form = False

    top_left_col, top_right_col = st.columns(2)
    with top_left_col:
        st.subheader("Folder workflow")
        active_folder_source = st.session_state.get("active_folder_source_mode", "Use staged folder")
        if active_folder_source in FOLDER_SOURCE_OPTIONS:
            st.session_state.setdefault("folder_source_mode", active_folder_source)
        folder_source = st.radio(
            "Choose Folder Source",
            FOLDER_SOURCE_OPTIONS,
            key="folder_source_mode",
        )

        if folder_source == "Use staged folder":
            staged_select_col, staged_refresh_col = st.columns([4, 1])
            with staged_select_col:
                active_staged_folder = st.session_state.get("active_staged_folder_select", "")
                staged_folder_options = list(staged_folder_names)
                if active_staged_folder and active_staged_folder not in staged_folder_options:
                    staged_folder_options.insert(0, active_staged_folder)
                if not st.session_state.get("stage_folder_list_loaded", False) and not staged_folder_options:
                    st.info("Load staged folders when you are ready to choose one.")
                    staged_folder_name = ""
                else:
                    staged_folder_name = st.selectbox(
                        "Dropbox folder",
                        staged_folder_options,
                        index=selectbox_index_without_state_conflict(
                            "staged_folder_select",
                            staged_folder_options,
                            active_staged_folder,
                        ),
                        placeholder="Select a staged folder",
                        key="staged_folder_select",
                    )
            with staged_refresh_col:
                st.write("")
                load_stage_label = "Refresh" if st.session_state.get("stage_folder_list_loaded", False) else "Load"
                if st.button(load_stage_label, key="refresh_staged_folders_btn", width="stretch"):
                    st.session_state["pending_perf_action_label"] = f"{load_stage_label.lower()} staged folders"
                    st.session_state["stage_folder_list_loaded"] = True
                    refresh_cached_folder_names("stage")
                    clear_cached_listing_memory()
                    clear_runtime_caches()
                    st.rerun()
        elif folder_source == "Restage finished folder":
            if not finished_folder_names:
                finished_folder_names = get_cached_folder_names("finished", finished_root, "finished folders")
            active_finished_folder = st.session_state.get("active_finished_folder_select", "")
            selected_finished_folder = st.selectbox(
                "Dropbox folder",
                finished_folder_names,
                index=selectbox_index_without_state_conflict(
                    "finished_folder_select",
                    finished_folder_names,
                    active_finished_folder,
                ),
                placeholder="Select a finished folder to restage",
                key="finished_folder_select",
            )

            if st.button(
                "Move selected folder back to staging",
                key="restage_finished_folder_button",
                width="stretch",
            ):
                if not selected_finished_folder:
                    st.warning("Select a finished folder first.")
                    st.stop()

                st.session_state["pending_perf_action_label"] = "restage finished folder"
                try:
                    result = restage_finished_listing_for_review(
                        dropbox_cfg=dropbox_cfg,
                        profiles=profiles,
                        fallback_profile=profile,
                        finished_folder_name=selected_finished_folder,
                    )

                    if result.get("status") != "Success":
                        raise RuntimeError(result.get("error") or "Restage failed.")

                    clear_runtime_caches()
                    set_workflow_flash(
                        "success",
                        f"Restaged successfully: {result.get('new_staged_folder_name', '')}",
                        result.get("warning", ""),
                    )

                    reset_restaged_selection_state()
                    st.session_state["staged_folder_select"] = result.get("new_staged_folder_name", "")
                    st.session_state["active_staged_folder_select"] = result.get("new_staged_folder_name", "")
                    st.session_state["auto_switch_to_staged"] = True
                    st.session_state["finished_restage_results"] = [result]

                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not restage folder: {exc}")
                    st.stop()
        else:
            show_create_task_form = True

    with top_right_col:
        st.subheader("Template selection")
        if detection_message:
            if detection_level == "warning":
                st.warning(detection_message)
            else:
                st.info(detection_message)
        select_col1, select_col2 = st.columns(2)
        with select_col1:
            active_family_selection = st.session_state.get("active_template_family_select", selected_family)
            st.selectbox(
                "Template family",
                families,
                index=selectbox_index_without_state_conflict(
                    "template_family_select",
                    families,
                    active_family_selection,
                ),
                key="template_family_select",
            )
        with select_col2:
            active_template_selection = st.session_state.get("active_listing_template_select", selected_label)
            st.selectbox(
                "Garment template",
                family_labels,
                index=selectbox_index_without_state_conflict(
                    "listing_template_select",
                    family_labels,
                    active_template_selection,
                ),
                key="listing_template_select",
            )
        st.selectbox(
            "Assets prepared by",
            workflow_assignees,
            key="assets_prepared_by",
        )

    if show_create_task_form:
        render_create_staged_listing_task_form(
            profile=profile,
            dropbox_cfg=dropbox_cfg,
            merchant_shipping_group_options=merchant_shipping_group_options,
            sku_decoration_options=sku_decoration_options,
            default_variant_quantity=default_variant_quantity,
            get_default_sku_decoration_code=get_default_sku_decoration_code,
            sanitize_sku=sanitize_sku,
            generate_unique_sku=generate_unique_sku,
            get_default=get_default,
            build_parent_sku_from_context=build_parent_sku_from_context,
            create_listing_task=create_listing_task,
            refresh_cached_folder_names=refresh_cached_folder_names,
            clear_cached_listing_memory=clear_cached_listing_memory,
            clear_runtime_caches=clear_runtime_caches,
            set_workflow_flash=set_workflow_flash,
        )

    with st.expander("Staged folder readiness", expanded=False):
        st.caption("Scan staged folders to see which ones are ready to generate.")
        if st.button("Scan staged folders", key="scan_staged_folders_btn"):
            stage_root = dropbox_cfg.get("stage_root", "").rstrip("/")
            try:
                scan_folder_names = list_folder_names(stage_root) if stage_root else []
            except Exception as exc:
                st.session_state["staged_folder_readiness_results"] = []
                st.session_state["staged_folder_readiness_error"] = str(exc)
            else:
                st.session_state["staged_folder_readiness_error"] = ""
                st.session_state["staged_folder_readiness_results"] = [
                    scan_staged_folder_readiness(folder_name, profiles, dropbox_cfg)
                    for folder_name in scan_folder_names
                ]

        readiness_error = st.session_state.get("staged_folder_readiness_error", "")
        readiness_results = st.session_state.get("staged_folder_readiness_results", [])

        if readiness_error:
            st.error(readiness_error)
        elif readiness_results:
            st.dataframe(
                readiness_results,
                width="stretch",
                hide_index=True,
            )
        else:
            st.caption("No scan results yet.")

    st.session_state["active_folder_source_mode"] = st.session_state.get("folder_source_mode") or "Use staged folder"
    st.session_state["active_staged_folder_select"] = st.session_state.get("staged_folder_select") or ""
    st.session_state["active_finished_folder_select"] = st.session_state.get("finished_folder_select") or ""
    st.session_state["active_template_family_select"] = st.session_state.get("template_family_select") or selected_family
    st.session_state["active_listing_template_select"] = st.session_state.get("listing_template_select") or selected_label

    return folder_source, staged_folder_name, selected_finished_folder


def render_product_setup(
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
    dropbox_cfg: dict[str, Any],
    staged_folder_name: str | None,
    image_mapping_context_key: str,
    dropbox_overview: dict[str, Any],
    staged_resource_paths: list[str],
    staged_preview_paths: list[str],
    selected_variants: dict[str, list[str]],
    staged_resource_entries: list[dict[str, Any]],
    garment_resource_entries: list[dict[str, Any]],
    global_resource_entries: list[dict[str, Any]],
    parent_main_image_options: list[tuple[str, str]],
    variant_dimensions: list[dict[str, Any]],
    design_color_preview_entries: list[dict[str, Any]],
    staged_variant_entries: list[dict[str, Any]],
    profile: dict[str, Any],
    parent_sku_from_config: str,
    title: str,
    active_profile: dict[str, Any],
    global_brand_name: str,
    render_active_product_context: Callable[..., None],
    render_stage_images_zip_upload: Callable[..., None],
    build_variants_summary: Callable[..., str],
    render_path_grid: Callable[..., None],
    selectbox_index_without_state_conflict: Callable[..., int],
    render_design_color_grid: Callable[..., None],
    render_color_grid: Callable[..., None],
    render_variant_combinations_preview: Callable[..., None],
    get_default: Callable[..., Any],
    get_stock_reference: Callable[..., dict[str, Any]],
    is_strict_stock_ready: Callable[..., bool],
) -> None:
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
    render_stage_images_zip_upload(dropbox_cfg, staged_folder_name)

    load_images_disabled = not bool(staged_folder_name)
    if st.button(
        "Load / refresh image mappings",
        key="load_image_mappings_setup",
        width="stretch",
        disabled=load_images_disabled,
    ):
        st.session_state["pending_perf_action_label"] = "load/refresh image mappings"

        st.session_state["load_image_mappings_now"] = True
        if staged_folder_name:
            st.session_state["image_mappings_loaded_folder"] = staged_folder_name
            st.session_state["image_mappings_loaded_context"] = image_mapping_context_key

        st.rerun()

    if load_images_disabled:
        st.caption("Select a staged folder before loading image mappings.")

    st.subheader("Image review")

    if image_mapping_status != "loaded":
        st.caption(
            "Images remain unloaded for faster editing. They are resolved during quality checks "
            "and generation, or when Load / refresh image mappings is clicked."
        )
    else:
        with st.expander("Dropbox image overview", expanded=True):
            if not dropbox_overview:
                st.warning("No shared Dropbox config loaded yet.")
            else:
                st.write(f"Resource root: `{dropbox_overview['resource_root']}`")
                st.write(f"Variant folder: `{dropbox_overview['variant_folder']}`")
                if dropbox_overview.get("garment_resource_warning") and not staged_resource_paths:
                    st.warning(dropbox_overview["garment_resource_warning"])

                st.write(f"Staged image files found: `{len(staged_preview_paths)}`")
                st.write(f"Staged resources folder files found: `{len(staged_resource_paths)}`")
                st.write(f"Selected variants: `{build_variants_summary(selected_variants)}`")
                st.write(f"Fallback garment support files configured: `{len(dropbox_overview.get('garment_resource_images', []))}`")
                st.write(f"Fallback shared support files configured: `{len(dropbox_overview.get('shared_resource_images', []))}`")
                st.checkbox(
                    "Use fallback resource images when listing resources is empty",
                    key="use_resource_fallback_images",
                    help="When this is off, only images inside the staged folder's resources folder are used as secondary images.",
                )

                if st.session_state.get("show_header_debug", False):
                    with st.expander("Raw staged folder contents", expanded=False):
                        if not staged_folder_name:
                            st.caption("Select a staged Dropbox folder to preview its images.")
                        elif staged_preview_paths:
                            for preview_path in staged_preview_paths:
                                st.code(preview_path, language=None)
                        else:
                            st.caption("No staged image files found.")

                tab_names = ["Staged variant images", "Secondary images", "Variant combinations"]
                colours_tab, resources_tab, combos_tab = st.tabs(tab_names)

                with resources_tab:
                    st.caption("Images in the staged folder's resources folder are used first. Shared resources are used only when that folder has no images.")
                    render_path_grid(
                        "Listing resources folder",
                        staged_resource_entries,
                        cols_per_row=5,
                        image_width=150,
                    )
                    render_path_grid(
                        "Fallback garment support images",
                        garment_resource_entries,
                        cols_per_row=5,
                        image_width=150,
                    )
                    render_path_grid(
                        "Fallback global resource images",
                        global_resource_entries,
                        cols_per_row=5,
                        image_width=150,
                    )

                with colours_tab:
                    st.caption("These are the staged mapped variant images expected from the selected staged folder.")
                    parent_main_option_labels = ["Automatic (recommended)"] + [
                        label for label, _ in parent_main_image_options
                    ]
                    current_parent_main_label = st.session_state.get("parent_main_image_choice", "Automatic (recommended)")
                    if current_parent_main_label not in parent_main_option_labels:
                        current_parent_main_label = "Automatic (recommended)"
                    st.selectbox(
                        "Parent main image",
                        parent_main_option_labels,
                        index=selectbox_index_without_state_conflict(
                            "parent_main_image_choice",
                            parent_main_option_labels,
                            current_parent_main_label,
                        ),
                        key="parent_main_image_choice",
                    )
                    has_design_dimension = any(
                        str(dim.get("name", "")).strip().lower() == "design"
                        for dim in variant_dimensions
                    )
                    if has_design_dimension and preview_design_color_image_url_map:
                        render_design_color_grid(
                            design_color_preview_entries,
                            cols_per_row=5,
                            image_width=150,
                        )
                    else:
                        render_color_grid(
                            staged_variant_entries,
                            cols_per_row=5,
                            image_width=150,
                        )

                with combos_tab:
                    if has_design_dimension:
                        render_design_color_grid(
                            design_color_preview_entries,
                            cols_per_row=5,
                            image_width=150,
                        )
                    else:
                        render_variant_combinations_preview(
                            profile,
                            parent_sku_from_config,
                            selected_variants,
                            base_title=title,
                            sku_decoration_code="",
                            sku_listing_code="",
                        )

    st.subheader("Product template details")
    col1, col2 = st.columns(2)
    with col1:
        st.text_input("Garment code", value=parent_sku_from_config, disabled=True)
        st.text_input("Brand", value=global_brand_name, disabled=True)
        st.text_input("Manufacturer", value=str(get_default(profile, "manufacturer", "Generic")), disabled=True)
        st.text_input("Product type", value=str(get_default(profile, "feed_product_type", "")), disabled=True)
        st.text_input("Department", value=str(get_default(profile, "department_name", "")), disabled=True)
    with col2:
        st.text_input("Target gender", value=str(get_default(profile, "target_gender", "")), disabled=True)
        st.text_input("Age range", value=str(get_default(profile, "age_range_description", "Adult")), disabled=True)
        st.text_input("Material type", value=str(get_default(profile, "material_type", "")), disabled=True)
        st.text_input("Style", value=str(get_default(profile, "style_name", "")), disabled=True)
        st.text_input(
            "Recommended browse node",
            value=str(get_default(profile, "recommended_browse_nodes", "")),
            disabled=True,
        )
    stock_reference_key = str(active_profile.get("stock_reference_key", "") or "").strip()
    if stock_reference_key:
        stock_reference = get_stock_reference(active_profile)
        st.subheader("Stock reference")
        stock_col1, stock_col2, stock_col3 = st.columns(3)
        stock_col1.text_input("Reference key", value=stock_reference_key, disabled=True)
        stock_col2.text_input("Supplier", value=str(stock_reference.get("supplier", "") or ""), disabled=True)
        stock_col3.text_input(
            "Stock-ready mode",
            value="Strict" if is_strict_stock_ready(active_profile) else "Warning only",
            disabled=True,
        )
        if not stock_reference:
            st.warning("This template has a stock_reference_key, but no matching config/stock_references.json entry was found.")
