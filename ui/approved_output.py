from __future__ import annotations

from typing import Any, Callable

import streamlit as st


def render_approved_output(
    *,
    finished_folder_names: list[str],
    approved_folder_names: list[str],
    approved_root: str,
    dropbox_cfg: dict[str, Any],
    profiles: list[dict[str, Any]],
    profile: dict[str, Any],
    WORKFLOW_ASSIGNEES: list[str],
    restage_finished_listing_for_review: Callable[..., dict[str, Any]],
    mark_finished_generation_ignored: Callable[..., dict[str, Any]],
    refresh_cached_folder_names: Callable[..., None],
    clear_cached_listing_memory: Callable[..., None],
    clear_runtime_caches: Callable[..., None],
    set_workflow_flash: Callable[..., None],
    get_cached_folder_names: Callable[..., list[str]],
    render_approved_queue_view: Callable[..., None],
) -> None:
    st.caption("Generate selected or all approved folders and download completed workbooks.")

    with st.expander("Bring finished folders back", expanded=bool(st.session_state.get("finished_restage_results", []))):
        existing_finished_restage_selection = list(st.session_state.get("finished_output_restage_selected", []))
        valid_finished_restage_selection = [
            folder_name for folder_name in existing_finished_restage_selection
            if folder_name in finished_folder_names
        ]
        if valid_finished_restage_selection != existing_finished_restage_selection:
            st.session_state["finished_output_restage_selected"] = valid_finished_restage_selection

        with st.form("finished_output_restaging_form"):
            selected_finished_folders_to_restage = st.multiselect(
                "Select finished folders",
                finished_folder_names,
                key="finished_output_restage_selected",
            )
            finished_return_destination = st.radio(
                "Bring back to",
                ["Approved output", "Product setup / staging"],
                key="finished_output_return_destination",
                horizontal=True,
                help=(
                    "Use Approved output when you only need to regenerate or redownload with app updates. "
                    "Use staging when you need to edit the listing setup/content first."
                ),
            )
            restage_selected_finished = st.form_submit_button(
                "Bring selected finished folders back",
                width="stretch",
                disabled=not bool(finished_folder_names),
            )

        if restage_selected_finished:
            if not selected_finished_folders_to_restage:
                st.warning("Select at least one finished folder.")
            else:
                target_state = "stage" if finished_return_destination == "Product setup / staging" else "approved"
                restage_action_label = (
                    "bring finished folder back"
                    if len(selected_finished_folders_to_restage) == 1
                    else "bulk bring finished folders back"
                )
                st.session_state["active_perf_action_label"] = restage_action_label
                st.session_state["pending_perf_action_label"] = restage_action_label

                restage_results = [
                    restage_finished_listing_for_review(
                        dropbox_cfg=dropbox_cfg,
                        profiles=profiles,
                        fallback_profile=profile,
                        finished_folder_name=finished_folder_name,
                        target_state=target_state,
                    )
                    for finished_folder_name in selected_finished_folders_to_restage
                ]
                success_results = [
                    row for row in restage_results
                    if row.get("status") == "Success"
                ]
                failed_results = [
                    row for row in restage_results
                    if row.get("status") == "Failed"
                ]

                st.session_state["finished_restage_results"] = restage_results

                if len(selected_finished_folders_to_restage) == 1 and len(success_results) == 1:
                    if target_state == "approved":
                        returned_name = success_results[0].get("new_approved_folder_name", "")
                        flash_title = f"Moved back to approved: {returned_name}"
                        flash_detail = success_results[0].get("warning", "") or "Generate it again from Approved output."
                    else:
                        returned_name = success_results[0].get("new_staged_folder_name", "")
                        flash_title = f"Moved back to staging: {returned_name}"
                        flash_detail = success_results[0].get("warning", "") or "Open it from Product setup to edit."
                else:
                    target_label = "approved" if target_state == "approved" else "staging"
                    flash_title = f"Moved {len(success_results)} of {len(selected_finished_folders_to_restage)} selected finished folders back to {target_label}."
                    flash_detail = (
                        "Use Approved output to generate them again."
                        if target_state == "approved"
                        else "Use Product setup to edit them."
                    )
                    if failed_results:
                        flash_detail = f"{len(failed_results)} folder(s) failed. " + flash_detail

                refresh_cached_folder_names("finished", "approved" if target_state == "approved" else "stage")
                clear_cached_listing_memory()
                clear_runtime_caches()
                set_workflow_flash(
                    "success" if not failed_results else "warning",
                    flash_title,
                    flash_detail,
                )
                st.rerun()

        finished_restage_results = list(st.session_state.get("finished_restage_results", []))
        if finished_restage_results:
            success_count = sum(1 for row in finished_restage_results if row.get("status") == "Success")
            failed_count = sum(1 for row in finished_restage_results if row.get("status") == "Failed")
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("Selected", len(finished_restage_results))
            col_b.metric("Success", success_count)
            col_c.metric("Failed", failed_count)
            st.dataframe(finished_restage_results, width="stretch", hide_index=True)

        st.divider()
        st.markdown("**Ignore bad generation**")
        st.caption("Marks a finished workbook as ignored without deleting or moving the Dropbox folder.")

        existing_finished_ignore_selection = list(st.session_state.get("finished_output_ignore_selected", []))
        valid_finished_ignore_selection = [
            folder_name for folder_name in existing_finished_ignore_selection
            if folder_name in finished_folder_names
        ]
        if valid_finished_ignore_selection != existing_finished_ignore_selection:
            st.session_state["finished_output_ignore_selected"] = valid_finished_ignore_selection

        with st.form("finished_output_ignore_form"):
            selected_finished_folders_to_ignore = st.multiselect(
                "Select finished generations to ignore",
                finished_folder_names,
                key="finished_output_ignore_selected",
            )
            ignore_reason = st.text_input(
                "Reason",
                value="Manual Amazon upload used instead",
                key="finished_output_ignore_reason",
            )
            ignored_by = st.selectbox(
                "Marked by",
                WORKFLOW_ASSIGNEES,
                key="finished_output_ignore_by",
            )
            ignore_selected_finished = st.form_submit_button(
                "Mark selected generation(s) ignored",
                width="stretch",
                disabled=not bool(finished_folder_names),
            )

        if ignore_selected_finished:
            if not selected_finished_folders_to_ignore:
                st.warning("Select at least one finished generation to ignore.")
            else:
                st.session_state["active_perf_action_label"] = "ignore finished generation"
                st.session_state["pending_perf_action_label"] = "ignore finished generation"

                ignore_results = [
                    mark_finished_generation_ignored(
                        dropbox_cfg=dropbox_cfg,
                        profiles=profiles,
                        fallback_profile=profile,
                        finished_folder_name=finished_folder_name,
                        reason=ignore_reason.strip(),
                        actor=ignored_by,
                    )
                    for finished_folder_name in selected_finished_folders_to_ignore
                ]
                success_results = [
                    row for row in ignore_results
                    if row.get("status") == "Success"
                ]
                failed_results = [
                    row for row in ignore_results
                    if row.get("status") == "Failed"
                ]

                st.session_state["finished_ignore_results"] = ignore_results
                clear_runtime_caches()
                set_workflow_flash(
                    "success" if not failed_results else "warning",
                    f"Ignored {len(success_results)} of {len(selected_finished_folders_to_ignore)} selected generation(s).",
                    "No files were deleted or moved.",
                )
                st.rerun()

        finished_ignore_results = list(st.session_state.get("finished_ignore_results", []))
        if finished_ignore_results:
            success_count = sum(1 for row in finished_ignore_results if row.get("status") == "Success")
            failed_count = sum(1 for row in finished_ignore_results if row.get("status") == "Failed")
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("Selected", len(finished_ignore_results))
            col_b.metric("Ignored", success_count)
            col_c.metric("Failed", failed_count)
            st.dataframe(finished_ignore_results, width="stretch", hide_index=True)

    approved_col1, approved_col2 = st.columns([1, 3])
    with approved_col1:
        if st.button("Load / refresh approved output", key="load_approved_output_tab_btn", width="stretch"):
            st.session_state["active_perf_action_label"] = "load approved output"
            refresh_cached_folder_names("approved")
            clear_cached_listing_memory()
            st.session_state.pop("approved_queue_items_cache", None)
            st.session_state["approved_output_tab_loaded"] = True
    with approved_col2:
        if not st.session_state.get("approved_output_tab_loaded", False):
            st.info("Approved output is not loaded yet. Click Load / refresh approved output when you need generation.")

    if st.session_state.get("approved_output_tab_loaded", False):
        if not approved_folder_names:
            approved_folder_names = get_cached_folder_names("approved", approved_root, "approved folders")
        render_approved_queue_view(
            approved_folder_names=approved_folder_names,
            profiles=profiles,
            dropbox_cfg=dropbox_cfg,
        )


