from __future__ import annotations
from datetime import datetime
import time
import json
import re
import random
import string

from copy import copy
from pathlib import Path
from typing import Any, Callable
from utils.image_resolver import resolve_one
import streamlit as st
from openpyxl import load_workbook
from itertools import product
from services.quality_checks import validate_listing_quality

from utils.dropbox_client import (
    get_or_create_shared_link,
    to_direct_url,
    list_folder_files,
    list_folder_names,
    create_folder_if_missing,
    move_dropbox_folder,
    path_exists,
    upload_text_file,
    download_text_file,
)

GLOBAL_BRAND_NAME = "Generic"
WORKFLOW_ASSIGNEES = ["", "Hannan", "Amroz", "Moon", "Sal", "Richard", "Ben"]

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
CONFIG_DIR = BASE_DIR / "config"
OUTPUT_DIR = BASE_DIR / "outputs"

LOAD_EVENT_LIMIT = 160


def reset_load_events() -> None:
    st.session_state["current_load_events"] = []
    st.session_state["current_rerun_started_at"] = time.perf_counter()


def record_load_event(label: str, started_at: float, detail: str = "") -> None:
    try:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
        events = st.session_state.setdefault("current_load_events", [])
        events.append({
            "step": label,
            "ms": elapsed_ms,
            "detail": detail,
        })
        if len(events) > LOAD_EVENT_LIMIT:
            st.session_state["current_load_events"] = events[-LOAD_EVENT_LIMIT:]
    except Exception:
        # Loading debug must never break the app.
        pass


def format_folder_detail(folder_path: str) -> str:
    folder_path = str(folder_path or "").rstrip("/")
    return folder_path.split("/")[-1] if folder_path else ""


def get_cached_folder_names(cache_key: str, root_path: str, label: str) -> list[str]:
    cache = st.session_state.setdefault("dropbox_folder_list_cache", {})
    cached = cache.get(cache_key)

    if cached and cached.get("root_path") == root_path:
        folder_names = list(cached.get("folder_names", []))
        record_load_event(
            f"Dropbox: cached {label}",
            time.perf_counter(),
            f"{len(folder_names)} folder(s)",
        )
        return folder_names

    started_at = time.perf_counter()
    folder_names = list_folder_names(root_path)
    record_load_event(
        f"Dropbox: list {label}",
        started_at,
        f"{len(folder_names)} folder(s)",
    )

    cache[cache_key] = {
        "root_path": root_path,
        "folder_names": folder_names,
    }
    return folder_names


def refresh_cached_folder_names(*cache_keys: str) -> None:
    cache = st.session_state.setdefault("dropbox_folder_list_cache", {})
    for cache_key in cache_keys:
        cache.pop(cache_key, None)


DEBUG_STATE_SKIP_KEYS = {
    "current_load_events",
    "current_rerun_started_at",
    "last_debug_state_snapshot",
    "current_rerun_changed_keys",
    "perf_history",
    "last_perf_saved_signature",
}

DEBUG_STATE_SKIP_PREFIXES = (
    "_",
)


def normalize_debug_state_value(value: Any) -> str:
    try:
        if isinstance(value, (str, int, float, bool, type(None))):
            return repr(value)
        if isinstance(value, (list, tuple, set)):
            return f"{type(value).__name__}(len={len(value)})::{repr(list(value)[:8])}"
        if isinstance(value, dict):
            keys = list(value.keys())[:8]
            return f"dict(len={len(value)}, keys={keys})"
        return f"{type(value).__name__}::{repr(value)[:180]}"
    except Exception:
        return f"{type(value).__name__}::<unreadable>"


def build_debug_state_snapshot() -> dict[str, str]:
    snapshot: dict[str, str] = {}

    for key, value in st.session_state.items():
        key_text = str(key)

        if key_text in DEBUG_STATE_SKIP_KEYS:
            continue

        if key_text.startswith(DEBUG_STATE_SKIP_PREFIXES):
            continue

        snapshot[key_text] = normalize_debug_state_value(value)

    return snapshot


def capture_rerun_cause() -> None:
    try:
        previous = dict(st.session_state.get("last_debug_state_snapshot", {}))
        current = build_debug_state_snapshot()

        changed_keys: list[dict[str, str]] = []
        all_keys = sorted(set(previous.keys()) | set(current.keys()))

        for key in all_keys:
            before = previous.get(key, "<missing>")
            after = current.get(key, "<missing>")

            if before != after:
                changed_keys.append({
                    "key": key,
                    "before": before[:220],
                    "after": after[:220],
                })

        st.session_state["current_rerun_changed_keys"] = changed_keys[:80]
    except Exception as exc:
        st.session_state["current_rerun_changed_keys"] = [{
            "key": "debug_error",
            "before": "",
            "after": str(exc),
        }]


def save_debug_state_snapshot() -> None:
    try:
        st.session_state["last_debug_state_snapshot"] = build_debug_state_snapshot()
    except Exception:
        pass


def consume_pending_perf_action_label() -> None:
    pending_label = str(st.session_state.pop("pending_perf_action_label", "")).strip()
    if pending_label:
        st.session_state["active_perf_action_label"] = pending_label


def infer_perf_action_label_from_changed_keys() -> str:
    changed_keys = [
        str(row.get("key", ""))
        for row in st.session_state.get("current_rerun_changed_keys", [])
    ]

    if not changed_keys:
        return ""

    debug_keys = {
        "show_loading_debug_inline",
        "perf_action_label",
        "clear_perf_history_btn",
        "download_perf_history_csv",
    }

    non_debug_keys = [
        key for key in changed_keys
        if key and key not in debug_keys
    ]

    if not non_debug_keys:
        return "debug/profiler toggle"

    key_set = set(non_debug_keys)

    if "load_image_mappings_now" in key_set or "image_mappings_loaded_folder" in key_set:
        return "load/refresh image mappings"

    if "staged_folder_select" in key_set:
        return "select staged folder"

    if "folder_source_mode" in key_set:
        return "change folder source"

    if "template_family_select" in key_set or "listing_template_select" in key_set:
        return "change template"

    if "parent_main_image_choice" in key_set:
        return "change parent main image"

    if "title_input" in key_set:
        return "edit title"

    if any(key.startswith("bullet_") for key in key_set):
        return "edit bullets"

    if "product_description" in key_set:
        return "edit description"

    if "generic_keywords" in key_set:
        return "edit search terms"

    if "variant_quantity" in key_set:
        return "change quantity"

    if any(key.startswith("price_") for key in key_set):
        return "change price"

    if any("selected_variant" in key or key.startswith("variant_") for key in key_set):
        return "change variants"

    if "ready_queue_review_folder" in key_set:
        return "select review queue item"

    if "review_queue_reviewed_by" in key_set:
        return "change reviewer"

    if "approved_queue_review_folder" in key_set:
        return "select approved review item"

    if "approved_queue_selected_folders" in key_set:
        return "select approved folders"

    if "review_queue_tab_loaded" in key_set:
        return "load review queue"

    if "approved_output_tab_loaded" in key_set:
        return "load approved output"

    preview = ", ".join(non_debug_keys[:4])
    return f"rerun: {preview}"


def get_current_perf_action_label() -> str:
    active_label = str(st.session_state.get("active_perf_action_label", "")).strip()
    manual_label = str(st.session_state.get("perf_action_label", "")).strip()
    inferred_label = infer_perf_action_label_from_changed_keys()

    # One-shot button labels win. Manual label is useful for controlled test sessions.
    # If neither exists, infer from changed Streamlit session-state keys.
    return active_label or manual_label or inferred_label or "(unlabeled)"


def build_current_perf_summary() -> dict[str, Any]:
    events = list(st.session_state.get("current_load_events", []))
    rerun_started_at = st.session_state.get("current_rerun_started_at")

    full_rerun_ms = None
    if rerun_started_at:
        full_rerun_ms = round((time.perf_counter() - float(rerun_started_at)) * 1000, 1)

    recorded_load_ms = round(
        sum(float(event.get("ms", 0) or 0) for event in events),
        1,
    )

    estimated_ui_ms = None
    if full_rerun_ms is not None:
        estimated_ui_ms = round(max(full_rerun_ms - recorded_load_ms, 0), 1)

    slowest_event = ""
    slowest_ms = 0.0
    if events:
        slowest = max(events, key=lambda event: float(event.get("ms", 0) or 0))
        slowest_event = str(slowest.get("step", ""))
        slowest_ms = float(slowest.get("ms", 0) or 0)

    return {
        "events": events,
        "full_rerun_ms": full_rerun_ms,
        "recorded_load_ms": recorded_load_ms,
        "estimated_ui_build_ms": estimated_ui_ms,
        "slowest_event": slowest_event,
        "slowest_ms": round(slowest_ms, 1),
        "event_count": len(events),
    }


def should_skip_perf_history_row(action_label: str) -> bool:
    changed_keys = [
        row.get("key", "")
        for row in st.session_state.get("current_rerun_changed_keys", [])
    ]

    debug_only_keys = {
        "show_loading_debug_inline",
        "perf_action_label",
        "clear_perf_history_btn",
        "download_perf_history_csv",
    }

    if changed_keys and all(key in debug_only_keys for key in changed_keys):
        return True

    return False


def save_current_perf_run() -> None:
    try:
        summary = build_current_perf_summary()
        events = summary["events"]

        if not events:
            return

        action_label = get_current_perf_action_label()

        if should_skip_perf_history_row(action_label):
            return

        run_signature = {
            "action": action_label,
            "events": events,
            "full_rerun_ms": summary["full_rerun_ms"],
            "recorded_load_ms": summary["recorded_load_ms"],
            "estimated_ui_build_ms": summary["estimated_ui_build_ms"],
            "slowest_event": summary["slowest_event"],
            "slowest_ms": summary["slowest_ms"],
        }

        signature_text = json.dumps(run_signature, sort_keys=True, default=str)
        last_saved_signature = st.session_state.get("last_perf_saved_signature", "")

        if signature_text == last_saved_signature:
            return

        history = st.session_state.setdefault("perf_history", [])

        history.append({
            "run": len(history) + 1,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action_label,
            "full_rerun_ms": summary["full_rerun_ms"],
            "recorded_load_ms": summary["recorded_load_ms"],
            "estimated_ui_build_ms": summary["estimated_ui_build_ms"],
            "slowest_event": summary["slowest_event"],
            "slowest_ms": summary["slowest_ms"],
            "event_count": summary["event_count"],
        })

        if len(history) > 300:
            st.session_state["perf_history"] = history[-300:]

        st.session_state["last_perf_saved_signature"] = signature_text

        # One-shot button labels should not leak into later debug toggles/reruns.
        st.session_state.pop("active_perf_action_label", None)
    except Exception:
        pass


def render_inline_loading_debug() -> None:
    save_current_perf_run()

    st.divider()

    control_col1, control_col2 = st.columns([1, 4])
    with control_col1:
        show_debug = st.checkbox(
            "Show profiler",
            key="show_loading_debug_inline",
            value=False,
        )
    with control_col2:
        st.text_input(
            "Manual action label for next test",
            key="perf_action_label",
            placeholder="Optional label: edit title, change reviewer, load images...",
            label_visibility="collapsed",
        )

    if not show_debug:
        return

    st.subheader("Loading / render debug")

    summary = build_current_perf_summary()
    events = summary["events"]

    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
    metric_col1.metric("Full rerun", f"{summary['full_rerun_ms'] or 0} ms")
    metric_col2.metric("Recorded load", f"{summary['recorded_load_ms']} ms")
    metric_col3.metric("UI/build estimate", f"{summary['estimated_ui_build_ms'] or 0} ms")
    metric_col4.metric("Events", str(summary["event_count"]))

    if summary["slowest_event"]:
        st.caption(
            f"Slowest recorded load step: {summary['slowest_event']} ({summary['slowest_ms']} ms)"
        )

    with st.expander("Current rerun events", expanded=False):
        if not events:
            st.warning("No loading events recorded for this rerun.")
        else:
            rows = [
                {
                    "step": event.get("step", ""),
                    "ms": event.get("ms", ""),
                    "detail": event.get("detail", ""),
                }
                for event in events
            ]
            st.dataframe(rows, hide_index=True, width="stretch")

    approved_generation_step_rows = list(st.session_state.get("approved_generation_step_rows", []))
    if approved_generation_step_rows:
        with st.expander("Last approved generation step breakdown", expanded=True):
            st.dataframe(approved_generation_step_rows, hide_index=True, width="stretch")

    history = list(st.session_state.get("perf_history", []))
    st.markdown("### Performance history")

    clear_col, download_col = st.columns([1, 3])
    with clear_col:
        if st.button("Clear perf history", key="clear_perf_history_btn", width="stretch"):
            st.session_state["perf_history"] = []
            st.session_state.pop("last_perf_saved_signature", None)
            st.session_state.pop("active_perf_action_label", None)
            st.session_state.pop("perf_action_label", None)
            st.rerun()

    if not history:
        st.caption("No completed runs saved yet.")
        return

    st.dataframe(history[-50:], hide_index=True, width="stretch")

    csv_lines = [
        "run,timestamp,action,full_rerun_ms,recorded_load_ms,estimated_ui_build_ms,slowest_event,slowest_ms,event_count"
    ]

    for row in history:
        values = [
            row.get("run", ""),
            row.get("timestamp", ""),
            str(row.get("action", "")).replace('"', '""'),
            row.get("full_rerun_ms", ""),
            row.get("recorded_load_ms", ""),
            row.get("estimated_ui_build_ms", ""),
            str(row.get("slowest_event", "")).replace('"', '""'),
            row.get("slowest_ms", ""),
            row.get("event_count", ""),
        ]
        csv_lines.append(
            ",".join(
                f'"{value}"' if isinstance(value, str) and "," in value else str(value)
                for value in values
            )
        )

    with download_col:
        st.download_button(
            "Download performance history CSV",
            data="\n".join(csv_lines).encode("utf-8"),
            file_name="amazon_lister_performance_history.csv",
            mime="text/csv",
            key="download_perf_history_csv",
        )

def render_rerun_cause_debug() -> None:
    if not st.session_state.get("show_loading_debug_inline", False):
        return

    changed_keys = list(st.session_state.get("current_rerun_changed_keys", []))

    st.markdown("### Rerun cause tracker")
    st.caption(
        "These are Streamlit session-state keys that changed since the previous completed rerun. "
        "This helps identify which widget/action triggered the loading spinner."
    )

    if not changed_keys:
        st.success("No session-state changes detected from the previous completed rerun.")
        return

    summary = ", ".join(row.get("key", "") for row in changed_keys[:12])
    st.info(f"Likely trigger key(s): {summary}")

    with st.expander("Changed session-state keys", expanded=False):
        st.dataframe(changed_keys, hide_index=True, width="stretch")

SHEET_NAME = "Template"
HEADER_ROW = 3
PARENT_ROW = 4
FIRST_CHILD_ROW = 5


def load_dropbox_templates_config() -> dict[str, Any]:
    config_path = CONFIG_DIR / "dropbox_templates.json"
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def list_template_profiles() -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    if not TEMPLATES_DIR.exists():
        return profiles

    for family_folder in sorted(TEMPLATES_DIR.iterdir()):
        if not family_folder.is_dir():
            continue

        schema_path = family_folder / "schema.json"
        if not schema_path.exists():
            continue

        try:
            with schema_path.open("r", encoding="utf-8") as f:
                schema = json.load(f)
        except Exception:
            continue

        for garment_folder in sorted(family_folder.iterdir()):
            if not garment_folder.is_dir():
                continue

            config_path = garment_folder / "config.json"
            if not config_path.exists():
                continue

            try:
                with config_path.open("r", encoding="utf-8") as f:
                    config = json.load(f)

                config["_folder"] = garment_folder
                config["_slug"] = garment_folder.name
                config["_family_folder"] = family_folder
                config["_family_slug"] = family_folder.name
                config["_schema"] = schema

                # family owns workbook now
                config["template_file"] = schema.get("workbook_file", "")
                profiles.append(config)
            except Exception:
                continue

    return profiles


def get_default(profile: dict[str, Any], key: str, fallback: Any = "") -> Any:
    return profile.get(key, fallback)


@st.cache_data(show_spinner=False)
def dropbox_preview_url(path: str) -> str:
    if not path:
        return ""

    try:
        shared = get_or_create_shared_link(path)
        return to_direct_url(shared)
    except Exception as exc:
        raise FileNotFoundError(f"Dropbox preview failed for {path}: {exc}") from exc


def get_cached_dropbox_shared_link(path: str) -> str:
    path = str(path or "").strip()
    if not path:
        return ""

    cache = st.session_state.setdefault("dropbox_shared_link_cache", {})
    if path in cache:
        return str(cache[path])

    shared_link = get_or_create_shared_link(path)
    cache[path] = shared_link
    return shared_link


def render_dropbox_folder_links(
    source_folder_path: str | None,
    dropbox_overview: dict[str, Any],
) -> None:
    st.markdown("**Dropbox folders**")

    folder_rows: list[dict[str, str]] = []

    if source_folder_path:
        folder_rows.append({
            "label": "Listing folder",
            "path": source_folder_path,
        })

    resource_root = str(dropbox_overview.get("resource_root", "") or "").strip()
    garment_resource_root = str(dropbox_overview.get("garment_resource_root", "") or "").strip()

    if garment_resource_root:
        folder_rows.append({
            "label": "Garment resources",
            "path": garment_resource_root,
        })

    if resource_root:
        folder_rows.append({
            "label": "Shared resources root",
            "path": resource_root,
        })

    if not folder_rows:
        st.caption("No Dropbox folder links available.")
        return

    for row in folder_rows:
        label = row["label"]
        path = row["path"]

        try:
            shared_link = get_cached_dropbox_shared_link(path)
            st.markdown(f"- **{label}:** [{path}]({shared_link})")
        except Exception:
            st.markdown(f"- **{label}:** `{path}`")


def build_header_map(ws, header_row: int) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for col in range(1, ws.max_column + 1):
        value = ws.cell(row=header_row, column=col).value
        if value is not None:
            key = str(value).strip()
            if key:
                mapping[key] = col
    return mapping


def copy_row_format(ws, source_row: int, target_row: int) -> None:
    for col in range(1, ws.max_column + 1):
        source = ws.cell(source_row, col)
        target = ws.cell(target_row, col)

        if source.has_style:
            target._style = copy(source._style)
        target.number_format = source.number_format
        target.font = copy(source.font)
        target.fill = copy(source.fill)
        target.border = copy(source.border)
        target.alignment = copy(source.alignment)
        target.protection = copy(source.protection)

    ws.row_dimensions[target_row].height = ws.row_dimensions[source_row].height


def clear_row_values(ws, row_idx: int) -> None:
    for col in range(1, ws.max_column + 1):
        ws.cell(row_idx, col).value = None


def set_field(ws, row_idx: int, header_map: dict[str, int], field: str, value: Any) -> bool:
    col = header_map.get(field)
    if col is None:
        return False

    ws.cell(row_idx, col).value = value
    return True

def write_values_with_debug(
    ws,
    row_idx: int,
    header_map: dict[str, int],
    values: dict[str, Any],
    row_label: str,
) -> None:
    missing_fields: list[str] = []

    for field, value in values.items():
        written = set_field(ws, row_idx, header_map, field, value)
        if not written:
            missing_fields.append(field)

    if missing_fields and st.session_state.get("show_header_debug", False):
        st.warning(f"{row_label}: {len(missing_fields)} field(s) not found in template headers")
        st.code("\n".join(missing_fields), language=None)

def normalize_size(size: str) -> str:
    size_map = {
        "2XL": "XXL",
        "XXL": "XXL",
        "3XL": "3XL",
        "4XL": "4XL",
        "5XL": "5XL",
        "6XL": "6XL",
    }
    return size_map.get(size, size)

def is_variant_combo_allowed(profile: dict[str, Any], variant_values: dict[str, str]) -> bool:
    color = variant_values.get("color", "")
    size = variant_values.get("size", "")

    color_size_map = profile.get("color_size_map", {})
    if color and size and color_size_map:
        allowed_sizes = color_size_map.get(color)
        if allowed_sizes is not None and size not in allowed_sizes:
            return False

    return True


def build_variant_combinations(
    profile: dict[str, Any],
    selected_variants: dict[str, list[str]],
) -> list[dict[str, str]]:
    keys = list(selected_variants.keys())
    if not keys:
        return []

    value_lists = [selected_variants[k] for k in keys]
    combos: list[dict[str, str]] = []

    for values in product(*value_lists):
        combo = dict(zip(keys, values))
        if is_variant_combo_allowed(profile, combo):
            combos.append(combo)

    return combos


def get_selected_colors_for_image_resolution(
    profile: dict[str, Any],
    selected_variants: dict[str, list[str]],
) -> list[str]:
    variant_dimensions = profile.get("variant_dimensions", [])
    if variant_dimensions:
        for dim in variant_dimensions:
            dim_name = dim.get("name", "")
            if dim_name.lower() == "color":
                return list(selected_variants.get(dim_name, []))

    return list(selected_variants.get("color", []))


def build_child_sku(profile: dict[str, Any], parent_sku: str, variant_values: dict[str, str]) -> str:
    color_map = profile.get("color_sku_map", {})
    size_map = profile.get("size_code_map", {})
    design_map = profile.get("design_sku_map", {})

    color_code = ""
    size_code = ""
    design_code = ""

    if "color" in variant_values:
        color_value = variant_values["color"]
        color_code = color_map.get(color_value, slugify_part(color_value))

    if "size" in variant_values:
        size_value = variant_values["size"]
        size_code = size_map.get(size_value, slugify_part(size_value))

    if "design" in variant_values:
        design_value = variant_values["design"]
        design_code = design_map.get(design_value, slugify_part(design_value))

    parts: list[str] = []

    if color_code:
        if color_code.startswith(parent_sku):
            parts.append(color_code)
        else:
            parts.append(parent_sku)
            parts.append(color_code)
    else:
        parts.append(parent_sku)

    if size_code:
        parts.append(size_code)

    if design_code:
        parts.append(design_code)

    return "-".join(parts)

