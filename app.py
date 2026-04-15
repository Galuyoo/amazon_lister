from __future__ import annotations
from datetime import datetime
import time
import json
import re
import random
import string

from copy import copy
from pathlib import Path
from typing import Any
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

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
CONFIG_DIR = BASE_DIR / "config"
OUTPUT_DIR = BASE_DIR / "outputs"

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


def build_listing_memory_payload(profile: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return {
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
    }


def save_listing_memory_to_dropbox(
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

def apply_listing_memory_to_session(listing_memory: dict[str, Any], profile: dict[str, Any]) -> None:
    st.session_state["title_input"] = listing_memory.get("title", "")

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

    saved_selected_variants = listing_memory.get("selected_variants", {})
    variant_dimensions = profile.get("variant_dimensions", [])

    if variant_dimensions:
        for dim in variant_dimensions:
            dim_name = dim.get("name", "")
            st.session_state[f"variant_{dim_name}"] = saved_selected_variants.get(dim_name, dim.get("options", []))
    else:
        st.session_state["selected_colours"] = saved_selected_variants.get("color", profile.get("colors", []))
        st.session_state["selected_sizes"] = saved_selected_variants.get("size", profile.get("sizes", []))

def finalize_staged_dropbox_folder(
    dropbox_cfg: dict[str, Any],
    staged_folder_name: str,
    parent_sku: str,
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

    for _ in range(max_attempts):
        unique_sku = generate_unique_sku()
        final_sku = build_final_folder_sku(parent_sku, unique_sku)
        final_folder_path = build_finished_folder_path(dropbox_cfg, final_sku)

        if not path_exists(final_folder_path):
            moved_path = move_dropbox_folder(stage_path, final_folder_path)
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

    files = [p for p in list_folder_files(stage_folder_path) if is_image_file(p)]
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


def build_preview_image_cache_key(
    profile: dict[str, Any],
    dropbox_cfg: dict[str, Any],
    staged_folder_name: str,
    selected_variants: dict[str, list[str]],
) -> str:
    template_key = profile.get("template_key", "")
    cache_parts = {
        "template_key": template_key,
        "staged_folder_name": staged_folder_name,
        "selected_colors": selected_variants.get("color", []),
        "selected_designs": selected_variants.get("design", []),
        "template_cfg": dropbox_cfg.get("templates", {}).get(template_key, {}),
        "general_resource_images": dropbox_cfg.get("general_resource_images", []),
    }
    return json.dumps(cache_parts, sort_keys=True)


def get_cached_preview_image_data(
    profile: dict[str, Any],
    dropbox_cfg: dict[str, Any],
    staged_folder_name: str,
    selected_variants: dict[str, list[str]],
    dropbox_overview: dict[str, Any],
) -> dict[str, Any]:
    cache_key = build_preview_image_cache_key(
        profile,
        dropbox_cfg,
        staged_folder_name,
        selected_variants,
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
                entries.append({
                    "label": label,
                    "path": path,
                    "exists": False,
                    "direct_url": "",
                })
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
                entries.append({
                    "label": label,
                    "path": path,
                    "exists": False,
                    "direct_url": "",
                })
        return entries

    if staged_folder_name:
        try:
            preview_stage_folder_path = build_stage_folder_path(dropbox_cfg, staged_folder_name)
            _, _, preview_color_image_map, preview_design_color_image_url_map = resolve_folder_image_urls(
                profile,
                selected_variants,
                selected_variants.get("color", []),
                dropbox_overview,
                preview_stage_folder_path,
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

    staged_preview_entries = resolve_display_entries([
        (Path(path).name, path) for path in staged_preview_paths
    ])
    garment_resource_entries = resolve_display_entries([
        (Path(path).name, path) for path in dropbox_overview.get("garment_resource_images", [])
    ])
    global_resource_entries = resolve_display_entries([
        (Path(path).name, path) for path in dropbox_overview.get("shared_resource_images", [])
    ])

    stage_folder_path_for_preview = (
        build_stage_folder_path(dropbox_cfg, staged_folder_name)
        if staged_folder_name else ""
    )
    staged_variant_entries = resolve_display_entries([
        (
            color,
            f"{stage_folder_path_for_preview}/{dropbox_overview.get('main_image_map', {}).get(color, '')}"
            if stage_folder_path_for_preview and dropbox_overview.get("main_image_map", {}).get(color, "")
            else "",
        )
        for color in profile.get("colors", [])
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
    st.session_state["preview_image_cache"] = {
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

    use_same_price = st.checkbox(
        "Use one price for all sizes",
        value=default_same_price,
        key="use_same_price_for_all_sizes",
    )

    size_price_map: dict[str, float] = {}

    if use_same_price:
        fallback_price = 29.99
        if default_same_price and sizes:
            fallback_price = float(saved_prices.get(sizes[0], 29.99))

        shared_price = st.number_input(
            "Price for all sizes",
            min_value=0.0,
            value=float(fallback_price),
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
            size_price_map[size] = st.number_input(
                f"{size} price",
                min_value=0.0,
                value=float(saved_prices.get(size, 29.99)),
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
) -> dict[str, Any]:
    preview_parent_sku = str(get_default(profile, "parent_sku", "")).strip()
    preview_selected_colors = selected_variants.get("color", [])
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
        "other_images": [],
        "color_image_map": {},
        "design_color_image_url_map": {},
        "dynamic_profile_fields": {},
    }

    if staged_folder_name and preview_selected_colors:
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

    profiles = list_template_profiles()
    dropbox_cfg = load_dropbox_templates_config()

    stage_root = dropbox_cfg.get("stage_root", "")
    finished_root = dropbox_cfg.get("finished_root", "")

    if not stage_root or not finished_root:
        st.error("stage_root and finished_root must be set in config/dropbox_templates.json")
        st.stop()

    try:
        staged_folder_names = list_folder_names(stage_root)
        finished_folder_names = list_folder_names(finished_root)
    except Exception as exc:
        st.error(f"Could not read Dropbox folders: {exc}")
        st.stop()

    if not profiles:
        st.error("No template profiles found. Create family folders under templates/ with schema.json, a shared workbook, and garment subfolders containing config.json.")
        st.stop()

    families = sorted({profile.get("_family_slug", "") for profile in profiles if profile.get("_family_slug")})
    detection_message = ""
    detection_level = ""

    current_folder_source_mode = st.session_state.get("folder_source_mode", "Use staged folder")
    current_detect_folder = st.session_state.get("staged_folder_select", "") if current_folder_source_mode == "Use staged folder" else ""

    if current_detect_folder:
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

    selected_family = st.sidebar.selectbox(
        "Template family",
        families,
        key="template_family_select",
    )

    family_profiles = [
        profile for profile in profiles
        if profile.get("_family_slug") == selected_family
    ]

    family_labels = [profile.get("label", profile["_slug"]) for profile in family_profiles]

    selected_label = st.sidebar.selectbox(
        "Garment template",
        family_labels,
        key="listing_template_select",
    )

    profile = family_profiles[family_labels.index(selected_label)]

    if detection_message:
        if detection_level == "warning":
            st.sidebar.warning(detection_message)
        else:
            st.sidebar.info(detection_message)

    st.sidebar.markdown("### Active template")
    st.sidebar.write(f"Family: `{profile.get('_family_slug', '')}`")
    st.sidebar.write(f"Template: `{profile['_slug']}`")
    st.sidebar.write(f"Workbook: `{profile.get('template_file', '')}`")
    st.sidebar.write(f"Variation theme: `{profile.get('variation_theme', '')}`")
    st.sidebar.checkbox("Show troubleshooting debug", key="show_header_debug", value=False)
    st.sidebar.checkbox("Copy row styles", key="copy_row_styles", value=True)
    if st.sidebar.button("Reload images", use_container_width=True):
        st.session_state.pop("dropbox_overview_cache", None)
        st.session_state.pop("preview_image_cache", None)

    colors_available = profile.get("colors", [])
    sizes_available = profile.get("sizes", [])
    dropbox_overview = get_cached_dropbox_overview(profile, dropbox_cfg)

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


    parent_sku_from_config = str(get_default(profile, "parent_sku", "")).strip()

    col1, col2 = st.columns(2)

    with col1:
        # base_sku = st.text_input("Base SKU")
        st.text_input(
            "Parent SKU",
            value=parent_sku_from_config,
            disabled=True,
        )

        if st.session_state.pop("auto_switch_to_staged", False):
            st.session_state["folder_source_mode"] = "Use staged folder"        

        folder_source = st.radio(
            "Choose Folder Source",
            ["Use staged folder", "Restage finished folder"],
            horizontal=True,
            key="folder_source_mode",
        )

        staged_folder_name = None
        selected_finished_folder = None

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
                use_container_width=True,
            ):
                if not selected_finished_folder:
                    st.warning("Select a finished folder first.")
                    st.stop()

                try:
                    moved_path = restage_finished_dropbox_folder(
                        dropbox_cfg=dropbox_cfg,
                        finished_folder_name=selected_finished_folder,
                    )

                    st.success(f"Restaged successfully: {moved_path}")

                    st.session_state["last_loaded_listing_memory_folder"] = ""
                    st.session_state.pop("finalized_stage_folder", None)
                    st.session_state.pop("finalized_finished_folder_path", None)
                    st.session_state.pop("finalized_sku", None)
                    restaged_folder_name = Path(moved_path).name
                    st.session_state["staged_folder_select"] = restaged_folder_name
                    st.session_state["auto_switch_to_staged"] = True

                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not restage folder: {exc}")
                    st.stop()
        


        listing_memory: dict[str, Any] = {}
        if staged_folder_name:
            stage_folder_path = build_stage_folder_path(dropbox_cfg, staged_folder_name)
            try:
                listing_memory = load_listing_memory_from_dropbox(stage_folder_path)
                if listing_memory:
                    last_loaded_folder = st.session_state.get("last_loaded_listing_memory_folder")
                    if last_loaded_folder != staged_folder_name:
                        apply_listing_memory_to_session(listing_memory, profile)
                        st.session_state["last_loaded_listing_memory_folder"] = staged_folder_name
                    st.info("Loaded saved listing inputs from staged folder.")
            except Exception as exc:
                st.warning(f"Could not load saved listing inputs: {exc}")
        
        staged_preview_paths = build_stage_preview_paths(dropbox_cfg, staged_folder_name) if staged_folder_name else []

        title = st.text_input(
            "Product title",
            value=listing_memory.get("title", ""),
            key="title_input",
        )

        title_chars = len(title.strip())
        if title_chars < 150:
            st.caption(f"Title: {title_chars} chars - target 150 chars")
        else:
            st.caption(f"Title: {title_chars} chars - good")

    with col2:
        st.text_input("Brand", value=GLOBAL_BRAND_NAME, disabled=True)
        st.text_input("Manufacturer", value=str(get_default(profile, "manufacturer", "Generic")), disabled=True)
        st.text_input("Product type", value=str(get_default(profile, "feed_product_type", "")), disabled=True)
        st.text_input("Department", value=str(get_default(profile, "department_name", "")), disabled=True)
        st.text_input("Target gender", value=str(get_default(profile, "target_gender", "")), disabled=True)
        st.text_input("Age range", value=str(get_default(profile, "age_range_description", "Adult")), disabled=True)
        st.text_input("Material type", value=str(get_default(profile, "material_type", "")), disabled=True)
        st.text_input("Style", value=str(get_default(profile, "style_name", "")), disabled=True)
        st.text_input(
            "Recommended browse node",
            value=str(get_default(profile, "recommended_browse_nodes", "")),
            disabled=True,
        )

    st.subheader("Bullets")

    saved_bullets = listing_memory.get("bullet_points", [])
    saved_bullets = (saved_bullets + ["", "", "", "", ""])[:5]

    bullets = [
        st.text_input("Bullet 1", value=saved_bullets[0], key="bullet_1"),
        st.text_input("Bullet 2", value=saved_bullets[1], key="bullet_2"),
        st.text_input("Bullet 3", value=saved_bullets[2], key="bullet_3"),
        st.text_input("Bullet 4", value=saved_bullets[3], key="bullet_4"),
        st.text_input("Bullet 5", value=saved_bullets[4], key="bullet_5"),
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
        value=listing_memory.get("product_description", ""),
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
        value=listing_memory.get("generic_keywords", ""),
    )

    byte_count = len(generic_keywords.encode("utf-8"))
    max_bytes = 249

    if byte_count < max_bytes * 0.8:
        st.caption(f"🟢 {byte_count}/{max_bytes} bytes")
    elif byte_count <= max_bytes:
        st.warning(f"🟡 {byte_count}/{max_bytes} bytes (near limit)")
    else:
        st.error(f"🔴 {byte_count}/{max_bytes} bytes (too long)")

    trimmed_keywords = trim_search_terms(generic_keywords)
    if trimmed_keywords != generic_keywords.strip():
        st.warning("Search terms will be trimmed to fit Amazon limit:")
        st.code(trimmed_keywords)

    st.subheader("Variants")

    variant_dimensions = profile.get("variant_dimensions", [])

    selected_variants: dict[str, list[str]] = {}

    if variant_dimensions:
        saved_selected_variants = listing_memory.get("selected_variants", {})

        for dim in variant_dimensions:
            dim_name = dim.get("name", "")
            dim_label = dim.get("label", dim_name.title())
            dim_options = dim.get("options", [])
            default_options = saved_selected_variants.get(dim_name, dim_options)

            valid_default_options = [option for option in default_options if option in dim_options]

            selected_variants[dim_name] = st.multiselect(
                dim_label,
                dim_options,
                default=valid_default_options if valid_default_options else dim_options,
                key=f"variant_{dim_name}",
            )
    else:
        saved_selected_variants = listing_memory.get("selected_variants", {})

        saved_colors = saved_selected_variants.get("color", colors_available)
        saved_sizes = saved_selected_variants.get("size", sizes_available)

        valid_saved_colors = [color for color in saved_colors if color in colors_available]
        valid_saved_sizes = [size for size in saved_sizes if size in sizes_available]

        selected_colors = st.multiselect(
            "Colours",
            colors_available,
            default=valid_saved_colors if valid_saved_colors else colors_available,
            key="selected_colours",
        )

        if profile.get("color_size_map"):
            st.caption("Some colours have restricted size availability. Only valid combinations will be generated.")

        available_sizes_for_selected_colors = get_available_sizes_for_selected_colors(
            profile,
            selected_colors,
        )

        valid_saved_sizes = [
            size for size in saved_sizes
            if size in available_sizes_for_selected_colors
        ]

        selected_sizes = st.multiselect(
            "Sizes",
            available_sizes_for_selected_colors,
            default=valid_saved_sizes if valid_saved_sizes else available_sizes_for_selected_colors,
            key="selected_sizes",
        )


        selected_variants = {
            "color": selected_colors,
            "size": selected_sizes,
        }
        
    preview_image_data = get_cached_preview_image_data(
        profile=profile,
        dropbox_cfg=dropbox_cfg,
        staged_folder_name=staged_folder_name or "",
        selected_variants=selected_variants,
        dropbox_overview=dropbox_overview,
    )
    staged_preview_entries = preview_image_data.get("staged_preview_entries", [])
    design_color_preview_entries = preview_image_data.get("design_color_preview_entries", [])
    parent_main_image_options = preview_image_data.get("parent_main_image_options", [])
    garment_resource_entries = preview_image_data.get("garment_resource_entries", [])
    global_resource_entries = preview_image_data.get("global_resource_entries", [])
    staged_variant_entries = preview_image_data.get("staged_variant_entries", [])

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
        value=int(listing_memory.get("quantity", 100)),
        step=1,
        key="variant_quantity",
    )

    with st.expander("Dropbox image overview", expanded=True):
        if not dropbox_overview:
            st.warning("No shared Dropbox config loaded yet.")
        else:
            st.write(f"Resource root: `{dropbox_overview['resource_root']}`")
            st.write(f"Variant folder: `{dropbox_overview['variant_folder']}`")
            if dropbox_overview.get("garment_resource_warning"):
                st.warning(dropbox_overview["garment_resource_warning"])

            tab_names = ["Shared resources", "Staged variant images", "Variant combinations"]
            resources_tab, colours_tab, combos_tab = st.tabs(tab_names)

            with st.expander("Raw staged folder contents", expanded=False):
                if not staged_folder_name:
                    st.caption("Select a staged Dropbox folder to preview its images.")
                else:
                    st.write(f"Stage folder: `{staged_folder_name}`")
                    render_path_grid(
                        "Selected staged images",
                        staged_preview_entries,
                        cols_per_row=5,
                        image_width=150,
                    )

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

    st.caption("Check listing score to review quality before generating the workbook.")
    btn_col1, btn_col2 = st.columns(2)

    with btn_col1:
        score_clicked = st.button("Check listing score", use_container_width=True)

    with btn_col2:
        submitted = st.button("Generate workbook", use_container_width=True)

    if not score_clicked and not submitted:
        return

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
    )

    preview_payload = preflight["preview_payload"]
    all_preview_errors = preflight["all_preview_errors"]
    quality_report = preflight["quality_report"]

    render_preflight_dashboard(
        quality_report=quality_report,
        all_preview_errors=all_preview_errors,
    )

    render_listing_score_result(
        quality_report=quality_report,
        all_preview_errors=all_preview_errors,
    )

    if score_clicked and not submitted:
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
    generation_errors = generation_prep["errors"]
    selected_parent_main_label = st.session_state.get("parent_main_image_choice", "Automatic (recommended)")
    selected_parent_main_image_url = next(
        (url for label, url in parent_main_image_options if label == selected_parent_main_label),
        "",
    )

    if generation_errors:
        st.error("Fix the validation errors before generating.")
        st.stop()

    if quality_report["blockers"]:
        st.error("Fix the listing quality blockers before generating.")
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

if __name__ == "__main__":
    main()
