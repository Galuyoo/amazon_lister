from __future__ import annotations

from typing import Any, Callable

import streamlit as st


def render_review_queue(
    *,
    ready_folder_names: list[str],
    ready_root: str,
    profiles: list[dict[str, Any]],
    dropbox_cfg: dict[str, Any],
    refresh_cached_folder_names: Callable[..., None],
    clear_cached_listing_memory: Callable[..., None],
    get_cached_folder_names: Callable[..., list[str]],
    render_review_queue_view: Callable[..., None],
) -> None:
    st.caption("Review ready listings and approve them for generation.")

    review_col1, review_col2 = st.columns([1, 3])
    with review_col1:
        if st.button("Load / refresh review queue", key="load_review_queue_tab_btn", width="stretch"):
            st.session_state["active_perf_action_label"] = "load review queue"
            refresh_cached_folder_names("ready")
            clear_cached_listing_memory()
            st.session_state.pop("ready_queue_items_cache", None)
            st.session_state["review_queue_tab_loaded"] = True
    with review_col2:
        if not st.session_state.get("review_queue_tab_loaded", False):
            st.info("Review queue is not loaded yet. Click Load / refresh review queue when you need admin review.")

    if st.session_state.get("review_queue_tab_loaded", False):
        if not ready_folder_names:
            ready_folder_names = get_cached_folder_names("ready", ready_root, "ready folders")
        render_review_queue_view(
            ready_folder_names=ready_folder_names,
            profiles=profiles,
            dropbox_cfg=dropbox_cfg,
        )