def build_variant_field_values(profile: dict[str, Any], variant_values: dict[str, str]) -> dict[str, Any]:
    values: dict[str, Any] = {}

    if "color" in variant_values:
        values["color_name"] = variant_values["color"]

    if "size" in variant_values:
        normalized_size = normalize_size(variant_values["size"])
        values["size_name"] = normalized_size
        values["apparel_size"] = normalized_size

    if "design" in variant_values:
        values["style_name"] = variant_values["design"]

    return values


def validate_variant_dimensions(selected_variants: dict[str, list[str]]) -> list[str]:
    errors: list[str] = []

    for dim_name, items in selected_variants.items():
        if not items:
            errors.append(f"At least one option is required for {dim_name}.")

    return errors

def slugify_part(value: str) -> str:
    safe = value.strip().replace(" ", "-").replace("/", "-")
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe

def sanitize_sku(value: str) -> str:
    safe = value.strip()
    for ch in ['\\', '/', ':', '*', '?', '"', '<', '>', '|', ' ']:
        safe = safe.replace(ch, '-')
    while '--' in safe:
        safe = safe.replace('--', '-')
    return safe.strip('-')


def generate_unique_sku(length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choices(alphabet, k=length))


def build_final_folder_sku(parent_sku: str, unique_sku: str) -> str:
    return f"{unique_sku}-{sanitize_sku(parent_sku)}"


def build_stage_folder_path(dropbox_cfg: dict[str, Any], staged_folder_name: str) -> str:
    stage_root = dropbox_cfg.get("stage_root", "").rstrip("/")
    return f"{stage_root}/{staged_folder_name}"


def build_finished_folder_path(dropbox_cfg: dict[str, Any], final_sku: str) -> str:
    finished_root = dropbox_cfg.get("finished_root", "").rstrip("/")
    return f"{finished_root}/{final_sku}"


def build_ready_folder_path(dropbox_cfg: dict[str, Any], ready_folder_name: str) -> str:
    ready_root = dropbox_cfg.get("ready_root", "").rstrip("/")
    return f"{ready_root}/{ready_folder_name}"


def build_approved_folder_path(dropbox_cfg: dict[str, Any], approved_folder_name: str) -> str:
    approved_root = dropbox_cfg.get("approved_root", "").rstrip("/")
    return f"{approved_root}/{approved_folder_name}"


def restage_finished_dropbox_folder(
    dropbox_cfg: dict[str, Any],
    finished_folder_name: str,
) -> str:
    stage_root = dropbox_cfg.get("stage_root", "").rstrip("/")
    finished_root = dropbox_cfg.get("finished_root", "").rstrip("/")

    if not finished_folder_name:
        raise ValueError("Finished folder name is required.")

    source_path = f"{finished_root}/{finished_folder_name}"

    candidate_name = f"{finished_folder_name}_restaged"
    target_path = f"{stage_root}/{candidate_name}"

    counter = 1
    while path_exists(target_path):
        candidate_name = f"{finished_folder_name}_restaged_{counter}"
        target_path = f"{stage_root}/{candidate_name}"
        counter += 1

    moved_path = move_dropbox_folder(source_path, target_path)
    return moved_path

def build_listing_memory_path(folder_path: str) -> str:
    return f"{folder_path.rstrip('/')}/listing_inputs.json"


def format_workflow_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def build_listing_memory_payload(profile: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    memory_payload = {
        "template_label": profile.get("label", profile.get("_slug", "")),
        "template_slug": profile.get("_slug", ""),
        "template_key": profile.get("template_key", ""),
        "title": payload.get("title", ""),
        "product_description": payload.get("product_description", ""),
        "generic_keywords": payload.get("generic_keywords", ""),
        "bullet_points": payload.get("bullet_points", []),
        "selected_variants": payload.get("selected_variants", {}),
        "size_price_map": payload.get("size_price_map", {}),
        "use_same_price_for_all_sizes": payload.get("use_same_price_for_all_sizes", False),
        "quantity": payload.get("quantity", 0),
        "assets_prepared_by": payload.get("assets_prepared_by", ""),
        "content_prepared_by": payload.get("content_prepared_by", ""),
        "reviewed_by": payload.get("reviewed_by", ""),
        "prepared_at": payload.get("prepared_at", ""),
        "reviewed_at": payload.get("reviewed_at", ""),
    }

    original_finished_folder_name = str(payload.get("original_finished_folder_name", "")).strip()
    if original_finished_folder_name:
        memory_payload["original_finished_folder_name"] = original_finished_folder_name

    return memory_payload


def save_listing_memory_to_dropbox(
    profile: dict[str, Any],
    payload: dict[str, Any],
    folder_path: str,
) -> str:
    return save_listing_inputs_json_to_dropbox(profile, payload, folder_path)


def save_listing_inputs_json_to_dropbox(
    profile: dict[str, Any],
    payload: dict[str, Any],
    folder_path: str,
) -> str:
    json_path = build_listing_memory_path(folder_path)
    memory_payload = build_listing_memory_payload(profile, payload)
    upload_text_file(
        json_path,
        json.dumps(memory_payload, indent=2, ensure_ascii=False),
    )
    return json_path


def load_listing_memory_from_dropbox(folder_path: str) -> dict[str, Any]:
    json_path = build_listing_memory_path(folder_path)
    if not path_exists(json_path):
        return {}
    content = download_text_file(json_path)
    return json.loads(content)

def initialize_listing_context_defaults(profile: dict[str, Any]) -> None:
    normalize_selected_variants_session_state(profile, {}, force_defaults=True)
    st.session_state["parent_main_image_choice"] = "Automatic (recommended)"


def apply_listing_memory_to_session(listing_memory: dict[str, Any], profile: dict[str, Any]) -> None:
    st.session_state["title_input"] = listing_memory.get("title", "")
    for field_name in ["assets_prepared_by", "content_prepared_by", "reviewed_by"]:
        if field_name not in st.session_state:
            st.session_state[field_name] = listing_memory.get(field_name, "")
    st.session_state["prepared_at"] = listing_memory.get("prepared_at", "")
    st.session_state["reviewed_at"] = listing_memory.get("reviewed_at", "")

    bullet_points = listing_memory.get("bullet_points", [])
    bullet_points = (bullet_points + ["", "", "", "", ""])[:5]
    for idx, value in enumerate(bullet_points, start=1):
        st.session_state[f"bullet_{idx}"] = value

    st.session_state["product_description"] = listing_memory.get("product_description", "")
    st.session_state["generic_keywords"] = listing_memory.get("generic_keywords", "")
    st.session_state["use_same_price_for_all_sizes"] = listing_memory.get("use_same_price_for_all_sizes", False)
    st.session_state["variant_quantity"] = int(listing_memory.get("quantity", 100))

    saved_prices = listing_memory.get("size_price_map", {})
    for size, price in saved_prices.items():
        st.session_state[f"price_{size}"] = float(price)

    normalize_selected_variants_session_state(profile, listing_memory, force_saved_values=True)

def finalize_staged_dropbox_folder(
    dropbox_cfg: dict[str, Any],
    staged_folder_name: str,
    parent_sku: str,
    reuse_finished_folder_name: str = "",
) -> tuple[str, str]:
    parent_sku = sanitize_sku(parent_sku)
    if not parent_sku:
        raise ValueError("Template parent_sku is missing.")

    finished_root = dropbox_cfg.get("finished_root", "").rstrip("/")
    stage_path = build_stage_folder_path(dropbox_cfg, staged_folder_name)

    create_folder_if_missing(finished_root)

    max_attempts = 20
    final_sku = ""
    final_folder_path = ""

    reuse_finished_folder_name = sanitize_sku(reuse_finished_folder_name)
    if reuse_finished_folder_name:
        final_sku = reuse_finished_folder_name
        final_folder_path = build_finished_folder_path(dropbox_cfg, final_sku)
        moved_path = move_dropbox_folder(stage_path, final_folder_path)
        return final_sku, moved_path

    for _ in range(max_attempts):
        unique_sku = generate_unique_sku()
        final_sku = build_final_folder_sku(parent_sku, unique_sku)
        final_folder_path = build_finished_folder_path(dropbox_cfg, final_sku)

        if not path_exists(final_folder_path):
            moved_path = move_dropbox_folder(stage_path, final_folder_path)
            return final_sku, moved_path

    raise ValueError("Could not generate a unique finished folder SKU after multiple attempts.")


def move_staged_dropbox_folder_to_ready(
    dropbox_cfg: dict[str, Any],
    staged_folder_name: str,
    ready_folder_name: str,
) -> str:
    ready_folder_name = sanitize_sku(ready_folder_name)
    if not ready_folder_name:
        raise ValueError("Ready folder name is required.")

    ready_root = dropbox_cfg.get("ready_root", "").rstrip("/")
    stage_path = build_stage_folder_path(dropbox_cfg, staged_folder_name)

    create_folder_if_missing(ready_root)

    final_ready_folder_name = ready_folder_name
    counter = 1

    while True:
        ready_folder_path = build_ready_folder_path(dropbox_cfg, final_ready_folder_name)
        if path_exists(ready_folder_path):
            final_ready_folder_name = f"{ready_folder_name}-{counter}"
            counter += 1
            continue

        moved_path = move_dropbox_folder(stage_path, ready_folder_path)
        if not moved_path:
            raise RuntimeError("Dropbox returned an empty path after moving the folder to ready.")
        return moved_path


def move_ready_dropbox_folder_to_approved(
    dropbox_cfg: dict[str, Any],
    ready_folder_name: str,
    approved_folder_name: str,
) -> str:
    approved_folder_name = sanitize_sku(approved_folder_name)
    if not approved_folder_name:
        raise ValueError("Approved folder name is required.")

    approved_root = dropbox_cfg.get("approved_root", "").rstrip("/")
    ready_path = build_ready_folder_path(dropbox_cfg, ready_folder_name)

    create_folder_if_missing(approved_root)

    final_approved_folder_name = approved_folder_name
    counter = 1

    while True:
        approved_folder_path = build_approved_folder_path(dropbox_cfg, final_approved_folder_name)
        if path_exists(approved_folder_path):
            final_approved_folder_name = f"{approved_folder_name}-{counter}"
            counter += 1
            continue

        moved_path = move_dropbox_folder(ready_path, approved_folder_path)
        if not moved_path:
            raise RuntimeError("Dropbox returned an empty path after moving the folder to approved.")
        return moved_path


def move_ready_dropbox_folder_to_denied_stage(
    dropbox_cfg: dict[str, Any],
    ready_folder_name: str,
) -> str:
    denied_folder_name = sanitize_sku(f"{ready_folder_name}_denied")
    if not denied_folder_name:
        raise ValueError("Denied folder name is required.")

    stage_root = dropbox_cfg.get("stage_root", "").rstrip("/")
    ready_path = build_ready_folder_path(dropbox_cfg, ready_folder_name)

    create_folder_if_missing(stage_root)

    final_denied_folder_name = denied_folder_name
    counter = 1

    while True:
        denied_stage_folder_path = build_stage_folder_path(dropbox_cfg, final_denied_folder_name)
        if path_exists(denied_stage_folder_path):
            final_denied_folder_name = f"{denied_folder_name}-{counter}"
            counter += 1
            continue

        moved_path = move_dropbox_folder(ready_path, denied_stage_folder_path)
        if not moved_path:
            raise RuntimeError("Dropbox returned an empty path after moving the folder back to staging.")
        return moved_path


def finalize_ready_dropbox_folder(
    dropbox_cfg: dict[str, Any],
    ready_folder_name: str,
    parent_sku: str,
    reuse_finished_folder_name: str = "",
) -> tuple[str, str]:
    parent_sku = sanitize_sku(parent_sku)
    if not parent_sku:
        raise ValueError("Template parent_sku is missing.")

    finished_root = dropbox_cfg.get("finished_root", "").rstrip("/")
    ready_path = build_ready_folder_path(dropbox_cfg, ready_folder_name)

    create_folder_if_missing(finished_root)

    max_attempts = 20

    reuse_finished_folder_name = sanitize_sku(reuse_finished_folder_name)
    if reuse_finished_folder_name:
        final_sku = reuse_finished_folder_name
        final_folder_path = build_finished_folder_path(dropbox_cfg, final_sku)
        moved_path = move_dropbox_folder(ready_path, final_folder_path)
        return final_sku, moved_path

    for _ in range(max_attempts):
        unique_sku = generate_unique_sku()
        final_sku = build_final_folder_sku(parent_sku, unique_sku)
        final_folder_path = build_finished_folder_path(dropbox_cfg, final_sku)

        if not path_exists(final_folder_path):
            moved_path = move_dropbox_folder(ready_path, final_folder_path)
            return final_sku, moved_path

    raise ValueError("Could not generate a unique finished folder SKU after multiple attempts.")

def finalize_approved_dropbox_folder(
    dropbox_cfg: dict[str, Any],
    approved_folder_name: str,
    parent_sku: str,
    reuse_finished_folder_name: str = "",
) -> tuple[str, str]:
    parent_sku = sanitize_sku(parent_sku)
    if not parent_sku:
        raise ValueError("Template parent_sku is missing.")

    finished_root = dropbox_cfg.get("finished_root", "").rstrip("/")
    approved_path = build_approved_folder_path(dropbox_cfg, approved_folder_name)

    create_folder_if_missing(finished_root)

    max_attempts = 20

    reuse_finished_folder_name = sanitize_sku(reuse_finished_folder_name)
    if reuse_finished_folder_name:
        final_sku = reuse_finished_folder_name
        final_folder_path = build_finished_folder_path(dropbox_cfg, final_sku)
        moved_path = move_dropbox_folder(approved_path, final_folder_path)
        return final_sku, moved_path

    for _ in range(max_attempts):
        unique_sku = generate_unique_sku()
        final_sku = build_final_folder_sku(parent_sku, unique_sku)
        final_folder_path = build_finished_folder_path(dropbox_cfg, final_sku)

        if not path_exists(final_folder_path):
            moved_path = move_dropbox_folder(approved_path, final_folder_path)
            return final_sku, moved_path

    raise ValueError("Could not generate a unique finished folder SKU after multiple attempts.")


def split_folder_images(folder_path: str) -> tuple[str, list[str]]:
    files = [p for p in list_folder_files(folder_path) if is_image_file(p)]
    files = sorted(files, key=lambda p: Path(p).name.lower())

    parent_main = ""
    other_images: list[str] = []

    for path in files:
        stem = Path(path).stem.lower()

        if stem == "main":
            parent_main = path
        else:
            other_images.append(path)

    if not parent_main and other_images:
        parent_main = other_images[0]
        other_images = other_images[1:]

    return parent_main, other_images

def build_stage_preview_paths(dropbox_cfg: dict[str, Any], staged_folder_name: str) -> list[str]:
    if not staged_folder_name:
        return []

    stage_root = dropbox_cfg.get("stage_root", "").rstrip("/")
    stage_folder_path = f"{stage_root}/{staged_folder_name}"

    try:
        files = [p for p in list_folder_files(stage_folder_path) if is_image_file(p)]
    except Exception:
        return []
    return sorted(files, key=lambda p: Path(p).name.lower())

def padded_list(values: list[str], target_len: int = 8) -> list[str]:
    trimmed = values[:target_len]
    return trimmed + [""] * (target_len - len(trimmed))

def is_image_file(path: str) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in {".png", ".jpg", ".jpeg", ".webp"}

def build_design_color_preview_paths(
    profile: dict[str, Any],
    dropbox_cfg: dict[str, Any],
    selected_variants: dict[str, list[str]],
    staged_folder_name: str,
) -> list[dict[str, str]]:
    template_key = profile.get("template_key", "")
    templates_map = dropbox_cfg.get("templates", {})
    template_block = templates_map.get(template_key, {})

    stage_root = dropbox_cfg.get("stage_root", "").rstrip("/")
    stage_folder_path = f"{stage_root}/{staged_folder_name}" if staged_folder_name else ""
    combo_map = template_block.get("design_color_image_map", {})

    selected_colors = selected_variants.get("color", [])
    selected_designs = selected_variants.get("design", [])

    rows: list[dict[str, str]] = []

    for color in selected_colors:
        design_map = combo_map.get(color, {})
        for design in selected_designs:
            filename = design_map.get(design, "")
            path = f"{stage_folder_path}/{filename}" if stage_folder_path and filename else ""
            rows.append({
                "color": color,
                "design": design,
                "path": path,
            })

    return rows


def render_design_color_grid(
    entries: list[dict[str, Any]],
    cols_per_row: int = 5,
    image_width: int = 150,
) -> None:
    st.markdown("**Design/colour image mapping**")

    if not entries:
        st.caption("No design/colour combinations configured.")
        return

    cols = st.columns(cols_per_row)
    for idx, entry in enumerate(entries):
        with cols[idx % cols_per_row]:
            label = entry.get("label", "")
            st.caption(label)

            path = entry.get("path", "")
            if not path:
                st.warning("Missing")
                continue

            if entry.get("exists") and entry.get("direct_url"):
                st.image(entry["direct_url"], width=image_width)
            else:
                st.warning("Not found")
                st.code(path, language=None)

def render_variant_combinations_preview(
    profile: dict[str, Any],
    parent_sku: str,
    selected_variants: dict[str, list[str]],
) -> None:
    combos = build_variant_combinations(profile, selected_variants)

    st.markdown("**Selected variant combinations**")

    if not combos:
        st.caption("No combinations selected.")
        return

    rows = []
    for idx, combo in enumerate(combos, start=1):
        row = {"#": idx}
        row.update(combo)
        row["child_sku"] = build_child_sku(profile, parent_sku, combo)
        rows.append(row)

    st.dataframe(rows, width="stretch", hide_index=True)

def get_profile_color_options(profile: dict[str, Any]) -> list[str]:
    colors = list(profile.get("colors", []))
    if colors:
        return colors

    color_size_map = profile.get("color_size_map", {})
    if color_size_map:
        return list(color_size_map.keys())

    color_sku_map = profile.get("color_sku_map", {})
    if color_sku_map:
        return list(color_sku_map.keys())

    return []


def normalize_saved_selected_variants(saved_selected_variants: dict[str, Any]) -> dict[str, list[str]]:
    normalized: dict[str, list[str]] = {}
    for key, value in dict(saved_selected_variants or {}).items():
        normalized_key = str(key).strip().lower()
        if isinstance(value, list):
            normalized[normalized_key] = list(value)
        elif value is None:
            normalized[normalized_key] = []
        else:
            normalized[normalized_key] = [value]
    return normalized


def get_saved_variant_values(
    saved_variants_normalized: dict[str, list[str]],
    dim_name: str,
) -> list[str]:
    normalized_name = str(dim_name).strip().lower()
    aliases = [normalized_name]

    if normalized_name in {"color", "colour", "colors", "colours"}:
        aliases.extend(["color", "colour", "colors", "colours"])
    elif normalized_name in {"size", "sizes"}:
        aliases.extend(["size", "sizes"])
    elif normalized_name in {"design", "style", "styles"}:
        aliases.extend(["design", "style", "styles"])

    for alias in aliases:
        candidate = saved_variants_normalized.get(alias)
        if candidate is not None:
            return list(candidate)

    return []


def normalize_multiselect_values(
    current_values: list[str] | None,
    valid_options: list[str],
    fallback_values: list[str] | None,
) -> tuple[list[str], bool]:
    valid_options = list(valid_options)
    current_list = list(current_values or [])
    fallback_list = list(fallback_values or [])

    valid_current = [value for value in current_list if value in valid_options]
    valid_fallback = [value for value in fallback_list if value in valid_options]

    if not valid_fallback:
        valid_fallback = list(valid_options)

    should_reset = (
        not current_list
        or not valid_current
        or len(valid_current) != len(current_list)
    )

    if should_reset:
        return valid_fallback, True

    return valid_current, False


def normalize_selected_variants_session_state(
    profile: dict[str, Any],
    listing_memory: dict[str, Any],
    force_saved_values: bool = False,
    force_defaults: bool = False,
) -> dict[str, list[str]]:
    saved_variants_normalized = normalize_saved_selected_variants(
        listing_memory.get("selected_variants", {})
    )
    variant_dimensions = profile.get("variant_dimensions", [])

    if variant_dimensions:
        normalized_variants: dict[str, list[str]] = {}
        for dim in variant_dimensions:
            dim_name = str(dim.get("name", "")).strip()
            dim_options = list(dim.get("options", []))
            widget_key = f"variant_{dim_name}"
            saved_values = [
                value for value in get_saved_variant_values(saved_variants_normalized, dim_name)
                if value in dim_options
            ]
            fallback_values = list(dim_options) if force_defaults else (saved_values or list(dim_options))
            current_values = [] if force_saved_values or force_defaults else st.session_state.get(widget_key, [])
            normalized_values, should_set = normalize_multiselect_values(
                current_values,
                dim_options,
                fallback_values,
            )
            if should_set or widget_key not in st.session_state:
                st.session_state[widget_key] = list(normalized_values)
            normalized_variants[dim_name] = list(st.session_state.get(widget_key, normalized_values))

        return normalized_variants

    color_options = get_profile_color_options(profile)
    saved_colors = [
        color for color in get_saved_variant_values(saved_variants_normalized, "color")
        if color in color_options
    ]
    color_fallback = list(color_options) if force_defaults else (saved_colors or list(color_options))
    current_colors = [] if force_saved_values or force_defaults else st.session_state.get("selected_colours", [])
    normalized_colors, should_set_colors = normalize_multiselect_values(
        current_colors,
        color_options,
        color_fallback,
    )
    if should_set_colors or "selected_colours" not in st.session_state:
        st.session_state["selected_colours"] = list(normalized_colors)
    selected_colors = list(st.session_state.get("selected_colours", normalized_colors))

    available_sizes = get_available_sizes_for_selected_colors(profile, selected_colors)
    saved_sizes = [
        size for size in get_saved_variant_values(saved_variants_normalized, "size")
        if size in available_sizes
    ]
    size_fallback = list(available_sizes) if force_defaults else (saved_sizes or list(available_sizes))
    current_sizes = [] if force_saved_values or force_defaults else st.session_state.get("selected_sizes", [])
    normalized_sizes, should_set_sizes = normalize_multiselect_values(
        current_sizes,
        available_sizes,
        size_fallback,
    )
    if should_set_sizes or "selected_sizes" not in st.session_state:
        st.session_state["selected_sizes"] = list(normalized_sizes)
    selected_sizes = list(st.session_state.get("selected_sizes", normalized_sizes))

    return {
        "color": selected_colors,
        "size": selected_sizes,
    }


def get_available_sizes_for_selected_colors(
    profile: dict[str, Any],
    selected_colors: list[str],
) -> list[str]:
    all_sizes = profile.get("sizes", [])
    color_size_map = profile.get("color_size_map", {})

    if not color_size_map or not selected_colors:
        return all_sizes

    allowed: list[str] = []
    seen: set[str] = set()

    for color in selected_colors:
        for size in color_size_map.get(color, []):
            if size in all_sizes and size not in seen:
                allowed.append(size)
                seen.add(size)

    return allowed

def build_dropbox_overview(profile: dict[str, Any], dropbox_cfg: dict[str, Any]) -> dict[str, Any]:
    if not dropbox_cfg:
        return {}

    template_key = profile.get("template_key", "")
    templates_map = dropbox_cfg.get("templates", {})
    template_block = templates_map.get(template_key, {})

    resource_root = dropbox_cfg.get("resource_root", "").rstrip("/")
    variant_folder = template_block.get("variant_folder", template_key)

    shared_resource_images = [
        f"{resource_root}/{name}"
        for name in dropbox_cfg.get("general_resource_images", [])
    ]

    garment_resource_root = f"{resource_root}/{variant_folder}" if resource_root and variant_folder else ""
    garment_resource_images: list[str] = []
    garment_resource_warning = ""

    if garment_resource_root:
        try:
            garment_resource_images = [
                p for p in list_folder_files(garment_resource_root)
                if is_image_file(p)
            ]
            garment_resource_images = sorted(
                garment_resource_images,
                key=lambda p: Path(p).name.lower(),
            )
            if not garment_resource_images:
                garment_resource_warning = (
                    f"No garment support images found in {garment_resource_root}."
                )
        except Exception as exc:
            garment_resource_warning = f"Garment support images unavailable: {exc}"

    return {
        "resource_root": resource_root,
        "template_key": template_key,
        "variant_folder": variant_folder,
        "garment_resource_root": garment_resource_root,
        "garment_resource_images": garment_resource_images,
        "garment_resource_warning": garment_resource_warning,
        "shared_resource_images": shared_resource_images,
        "main_image_map": template_block.get("main_image_map", {}),
        "design_color_image_map": template_block.get("design_color_image_map", {}),
    }

def resolve_child_variant_image_url(
    variant_values: dict[str, str],
    color_image_map: dict[str, str],
    design_color_image_url_map: dict[str, dict[str, str]] | None = None,
) -> str:
    design_color_image_url_map = design_color_image_url_map or {}

    color_value = variant_values.get("color", "")
    design_value = variant_values.get("design", "")

    if color_value and design_value:
        image_url = (
            design_color_image_url_map
            .get(color_value, {})
            .get(design_value, "")
        )
        if image_url:
            return image_url

    if color_value:
        return color_image_map.get(color_value, "")

    return ""


def build_parent_main_image_options(
    profile: dict[str, Any],
    selected_variants: dict[str, list[str]],
    color_image_map: dict[str, str],
    design_color_image_url_map: dict[str, dict[str, str]] | None = None,
) -> list[tuple[str, str]]:
    options: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    variant_combos = build_variant_combinations(profile, selected_variants)

    for combo in variant_combos:
        image_url = resolve_child_variant_image_url(
            variant_values=combo,
            color_image_map=color_image_map,
            design_color_image_url_map=design_color_image_url_map,
        )
        if not image_url or image_url in seen_urls:
            continue

        label = " / ".join([v for v in combo.values() if v]) or "Unnamed variant"
        options.append((label, image_url))
        seen_urls.add(image_url)

    return options


def build_dropbox_overview_cache_key(
    profile: dict[str, Any],
    dropbox_cfg: dict[str, Any],
) -> str:
    template_key = profile.get("template_key", "")
    cache_parts = {
        "template_key": template_key,
        "template_cfg": dropbox_cfg.get("templates", {}).get(template_key, {}),
        "general_resource_images": dropbox_cfg.get("general_resource_images", []),
        "resource_root": dropbox_cfg.get("resource_root", ""),
    }
    return json.dumps(cache_parts, sort_keys=True)


def get_cached_dropbox_overview(
    profile: dict[str, Any],
    dropbox_cfg: dict[str, Any],
) -> dict[str, Any]:
    cache_key = build_dropbox_overview_cache_key(profile, dropbox_cfg)
    cache = st.session_state.get("dropbox_overview_cache", {})

    if cache.get("key") == cache_key:
        return cache.get("data", {})

    data = build_dropbox_overview(profile, dropbox_cfg)
    st.session_state["dropbox_overview_cache"] = {
        "key": cache_key,
        "data": data,
    }
    return data


def clear_runtime_caches() -> None:
    for key in [
        "dropbox_folder_list_cache",
        "dropbox_overview_cache",
        "preview_image_cache",
        "preview_image_mapping_cache",
        "resolved_image_bundle_cache",
        "ready_queue_items_cache",
        "approved_queue_items_cache",
        "load_image_mappings_now",
        "current_run_image_resolution_debug",
    ]:
        st.session_state.pop(key, None)

    for key in list(st.session_state.keys()):
        if key.endswith("_load_image_review") or key.endswith("_run_full_quality"):
            st.session_state.pop(key, None)


def set_workflow_flash(level: str, message: str, detail: str = "") -> None:
    st.session_state["workflow_flash"] = {
        "level": level,
        "message": message,
        "detail": detail,
    }


def render_workflow_flash() -> None:
    flash = st.session_state.pop("workflow_flash", None)
    if not flash:
        return

    level = flash.get("level", "info")
    message = flash.get("message", "")
    detail = flash.get("detail", "")

    if message:
        if level == "success":
            st.success(message)
        elif level == "warning":
            st.warning(message)
        elif level == "error":
            st.error(message)
        else:
            st.info(message)

    if detail:
        st.info(detail)


def build_preview_image_cache_key(
    profile: dict[str, Any],
    dropbox_cfg: dict[str, Any],
    staged_folder_name: str,
    selected_variants: dict[str, list[str]],
    include_mappings: bool = False,
    resolve_preview_urls: bool = False,
) -> str:
    template_key = profile.get("template_key", "")
    cache_parts = {
        "template_key": template_key,
        "staged_folder_name": staged_folder_name,
        "selected_colors": get_selected_colors_for_image_resolution(profile, selected_variants),
        "selected_designs": selected_variants.get("design", []),
        "template_cfg": dropbox_cfg.get("templates", {}).get(template_key, {}),
        "general_resource_images": dropbox_cfg.get("general_resource_images", []),
        "include_mappings": include_mappings,
        "resolve_preview_urls": resolve_preview_urls,
    }
    return json.dumps(cache_parts, sort_keys=True)


def build_preview_image_mapping_cache_key(
    profile: dict[str, Any],
    dropbox_cfg: dict[str, Any],
    staged_folder_name: str,
) -> str:
    template_key = profile.get("template_key", "")
    cache_parts = {
        "template_key": template_key,
        "template_slug": profile.get("_slug", ""),
        "staged_folder_name": staged_folder_name,
        "template_cfg": dropbox_cfg.get("templates", {}).get(template_key, {}),
        "general_resource_images": dropbox_cfg.get("general_resource_images", []),
        "resource_root": dropbox_cfg.get("resource_root", ""),
    }
    return json.dumps(cache_parts, sort_keys=True)


def build_image_mapping_variants_for_cache(
    profile: dict[str, Any],
    selected_variants: dict[str, list[str]],
) -> dict[str, list[str]]:
    # Heavy Dropbox image mapping should be cached at folder/template level,
    # not invalidated by normal listing-content variant edits.
    mapping_variants: dict[str, list[str]] = {}

    colors = get_profile_color_options(profile)
    if colors:
        mapping_variants["color"] = list(colors)
    elif selected_variants.get("color"):
        mapping_variants["color"] = list(selected_variants.get("color", []))

    for dim in profile.get("variant_dimensions", []):
        dim_name = str(dim.get("name", "")).strip().lower()
        if dim_name == "design":
            options = list(dim.get("options", []))
            if options:
                mapping_variants["design"] = options
            elif selected_variants.get("design"):
                mapping_variants["design"] = list(selected_variants.get("design", []))

    return mapping_variants or dict(selected_variants)


def filter_preview_image_maps_for_selected_variants(
    profile: dict[str, Any],
    selected_variants: dict[str, list[str]],
    full_color_image_map: dict[str, str],
    full_design_color_image_url_map: dict[str, dict[str, str]],
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    selected_colors = get_selected_colors_for_image_resolution(profile, selected_variants)
    selected_designs = list(selected_variants.get("design", []))

    if selected_colors:
        color_image_map = {
            color: image_url
            for color, image_url in full_color_image_map.items()
            if color in selected_colors
        }
    else:
        color_image_map = dict(full_color_image_map)

    if selected_colors or selected_designs:
        design_color_image_url_map: dict[str, dict[str, str]] = {}
        for color, design_map in full_design_color_image_url_map.items():
            if selected_colors and color not in selected_colors:
                continue

            filtered_design_map = {
                design: image_url
                for design, image_url in dict(design_map).items()
                if not selected_designs or design in selected_designs
            }

            if filtered_design_map:
                design_color_image_url_map[color] = filtered_design_map
    else:
        design_color_image_url_map = {
            color: dict(design_map)
            for color, design_map in full_design_color_image_url_map.items()
        }

    return color_image_map, design_color_image_url_map


def get_cached_preview_image_data(
    profile: dict[str, Any],
    dropbox_cfg: dict[str, Any],
    staged_folder_name: str,
    selected_variants: dict[str, list[str]],
    dropbox_overview: dict[str, Any],
    include_mappings: bool = False,
    resolve_preview_urls: bool = False,
) -> dict[str, Any]:
    cache_key = build_preview_image_cache_key(
        profile,
        dropbox_cfg,
        staged_folder_name,
        selected_variants,
        include_mappings,
        resolve_preview_urls,
    )
    cache = st.session_state.get("preview_image_cache", {})

    if cache.get("key") == cache_key:
        return cache.get("data", {})

    staged_preview_paths = build_stage_preview_paths(dropbox_cfg, staged_folder_name) if staged_folder_name else []
    design_color_preview_rows = build_design_color_preview_paths(
        profile=profile,
        dropbox_cfg=dropbox_cfg,
        selected_variants=selected_variants,
        staged_folder_name=staged_folder_name or "",
    )

    preview_color_image_map: dict[str, str] = {}
    preview_design_color_image_url_map: dict[str, dict[str, str]] = {}
    parent_main_image_options: list[tuple[str, str]] = []

    def resolve_display_entries(items: list[tuple[str, str]]) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for label, path in items:
            if not path:
                entries.append({"label": label, "path": path, "exists": False, "direct_url": ""})
                continue
            if not resolve_preview_urls:
                entries.append({"label": label, "path": path, "exists": True, "direct_url": ""})
                continue
            try:
                result = resolve_one(path, label)
                entries.append({
                    "label": label,
                    "path": path,
                    "exists": result.get("exists", False),
                    "direct_url": result.get("direct_url", ""),
                })
            except Exception:
                entries.append({"label": label, "path": path, "exists": False, "direct_url": ""})
        return entries

    if staged_folder_name and include_mappings:
        try:
            preview_stage_folder_path = build_stage_folder_path(dropbox_cfg, staged_folder_name)
            mapping_cache_key = build_preview_image_mapping_cache_key(
                profile,
                dropbox_cfg,
                staged_folder_name,
            )
            mapping_cache = st.session_state.get("preview_image_mapping_cache", {})

            if mapping_cache.get("key") == mapping_cache_key:
                mapping_data = dict(mapping_cache.get("data", {}))
                full_color_image_map = dict(mapping_data.get("color_image_map", {}))
                full_design_color_image_url_map = {
                    color: dict(design_map)
                    for color, design_map in dict(mapping_data.get("design_color_image_url_map", {})).items()
                }
            else:
                mapping_variants = build_image_mapping_variants_for_cache(profile, selected_variants)
                mapping_colors = get_selected_colors_for_image_resolution(profile, mapping_variants)

                _, _, full_color_image_map, full_design_color_image_url_map = resolve_folder_image_urls(
                    profile,
                    mapping_variants,
                    mapping_colors,
                    dropbox_overview,
                    preview_stage_folder_path,
                )

                st.session_state["preview_image_mapping_cache"] = {
                    "key": mapping_cache_key,
                    "data": {
                        "color_image_map": dict(full_color_image_map),
                        "design_color_image_url_map": {
                            color: dict(design_map)
                            for color, design_map in dict(full_design_color_image_url_map).items()
                        },
                    },
                }

            preview_color_image_map, preview_design_color_image_url_map = filter_preview_image_maps_for_selected_variants(
                profile,
                selected_variants,
                full_color_image_map,
                full_design_color_image_url_map,
            )
            parent_main_image_options = build_parent_main_image_options(
                profile=profile,
                selected_variants=selected_variants,
                color_image_map=preview_color_image_map,
                design_color_image_url_map=preview_design_color_image_url_map,
            )
        except Exception:
            preview_color_image_map = {}
            preview_design_color_image_url_map = {}
            parent_main_image_options = []

    staged_preview_entries = resolve_display_entries([(Path(path).name, path) for path in staged_preview_paths])
    garment_resource_entries = resolve_display_entries([(Path(path).name, path) for path in dropbox_overview.get("garment_resource_images", [])])
    global_resource_entries = resolve_display_entries([(Path(path).name, path) for path in dropbox_overview.get("shared_resource_images", [])])

    stage_folder_path_for_preview = build_stage_folder_path(dropbox_cfg, staged_folder_name) if staged_folder_name else ""
    color_preview_source = get_selected_colors_for_image_resolution(profile, selected_variants) or get_profile_color_options(profile)
    staged_variant_entries = resolve_display_entries([
        (
            color,
            f"{stage_folder_path_for_preview}/{dropbox_overview.get('main_image_map', {}).get(color, '')}"
            if stage_folder_path_for_preview and dropbox_overview.get("main_image_map", {}).get(color, "")
            else "",
        )
        for color in color_preview_source
    ])
    design_color_preview_entries = resolve_display_entries([
        (f"{row['color']} / {row['design']}", row.get("path", ""))
        for row in design_color_preview_rows
    ])

    data = {
        "staged_preview_paths": staged_preview_paths,
        "staged_preview_entries": staged_preview_entries,
        "design_color_preview_rows": design_color_preview_rows,
        "design_color_preview_entries": design_color_preview_entries,
        "color_image_map": preview_color_image_map,
        "design_color_image_url_map": preview_design_color_image_url_map,
        "parent_main_image_options": parent_main_image_options,
        "garment_resource_entries": garment_resource_entries,
        "global_resource_entries": global_resource_entries,
        "staged_variant_entries": staged_variant_entries,
    }
    st.session_state["preview_image_cache"] = {"key": cache_key, "data": data}
    return data

def build_resolved_image_bundle_cache_key(
    profile: dict[str, Any],
    dropbox_cfg: dict[str, Any],
    staged_folder_name: str,
    selected_variants: dict[str, list[str]],
    selected_parent_main_image_url: str = "",
) -> str:
    template_key = profile.get("template_key", "")
    cache_parts = {
        "template_key": template_key,
        "staged_folder_name": staged_folder_name,
        "selected_colors": get_selected_colors_for_image_resolution(profile, selected_variants),
        "selected_designs": selected_variants.get("design", []),
        "selected_parent_main_image_url": selected_parent_main_image_url,
        "template_cfg": dropbox_cfg.get("templates", {}).get(template_key, {}),
        "general_resource_images": dropbox_cfg.get("general_resource_images", []),
        "resource_root": dropbox_cfg.get("resource_root", ""),
    }
    return json.dumps(cache_parts, sort_keys=True)


def get_cached_resolved_image_bundle(
    profile: dict[str, Any],
    dropbox_cfg: dict[str, Any],
    staged_folder_name: str,
    selected_variants: dict[str, list[str]],
    dropbox_overview: dict[str, Any],
    selected_parent_main_image_url: str = "",
) -> dict[str, Any]:
    if not staged_folder_name:
        return {
            "parent_main_image_url": "",
            "other_images": [],
            "color_image_map": {},
            "design_color_image_url_map": {},
        }

    cache_key = build_resolved_image_bundle_cache_key(
        profile,
        dropbox_cfg,
        staged_folder_name,
        selected_variants,
        selected_parent_main_image_url,
    )
    cache = st.session_state.get("resolved_image_bundle_cache", {})

    if cache.get("key") == cache_key:
        return cache.get("data", {})

    stage_folder_path = build_stage_folder_path(dropbox_cfg, staged_folder_name)
    parent_main_image_url, other_images, color_image_map, design_color_image_url_map = resolve_folder_image_urls(
        profile,
        selected_variants,
        get_selected_colors_for_image_resolution(profile, selected_variants),
        dropbox_overview,
        stage_folder_path,
        selected_parent_main_image_url=selected_parent_main_image_url,
    )

    data = {
        "parent_main_image_url": parent_main_image_url,
        "other_images": other_images,
        "color_image_map": color_image_map,
        "design_color_image_url_map": design_color_image_url_map,
    }
    st.session_state["resolved_image_bundle_cache"] = {
        "key": cache_key,
        "data": data,
    }
    return data


def resolve_folder_image_urls(
    profile: dict[str, Any],
    selected_variants: dict[str, list[str]],
    selected_colors: list[str],
    dropbox_overview: dict[str, Any],
    folder_path: str,
    selected_parent_main_image_url: str = "",
) -> tuple[str, list[str], dict[str, str], dict[str, dict[str, str]]]:
    main_image_map = dropbox_overview.get("main_image_map", {})
    design_color_image_map = dropbox_overview.get("design_color_image_map", {})
    garment_resource_images = dropbox_overview.get("garment_resource_images", [])
    shared_resource_images = dropbox_overview.get("shared_resource_images", [])
    variant_combos = build_variant_combinations(profile, selected_variants)

    color_image_map: dict[str, str] = {}
    for color in selected_colors:
        filename = main_image_map.get(color, "")
        if not filename:
            continue
        path = f"{folder_path}/{filename}"
        if not path_exists(path):
            raise ValueError(f"Missing staged mapped image for colour '{color}': {filename}")
        url = dropbox_preview_url(path)
        if url:
            color_image_map[color] = url

    design_color_image_url_map: dict[str, dict[str, str]] = {}
    for color in selected_colors:
        design_map = design_color_image_map.get(color, {})
        design_color_image_url_map[color] = {}
        for design, filename in design_map.items():
            if not filename:
                continue
            path = f"{folder_path}/{filename}"
            if not path_exists(path):
                continue
            url = dropbox_preview_url(path)
            if url:
                design_color_image_url_map[color][design] = url

    parent_main_image_url = ""
    missing_variant_labels: list[str] = []

    parent_main_options = build_parent_main_image_options(
        profile=profile,
        selected_variants=selected_variants,
        color_image_map=color_image_map,
        design_color_image_url_map=design_color_image_url_map,
    )

    for combo in variant_combos:
        image_url = resolve_child_variant_image_url(
            variant_values=combo,
            color_image_map=color_image_map,
            design_color_image_url_map=design_color_image_url_map,
        )
        if not image_url:
            label = " / ".join([v for v in combo.values() if v]) or "Unnamed variant"
            missing_variant_labels.append(label)

    if missing_variant_labels:
        raise ValueError(
            "Missing staged mapped image for variant(s): " + ", ".join(missing_variant_labels)
        )

    if selected_parent_main_image_url:
        parent_main_image_url = selected_parent_main_image_url
    elif parent_main_options:
        parent_main_image_url = parent_main_options[0][1]

    if not parent_main_image_url:
        raise ValueError("No staged mapped image exists for the selected variants.")

    garment_resource_urls: list[str] = []
    for path in garment_resource_images:
        try:
            url = dropbox_preview_url(path)
        except Exception:
            continue
        if url:
            garment_resource_urls.append(url)

    shared_resource_urls: list[str] = []
    for path in shared_resource_images:
        try:
            url = dropbox_preview_url(path)
        except Exception:
            continue
        if url:
            shared_resource_urls.append(url)

    other_images = list(dict.fromkeys(garment_resource_urls + shared_resource_urls))

    return (
        parent_main_image_url,
        other_images,
        color_image_map,
        design_color_image_url_map,
    )

def render_path_grid(
    title: str,
    entries: list[dict[str, Any]],
    cols_per_row: int = 5,
    image_width: int = 150,
) -> None:
    st.markdown(f"**{title}**")
    if not entries:
        st.caption("No files configured.")
        return

    cols = st.columns(cols_per_row)
    for idx, entry in enumerate(entries):
        with cols[idx % cols_per_row]:
            path = entry.get("path", "")
            st.caption(entry.get("label", Path(path).name if path else ""))
            if entry.get("exists") and entry.get("direct_url"):
                st.image(entry["direct_url"], width=image_width)
            else:
                st.warning("Not found")
                st.code(path, language=None)


def render_color_grid(
    entries: list[dict[str, Any]],
    cols_per_row: int = 5,
    image_width: int = 150,
) -> None:
    st.markdown("**Colour image mapping**")
    if not entries:
        st.caption("No colours configured.")
        return

    cols = st.columns(cols_per_row)
    for idx, entry in enumerate(entries):
        with cols[idx % cols_per_row]:
            label = entry.get("label", "")
            path = entry.get("path", "")
            st.caption(label)
            if not path:
                st.warning("Missing")
                continue

            if entry.get("exists") and entry.get("direct_url"):
                st.image(entry["direct_url"], width=image_width)
            else:
                st.warning("Not found")
                st.code(path, language=None)


def render_active_product_context(
    active_staged_folder_name: str,
    active_template_label: str,
    selected_parent_main_label: str,
    preview_parent_main_image_url: str,
    preview_color_image_map: dict[str, str],
    preview_design_color_image_url_map: dict[str, dict[str, str]],
    preview_other_images: list[str],
    image_mapping_status: str = "not_loaded",
    image_mapping_detail: str = "",
) -> None:
    st.subheader("Active product context")
    col1, col2 = st.columns(2)
    with col1:
        st.write(f"Staged folder: `{active_staged_folder_name or '-'}`")
        st.write(f"Template: `{active_template_label or '-'}`")
        st.write(f"Parent main image choice: `{selected_parent_main_label or 'Automatic (recommended)'}`")
    with col2:
        if image_mapping_status == "loaded":
            parent_status = "Resolved" if preview_parent_main_image_url else "Loaded but unresolved"
            support_count = len(preview_other_images)
            child_count = len(preview_color_image_map) + sum(
                len(design_map) for design_map in preview_design_color_image_url_map.values()
            )
            st.write("Image mappings: `Loaded`")
            st.write(f"Parent main image: `{parent_status}`")
            st.write(f"Child image mappings: `{child_count}`")
            st.write(f"Support images: `{support_count}`")
        elif image_mapping_status == "error":
            st.write("Image mappings: `Missing/errors`")
            st.caption(image_mapping_detail or "Image mappings could not be resolved.")
        else:
            st.write("Image mappings: `Not loaded yet`")
            st.caption(image_mapping_detail or "Load image mappings to resolve parent, child, and support image URLs.")


def trim_search_terms(value: str, max_bytes: int = 249) -> str:
    value = (value or "").strip()
    if not value:
        return ""

    # Split on commas first, since Amazon search terms are usually entered that way sasd
    terms = [term.strip() for term in value.split(",") if term.strip()]

    result_terms: list[str] = []
    current = ""

    for term in terms:
        candidate = term if not current else f"{current}, {term}"

        if len(candidate.encode("utf-8")) <= max_bytes:
            current = candidate
            result_terms.append(term)
        else:
            break

    return current.rstrip(" ,;")




def build_size_price_inputs(
    sizes: list[str],
    saved_prices: dict[str, float] | None = None,
) -> dict[str, float]:
    st.markdown("**Price by size**")
    if not sizes:
        st.caption("No sizes configured.")
        return {}

    saved_prices = saved_prices or {}

    default_same_price = False
    if sizes:
        existing_values = [saved_prices.get(size) for size in sizes if size in saved_prices]
        unique_existing_values = {v for v in existing_values if v is not None}
        if len(unique_existing_values) == 1 and len(existing_values) == len(sizes):
            default_same_price = True

    if "use_same_price_for_all_sizes" not in st.session_state:
        st.session_state["use_same_price_for_all_sizes"] = default_same_price

    use_same_price = st.checkbox(
        "Use one price for all sizes",
        key="use_same_price_for_all_sizes",
    )

    size_price_map: dict[str, float] = {}

    if use_same_price:
        fallback_price = 29.99
        if default_same_price and sizes:
            fallback_price = float(saved_prices.get(sizes[0], 29.99))

        if "shared_price_all_sizes" not in st.session_state:
            st.session_state["shared_price_all_sizes"] = float(fallback_price)

        shared_price = st.number_input(
            "Price for all sizes",
            min_value=0.0,
            step=0.50,
            key="shared_price_all_sizes",
        )

        for size in sizes:
            size_price_map[size] = shared_price

        return size_price_map

    cols_per_row = 4
    cols = st.columns(cols_per_row)

    for idx, size in enumerate(sizes):
        with cols[idx % cols_per_row]:
            if f"price_{size}" not in st.session_state:
                st.session_state[f"price_{size}"] = float(saved_prices.get(size, 29.99))

            size_price_map[size] = st.number_input(
                f"{size} price",
                min_value=0.0,
                step=0.50,
                key=f"price_{size}",
            )

    return size_price_map

def resolve_template_path(profile: dict[str, Any]) -> Path:
    family_folder = profile.get("_family_folder")
    profile_folder = profile.get("_folder")
    template_file = profile.get("template_file", "")

    if family_folder:
        return (Path(family_folder) / template_file).resolve()
    if profile_folder:
        return (Path(profile_folder) / template_file).resolve()
    return (BASE_DIR / "templates" / template_file).resolve()

def write_parent_row(ws, header_map: dict[str, int], data: dict[str, Any]) -> None:
    clear_row_values(ws, PARENT_ROW)
    other_images = padded_list(data.get("other_images", []), 14)

    variation_theme = data.get("variation_theme", "")
    product_category = data.get("product_category", "apparel")
    is_apparel = product_category == "apparel"
    has_size = "Size" in variation_theme

    values = {
        "item_sku": data["parent_sku"],
        "parent_sku": "",
        "item_name": data["title"],
        "brand_name": data["brand_name"],
        "manufacturer": data["manufacturer"],
        "product_description": data["product_description"],
        "generic_keywords": data["generic_keywords"],
        "bullet_point1": data["bullet_points"][0],
        "bullet_point2": data["bullet_points"][1],
        "bullet_point3": data["bullet_points"][2],
        "bullet_point4": data["bullet_points"][3],
        "bullet_point5": data["bullet_points"][4],
        "recommended_browse_nodes": data["recommended_browse_nodes"],

        "parent_child": "parent",
        "relationship_type": "",
        "variation_theme": variation_theme,

        "department_name": data["department_name"],
        "feed_product_type": data["feed_product_type"],
        "target_gender": data["target_gender"],
        "age_range_description": data["age_range_description"],

        "outer_material_type": data["material_type"],
        "material_type1": data["material_type"],
        "fabric_type": data["material_type"],

        "style_name": data["style_name"],
        "care_instructions": data["care_instructions"],
        "theme": data["theme"],

        "color_name": "",
        "size_name": "",

        "apparel_size_system": "UK" if has_size and is_apparel else "",
        "apparel_size_class": "Alpha" if has_size and is_apparel else "",
        "apparel_size": "One Size",
        "apparel_body_type": "Regular" if is_apparel else "",
        "apparel_height_type": "Regular" if is_apparel else "",

        "item_type_name": data["item_type_name"],
        "country_of_origin": data.get("country_of_origin", "United Kingdom"),
        "condition_type": data["condition_type"],

        "fulfillment_availability#1.fulfillment_channel_code": "",
        "fulfillment_availability#1.quantity": "",
        "fulfillment_availability#1.lead_time_to_ship_max_days": "",
        "purchasable_offer[marketplace_id=A1F83G8C2ARO7P]#1.our_price#1.schedule#1.value_with_tax": "",
        "list_price_with_tax": "",

        "main_image_url": data.get("parent_main_image_url", ""),

        "other_image_url1": other_images[0],
        "other_image_url2": other_images[1],
        "other_image_url3": other_images[2],
        "other_image_url4": other_images[3],
        "other_image_url5": other_images[4],
        "other_image_url6": other_images[5],
        "other_image_url7": other_images[6],
        "other_image_url8": other_images[7],

        "other_image_url_ps01": other_images[8],
        "other_image_url_ps02": other_images[9],
        "other_image_url_ps03": other_images[10],
        "other_image_url_ps04": other_images[11],
        "other_image_url_ps05": other_images[12],
        "other_image_url_ps06": other_images[13],
    }

    field_aliases = data.get("field_aliases", {})

    dynamic_profile_fields = data.get("dynamic_profile_fields", {})
    values.update(dynamic_profile_fields)

    extra_parent_fields = data.get("extra_parent_fields", {})
    values = prepare_row_values(values, field_aliases, extra_parent_fields)

    if "dangerous_goods_regulation" in header_map:
        values["dangerous_goods_regulation"] = "Not Applicable"

    if "search_terms" in header_map:
        values["search_terms"] = trim_search_terms(data["generic_keywords"])

    write_values_with_debug(ws, PARENT_ROW, header_map, values, "Parent row")

def write_child_rows(ws, header_map: dict[str, int], profile: dict[str, Any], data: dict[str, Any]) -> int:
    row_idx = FIRST_CHILD_ROW
    template_row = FIRST_CHILD_ROW
    variants_written = 0
    other_images = padded_list(data.get("other_images", []), 14)

    variation_theme = data.get("variation_theme", "")
    product_category = data.get("product_category", "apparel")
    is_apparel = product_category == "apparel"

    selected_variants = data.get("selected_variants", {})
    variant_combos = build_variant_combinations(profile, selected_variants)

    for variant_values in variant_combos:
        if row_idx != template_row and st.session_state.get("copy_row_styles", True):
            copy_row_format(ws, template_row, row_idx)
        clear_row_values(ws, row_idx)

        variant_field_values = build_variant_field_values(profile, variant_values)

        size_value = variant_values.get("size", "")
        normalized_size = normalize_size(size_value) if size_value else ""
        design_value = variant_values.get("design", "")
        color_value = variant_values.get("color", "")

        price_key = size_value if size_value else "default"
        price = data["size_price_map"].get(price_key, 0)

        image_url = resolve_child_variant_image_url(
            variant_values=variant_values,
            color_image_map=data.get("color_image_map", {}),
            design_color_image_url_map=data.get("design_color_image_url_map", {}),
        )

        values = {
            "item_sku": build_child_sku(profile, data["parent_sku"], variant_values),
            "parent_sku": data["parent_sku"],
            "item_name": data["title"],
            "brand_name": data["brand_name"],
            "manufacturer": data["manufacturer"],
            "product_description": data["product_description"],
            "generic_keywords": data["generic_keywords"],

            "bullet_point1": data["bullet_points"][0],
            "bullet_point2": data["bullet_points"][1],
            "bullet_point3": data["bullet_points"][2],
            "bullet_point4": data["bullet_points"][3],
            "bullet_point5": data["bullet_points"][4],

            "recommended_browse_nodes": data["recommended_browse_nodes"],
            "condition_type": data["condition_type"],

            "parent_child": "child",
            "relationship_type": "variation",
            "variation_theme": variation_theme,

            "color_name": color_value,
            "size_name": normalized_size,
            "apparel_size": normalized_size if is_apparel else "",

            "department_name": data["department_name"],
            "feed_product_type": data["feed_product_type"],
            "target_gender": data["target_gender"],
            "age_range_description": data["age_range_description"],

            "outer_material_type": data["material_type"],
            "material_type1": data["material_type"],
            "fabric_type": data["material_type"],

            "style_name": design_value or data["style_name"],
            "care_instructions": data["care_instructions"],
            "theme": data["theme"],

            "apparel_size_system": "UK" if normalized_size and is_apparel else "",
            "apparel_size_class": "Alpha" if normalized_size and is_apparel else "",
            "apparel_body_type": "Regular" if is_apparel else "",
            "apparel_height_type": "Regular" if is_apparel else "",

            "item_type_name": data["item_type_name"],
            "country_of_origin": data.get("country_of_origin", "United Kingdom"),

            "fulfillment_availability#1.fulfillment_channel_code": "DEFAULT",
            "fulfillment_availability#1.quantity": data["quantity"],
            "fulfillment_availability#1.lead_time_to_ship_max_days": 5,
            "purchasable_offer[marketplace_id=A1F83G8C2ARO7P]#1.our_price#1.schedule#1.value_with_tax": price,
            "list_price_with_tax": price,

            "main_image_url": image_url,

            "other_image_url1": other_images[0],
            "other_image_url2": other_images[1],
            "other_image_url3": other_images[2],
            "other_image_url4": other_images[3],
            "other_image_url5": other_images[4],
            "other_image_url6": other_images[5],
            "other_image_url7": other_images[6],
            "other_image_url8": other_images[7],

            "other_image_url_ps01": other_images[8],
            "other_image_url_ps02": other_images[9],
            "other_image_url_ps03": other_images[10],
            "other_image_url_ps04": other_images[11],
            "other_image_url_ps05": other_images[12],
            "other_image_url_ps06": other_images[13],
        }

        dynamic_profile_fields = data.get("dynamic_profile_fields", {})
        values.update(dynamic_profile_fields)

        values.update(variant_field_values)

        field_aliases = data.get("field_aliases", {})
        extra_child_fields = data.get("extra_child_fields", {})
        values = prepare_row_values(values, field_aliases, extra_child_fields)

        if st.session_state.get("show_header_debug", False) and row_idx == FIRST_CHILD_ROW:
            st.write("First child size values snapshot")
            st.json({
                "apparel_size_system": values.get("apparel_size_system"),
                "apparel_size_class": values.get("apparel_size_class"),
                "apparel_body_type": values.get("apparel_body_type"),
                "apparel_height_type": values.get("apparel_height_type"),
                "field_aliases": field_aliases,
            })

        if "dangerous_goods_regulation" in header_map:
            values["dangerous_goods_regulation"] = "Not Applicable"

        if "search_terms" in header_map:
            values["search_terms"] = trim_search_terms(data["generic_keywords"])

        label_bits = [v for v in [color_value, size_value, design_value] if v]
        row_label = " / ".join(label_bits) if label_bits else f"row {row_idx}"

        write_values_with_debug(
            ws,
            row_idx,
            header_map,
            values,
            f"Child row {row_idx} ({row_label})",
        )

        row_idx += 1
        variants_written += 1

    return variants_written

def get_extra_parent_fields(profile: dict[str, Any]) -> dict[str, Any]:
    return profile.get("extra_parent_fields", profile.get("extra_fields", {}))

def get_extra_child_fields(profile: dict[str, Any]) -> dict[str, Any]:
    return profile.get("extra_child_fields", profile.get("extra_fields", {}))

def get_field_aliases(profile: dict[str, Any]) -> dict[str, list[str]]:
    return profile.get("field_aliases", {})

def debug_find_headers(header_map: dict[str, int], patterns: list[str]) -> None:
    st.write("Header matches:")
    for pattern in patterns:
        matches = [key for key in header_map.keys() if pattern.lower() in key.lower()]
        st.write(f"{pattern}: {matches}")

def expand_field_aliases(values: dict[str, Any], field_aliases: dict[str, list[str]]) -> dict[str, Any]:
    expanded = dict(values)

    for source_field, aliases in field_aliases.items():
        if source_field in expanded:
            for alias in aliases:
                expanded[alias] = expanded[source_field]

    return expanded

def prepare_row_values(
    values: dict[str, Any],
    field_aliases: dict[str, list[str]],
    extra_fields: dict[str, Any],
) -> dict[str, Any]:
    values = expand_field_aliases(values, field_aliases)
    values.update(extra_fields)
    return values


def validate_profile_schema(profile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required_fields = get_required_profile_fields(profile)

    for field in required_fields:
        value = profile.get(field)
        if isinstance(value, str):
            if not value.strip():
                errors.append(f"Template config missing required field: {field}")
        elif value in (None, "", [], {}):
            errors.append(f"Template config missing required field: {field}")

    return errors

def get_schema(profile: dict[str, Any]) -> dict[str, Any]:
    return profile.get("_schema", {})

def get_allowed_dynamic_fields(profile: dict[str, Any]) -> list[str]:
    return get_schema(profile).get("allowed_dynamic_fields", [])

def get_required_profile_fields(profile: dict[str, Any]) -> list[str]:
    return get_schema(profile).get("required_profile_fields", [])

def get_required_workbook_headers(profile: dict[str, Any]) -> list[str]:
    return get_schema(profile).get("required_workbook_headers", [])

def validate_template_file(profile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    template_file = profile.get("template_file", "")

    if not template_file:
        return ["Template file is missing in config."]

    template_path = resolve_template_path(profile)

    if not template_path.exists():
        return [f"Template file not found: {template_path}"]

    try:
        wb = load_workbook(template_path, keep_vba=True, read_only=True)
    except Exception as exc:
        return [f"Template workbook could not be opened: {exc}"]

    try:
        if SHEET_NAME not in wb.sheetnames:
            return [f"Sheet '{SHEET_NAME}' not found in template workbook."]

        ws = wb[SHEET_NAME]
        header_map = build_header_map(ws, HEADER_ROW)

        required_headers = get_required_workbook_headers(profile) or [
            "item_sku",
            "item_name",
            "brand_name",
            "manufacturer",
            "product_description",
            "bullet_point1",
            "bullet_point2",
            "bullet_point3",
            "bullet_point4",
            "bullet_point5",
            "generic_keywords",
            "recommended_browse_nodes",
            "parent_child",
            "relationship_type",
            "variation_theme",
            "condition_type",
            "main_image_url",
        ]

        missing_headers = [header for header in required_headers if header not in header_map]
        if missing_headers:
            errors.append("Template is missing required headers: " + ", ".join(missing_headers))
    finally:
        wb.close()

    return errors


def build_workbook(profile: dict[str, Any], payload: dict[str, Any]) -> tuple[Path, dict[str, float]]:

    template_path = resolve_template_path(profile)

    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    t0 = time.perf_counter()
    wb = load_workbook(template_path, keep_vba=True)
    t1 = time.perf_counter()

    ws = wb[SHEET_NAME]
    header_map = build_header_map(ws, HEADER_ROW)


    dynamic_profile_fields = get_dynamic_profile_fields(profile, header_map)

    if st.session_state.get("show_header_debug", False):
        allowed_fields = set(get_allowed_dynamic_fields(profile))
        missing_dynamic_headers = [
            key for key in allowed_fields
            if profile.get(key) not in (None, "", [], {}) and key not in header_map
        ]
        if missing_dynamic_headers:
            st.write("Allowed dynamic fields missing from workbook headers")
            st.json(missing_dynamic_headers)

    payload = dict(payload)
    payload["dynamic_profile_fields"] = dynamic_profile_fields

    if st.session_state.get("show_header_debug", False):
        st.write("Dynamic profile fields matched to workbook headers")
        st.json(dynamic_profile_fields)

    debug_size_headers(header_map)

    if st.session_state.get("show_header_debug", False):
        debug_find_headers(
            header_map,
            [
                "body",
                "height",
                "fulfillment",
                "quantity",
                "lead_time",
                "ship",
                "price",
                "value_with_tax",
            ],
        )

    write_parent_row(ws, header_map, payload)
    t2 = time.perf_counter()

    variants_written = write_child_rows(ws, header_map, profile, payload)
    t3 = time.perf_counter()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_name = f"{payload['parent_sku']}_{profile['_slug']}_amazon_listing.xlsm"
    output_path = OUTPUT_DIR / output_name
    wb.save(output_path)
    wb.close()
    t4 = time.perf_counter()

    if variants_written == 0:
        raise ValueError("No child variants were generated.")

    timings = {
        "load_workbook": t1 - t0,
        "write_parent_row": t2 - t1,
        "write_child_rows": t3 - t2,
        "save_workbook": t4 - t3,
        "total_build": t4 - t0,
    }

    return output_path, timings


def validate_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    required_fields = [
        "parent_sku",
        "title",
        "brand_name",
        "manufacturer",
        "recommended_browse_nodes",
        "feed_product_type",
        "item_type_name",
        "material_type",
        "condition_type",
        "variation_theme",
        "product_category",
    ]

    for field in required_fields:
        value = payload.get(field, "")
        if isinstance(value, str):
            if not value.strip():
                errors.append(f"{field} is required.")
        elif value in (None, "", []):
            errors.append(f"{field} is required.")

    allowed_variation_themes = {"SizeColor","Colour & Style", ""}
    if payload.get("variation_theme", "") not in allowed_variation_themes:
        errors.append("variation_theme must be one of: SizeColor, Colour & Style, or empty.")

    allowed_product_categories = {"apparel", "accessory"}
    if payload.get("product_category", "") not in allowed_product_categories:
        errors.append("product_category must be either 'apparel' or 'accessory'.")

    return errors

def validate_variants(
    selected_variants: dict[str, list[str]],
    size_price_map: dict[str, float],
    quantity: int,
) -> list[str]:
    errors: list[str] = []

    for dim_name, values in selected_variants.items():
        if not values:
            errors.append(f"At least one option is required for {dim_name}.")

    if quantity < 0:
        errors.append("Quantity cannot be negative.")

    size_values = selected_variants.get("size", [])
    if size_values:
        for size in size_values:
            if size_price_map.get(size, 0) <= 0:
                errors.append(f"Invalid price for size {size}.")
    else:
        if not size_price_map:
            errors.append("At least one price is required.")
        elif all(price <= 0 for price in size_price_map.values()):
            errors.append("At least one valid price is required.")

    return errors

def validate_parent_child_structure(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    if not payload.get("parent_sku", "").strip():
        errors.append("parent_sku is required.")

    allowed_variation_themes = {"SizeColor","Colour & Style", ""}
    if payload.get("variation_theme", "") not in allowed_variation_themes:
        errors.append("variation_theme must be one of: SizeColor, Colour & Style, or empty.")

    allowed_product_categories = {"apparel", "accessory"}
    if payload.get("product_category", "") not in allowed_product_categories:
        errors.append("product_category must be either 'apparel' or 'accessory'.")

    return errors

def build_preflight_report(
    profile: dict[str, Any],
    dropbox_cfg: dict[str, Any],
    dropbox_overview: dict[str, Any],
    staged_folder_name: str,
    title: str,
    bullets: list[str],
    product_description: str,
    generic_keywords: str,
    selected_variants: dict[str, list[str]],
    size_price_map: dict[str, float],
    quantity: int,
    resolved_parent_main_image_url: str = "",
    resolved_other_images: list[str] | None = None,
    resolved_color_image_map: dict[str, str] | None = None,
    resolved_design_color_image_url_map: dict[str, dict[str, str]] | None = None,
    allow_image_resolution_fallback: bool = True,
) -> dict[str, Any]:
    preview_parent_sku = str(get_default(profile, "parent_sku", "")).strip()
    preview_selected_colors = get_selected_colors_for_image_resolution(profile, selected_variants)
    preview_selected_sizes = selected_variants.get("size", [])
    profile_schema_errors = validate_profile_schema(profile)


    preview_payload = {
        "parent_sku": preview_parent_sku,
        "title": title.strip(),
        "brand_name": GLOBAL_BRAND_NAME,
        "manufacturer": profile.get("manufacturer", ""),
        "recommended_browse_nodes": profile.get("recommended_browse_nodes", ""),
        "size_price_map": size_price_map,
        "quantity": quantity,
        "department_name": profile.get("department_name", ""),
        "target_gender": profile.get("target_gender", ""),
        "age_range_description": profile.get("age_range_description", ""),
        "feed_product_type": profile.get("feed_product_type", ""),
        "variation_theme": profile.get("variation_theme", "SizeColor"),
        "product_category": profile.get("product_category", "apparel"),
        "condition_type": profile.get("condition_type", "New"),
        "item_type_name": profile.get("item_type_name", ""),
        "country_of_origin": profile.get("country_of_origin", "United Kingdom"),
        "material_type": profile.get("material_type", ""),
        "style_name": profile.get("style_name", ""),
        "care_instructions": profile.get("care_instructions", ""),
        "theme": profile.get("theme", ""),
        "field_aliases": get_field_aliases(profile),
        "extra_parent_fields": get_extra_parent_fields(profile),
        "extra_child_fields": get_extra_child_fields(profile),
        "parent_main_image_url": "",
        "product_description": product_description.strip(),
        "generic_keywords": generic_keywords.strip(),
        "bullet_points": [bullet.strip() for bullet in bullets],
        "selected_variants": selected_variants,
        "colors": preview_selected_colors,
        "sizes": preview_selected_sizes,
        "other_images": list(resolved_other_images or []),
        "color_image_map": dict(resolved_color_image_map or {}),
        "design_color_image_url_map": dict(resolved_design_color_image_url_map or {}),
        "dynamic_profile_fields": {},
    }
    if resolved_parent_main_image_url:
        preview_payload["parent_main_image_url"] = resolved_parent_main_image_url

    if (
        allow_image_resolution_fallback
        and not resolved_parent_main_image_url
        and not resolved_other_images
        and not resolved_color_image_map
        and not resolved_design_color_image_url_map
        and staged_folder_name
        and preview_selected_colors
    ):
        try:
            stage_folder_path = build_stage_folder_path(dropbox_cfg, staged_folder_name)
            (
                preview_payload["parent_main_image_url"],
                preview_payload["other_images"],
                preview_payload["color_image_map"],
                preview_payload["design_color_image_url_map"],
            ) = resolve_folder_image_urls(
                profile,
                selected_variants,
                preview_selected_colors,
                dropbox_overview,
                stage_folder_path,
            )
        except Exception:
            pass

    try:
        template_path = resolve_template_path(profile)
        if template_path.exists():
            wb = load_workbook(template_path, keep_vba=True, read_only=True)
            try:
                if SHEET_NAME in wb.sheetnames:
                    ws = wb[SHEET_NAME]
                    header_map = build_header_map(ws, HEADER_ROW)
                    preview_payload["dynamic_profile_fields"] = get_dynamic_profile_fields(profile, header_map)
                else:
                    preview_payload["dynamic_profile_fields"] = {}
            finally:
                wb.close()
        else:
            preview_payload["dynamic_profile_fields"] = {}
    except Exception:
        preview_payload["dynamic_profile_fields"] = {}

    preview_payload_errors = validate_payload(preview_payload)
    preview_variant_errors = validate_variants(
        selected_variants,
        size_price_map,
        quantity,
    )
    preview_structure_errors = validate_parent_child_structure(preview_payload)

    template_errors = validate_template_file(profile)

    all_preview_errors = [
        *profile_schema_errors,
        *preview_payload_errors,
        *preview_variant_errors,
        *preview_structure_errors,
        *template_errors,
    ]

    quality_report = validate_listing_quality(profile, preview_payload)

    return {
        "preview_payload": preview_payload,
        "all_preview_errors": all_preview_errors,
        "quality_report": quality_report,
    }


def prepare_generation_payload(
    profile: dict[str, Any],
    title: str,
    bullets: list[str],
    product_description: str,
    generic_keywords: str,
    selected_variants: dict[str, list[str]],
    size_price_map: dict[str, float],
    quantity: int,
    staged_folder_name: str,
) -> dict[str, Any]:
    parent_sku = str(get_default(profile, "parent_sku", "")).strip()

    payload = {
        "parent_sku": parent_sku,
        "title": title.strip(),
        "brand_name": GLOBAL_BRAND_NAME,
        "manufacturer": profile.get("manufacturer", ""),
        "recommended_browse_nodes": profile.get("recommended_browse_nodes", ""),
        "size_price_map": size_price_map,
        "use_same_price_for_all_sizes": st.session_state.get("use_same_price_for_all_sizes", False),
        "quantity": quantity,
        "department_name": profile.get("department_name", ""),
        "target_gender": profile.get("target_gender", ""),
        "age_range_description": profile.get("age_range_description", ""),
        "feed_product_type": profile.get("feed_product_type", ""),
        "variation_theme": profile.get("variation_theme", "SizeColor"),
        "product_category": profile.get("product_category", "apparel"),
        "condition_type": profile.get("condition_type", "New"),
        "item_type_name": profile.get("item_type_name", ""),
        "country_of_origin": profile.get("country_of_origin", "United Kingdom"),
        "material_type": profile.get("material_type", ""),
        "style_name": profile.get("style_name", ""),
        "care_instructions": profile.get("care_instructions", ""),
        "theme": profile.get("theme", ""),
        "field_aliases": get_field_aliases(profile),
        "extra_parent_fields": get_extra_parent_fields(profile),
        "extra_child_fields": get_extra_child_fields(profile),
        "parent_main_image_url": "",
        "product_description": product_description.strip(),
        "generic_keywords": generic_keywords.strip(),
        "bullet_points": [bullet.strip() for bullet in bullets],
        "selected_variants": selected_variants,
        "colors": selected_variants.get("color", []),
        "sizes": selected_variants.get("size", []),
        "other_images": [],
        "color_image_map": {},
        "design_color_image_url_map": {},
        "dynamic_profile_fields": {},
    }

    errors: list[str] = []

    description_chars = len(payload["product_description"])
    if description_chars < 1000:
        errors.append("Description must be at least 1000 characters.")
    if description_chars > 2000:
        errors.append("Description must be under 2000 characters.")

    if not payload["title"]:
        errors.append("Title is required.")

    if any(not bullet for bullet in payload["bullet_points"]):
        errors.append("All five bullet points are required.")

    if not staged_folder_name:
        errors.append("Select a staged Dropbox folder.")

    if not parent_sku:
        errors.append("This template is missing parent_sku in its config.")

    errors.extend(validate_variant_dimensions(selected_variants))
    errors.extend(validate_payload(payload))
    errors.extend(validate_variants(selected_variants, size_price_map, quantity))
    errors.extend(validate_parent_child_structure(payload))
    errors.extend(validate_template_file(profile))

    quality_report = validate_listing_quality(profile, payload)

    return {
        "payload": payload,
        "errors": errors,
        "quality_report": quality_report,
    }


def get_dynamic_profile_fields(
    profile: dict[str, Any],
    header_map: dict[str, int],
) -> dict[str, Any]:
    allowed_fields = set(get_allowed_dynamic_fields(profile))
    dynamic: dict[str, Any] = {}

    for key in allowed_fields:
        if key not in header_map:
            continue

        value = profile.get(key)
        if isinstance(value, (list, dict)) or value in (None, ""):
            continue

        dynamic[key] = value

    return dynamic

def render_preflight_dashboard(
    quality_report: dict[str, Any],
    all_preview_errors: list[str],
) -> None:
    blockers = quality_report.get("blockers", [])
    warnings = quality_report.get("warnings", [])
    breakdown = quality_report.get("breakdown", {})
    search_terms_bytes = quality_report.get("search_terms_bytes", 0)

    template_ok = not any("Template" in err or "Sheet" in err for err in all_preview_errors)
    variants_ok = breakdown.get("variant_integrity", 0) > 0 and not any(
        "price" in err.lower() or "variant" in err.lower() or "parent_sku" in err.lower()
        for err in all_preview_errors + blockers
    )
    images_ok = breakdown.get("image_integrity", 0) > 0 and not any(
        "image" in err.lower() for err in blockers
    )

    copy_status = "Pass"
    if blockers:
        copy_status = "Fail"
    elif warnings:
        copy_status = "Warn"

    template_status = "Pass" if template_ok else "Fail"
    variants_status = "Pass" if variants_ok else "Fail"

    if any("image" in item.lower() for item in blockers):
        images_status = "Fail"
    elif any("image" in item.lower() for item in warnings):
        images_status = "Warn"
    else:
        images_status = "Pass"

    ready_to_generate = not all_preview_errors and not blockers

    st.subheader("Preflight dashboard")

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Template", template_status)
    col2.metric("Copy", copy_status)
    col3.metric("Variants", variants_status)
    col4.metric("Images", images_status)
    col5.metric("Search terms", f"{search_terms_bytes}/249")
    col6.metric("Ready", "Yes" if ready_to_generate else "No")

    top_fixes: list[str] = []
    top_fixes.extend(all_preview_errors[:3])
    top_fixes.extend(blockers[:3])

    for warning in warnings:
        if len(top_fixes) >= 6:
            break
        top_fixes.append(warning)

    if top_fixes:
        st.markdown("**Top fixes**")
        for item in top_fixes[:6]:
            st.write(f"- {item}")
    else:
        st.success("Everything looks ready.")

def render_listing_score_result(
    quality_report: dict[str, Any],
    all_preview_errors: list[str],
) -> None:
    st.subheader("Listing score result")
    st.metric("Internal quality score", f"{quality_report['score']}/100")

    with st.expander("Quality details", expanded=True):
        st.write("Breakdown:")
        st.json(quality_report["breakdown"])

        st.write("Copy metrics:")
        st.write(f"- Title characters: {quality_report.get('title_chars', 0)}")
        st.write(f"- Description characters: {quality_report.get('description_chars', 0)}")
        st.write(f"- Search terms bytes: {quality_report.get('search_terms_bytes', 0)}/249")

        bullet_char_counts = quality_report.get("bullet_char_counts", [])
        if bullet_char_counts:
            st.write("- Bullet character counts:")
            for idx, count in enumerate(bullet_char_counts, start=1):
                st.write(f"  - Bullet {idx}: {count}")

        if all_preview_errors:
            st.error("Validation errors:")
            for item in all_preview_errors:
                st.write(f"- {item}")

        if quality_report["blockers"]:
            st.error("Quality blockers:")
            for item in quality_report["blockers"]:
                st.write(f"- {item}")
        else:
            st.success("No quality blockers found.")

        if quality_report["warnings"]:
            st.warning("Warnings:")
            for item in quality_report["warnings"]:
                st.write(f"- {item}")
        else:
            st.info("No warnings.")


def find_template_matches_for_staged_folder(
    staged_folder_name: str,
    profiles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    folder_name = (staged_folder_name or "").strip()
    if not folder_name:
        return []

    folder_upper = folder_name.upper()

    def bounded_match(code: str) -> bool:
        code = (code or "").strip().upper()
        if not code:
            return False
        pattern = rf"(?<![A-Z0-9]){re.escape(code)}(?![A-Z0-9])"
        return bool(re.search(pattern, folder_upper))

    matches: list[tuple[int, dict[str, Any]]] = []
    seen_slugs: set[str] = set()

    for profile in profiles:
        template_key = str(profile.get("template_key", "")).strip()
        parent_sku = str(profile.get("parent_sku", "")).strip()

        score = 0
        if bounded_match(template_key):
            score = 2
        elif bounded_match(parent_sku):
            score = 1

        if score <= 0:
            continue

        slug = profile.get("_slug", "")
        if slug in seen_slugs:
            continue

        seen_slugs.add(slug)
        matches.append((score, profile))

    matches.sort(key=lambda item: (-item[0], item[1].get("_family_slug", ""), item[1].get("label", item[1].get("_slug", ""))))
    return [profile for _, profile in matches]


def scan_staged_folder_readiness(
    staged_folder_name: str,
    profiles: list[dict[str, Any]],
    dropbox_cfg: dict[str, Any],
) -> dict[str, Any]:
    matches = find_template_matches_for_staged_folder(staged_folder_name, profiles)

    result = {
        "folder_name": staged_folder_name,
        "detected_template": "",
        "detection_status": "",
        "staged_image_readiness": "",
        "garment_support_readiness": "",
        "overall_status": "",
        "reason": "",
    }

    if not matches:
        result.update({
            "detection_status": "No match",
            "staged_image_readiness": "Unknown",
            "garment_support_readiness": "Unknown",
            "overall_status": "Blocked",
            "reason": "No template match found from the staged folder name.",
        })
        return result

    if len(matches) > 1:
        match_labels = ", ".join(match.get("label", match.get("_slug", "")) for match in matches)
        result.update({
            "detected_template": match_labels,
            "detection_status": "Ambiguous",
            "staged_image_readiness": "Unknown",
            "garment_support_readiness": "Unknown",
            "overall_status": "Blocked",
            "reason": "Multiple template matches found; confirm the template manually.",
        })
        return result

    profile = matches[0]
    result["detected_template"] = profile.get("label", profile.get("_slug", ""))
    result["detection_status"] = "Single match"

    stage_folder_path = build_stage_folder_path(dropbox_cfg, staged_folder_name)
    dropbox_overview = build_dropbox_overview(profile, dropbox_cfg)
    main_image_map = dropbox_overview.get("main_image_map", {})

    missing_files: list[str] = []
    for filename in main_image_map.values():
        if not filename:
            continue
        staged_path = f"{stage_folder_path}/{filename}"
        if not path_exists(staged_path):
            missing_files.append(filename)

    if missing_files:
        result.update({
            "staged_image_readiness": "Missing required mapped images",
            "garment_support_readiness": "Present" if dropbox_overview.get("garment_resource_images") else "Missing or unavailable",
            "overall_status": "Blocked",
            "reason": f"Missing staged mapped images: {', '.join(missing_files[:3])}" + ("..." if len(missing_files) > 3 else ""),
        })
        return result

    garment_support_images = dropbox_overview.get("garment_resource_images", [])
    garment_warning = dropbox_overview.get("garment_resource_warning", "")

    if garment_support_images:
        result.update({
            "staged_image_readiness": "Ready",
            "garment_support_readiness": "Ready",
            "overall_status": "Ready",
            "reason": "Template detected and required staged/support images are present.",
        })
        return result

    result.update({
        "staged_image_readiness": "Ready",
        "garment_support_readiness": "Missing or unavailable",
        "overall_status": "Warning",
        "reason": garment_warning or "Required staged mapped images exist, but garment support images are missing.",
    })
    return result


def find_profile_for_listing_memory(
    profiles: list[dict[str, Any]],
    listing_memory: dict[str, Any],
) -> dict[str, Any] | None:
    template_key = str(listing_memory.get("template_key", "")).strip()
    if template_key:
        for profile in profiles:
            if str(profile.get("template_key", "")).strip() == template_key:
                return profile

    template_slug = str(listing_memory.get("template_slug", "")).strip()
    if template_slug:
        for profile in profiles:
            if str(profile.get("_slug", "")).strip() == template_slug:
                return profile

    return None


def build_variants_summary(selected_variants: dict[str, list[str]]) -> str:
    parts = [
        f"{dim_name}: {len(values)}"
        for dim_name, values in selected_variants.items()
        if values
    ]
    return ", ".join(parts) if parts else "No variants"


def build_price_summary(size_price_map: dict[str, float]) -> str:
    if not size_price_map:
        return "No pricing"

    prices = [float(price) for price in size_price_map.values()]
    if not prices:
        return "No pricing"

    if len(set(prices)) == 1:
        return f"{len(prices)} variant(s) at {prices[0]:.2f}"

    return f"{len(prices)} variant(s) from {min(prices):.2f} to {max(prices):.2f}"


def build_ready_review_data(
    profile: dict[str, Any] | None,
    listing_memory: dict[str, Any],
    ready_folder_name: str,
    dropbox_cfg: dict[str, Any],
    source_folder_path: str | None = None,
    include_images: bool = False,
    include_quality: bool = False,
) -> dict[str, Any]:
    review_data = {
        "folder_name": ready_folder_name,
        "template": listing_memory.get("template_label", "") or listing_memory.get("template_slug", "") or "Unknown",
        "assets_prepared_by": listing_memory.get("assets_prepared_by", ""),
        "content_prepared_by": listing_memory.get("content_prepared_by", ""),
        "reviewed_by": listing_memory.get("reviewed_by", ""),
        "prepared_at": listing_memory.get("prepared_at", ""),
        "reviewed_at": listing_memory.get("reviewed_at", ""),
        "title": listing_memory.get("title", ""),
        "bullet_points": (list(listing_memory.get("bullet_points", [])) + ["", "", "", "", ""])[:5],
        "product_description": listing_memory.get("product_description", ""),
        "generic_keywords": listing_memory.get("generic_keywords", ""),
        "variants_summary": build_variants_summary(dict(listing_memory.get("selected_variants", {}))),
        "quantity": int(listing_memory.get("quantity", 0) or 0),
        "price_summary": build_price_summary(dict(listing_memory.get("size_price_map", {}))),
        "parent_main_image_url": "",
        "support_images": [],
        "child_image_rows": [],
        "quality_report": {"blockers": [], "warnings": [], "score": 0, "breakdown": {}},
        "errors": [],
        "image_review_loaded": include_images or include_quality,
        "quality_check_loaded": include_quality,
    }

    if not profile:
        review_data["errors"].append("Template profile could not be resolved for this ready listing.")
        return review_data

    review_data["template"] = profile.get("label", profile.get("_slug", review_data["template"]))

    bullets = review_data["bullet_points"]
    selected_variants = dict(listing_memory.get("selected_variants", {}))
    size_price_map = {
        str(size): float(price)
        for size, price in dict(listing_memory.get("size_price_map", {})).items()
    }

    generation_prep = prepare_generation_payload(
        profile=profile,
        title=str(listing_memory.get("title", "")),
        bullets=bullets,
        product_description=str(listing_memory.get("product_description", "")),
        generic_keywords=str(listing_memory.get("generic_keywords", "")),
        selected_variants=selected_variants,
        size_price_map=size_price_map,
        quantity=review_data["quantity"],
        staged_folder_name=ready_folder_name,
    )

    review_data["errors"].extend(generation_prep["errors"])
    payload = dict(generation_prep["payload"])

    if not (include_images or include_quality):
        return review_data

    dropbox_overview = get_cached_dropbox_overview(profile, dropbox_cfg)
    ready_folder_path = source_folder_path or build_ready_folder_path(dropbox_cfg, ready_folder_name)
    selected_colors = payload.get("colors", [])

    try:
        (
            payload["parent_main_image_url"],
            payload["other_images"],
            payload["color_image_map"],
            payload["design_color_image_url_map"],
        ) = resolve_folder_image_urls(
            profile,
            selected_variants,
            selected_colors,
            dropbox_overview,
            ready_folder_path,
        )
    except Exception as exc:
        review_data["errors"].append(str(exc))

    review_data["parent_main_image_url"] = payload.get("parent_main_image_url", "")
    review_data["support_images"] = [
        {
            "label": f"{idx}. {Path(image_url).name}",
            "filename": Path(image_url).name,
            "url": image_url,
        }
        for idx, image_url in enumerate(payload.get("other_images", []), start=1)
        if image_url
    ]

    child_image_rows: list[dict[str, str]] = []
    color_image_map = payload.get("color_image_map", {}) or {}
    design_color_image_url_map = payload.get("design_color_image_url_map", {}) or {}

    for color, image_url in color_image_map.items():
        child_image_rows.append({
            "variant": color,
            "filename": Path(image_url).name if image_url else "",
            "url": image_url,
        })

    for color, design_map in design_color_image_url_map.items():
        for design, image_url in design_map.items():
            child_image_rows.append({
                "variant": f"{color} / {design}",
                "filename": Path(image_url).name if image_url else "",
                "url": image_url,
            })

    review_data["child_image_rows"] = child_image_rows

    if include_quality:
        review_data["quality_report"] = validate_listing_quality(profile, payload)

    return review_data


def render_ready_review_panel(
    item: dict[str, Any],
    dropbox_cfg: dict[str, Any],
    key_prefix: str = "ready_review",
    source_folder_path: str | None = None,
) -> None:
    folder_key = str(item.get("folder_name", "listing")).replace("/", "_").replace("\\", "_").replace(" ", "_")
    review_key_prefix = f"{key_prefix}_{folder_key}"
    image_review_loaded = bool(st.session_state.get(f"{review_key_prefix}_load_image_review", False))
    quality_check_loaded = bool(st.session_state.get(f"{review_key_prefix}_run_full_quality", False))

    review_data = build_ready_review_data(
        profile=item.get("profile"),
        listing_memory=item.get("listing_memory", {}),
        ready_folder_name=item.get("folder_name", ""),
        dropbox_cfg=dropbox_cfg,
        source_folder_path=source_folder_path,
        include_images=image_review_loaded or quality_check_loaded,
        include_quality=quality_check_loaded,
    )

    overview_tab, content_tab, images_tab, quality_tab = st.tabs(
        ["Overview", "Content", "Images", "Quality"]
    )

    with overview_tab:
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"Folder: `{review_data['folder_name']}`")
            st.write(f"Template: `{review_data['template']}`")
            st.write(f"Assets prepared by: `{review_data['assets_prepared_by'] or '-'}`")
            st.write(f"Content prepared by: `{review_data['content_prepared_by'] or '-'}`")
            st.write(f"Reviewed by: `{review_data['reviewed_by'] or '-'}`")
        with col2:
            st.write(f"Prepared at: `{review_data['prepared_at'] or '-'}`")
            st.write(f"Reviewed at: `{review_data['reviewed_at'] or '-'}`")
            st.write(f"Variants: {review_data['variants_summary']}")
            st.write(f"Quantity: {review_data['quantity']}")
            st.write(f"Pricing: {review_data['price_summary']}")

    with content_tab:
        st.markdown("**Title**")
        st.write(review_data["title"] or "-")
        st.markdown("**Bullets**")
        for bullet in review_data["bullet_points"]:
            st.write(f"- {bullet}" if bullet else "-")
        st.markdown("**Description**")
        st.text_area("Description preview", value=review_data["product_description"], height=180, disabled=True)
        st.markdown("**Keywords**")
        st.text_area("Keywords preview", value=review_data["generic_keywords"], height=100, disabled=True)

    with images_tab:
        dropbox_overview = get_cached_dropbox_overview(item.get("profile", {}), dropbox_cfg)
        render_dropbox_folder_links(source_folder_path, dropbox_overview)

        if not review_data["image_review_loaded"]:
            st.info("Image mappings are not loaded for this review yet. Use the Dropbox folder links above for normal review.")
            if st.button("Load image review", key=f"{review_key_prefix}_load_image_review_btn", width="content"):
                st.session_state["active_perf_action_label"] = "load image review"
                st.session_state[f"{review_key_prefix}_load_image_review"] = True
                st.rerun()
        else:
            support_images = review_data.get("support_images", [])
            child_image_rows = review_data.get("child_image_rows", [])

            st.success("Image review data loaded.")

            st.markdown("**Parent main image**")
            if review_data["parent_main_image_url"]:
                st.image(review_data["parent_main_image_url"], width=240)
                st.caption(Path(review_data["parent_main_image_url"]).name)
            else:
                st.caption("No resolved parent main image.")

            st.markdown("**Support image order**")
            if support_images:
                cols = st.columns(min(4, len(support_images)))
                for idx, image_entry in enumerate(support_images):
                    with cols[idx % len(cols)]:
                        st.image(image_entry["url"], width=170)
                        st.caption(image_entry["label"])
            else:
                st.caption("No support images found.")

            st.markdown("**Child variant image mapping**")
            if child_image_rows:
                cols_per_row = 3
                cols = st.columns(cols_per_row)
                for idx, image_entry in enumerate(child_image_rows):
                    with cols[idx % cols_per_row]:
                        st.markdown(f"**{image_entry['variant']}**")
                        if image_entry.get("url"):
                            st.image(image_entry["url"], width=180)
                            st.caption(image_entry.get("filename", ""))
                        else:
                            st.caption("No resolved image URL.")
            else:
                st.caption("No child image mappings found.")

            with st.expander("Technical image URLs and filenames", expanded=False):
                st.markdown("**Parent main image URL**")
                if review_data["parent_main_image_url"]:
                    st.code(review_data["parent_main_image_url"], language=None)
                else:
                    st.caption("No resolved parent main image.")

                st.markdown("**Support image order**")
                if support_images:
                    for image_entry in support_images:
                        st.write(image_entry["label"])
                        st.code(image_entry["url"], language=None)
                else:
                    st.caption("No support images found.")

                st.markdown("**Child variant image mapping**")
                if child_image_rows:
                    st.dataframe(child_image_rows, width="stretch", hide_index=True)
                else:
                    st.caption("No child image mappings found.")

    with quality_tab:
        if not review_data["quality_check_loaded"]:
            st.info("Full image quality check has not been run yet.")
            if st.button("Run full image quality check", key=f"{review_key_prefix}_run_full_quality_btn", width="content"):
                st.session_state[f"{review_key_prefix}_run_full_quality"] = True
                st.rerun()
        else:
            if review_data["errors"]:
                st.error("Preflight issues found")
                for error in review_data["errors"]:
                    st.write(f"- {error}")
            else:
                st.success("No preflight issues found.")

            blockers = review_data["quality_report"].get("blockers", [])
            warnings = review_data["quality_report"].get("warnings", [])

            st.markdown("**Quality blockers**")
            if blockers:
                for blocker in blockers:
                    st.write(f"- {blocker}")
            else:
                st.write("None")

            st.markdown("**Quality warnings**")
            if warnings:
                for warning in warnings:
                    st.write(f"- {warning}")
            else:
                st.write("None")


def build_queue_items(
    folder_names: list[str],
    profiles: list[dict[str, Any]],
    dropbox_cfg: dict[str, Any],
    folder_path_builder: Callable[[dict[str, Any], str], str],
    ready_label: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    for folder_name in folder_names:
        folder_path = folder_path_builder(dropbox_cfg, folder_name)
        load_error = ""
        listing_memory: dict[str, Any] = {}

        try:
            listing_memory = load_listing_memory_from_dropbox(folder_path)
        except Exception as exc:
            load_error = str(exc)

        profile = find_profile_for_listing_memory(profiles, listing_memory) if listing_memory else None
        template_label = (
            profile.get("label", profile.get("_slug", ""))
            if profile else
            listing_memory.get("template_label", "") or listing_memory.get("template_slug", "") or "Unknown"
        )
        selected_variants = listing_memory.get("selected_variants", {}) if listing_memory else {}

        items.append({
            "folder_name": folder_name,
            "template": template_label,
            "title": listing_memory.get("title", "") if listing_memory else "",
            "variants_summary": build_variants_summary(selected_variants),
            "load_status": ready_label if listing_memory and not load_error else "Missing or invalid inputs",
            "profile": profile,
            "listing_memory": listing_memory,
            "load_error": load_error,
        })

    return items


def build_ready_queue_items(
    ready_folder_names: list[str],
    profiles: list[dict[str, Any]],
    dropbox_cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    return build_queue_items(
        ready_folder_names,
        profiles,
        dropbox_cfg,
        build_ready_folder_path,
        "Ready for approval",
    )


def build_approved_queue_items(
    approved_folder_names: list[str],
    profiles: list[dict[str, Any]],
    dropbox_cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    return build_queue_items(
        approved_folder_names,
        profiles,
        dropbox_cfg,
        build_approved_folder_path,
        "Approved",
    )


def generate_approved_listing(
    profile: dict[str, Any],
    listing_memory: dict[str, Any],
    approved_folder_name: str,
    dropbox_cfg: dict[str, Any],
) -> dict[str, Any]:
    if not profile:
        raise ValueError("Could not find a template profile for this approved listing.")

    title = str(listing_memory.get("title", ""))
    bullets = list(listing_memory.get("bullet_points", []))
    bullets = (bullets + ["", "", "", "", ""])[:5]
    product_description = str(listing_memory.get("product_description", ""))
    generic_keywords = str(listing_memory.get("generic_keywords", ""))
    selected_variants = dict(listing_memory.get("selected_variants", {}))
    size_price_map = {
        str(size): float(price)
        for size, price in dict(listing_memory.get("size_price_map", {})).items()
    }
    quantity = int(listing_memory.get("quantity", 0))

    generation_prep = prepare_generation_payload(
        profile=profile,
        title=title,
        bullets=bullets,
        product_description=product_description,
        generic_keywords=generic_keywords,
        selected_variants=selected_variants,
        size_price_map=size_price_map,
        quantity=quantity,
        staged_folder_name=approved_folder_name,
    )
    generation_payload = generation_prep["payload"]
    original_finished_folder_name = str(listing_memory.get("original_finished_folder_name", "")).strip()
    if original_finished_folder_name:
        generation_payload["original_finished_folder_name"] = original_finished_folder_name
    generation_payload["assets_prepared_by"] = listing_memory.get("assets_prepared_by", "")
    generation_payload["content_prepared_by"] = listing_memory.get("content_prepared_by", "")
    generation_payload["reviewed_by"] = listing_memory.get("reviewed_by", "")
    generation_payload["prepared_at"] = listing_memory.get("prepared_at", "")
    generation_payload["reviewed_at"] = listing_memory.get("reviewed_at", "") or format_workflow_timestamp()
    generation_errors = generation_prep["errors"]
    if generation_errors:
        raise ValueError("; ".join(generation_errors))

    dropbox_overview = get_cached_dropbox_overview(profile, dropbox_cfg)
    approved_folder_path = build_approved_folder_path(dropbox_cfg, approved_folder_name)
    selected_colors = generation_payload["colors"]

    generation_timings: dict[str, float] = {}

    step_started_at = time.perf_counter()
    template_path = resolve_template_path(profile)
    wb = load_workbook(template_path, keep_vba=True, read_only=True)
    wb.close()
    generation_timings["template_check"] = round(time.perf_counter() - step_started_at, 4)

    step_started_at = time.perf_counter()
    resolve_folder_image_urls(
        profile,
        selected_variants,
        selected_colors,
        dropbox_overview,
        approved_folder_path,
    )
    generation_timings["pre_move_image_check"] = round(time.perf_counter() - step_started_at, 4)

    finished_folder_path = ""

    try:
        step_started_at = time.perf_counter()
        final_sku, finished_folder_path = finalize_approved_dropbox_folder(
            dropbox_cfg=dropbox_cfg,
            approved_folder_name=approved_folder_name,
            parent_sku=generation_payload["parent_sku"],
            reuse_finished_folder_name=original_finished_folder_name,
        )
        generation_timings["move_approved_to_finished"] = round(time.perf_counter() - step_started_at, 4)

        step_started_at = time.perf_counter()
        parent_main_image_url, other_images, color_image_map, design_color_image_url_map = resolve_folder_image_urls(
            profile,
            selected_variants,
            selected_colors,
            dropbox_overview,
            finished_folder_path,
        )
        generation_timings["final_image_resolve"] = round(time.perf_counter() - step_started_at, 4)

        payload = dict(generation_payload)
        payload["parent_sku"] = final_sku
        payload["parent_main_image_url"] = parent_main_image_url
        payload["other_images"] = other_images
        payload["color_image_map"] = color_image_map
        payload["design_color_image_url_map"] = design_color_image_url_map

        step_started_at = time.perf_counter()
        output_path, workbook_timings = build_workbook(profile, payload)
        generation_timings["build_workbook_total"] = round(time.perf_counter() - step_started_at, 4)
        for workbook_step, workbook_seconds in workbook_timings.items():
            generation_timings[f"workbook_{workbook_step}"] = round(float(workbook_seconds), 4)

        step_started_at = time.perf_counter()
        save_listing_inputs_json_to_dropbox(profile=profile, payload=payload, folder_path=finished_folder_path)
        generation_timings["save_finished_listing_inputs"] = round(time.perf_counter() - step_started_at, 4)

        return {
            "folder_name": approved_folder_name,
            "status": "Success",
            "message": f"Generated {output_path.name}",
            "output_path": str(output_path),
            "output_name": output_path.name,
            "finished_folder_path": finished_folder_path,
            "timings": generation_timings,
        }
    except Exception:
        if finished_folder_path and path_exists(finished_folder_path):
            try:
                move_dropbox_folder(finished_folder_path, approved_folder_path)
            except Exception:
                pass
        raise


def render_generation_results(results: list[dict[str, Any]], download_key_prefix: str) -> None:
    if not results:
        return

    summary_rows = [
        {
            "folder_name": result.get("folder_name", ""),
            "status": result.get("status", ""),
            "message": result.get("message", ""),
        }
        for result in results
    ]
    st.dataframe(summary_rows, width="stretch", hide_index=True)

    success_results = [
        result for result in results
        if result.get("status") == "Success" and result.get("output_path")
    ]
    if not success_results:
        return

    st.markdown("**Downloads**")
    for result in success_results:
        output_path = Path(result["output_path"])
        if not output_path.exists():
            st.warning(f"Workbook not found for {result.get('folder_name', '')}: {output_path.name}")
            continue

        with output_path.open("rb") as f:
            st.download_button(
                label=f"Download {result.get('output_name', output_path.name)}",
                data=f.read(),
                file_name=result.get("output_name", output_path.name),
                mime="application/vnd.ms-excel.sheet.macroEnabled.12",
                key=f"{download_key_prefix}_{result.get('folder_name', '')}_{result.get('output_name', output_path.name)}",
            )


def render_review_queue_view(
    ready_folder_names: list[str],
    profiles: list[dict[str, Any]],
    dropbox_cfg: dict[str, Any],
) -> None:
    st.subheader("Review queue")

    queue_items = build_ready_queue_items(ready_folder_names, profiles, dropbox_cfg)
    summary_rows = [
        {
            "folder_name": item["folder_name"],
            "template": item["template"],
            "title": item["title"],
            "variants_summary": item["variants_summary"],
            "load_status": item["load_status"],
        }
        for item in queue_items
    ]

    if summary_rows:
        st.dataframe(summary_rows, width="stretch", hide_index=True)
    else:
        st.info("No listings are currently waiting for review.")
        return

    ready_lookup = {item["folder_name"]: item for item in queue_items}
    review_folder_options = [item["folder_name"] for item in queue_items if item["listing_memory"]]

    st.markdown("### Review ready listing")
    with st.container(border=True):
        if not review_folder_options:
            st.caption("No reviewable ready listings found.")
            return

        current_review_folder = st.session_state.get("ready_queue_review_folder", review_folder_options[0])
        if current_review_folder not in review_folder_options:
            current_review_folder = review_folder_options[0]
            st.session_state["ready_queue_review_folder"] = current_review_folder

        selected_review_folder = st.selectbox(
            "Review ready listing",
            review_folder_options,
            key="ready_queue_review_folder",
        )
        review_item = ready_lookup.get(selected_review_folder)
        if review_item:
            review_panel_key_suffix = selected_review_folder.replace("/", "_").replace("\\", "_").replace(" ", "_")
            review_panel_open_key = f"review_queue_panel_open_{review_panel_key_suffix}"

            panel_col1, panel_col2 = st.columns([1, 3])
            with panel_col1:
                if st.button("Open review panel", key=f"{review_panel_open_key}_open_btn", width="stretch"):
                    st.session_state["active_perf_action_label"] = "open ready review panel"
                    st.session_state[review_panel_open_key] = True
            with panel_col2:
                if st.session_state.get(review_panel_open_key, False):
                    if st.button("Hide review panel", key=f"{review_panel_open_key}_hide_btn"):
                        st.session_state["active_perf_action_label"] = "hide ready review panel"
                        st.session_state[review_panel_open_key] = False
                else:
                    st.info("Review panel is not loaded yet. Open it only when you need detailed content/image/quality review.")

            if st.session_state.get(review_panel_open_key, False):
                with st.expander("Review panel", expanded=True):
                    render_ready_review_panel(
                        review_item,
                        dropbox_cfg,
                        key_prefix="review_queue",
                        source_folder_path=build_ready_folder_path(dropbox_cfg, review_item["folder_name"]),
                    )

            default_reviewer = review_item.get("listing_memory", {}).get("reviewed_by", "")
            review_reviewer_key = st.session_state.get("review_queue_review_folder_reviewer_key", "")
            reviewer_context_key = f"{selected_review_folder}|{default_reviewer}"
            if review_reviewer_key != reviewer_context_key:
                st.session_state["review_queue_reviewed_by"] = default_reviewer if default_reviewer in WORKFLOW_ASSIGNEES else ""
                st.session_state["review_queue_review_folder_reviewer_key"] = reviewer_context_key

            with st.form("review_queue_decision_form"):
                st.selectbox(
                    "Reviewed by",
                    WORKFLOW_ASSIGNEES,
                    key="review_queue_reviewed_by",
                )
                action_col1, action_col2 = st.columns(2)
                with action_col1:
                    approve_clicked = st.form_submit_button(
                        "Approve for generation",
                        width="stretch",
                    )
                with action_col2:
                    deny_clicked = st.form_submit_button(
                        "Deny and return to staging",
                        width="stretch",
                    )

            if approve_clicked or deny_clicked:
                st.session_state["pending_perf_action_label"] = (
                    "approve ready listing" if approve_clicked else "deny ready listing"
                )
                reviewed_by = st.session_state.get("review_queue_reviewed_by", "")
                if not reviewed_by:
                    st.warning("Select who reviewed this listing before approving or denying it.")
                    return
                if not review_item.get("profile") or not review_item.get("listing_memory"):
                    st.error("This ready listing could not be loaded for review.")
                    return

                ready_folder_path = build_ready_folder_path(dropbox_cfg, selected_review_folder)
                payload = dict(review_item["listing_memory"])
                payload["reviewed_by"] = reviewed_by
                payload["reviewed_at"] = format_workflow_timestamp()

                try:
                    save_listing_inputs_json_to_dropbox(
                        profile=review_item["profile"],
                        payload=payload,
                        folder_path=ready_folder_path,
                    )
                    if approve_clicked:
                        approved_folder_path = move_ready_dropbox_folder_to_approved(
                            dropbox_cfg=dropbox_cfg,
                            ready_folder_name=selected_review_folder,
                            approved_folder_name=selected_review_folder,
                        )
                        st.session_state["last_approved_folder_path"] = approved_folder_path
                        clear_runtime_caches()
                        set_workflow_flash(
                            "success",
                            f"Approved successfully: {Path(approved_folder_path).name}",
                        )
                    else:
                        denied_stage_folder_path = move_ready_dropbox_folder_to_denied_stage(
                            dropbox_cfg=dropbox_cfg,
                            ready_folder_name=selected_review_folder,
                        )
                        st.session_state["pending_staged_folder_selection_on_rerun"] = Path(denied_stage_folder_path).name
                        st.session_state["auto_switch_to_staged"] = True
                        clear_runtime_caches()
                        set_workflow_flash(
                            "warning",
                            f"Denied and returned to staging: {Path(denied_stage_folder_path).name}",
                        )
                    st.rerun()
                except Exception as exc:
                    if approve_clicked:
                        st.error(f"Could not approve the listing: {exc}")
                    else:
                        st.error(f"Could not deny the listing: {exc}")


def render_approved_queue_view(
    approved_folder_names: list[str],
    profiles: list[dict[str, Any]],
    dropbox_cfg: dict[str, Any],
) -> None:
    st.subheader("Approved queue")

    queue_items = build_approved_queue_items(approved_folder_names, profiles, dropbox_cfg)
    summary_rows = [
        {
            "folder_name": item["folder_name"],
            "template": item["template"],
            "title": item["title"],
            "variants_summary": item["variants_summary"],
            "load_status": item["load_status"],
        }
        for item in queue_items
    ]

    stored_results = st.session_state.get("approved_queue_generation_results", [])
    if summary_rows:
        st.dataframe(summary_rows, width="stretch", hide_index=True)
    else:
        st.info("No approved folders found.")
        render_generation_results(stored_results, "approved_download")
        return

    approved_lookup = {item["folder_name"]: item for item in queue_items}
    review_folder_options = [item["folder_name"] for item in queue_items if item["listing_memory"]]

    st.markdown("### Review approved listing")
    with st.container(border=True):
        if review_folder_options:
            current_review_folder = st.session_state.get("approved_queue_review_folder", review_folder_options[0])
            if current_review_folder not in review_folder_options:
                current_review_folder = review_folder_options[0]
                st.session_state["approved_queue_review_folder"] = current_review_folder

            selected_review_folder = st.selectbox(
                "Review approved listing",
                review_folder_options,
                key="approved_queue_review_folder",
            )
            review_item = approved_lookup.get(selected_review_folder)
            if review_item:
                approved_panel_key_suffix = selected_review_folder.replace("/", "_").replace("\\", "_").replace(" ", "_")
                approved_panel_open_key = f"approved_output_panel_open_{approved_panel_key_suffix}"

                panel_col1, panel_col2 = st.columns([1, 3])
                with panel_col1:
                    if st.button("Open approved review panel", key=f"{approved_panel_open_key}_open_btn", width="stretch"):
                        st.session_state["active_perf_action_label"] = "open approved review panel"
                        st.session_state[approved_panel_open_key] = True
                with panel_col2:
                    if st.session_state.get(approved_panel_open_key, False):
                        if st.button("Hide approved review panel", key=f"{approved_panel_open_key}_hide_btn"):
                            st.session_state["active_perf_action_label"] = "hide approved review panel"
                            st.session_state[approved_panel_open_key] = False
                    else:
                        st.info("Approved review panel is not loaded yet. Open it only when you need detailed review.")

                if st.session_state.get(approved_panel_open_key, False):
                    with st.expander("Review panel", expanded=True):
                        render_ready_review_panel(
                            review_item,
                            dropbox_cfg,
                            key_prefix="approved_output",
                            source_folder_path=build_approved_folder_path(dropbox_cfg, review_item["folder_name"]),
                        )
        else:
            st.caption("No approved listings available to review yet.")

    st.markdown("### Generate output")
    with st.container(border=True):
        with st.form("approved_output_generation_form"):
            selected_approved_folders = st.multiselect(
                "Select approved folders to generate",
                [item["folder_name"] for item in queue_items if item["profile"] and item["listing_memory"] and not item["load_error"]],
                key="approved_queue_selected_folders",
            )

            col1, col2 = st.columns(2)
            with col1:
                generate_selected = st.form_submit_button("Generate selected", width="stretch")
            with col2:
                generate_all = st.form_submit_button("Generate all approved", width="stretch")

    if generate_selected:
        st.session_state["pending_perf_action_label"] = "generate selected approved"
    elif generate_all:
        st.session_state["pending_perf_action_label"] = "generate all approved"

    target_folders = selected_approved_folders if generate_selected else [
        item["folder_name"] for item in queue_items if item["profile"] and item["listing_memory"] and not item["load_error"]
    ] if generate_all else []
    if not target_folders:
        render_generation_results(stored_results, "approved_download")
        return

    approved_generation_started_at = time.perf_counter()
    approved_generation_target_count = len(target_folders)

    results: list[dict[str, Any]] = []
    for folder_name in target_folders:
        item = approved_lookup.get(folder_name)
        if not item:
            results.append({
                "folder_name": folder_name,
                "status": "Failed",
                "message": "Approved folder could not be loaded.",
            })
            continue

        try:
            result = generate_approved_listing(
                profile=item["profile"],
                listing_memory=item["listing_memory"],
                approved_folder_name=folder_name,
                dropbox_cfg=dropbox_cfg,
            )
            results.append(result)
        except Exception as exc:
            results.append({
                "folder_name": folder_name,
                "status": "Failed",
                "message": str(exc),
            })

    approved_generation_elapsed_ms = round(
        (time.perf_counter() - approved_generation_started_at) * 1000,
        1,
    )
    approved_generation_failures = sum(
        1 for result in results if result.get("status") == "Failed"
    )

    generation_step_rows: list[dict[str, Any]] = []
    for result in results:
        timings = result.get("timings", {}) if isinstance(result, dict) else {}
        for step_name, seconds in dict(timings).items():
            try:
                generation_step_rows.append({
                    "folder_name": result.get("folder_name", ""),
                    "step": step_name,
                    "ms": round(float(seconds) * 1000, 1),
                })
            except Exception:
                pass

    if generation_step_rows:
        slowest_generation_step = max(generation_step_rows, key=lambda row: row["ms"])
        slowest_generation_event = (
            f"Approved generation: {slowest_generation_step['step']} "
            f"({slowest_generation_step['folder_name']})"
        )
        slowest_generation_ms = slowest_generation_step["ms"]
    else:
        slowest_generation_event = f"Approved generation: {approved_generation_target_count} folder(s)"
        slowest_generation_ms = approved_generation_elapsed_ms

    st.session_state["approved_generation_step_rows"] = generation_step_rows

    perf_history = st.session_state.setdefault("perf_history", [])
    perf_history.append({
        "run": len(perf_history) + 1,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": (
            "generate selected approved actual"
            if generate_selected
            else "generate all approved actual"
        ),
        "full_rerun_ms": approved_generation_elapsed_ms,
        "recorded_load_ms": approved_generation_elapsed_ms,
        "estimated_ui_build_ms": 0,
        "slowest_event": slowest_generation_event,
        "slowest_ms": slowest_generation_ms,
        "event_count": approved_generation_target_count,
    })

    if len(perf_history) > 300:
        st.session_state["perf_history"] = perf_history[-300:]

    # Prevent the next display rerun from inheriting the generation label.
    st.session_state.pop("pending_perf_action_label", None)
    st.session_state.pop("active_perf_action_label", None)

    st.session_state["approved_queue_generation_results"] = results
    st.session_state.pop("approved_queue_selected_folders", None)
    clear_runtime_caches()
    st.rerun()

def debug_size_headers(header_map: dict[str, int]) -> None:
    if not st.session_state.get("show_header_debug", False):
        return

    patterns = [
        "size_system",
        "size_class",
        "size_value",
        "apparel_size",
        "body_type",
        "height_type",
    ]

    st.write("Detailed size/header matches")
    for pattern in patterns:
        matches = [key for key in header_map.keys() if pattern.lower() in key.lower()]
        st.write({pattern: matches})

def main() -> None:
    st.set_page_config(page_title="Amazon Listing Generator", layout="wide")
    st.title("Amazon Listing Generator")
    st.caption("Template-based Amazon flat file generator.")
    render_workflow_flash()
    reset_load_events()
    consume_pending_perf_action_label()
    capture_rerun_cause()

    started_at = time.perf_counter()
    profiles = list_template_profiles()
    record_load_event("Template profiles", started_at)

    started_at = time.perf_counter()
    dropbox_cfg = load_dropbox_templates_config()
    record_load_event("Dropbox template config", started_at)

    stage_root = dropbox_cfg.get("stage_root", "")
    ready_root = dropbox_cfg.get("ready_root", "")
    approved_root = dropbox_cfg.get("approved_root", "")
    finished_root = dropbox_cfg.get("finished_root", "")

    if not stage_root or not ready_root or not approved_root or not finished_root:
        st.error("stage_root, ready_root, approved_root, and finished_root must be set in config/dropbox_templates.json")
        st.stop()

    try:
        staged_folder_names = get_cached_folder_names("stage", stage_root, "_stage folders")
        ready_folder_names = get_cached_folder_names("ready", ready_root, "ready folders")
        approved_folder_names = get_cached_folder_names("approved", approved_root, "approved folders")
        finished_folder_names = get_cached_folder_names("finished", finished_root, "finished folders")
    except Exception as exc:
        st.error(f"Could not read Dropbox folders: {exc}")
        st.stop()

    if not profiles:
        st.error("No template profiles found. Create family folders under templates/ with schema.json, a shared workbook, and garment subfolders containing config.json.")
        st.stop()

    tab_setup, tab_content, tab_review_queue, tab_approved_output = st.tabs([
        "Product setup",
        "Listing content",
        "Review queue",
        "Approved output",
    ])

    families = sorted({profile.get("_family_slug", "") for profile in profiles if profile.get("_family_slug")})
    detection_message = ""
    detection_level = ""

    if st.session_state.pop("auto_switch_to_staged", False):
        st.session_state["folder_source_mode"] = "Use staged folder"

    pending_staged_folder_selection = st.session_state.pop("pending_staged_folder_selection_on_rerun", None)
    if pending_staged_folder_selection:
        st.session_state["staged_folder_select"] = pending_staged_folder_selection
        st.session_state.pop("last_detected_template_folder", None)
        st.session_state.pop("applied_listing_memory_key_v2", None)
        st.session_state.pop("initialized_listing_context_key", None)
        st.session_state.pop("last_loaded_listing_memory_signature", None)

    if st.session_state.pop("clear_staged_folder_selection_on_rerun", False):
        st.session_state["staged_folder_select"] = None
        st.session_state.pop("last_detected_template_folder", None)
        st.session_state.pop("applied_listing_memory_key_v2", None)
        st.session_state.pop("initialized_listing_context_key", None)
        st.session_state.pop("last_loaded_listing_memory_signature", None)

    folder_source = st.session_state.get("folder_source_mode", "Use staged folder")
    initial_staged_folder_name = st.session_state.get("staged_folder_select", "") if folder_source == "Use staged folder" else ""
    listing_memory: dict[str, Any] = {}
    authoritative_profile: dict[str, Any] | None = None

    if initial_staged_folder_name:
        stage_folder_path = build_stage_folder_path(dropbox_cfg, initial_staged_folder_name)
        try:
            listing_memory = load_listing_memory_from_dropbox(stage_folder_path)
            authoritative_profile = find_profile_for_listing_memory(profiles, listing_memory) if listing_memory else None
            if authoritative_profile:
                st.session_state["template_family_select"] = authoritative_profile.get("_family_slug", "")
                st.session_state["listing_template_select"] = authoritative_profile.get("label", authoritative_profile.get("_slug", ""))
        except Exception:
            listing_memory = {}
            authoritative_profile = None

    current_folder_source_mode = st.session_state.get("folder_source_mode", "Use staged folder")
    current_detect_folder = st.session_state.get("staged_folder_select", "") if current_folder_source_mode == "Use staged folder" else ""

    if current_detect_folder and not authoritative_profile:
        last_detect_folder = st.session_state.get("last_detected_template_folder", "")
        if last_detect_folder != current_detect_folder:
            matches = find_template_matches_for_staged_folder(current_detect_folder, profiles)
            st.session_state["last_detected_template_folder"] = current_detect_folder

            if len(matches) == 1:
                matched = matches[0]
                st.session_state["template_family_select"] = matched.get("_family_slug", "")
                st.session_state["listing_template_select"] = matched.get("label", matched.get("_slug", ""))
                st.session_state["template_detection_message"] = (
                    f"Auto-detected template `{matched.get('label', matched.get('_slug', ''))}` from staged folder `{current_detect_folder}`."
                )
                st.session_state["template_detection_level"] = "info"
            elif len(matches) > 1:
                matched_families = {match.get("_family_slug", "") for match in matches}
                if len(matched_families) == 1:
                    matched_family = next(iter(matched_families))
                    st.session_state["template_family_select"] = matched_family
                    match_labels = ", ".join(match.get("label", match.get("_slug", "")) for match in matches)
                    st.session_state["template_detection_message"] = (
                        f"Detected family `{matched_family}` from staged folder `{current_detect_folder}`. "
                        f"Please confirm which template to use: {match_labels}."
                    )
                    st.session_state["template_detection_level"] = "warning"
                else:
                    st.session_state["template_detection_message"] = (
                        f"Found multiple possible template matches for `{current_detect_folder}`. Please choose manually."
                    )
                    st.session_state["template_detection_level"] = "warning"
            else:
                st.session_state.pop("template_detection_message", None)
                st.session_state.pop("template_detection_level", None)

    detection_message = st.session_state.get("template_detection_message", "")
    detection_level = st.session_state.get("template_detection_level", "")

    if authoritative_profile:
        selected_family = authoritative_profile.get("_family_slug", "")
        selected_label = authoritative_profile.get("label", authoritative_profile.get("_slug", ""))
    else:
        selected_family = st.session_state.get("template_family_select", families[0] if families else "")
    if families and selected_family not in families:
        selected_family = families[0]
        st.session_state["template_family_select"] = selected_family

    family_profiles = [
        profile for profile in profiles
        if profile.get("_family_slug") == selected_family
    ]

    family_labels = [profile.get("label", profile["_slug"]) for profile in family_profiles]

    if not authoritative_profile:
        selected_label = st.session_state.get("listing_template_select", family_labels[0] if family_labels else "")
    if family_labels and selected_label not in family_labels:
        selected_label = family_labels[0]
        st.session_state["listing_template_select"] = selected_label

    profile = family_profiles[family_labels.index(selected_label)]
    active_staged_folder_name = initial_staged_folder_name
    active_listing_memory = listing_memory
    active_profile = profile
    active_profile_slug = active_profile.get("_slug", "")
    active_family_slug = active_profile.get("_family_slug", "")
    active_template_label = active_profile.get("label", active_profile_slug)

    st.sidebar.markdown("### Active template")
    st.sidebar.write(f"Family: `{active_family_slug}`")
    st.sidebar.write(f"Template: `{active_profile_slug}`")
    st.sidebar.write(f"Workbook: `{active_profile.get('template_file', '')}`")
    st.sidebar.write(f"Variation theme: `{active_profile.get('variation_theme', '')}`")
    st.sidebar.checkbox("Show troubleshooting debug", key="show_header_debug", value=False)
    st.sidebar.checkbox("Copy row styles", key="copy_row_styles", value=True)
    st.sidebar.checkbox("Auto-load image mappings", key="auto_load_image_mappings", value=False)
    if st.sidebar.button("Refresh Dropbox queues", key="refresh_dropbox_queues_btn", width="stretch"):
        st.session_state["pending_perf_action_label"] = "refresh Dropbox queues"
        refresh_cached_folder_names("stage", "ready", "approved", "finished")
        st.rerun()

    colors_available = get_profile_color_options(active_profile)
    sizes_available = active_profile.get("sizes", [])
    dropbox_overview_cache_hit = (
        st.session_state.get("dropbox_overview_cache", {}).get("key")
        == build_dropbox_overview_cache_key(active_profile, dropbox_cfg)
    )
    t_dropbox_overview_start = time.perf_counter()
    dropbox_overview = get_cached_dropbox_overview(active_profile, dropbox_cfg)
    t_dropbox_overview_end = time.perf_counter()

    with st.sidebar.expander("Dropbox debug"):
        try:
            test_path = ""
            if dropbox_overview.get("shared_resource_images"):
                test_path = dropbox_overview["shared_resource_images"][0]

            st.write("Test path:", test_path)
            if test_path:
                st.write("Preview URL:", dropbox_preview_url(test_path))
        except Exception as exc:
            st.error(f"Dropbox debug failed: {exc}")


    parent_sku_from_config = str(get_default(active_profile, "parent_sku", "")).strip()

    staged_folder_name = None
    selected_finished_folder = None
    content_debug_container = None
    content_preflight_container = None

    with tab_setup:
        top_left_col, top_right_col = st.columns(2)
        with top_left_col:
            st.subheader("Folder workflow")
            folder_source = st.radio(
                "Choose Folder Source",
                ["Use staged folder", "Restage finished folder"],
                key="folder_source_mode",
            )

            if folder_source == "Use staged folder":
                staged_folder_name = st.selectbox(
                    "Dropbox folder",
                    staged_folder_names,
                    index=None,
                    placeholder="Select a staged folder",
                    key="staged_folder_select",
                )
            else:
                selected_finished_folder = st.selectbox(
                    "Dropbox folder",
                    finished_folder_names,
                    index=None,
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

                    try:
                        moved_path = restage_finished_dropbox_folder(
                            dropbox_cfg=dropbox_cfg,
                            finished_folder_name=selected_finished_folder,
                        )

                        try:
                            restaged_listing_memory = load_listing_memory_from_dropbox(moved_path)
                        except Exception:
                            restaged_listing_memory = {}

                        restaged_listing_memory["original_finished_folder_name"] = selected_finished_folder
                        restaged_profile = find_profile_for_listing_memory(profiles, restaged_listing_memory) or profile
                        save_listing_inputs_json_to_dropbox(
                            profile=restaged_profile,
                            payload=restaged_listing_memory,
                            folder_path=moved_path,
                        )

                        clear_runtime_caches()
                        set_workflow_flash(
                            "success",
                            f"Restaged successfully: {Path(moved_path).name}",
                        )

                        st.session_state["last_loaded_listing_memory_folder"] = ""
                        st.session_state.pop("finalized_stage_folder", None)
                        st.session_state.pop("finalized_finished_folder_path", None)
                        st.session_state.pop("finalized_sku", None)
                        restaged_folder_name = Path(moved_path).name
                        st.session_state["staged_folder_select"] = restaged_folder_name
                        st.session_state["auto_switch_to_staged"] = True
                        st.session_state.pop("last_detected_template_folder", None)

                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not restage folder: {exc}")
                        st.stop()

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

        with top_right_col:
            st.subheader("Template selection")
            if detection_message:
                if detection_level == "warning":
                    st.warning(detection_message)
                else:
                    st.info(detection_message)
            select_col1, select_col2 = st.columns(2)
            with select_col1:
                st.selectbox(
                    "Template family",
                    families,
                    key="template_family_select",
                )
            with select_col2:
                st.selectbox(
                    "Garment template",
                    family_labels,
                    key="listing_template_select",
                )
            st.selectbox(
                "Assets prepared by",
                WORKFLOW_ASSIGNEES,
                key="assets_prepared_by",
            )
    folder_source = st.session_state.get("folder_source_mode", folder_source)
    if folder_source == "Use staged folder":
        staged_folder_name = st.session_state.get("staged_folder_select") or active_staged_folder_name
    else:
        selected_finished_folder = st.session_state.get("finished_folder_select")

    listing_memory = dict(active_listing_memory)
    listing_context_key = ""
    if staged_folder_name:
        listing_context_key = f"{staged_folder_name}|{active_profile.get('template_key', active_profile_slug)}"

    if staged_folder_name and listing_memory:
        memory_fingerprint = json.dumps(
            {
                "folder": staged_folder_name,
                "profile": active_profile.get("template_key", active_profile_slug),
                "template_key": listing_memory.get("template_key", ""),
                "template_slug": listing_memory.get("template_slug", ""),
                "title": listing_memory.get("title", ""),
                "bullet_points": listing_memory.get("bullet_points", []),
                "product_description": listing_memory.get("product_description", ""),
                "generic_keywords": listing_memory.get("generic_keywords", ""),
                "selected_variants": listing_memory.get("selected_variants", {}),
                "size_price_map": listing_memory.get("size_price_map", {}),
                "quantity": listing_memory.get("quantity", 100),
            },
            sort_keys=True,
        )

        applied_memory_key = st.session_state.get("applied_listing_memory_key_v2", "")
        should_apply_memory = applied_memory_key != memory_fingerprint

        if should_apply_memory:
            apply_listing_memory_to_session(listing_memory, active_profile)
            st.session_state["applied_listing_memory_key_v2"] = memory_fingerprint
            st.session_state["initialized_listing_context_key"] = listing_context_key
            st.session_state["last_loaded_listing_memory_signature"] = f"{staged_folder_name}|{active_profile_slug}"
    elif listing_context_key:
        initialized_context_key = st.session_state.get("initialized_listing_context_key", "")
        if initialized_context_key != listing_context_key:
            initialize_listing_context_defaults(active_profile)
            st.session_state["initialized_listing_context_key"] = listing_context_key

    if listing_memory:
        st.sidebar.info("Loaded saved listing inputs from staged folder.")

    for field_name in ["assets_prepared_by", "content_prepared_by", "reviewed_by", "prepared_at", "reviewed_at"]:
        if field_name not in st.session_state:
            current_value = str(listing_memory.get(field_name, ""))
            if field_name in {"assets_prepared_by", "content_prepared_by", "reviewed_by"} and current_value not in WORKFLOW_ASSIGNEES:
                current_value = ""
            st.session_state[field_name] = current_value

    title = st.session_state.get("title_input", listing_memory.get("title", ""))

    saved_bullets = listing_memory.get("bullet_points", [])
    saved_bullets = (saved_bullets + ["", "", "", "", ""])[:5]
    bullets = [
        st.session_state.get("bullet_1", saved_bullets[0]),
        st.session_state.get("bullet_2", saved_bullets[1]),
        st.session_state.get("bullet_3", saved_bullets[2]),
        st.session_state.get("bullet_4", saved_bullets[3]),
        st.session_state.get("bullet_5", saved_bullets[4]),
    ]

    product_description = st.session_state.get("product_description", listing_memory.get("product_description", ""))
    generic_keywords = st.session_state.get("generic_keywords", listing_memory.get("generic_keywords", ""))

    st.session_state.setdefault("title_input", title)
    for idx, bullet_value in enumerate(bullets, start=1):
        st.session_state.setdefault(f"bullet_{idx}", bullet_value)
    st.session_state.setdefault("product_description", product_description)
    st.session_state.setdefault("generic_keywords", generic_keywords)
    st.session_state.setdefault("variant_quantity", int(listing_memory.get("quantity", 100)))

    profile = active_profile
    variant_dimensions = active_profile.get("variant_dimensions", [])
    saved_selected_variants = listing_memory.get("selected_variants", {})
    selected_variants = normalize_selected_variants_session_state(active_profile, listing_memory)

    auto_load_image_mappings = bool(st.session_state.get("auto_load_image_mappings", False))
    load_image_mappings_now = bool(st.session_state.pop("load_image_mappings_now", False))
    manual_image_load_requested = bool(load_image_mappings_now and staged_folder_name)

    # Image mappings should persist while editing listing content.
    # Treat mappings as loaded for the staged folder + template, not for every selected colour/size change.
    image_mapping_context_key = json.dumps(
        {
            "folder": staged_folder_name or "",
            "template_slug": active_profile.get("_slug", ""),
            "template_key": active_profile.get("template_key", ""),
        },
        sort_keys=True,
    )

    persisted_image_mappings_loaded = bool(
        staged_folder_name
        and st.session_state.get("image_mappings_loaded_folder") == staged_folder_name
        and st.session_state.get("image_mappings_loaded_context") == image_mapping_context_key
    )

    image_mappings_stale = bool(
        staged_folder_name
        and st.session_state.get("image_mappings_loaded_folder") == staged_folder_name
        and st.session_state.get("image_mappings_loaded_context") != image_mapping_context_key
    )

    if manual_image_load_requested:
        st.session_state["image_mappings_loaded_folder"] = staged_folder_name
        st.session_state["image_mappings_loaded_context"] = image_mapping_context_key
        persisted_image_mappings_loaded = True
        image_mappings_stale = False

    # Only explicit load/auto-load may build image mappings.
    # Previously-loaded mappings are included only when the current folder/template/variant context matches.
    should_load_image_mappings = bool(staged_folder_name) and (
        auto_load_image_mappings
        or manual_image_load_requested
        or persisted_image_mappings_loaded
    )

    if auto_load_image_mappings and staged_folder_name:
        image_resolution_reason = "auto_load"
    elif manual_image_load_requested:
        image_resolution_reason = "manual_load"
    elif persisted_image_mappings_loaded and staged_folder_name:
        image_resolution_reason = "cache_reuse"
    elif image_mappings_stale:
        image_resolution_reason = "stale_context"
    else:
        image_resolution_reason = ""

    image_preview_variants = selected_variants
    if manual_image_load_requested:
        st.session_state["image_mappings_loaded_variants"] = dict(selected_variants)
    elif persisted_image_mappings_loaded and not auto_load_image_mappings:
        image_preview_variants = dict(
            st.session_state.get("image_mappings_loaded_variants", selected_variants)
        )

    preview_image_cache_hit = (
        st.session_state.get("preview_image_cache", {}).get("key")
        == build_preview_image_cache_key(
            profile,
            dropbox_cfg,
            staged_folder_name or "",
            image_preview_variants,
            should_load_image_mappings,
            should_load_image_mappings,
        )
    )
    t_preview_image_start = time.perf_counter()
    preview_image_data = get_cached_preview_image_data(
        profile=profile,
        dropbox_cfg=dropbox_cfg,
        staged_folder_name=staged_folder_name or "",
        selected_variants=image_preview_variants,
        dropbox_overview=dropbox_overview,
        include_mappings=should_load_image_mappings,
        resolve_preview_urls=should_load_image_mappings,
    )
    t_preview_image_end = time.perf_counter()
    record_load_event(
        "Images: preview/mapping data",
        t_preview_image_start,
        "with mappings" if should_load_image_mappings else "paths only",
    )
    staged_preview_paths = preview_image_data.get("staged_preview_paths", [])
    staged_preview_entries = preview_image_data.get("staged_preview_entries", [])
    design_color_preview_entries = preview_image_data.get("design_color_preview_entries", [])
    parent_main_image_options = preview_image_data.get("parent_main_image_options", [])
    garment_resource_entries = preview_image_data.get("garment_resource_entries", [])
    global_resource_entries = preview_image_data.get("global_resource_entries", [])
    staged_variant_entries = preview_image_data.get("staged_variant_entries", [])
    preview_color_image_map = preview_image_data.get("color_image_map", {})
    preview_design_color_image_url_map = preview_image_data.get("design_color_image_url_map", {})

    price_dimension_values = selected_variants.get("size", ["default"])
    saved_prices = listing_memory.get("size_price_map", {})
    existing_values = [saved_prices.get(size) for size in price_dimension_values if size in saved_prices]
    unique_existing_values = {v for v in existing_values if v is not None}
    default_same_price = bool(price_dimension_values) and len(unique_existing_values) == 1 and len(existing_values) == len(price_dimension_values)
    use_same_price = st.session_state.get("use_same_price_for_all_sizes", default_same_price)

    if use_same_price:
        fallback_price = float(saved_prices.get(price_dimension_values[0], 29.99)) if default_same_price and price_dimension_values else 29.99
        shared_price = float(st.session_state.get("shared_price_all_sizes", fallback_price))
        size_price_map = {size: shared_price for size in price_dimension_values}
    else:
        size_price_map = {
            size: float(st.session_state.get(f"price_{size}", saved_prices.get(size, 29.99)))
            for size in price_dimension_values
        }

    quantity = int(st.session_state.get("variant_quantity", listing_memory.get("quantity", 100)))
    selected_parent_main_label = st.session_state.get("parent_main_image_choice", "Automatic (recommended)")
    selected_parent_main_image_url = next(
        (url for label, url in parent_main_image_options if label == selected_parent_main_label),
        "",
    )
    preview_parent_main_image_url = (
        selected_parent_main_image_url
        or (parent_main_image_options[0][1] if parent_main_image_options else "")
    )
    resolved_image_bundle = {
        "parent_main_image_url": preview_parent_main_image_url if preview_parent_main_image_url else "",
        "other_images": [],
        "color_image_map": preview_color_image_map,
        "design_color_image_url_map": preview_design_color_image_url_map,
    }
    resolved_image_error = ""
    image_mappings_loaded_this_run = False
    current_resolved_image_cache_key = ""
    if staged_folder_name:
        current_resolved_image_cache_key = build_resolved_image_bundle_cache_key(
            profile,
            dropbox_cfg,
            staged_folder_name,
            image_preview_variants,
            selected_parent_main_image_url,
        )
    resolved_image_bundle_cache_hit = bool(
        current_resolved_image_cache_key
        and st.session_state.get("resolved_image_bundle_cache", {}).get("key") == current_resolved_image_cache_key
    )
    t_resolved_image_start = time.perf_counter()
    if staged_folder_name and (should_load_image_mappings or resolved_image_bundle_cache_hit):
        try:
            resolved_image_bundle = get_cached_resolved_image_bundle(
                profile=profile,
                dropbox_cfg=dropbox_cfg,
                staged_folder_name=staged_folder_name,
                selected_variants=image_preview_variants,
                dropbox_overview=dropbox_overview,
                selected_parent_main_image_url=selected_parent_main_image_url,
            )
            image_mappings_loaded_this_run = should_load_image_mappings and not resolved_image_bundle_cache_hit
        except Exception as exc:
            resolved_image_error = str(exc)
            resolved_image_bundle = {
                "parent_main_image_url": preview_parent_main_image_url if preview_parent_main_image_url else "",
                "other_images": [],
                "color_image_map": preview_color_image_map,
                "design_color_image_url_map": preview_design_color_image_url_map,
            }
    t_resolved_image_end = time.perf_counter()
    record_load_event(
        "Images: resolved image bundle",
        t_resolved_image_start,
        image_resolution_reason or "cache/no-load",
    )
    preview_parent_main_image_url = resolved_image_bundle.get("parent_main_image_url", preview_parent_main_image_url)
    preview_other_images = list(resolved_image_bundle.get("other_images", []))
    preview_color_image_map = dict(resolved_image_bundle.get("color_image_map", preview_color_image_map))
    preview_design_color_image_url_map = dict(
        resolved_image_bundle.get("design_color_image_url_map", preview_design_color_image_url_map)
    )
    image_mappings_loaded = bool(
        current_resolved_image_cache_key
        and st.session_state.get("resolved_image_bundle_cache", {}).get("key") == current_resolved_image_cache_key
    )
    if not staged_folder_name:
        image_mapping_status = "not_loaded"
        image_mapping_detail = "Select a staged folder to load image mappings."
    elif resolved_image_error:
        image_mapping_status = "error"
        image_mapping_detail = resolved_image_error
    elif image_mappings_loaded:
        image_mapping_status = "loaded"
        image_mapping_detail = "Image mappings loaded."
    elif image_mappings_stale:
        image_mapping_status = "not_loaded"
        image_mapping_detail = "Image mappings need refresh because the folder or template changed. Click Load / refresh image mappings to update them."
    else:
        image_mapping_status = "not_loaded"
        image_mapping_detail = "Image mappings not loaded yet. Use Load / refresh image mappings when you need image review or full checks."

    with tab_setup:
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

        with st.expander("Dropbox image overview", expanded=True):
            if not dropbox_overview:
                st.warning("No shared Dropbox config loaded yet.")
            else:
                st.write(f"Resource root: `{dropbox_overview['resource_root']}`")
                st.write(f"Variant folder: `{dropbox_overview['variant_folder']}`")
                if dropbox_overview.get("garment_resource_warning"):
                    st.warning(dropbox_overview["garment_resource_warning"])

                st.write(f"Staged image files found: `{len(staged_preview_paths)}`")
                st.write(f"Selected variants: `{build_variants_summary(selected_variants)}`")
                st.write(f"Garment support files configured: `{len(dropbox_overview.get('garment_resource_images', []))}`")
                st.write(f"Shared support files configured: `{len(dropbox_overview.get('shared_resource_images', []))}`")

                if st.session_state.get("show_header_debug", False):
                    with st.expander("Raw staged folder contents", expanded=False):
                        if not staged_folder_name:
                            st.caption("Select a staged Dropbox folder to preview its images.")
                        elif staged_preview_paths:
                            for preview_path in staged_preview_paths:
                                st.code(preview_path, language=None)
                        else:
                            st.caption("No staged image files found.")

                if image_mapping_status != "loaded":
                    st.info("Image mappings are not loaded yet. Use Load image mappings when you need parent/child/support image resolution.")
                else:
                    tab_names = ["Staged variant images", "Shared resources", "Variant combinations"]
                    colours_tab, resources_tab, combos_tab = st.tabs(tab_names)

                    with resources_tab:
                        render_path_grid(
                            "Garment support images",
                            garment_resource_entries,
                            cols_per_row=5,
                            image_width=150,
                        )
                        render_path_grid(
                            "Global resource images",
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
                            index=parent_main_option_labels.index(current_parent_main_label),
                            key="parent_main_image_choice",
                        )
                        render_color_grid(
                            staged_variant_entries,
                            cols_per_row=5,
                            image_width=150,
                        )

                    with combos_tab:
                        render_design_color_grid(
                            design_color_preview_entries,
                            cols_per_row=5,
                            image_width=150,
                        )

        st.subheader("Product template details")
        col1, col2 = st.columns(2)
        with col1:
            st.text_input("Parent SKU", value=parent_sku_from_config, disabled=True)
            st.text_input("Brand", value=GLOBAL_BRAND_NAME, disabled=True)
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

    with tab_content:
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

        title = st.text_input(
            "Product title",
            key="title_input",
        )

        title_chars = len(title.strip())
        if title_chars < 150:
            st.caption(f"Title: {title_chars} chars - target 150 chars")
        else:
            st.caption(f"Title: {title_chars} chars - good")

        st.subheader("Bullets")
        bullets = [
            st.text_input("Bullet 1", key="bullet_1"),
            st.text_input("Bullet 2", key="bullet_2"),
            st.text_input("Bullet 3", key="bullet_3"),
            st.text_input("Bullet 4", key="bullet_4"),
            st.text_input("Bullet 5", key="bullet_5"),
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
            key="product_description",
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
            key="generic_keywords",
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

        st.subheader("Variants")

        if variant_dimensions:
            selected_variants = {}
            for dim in variant_dimensions:
                dim_name = dim.get("name", "")
                dim_label = dim.get("label", dim_name.title())
                dim_options = dim.get("options", [])
                widget_key = f"variant_{dim_name}"
                selected_variants[dim_name] = st.multiselect(
                    dim_label,
                    dim_options,
                    key=widget_key,
                )
        else:
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

        with st.expander("Selected combinations preview", expanded=False):
            render_variant_combinations_preview(
                profile=profile,
                parent_sku=parent_sku_from_config,
                selected_variants=selected_variants,
            )

        price_dimension_values = selected_variants.get("size", ["default"])
        size_price_map = build_size_price_inputs(
            price_dimension_values,
            saved_prices=listing_memory.get("size_price_map", {}),
        )

        st.subheader("Inventory setup")
        quantity = st.number_input(
            "Quantity for all child variants",
            min_value=0,
            step=1,
            key="variant_quantity",
        )
        st.selectbox(
            "Content prepared by",
            WORKFLOW_ASSIGNEES,
            key="content_prepared_by",
        )

    score_clicked = False
    ready_clicked = False

    with tab_content:
        st.caption("Check listing score to review quality before submitting the folder for review.")
        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            score_clicked = st.button("Check listing score", width="stretch")
        with btn_col2:
            ready_clicked = st.button("Submit for Review", width="stretch")
        content_debug_container = st.container()
        content_preflight_container = st.container()
        content_action_result_container = st.container()

    with tab_review_queue:
        st.caption("Review ready listings and approve them for generation.")

        review_col1, review_col2 = st.columns([1, 3])
        with review_col1:
            if st.button("Load / refresh review queue", key="load_review_queue_tab_btn", width="stretch"):
                st.session_state["active_perf_action_label"] = "load review queue"
                st.session_state["review_queue_tab_loaded"] = True
        with review_col2:
            if not st.session_state.get("review_queue_tab_loaded", False):
                st.info("Review queue is not loaded yet. Click Load / refresh review queue when you need admin review.")

        if st.session_state.get("review_queue_tab_loaded", False):
            render_review_queue_view(
                ready_folder_names=ready_folder_names,
                profiles=profiles,
                dropbox_cfg=dropbox_cfg,
            )

    with tab_approved_output:
        st.caption("Generate selected or all approved folders and download completed workbooks.")

        approved_col1, approved_col2 = st.columns([1, 3])
        with approved_col1:
            if st.button("Load / refresh approved output", key="load_approved_output_tab_btn", width="stretch"):
                st.session_state["active_perf_action_label"] = "load approved output"
                st.session_state["approved_output_tab_loaded"] = True
        with approved_col2:
            if not st.session_state.get("approved_output_tab_loaded", False):
                st.info("Approved output is not loaded yet. Click Load / refresh approved output when you need generation.")

        if st.session_state.get("approved_output_tab_loaded", False):
            render_approved_queue_view(
                approved_folder_names=approved_folder_names,
                profiles=profiles,
                dropbox_cfg=dropbox_cfg,
            )

    render_inline_loading_debug()
    render_rerun_cause_debug()
    save_debug_state_snapshot()

    if not score_clicked and not ready_clicked:
        return

    if staged_folder_name and not image_mappings_loaded:
        image_resolution_reason = "submit_review" if ready_clicked else "score_check"
        with st.spinner("Loading image mappings for quality checks..."):
            try:
                resolved_image_bundle = get_cached_resolved_image_bundle(
                    profile=profile,
                    dropbox_cfg=dropbox_cfg,
                    staged_folder_name=staged_folder_name,
                    selected_variants=selected_variants,
                    dropbox_overview=dropbox_overview,
                    selected_parent_main_image_url=selected_parent_main_image_url,
                )
                image_mappings_loaded_this_run = True
                resolved_image_bundle_cache_hit = False
                resolved_image_error = ""
                preview_parent_main_image_url = resolved_image_bundle.get("parent_main_image_url", preview_parent_main_image_url)
                preview_other_images = list(resolved_image_bundle.get("other_images", []))
                preview_color_image_map = dict(resolved_image_bundle.get("color_image_map", preview_color_image_map))
                preview_design_color_image_url_map = dict(
                    resolved_image_bundle.get("design_color_image_url_map", preview_design_color_image_url_map)
                )
                image_mappings_loaded = True
                image_mapping_status = "loaded"
                image_mapping_detail = "Image mappings loaded."
            except Exception as exc:
                resolved_image_error = str(exc)
                image_mapping_status = "error"
                image_mapping_detail = resolved_image_error

    preflight = build_preflight_report(
        profile=profile,
        dropbox_cfg=dropbox_cfg,
        dropbox_overview=dropbox_overview,
        staged_folder_name=staged_folder_name or "",
        title=title,
        bullets=bullets,
        product_description=product_description,
        generic_keywords=generic_keywords,
        selected_variants=selected_variants,
        size_price_map=size_price_map,
        quantity=quantity,
        resolved_parent_main_image_url=preview_parent_main_image_url,
        resolved_other_images=preview_other_images,
        resolved_color_image_map=preview_color_image_map,
        resolved_design_color_image_url_map=preview_design_color_image_url_map,
        allow_image_resolution_fallback=False,
    )

    preview_payload = preflight["preview_payload"]
    all_preview_errors = preflight["all_preview_errors"]
    quality_report = preflight["quality_report"]

    if content_debug_container is not None and st.session_state.get("show_header_debug", False):
        with content_debug_container:
            with st.expander("Listing content image debug", expanded=False):
                st.write(
                    "cache_timings",
                    {
                        "dropbox_overview": {
                            "cache_hit": dropbox_overview_cache_hit,
                            "seconds": round(t_dropbox_overview_end - t_dropbox_overview_start, 4),
                        },
                        "preview_image_data": {
                            "cache_hit": preview_image_cache_hit,
                            "seconds": round(t_preview_image_end - t_preview_image_start, 4),
                        },
                        "resolved_image_bundle": {
                            "cache_hit": resolved_image_bundle_cache_hit,
                            "seconds": round(t_resolved_image_end - t_resolved_image_start, 4),
                            "loaded_this_run": image_mappings_loaded_this_run,
                            "reason": image_resolution_reason,
                            "status": image_mapping_status,
                        },
                    },
                )
                st.write("selected_variants", selected_variants)
                st.write("parent_main_image_options", parent_main_image_options)
                st.write("selected_parent_main_image_url", selected_parent_main_image_url)
                st.write("preview_parent_main_image_url", preview_parent_main_image_url)
                st.write("preview_color_image_map", preview_color_image_map)
                st.write("preview_design_color_image_url_map", preview_design_color_image_url_map)
                st.write("preview_other_images", preview_other_images)
                st.write(
                    "preview_payload_image_fields",
                    {
                        "parent_main_image_url": preview_payload.get("parent_main_image_url", ""),
                        "other_images": preview_payload.get("other_images", []),
                        "color_image_map": preview_payload.get("color_image_map", {}),
                        "design_color_image_url_map": preview_payload.get("design_color_image_url_map", {}),
                    },
                )

    if (score_clicked or ready_clicked) and content_preflight_container is not None:
        with content_preflight_container:
            render_preflight_dashboard(
                quality_report=quality_report,
                all_preview_errors=all_preview_errors,
            )
            render_listing_score_result(
                quality_report=quality_report,
                all_preview_errors=all_preview_errors,
            )

    if score_clicked and not ready_clicked:
        st.stop()

    generation_prep = prepare_generation_payload(
        profile=profile,
        title=title,
        bullets=bullets,
        product_description=product_description,
        generic_keywords=generic_keywords,
        selected_variants=selected_variants,
        size_price_map=size_price_map,
        quantity=quantity,
        staged_folder_name=staged_folder_name or "",
    )

    generation_payload = generation_prep["payload"]
    original_finished_folder_name = str(listing_memory.get("original_finished_folder_name", "")).strip()
    if original_finished_folder_name:
        generation_payload["original_finished_folder_name"] = original_finished_folder_name
    generation_payload["assets_prepared_by"] = st.session_state.get("assets_prepared_by", "")
    generation_payload["content_prepared_by"] = st.session_state.get("content_prepared_by", "")
    generation_payload["reviewed_by"] = st.session_state.get("reviewed_by", "")
    generation_payload["prepared_at"] = st.session_state.get("prepared_at", "")
    generation_payload["reviewed_at"] = format_workflow_timestamp()
    generation_errors = generation_prep["errors"]
    action_label = "submit this listing for review" if ready_clicked else "generate"

    if generation_errors:
        st.error(f"Fix the validation errors before trying to {action_label}.")
        st.stop()

    if quality_report["blockers"]:
        st.error(f"Fix the listing quality blockers before trying to {action_label}.")
        st.stop()

    if ready_clicked:
        try:
            staged_folder_name = staged_folder_name or ""
            ready_folder_name = staged_folder_name
            stage_folder_path = build_stage_folder_path(dropbox_cfg, staged_folder_name)
            generation_payload["prepared_at"] = format_workflow_timestamp()
            st.session_state["prepared_at"] = generation_payload["prepared_at"]

            listing_memory_path = save_listing_inputs_json_to_dropbox(
                profile=profile,
                payload=generation_payload,
                folder_path=stage_folder_path,
            )
            ready_folder_path = move_staged_dropbox_folder_to_ready(
                dropbox_cfg=dropbox_cfg,
                staged_folder_name=staged_folder_name,
                ready_folder_name=ready_folder_name,
            )

            st.session_state["last_ready_folder_path"] = ready_folder_path
            st.session_state["clear_staged_folder_selection_on_rerun"] = True
            clear_runtime_caches()
            set_workflow_flash(
                "success",
                f"Submitted for review: {Path(ready_folder_path).name}",
                f"Saved listing inputs to {listing_memory_path} and moved the folder to ready for admin review.",
            )
            st.rerun()
        except Exception as exc:
            target_container = content_action_result_container or st.container()
            with target_container:
                st.error(f"Could not submit the listing for review: {exc}")

            st.stop()

    try:
        progress_text = st.empty()
        progress_bar = st.progress(0)

        t0 = time.perf_counter()

        staged_folder_name = staged_folder_name or ""
        parent_sku_from_config = generation_payload["parent_sku"]
        selected_colors = generation_payload["colors"]
        selected_variants = generation_payload["selected_variants"]
        stage_folder_path = build_stage_folder_path(dropbox_cfg, staged_folder_name)

        if st.session_state.get("finalized_stage_folder") == staged_folder_name:
            progress_text.error("This staged folder was already finalized in the current session.")
            st.stop()

        progress_text.write("Checking workbook template...")
        progress_bar.progress(10)

        template_path = resolve_template_path(profile)
        wb = load_workbook(template_path, keep_vba=True, read_only=True)
        wb.close()
        t1 = time.perf_counter()

        progress_text.write("Checking staged Dropbox assets...")
        progress_bar.progress(20)

        resolve_folder_image_urls(
            profile,
            selected_variants,
            selected_colors,
            dropbox_overview,
            stage_folder_path,
            selected_parent_main_image_url=selected_parent_main_image_url,
        )
        t2 = time.perf_counter()

        progress_text.write("Moving staged folder into finished...")
        progress_bar.progress(35)

        final_sku, finished_folder_path = finalize_staged_dropbox_folder(
            dropbox_cfg=dropbox_cfg,
            staged_folder_name=staged_folder_name,
            parent_sku=parent_sku_from_config,
            reuse_finished_folder_name=original_finished_folder_name,
        )
        t3 = time.perf_counter()

        st.session_state["finalized_stage_folder"] = staged_folder_name
        st.session_state["finalized_finished_folder_path"] = finished_folder_path
        st.session_state["finalized_sku"] = final_sku

        progress_text.write("Fetching Dropbox image links...")
        progress_bar.progress(50)

        parent_main_image_url, other_images, color_image_map, design_color_image_url_map = resolve_folder_image_urls(
            profile,
            selected_variants,
            selected_colors,
            dropbox_overview,
            finished_folder_path,
            selected_parent_main_image_url=selected_parent_main_image_url,
        )
        t4 = time.perf_counter()

        payload = dict(generation_payload)
        payload["parent_sku"] = final_sku
        payload["parent_main_image_url"] = parent_main_image_url
        payload["other_images"] = other_images
        payload["color_image_map"] = color_image_map
        payload["design_color_image_url_map"] = design_color_image_url_map


        progress_text.write("Building workbook...")
        progress_bar.progress(75)

        output_path, workbook_timings = build_workbook(profile, payload)

        listing_memory_path = save_listing_memory_to_dropbox(
            profile=profile,
            payload=payload,
            folder_path=finished_folder_path,
        )

        t5 = time.perf_counter()

        progress_text.write("Finalizing output...")
        progress_bar.progress(95)

        variant_combos = build_variant_combinations(profile, selected_variants)
        child_count = len(variant_combos)

        progress_bar.progress(100)
        progress_text.success("Workbook generated successfully.")

        st.success(f"Workbook generated successfully: {output_path.name}")
        st.info(f"Generated 1 parent row and {child_count} child variants.")

        with st.expander("Performance breakdown", expanded=False):
            st.write(f"Check workbook template: {t1 - t0:.2f}s")
            st.write(f"Check staged Dropbox assets: {t2 - t1:.2f}s")
            st.write(f"Move staged folder: {t3 - t2:.2f}s")
            st.write(f"Resolve Dropbox image URLs: {t4 - t3:.2f}s")
            st.write(f"Build workbook: {t5 - t4:.2f}s")
            st.write(f"Total: {t5 - t0:.2f}s")
            st.write("---")
            st.write(f"Load workbook: {workbook_timings['load_workbook']:.2f}s")
            st.write(f"Write parent row: {workbook_timings['write_parent_row']:.2f}s")
            st.write(f"Write child rows: {workbook_timings['write_child_rows']:.2f}s")
            st.write(f"Save workbook: {workbook_timings['save_workbook']:.2f}s")

        with output_path.open("rb") as f:
            st.download_button(
                label="Download Amazon workbook",
                data=f.read(),
                file_name=output_path.name,
                mime="application/vnd.ms-excel.sheet.macroEnabled.12",
            )

    except Exception as exc:
        if "progress_bar" in locals():
            progress_bar.progress(100)
        if "progress_text" in locals():
            progress_text.error("Generation failed.")

        st.error("Workbook generation failed after finalizing Dropbox assets.")
        if "finished_folder_path" in locals():
            st.write(f"Finalized folder path: `{finished_folder_path}`")
        if "final_sku" in locals():
            st.write(f"Finalized SKU: `{final_sku}`")
        st.exception(exc)




    record_load_event(
        "Total: reached end of main",
        st.session_state.get("current_rerun_started_at", time.perf_counter()),
    )
    save_completed_load_events()


if __name__ == "__main__":
    main()





