from __future__ import annotations
from datetime import datetime
import time
import json
from copy import copy
from pathlib import Path
from typing import Any
from utils.image_resolver import resolve_one
import streamlit as st
from openpyxl import load_workbook
from itertools import product

from utils.dropbox_client import (
    get_or_create_shared_link,
    to_direct_url,
    list_folder_files,
    list_folder_names,
    create_folder_if_missing,
    move_dropbox_folder,
    path_exists,
    file_exists,
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

    for folder in sorted(TEMPLATES_DIR.iterdir()):
        if not folder.is_dir():
            continue

        config_path = folder / "config.json"
        if not config_path.exists():
            continue

        try:
            with config_path.open("r", encoding="utf-8") as f:
                config = json.load(f)
            config["_folder"] = folder
            config["_slug"] = folder.name
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

def build_variant_combinations(selected_variants: dict[str, list[str]]) -> list[dict[str, str]]:
    keys = list(selected_variants.keys())
    if not keys:
        return []

    value_lists = [selected_variants[k] for k in keys]
    combos = []

    for values in product(*value_lists):
        combos.append(dict(zip(keys, values)))

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


def generate_unique_sku(prefix: str = "AMZ") -> str:
    return f"{prefix}{datetime.now().strftime('%y%m%d%H%M%S')}"


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
        "parent_sku": payload.get("parent_sku", ""),
        "title": payload.get("title", ""),
        "brand_name": payload.get("brand_name", ""),
        "manufacturer": payload.get("manufacturer", ""),
        "recommended_browse_nodes": payload.get("recommended_browse_nodes", ""),
        "product_description": payload.get("product_description", ""),
        "generic_keywords": payload.get("generic_keywords", ""),
        "bullet_points": payload.get("bullet_points", []),
        "selected_variants": payload.get("selected_variants", {}),
        "size_price_map": payload.get("size_price_map", {}),
        "quantity": payload.get("quantity", 0),
        "department_name": payload.get("department_name", ""),
        "target_gender": payload.get("target_gender", ""),
        "age_range_description": payload.get("age_range_description", ""),
        "feed_product_type": payload.get("feed_product_type", ""),
        "variation_theme": payload.get("variation_theme", ""),
        "product_category": payload.get("product_category", ""),
        "condition_type": payload.get("condition_type", ""),
        "item_type_name": payload.get("item_type_name", ""),
        "material_type": payload.get("material_type", ""),
        "style_name": payload.get("style_name", ""),
        "care_instructions": payload.get("care_instructions", ""),
        "theme": payload.get("theme", ""),
        "extra_fields": payload.get("extra_fields", {}),
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

def split_finished_folder_images(folder_path: str) -> tuple[str, list[str]]:
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
) -> list[dict[str, str]]:
    template_key = profile.get("template_key", "")
    templates_map = dropbox_cfg.get("templates", {})
    template_block = templates_map.get(template_key, {})

    resource_root = dropbox_cfg.get("resource_root", "").rstrip("/")
    variant_folder = template_block.get("variant_folder", template_key)
    combo_map = template_block.get("design_color_image_map", {})

    selected_colors = selected_variants.get("color", [])
    selected_designs = selected_variants.get("design", [])

    rows: list[dict[str, str]] = []

    for color in selected_colors:
        design_map = combo_map.get(color, {})
        for design in selected_designs:
            filename = design_map.get(design, "")
            path = f"{resource_root}/{variant_folder}/{filename}" if filename else ""
            rows.append({
                "color": color,
                "design": design,
                "path": path,
            })

    return rows


def render_design_color_grid(
    rows: list[dict[str, str]],
    cols_per_row: int = 5,
    image_width: int = 150,
) -> None:
    st.markdown("**Design/colour image mapping**")

    if not rows:
        st.caption("No design/colour combinations configured.")
        return

    cols = st.columns(cols_per_row)
    for idx, row in enumerate(rows):
        with cols[idx % cols_per_row]:
            label = f"{row['color']} / {row['design']}"
            st.caption(label)

            path = row.get("path", "")
            if not path:
                st.warning("Missing")
                continue

            try:
                result = resolve_one(path, label)
                if result["exists"] and result["direct_url"]:
                    st.image(result["direct_url"], width=image_width)
                else:
                    st.warning("Not found")
                    st.code(path, language=None)
            except Exception as exc:
                st.error(str(exc))
                st.code(path, language=None)    

def render_variant_combinations_preview(
    profile: dict[str, Any],
    parent_sku: str,
    selected_variants: dict[str, list[str]],
) -> None:
    combos = build_variant_combinations(selected_variants)

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

    color_paths: dict[str, str] = {}
    for color, filename in template_block.get("main_image_map", {}).items():
        color_paths[color] = f"{resource_root}/{variant_folder}/{filename}"

    design_color_paths: dict[str, dict[str, str]] = {}
    for color, design_map in template_block.get("design_color_image_map", {}).items():
        design_color_paths[color] = {}
        for design, filename in design_map.items():
            design_color_paths[color][design] = f"{resource_root}/{variant_folder}/{filename}"

    return {
        "resource_root": resource_root,
        "template_key": template_key,
        "variant_folder": variant_folder,
        "shared_resource_images": shared_resource_images,
        "color_paths": color_paths,
        "design_color_paths": design_color_paths,
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

def resolve_workbook_image_urls(
    selected_colors: list[str],
    dropbox_overview: dict[str, Any],
    finished_folder_path: str,
) -> tuple[str, list[str], dict[str, str], dict[str, dict[str, str]]]:
    finished_main_path, finished_other_paths = split_finished_folder_images(finished_folder_path)
    shared_resource_images = dropbox_overview.get("shared_resource_images", [])
    color_paths = dropbox_overview.get("color_paths", {})
    design_color_paths = dropbox_overview.get("design_color_paths", {})

    parent_main_image_url = dropbox_preview_url(finished_main_path) if finished_main_path else ""

    other_images: list[str] = []
    for path in finished_other_paths + shared_resource_images:
        url = dropbox_preview_url(path)
        if url:
            other_images.append(url)

    color_image_map: dict[str, str] = {}
    for color in selected_colors:
        path = color_paths.get(color, "")
        if not path:
            continue
        url = dropbox_preview_url(path)
        if url:
            color_image_map[color] = url

    design_color_image_url_map: dict[str, dict[str, str]] = {}
    for color in selected_colors:
        design_map = design_color_paths.get(color, {})
        design_color_image_url_map[color] = {}
        for design, path in design_map.items():
            if not path:
                continue
            url = dropbox_preview_url(path)
            if url:
                design_color_image_url_map[color][design] = url

    return (
        parent_main_image_url,
        other_images,
        color_image_map,
        design_color_image_url_map,
    )

def render_path_grid(
    title: str,
    paths: list[str],
    cols_per_row: int = 5,
    image_width: int = 150,
) -> None:
    st.markdown(f"**{title}**")
    if not paths:
        st.caption("No files configured.")
        return

    cols = st.columns(cols_per_row)
    for idx, path in enumerate(paths):
        with cols[idx % cols_per_row]:
            st.caption(Path(path).name)
            try:
                result = resolve_one(path, Path(path).name)
                if result["exists"] and result["direct_url"]:
                    st.image(result["direct_url"], width=image_width)
                else:
                    st.warning("Not found")
                    st.code(path, language=None)
            except Exception as exc:
                st.error(str(exc))
                st.code(path, language=None)


def render_color_grid(
    colors: list[str],
    color_paths: dict[str, str],
    cols_per_row: int = 5,
    image_width: int = 150,
) -> None:
    st.markdown("**Colour image mapping**")
    if not colors:
        st.caption("No colours configured.")
        return

    cols = st.columns(cols_per_row)
    for idx, color in enumerate(colors):
        with cols[idx % cols_per_row]:
            st.caption(color)
            path = color_paths.get(color, "")
            if not path:
                st.warning("Missing")
                continue

            try:
                result = resolve_one(path, color)
                if result["exists"] and result["direct_url"]:
                    st.image(result["direct_url"], width=image_width)
                else:
                    st.warning("Not found")
                    st.code(path, language=None)
            except Exception as exc:
                st.error(str(exc))
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

    cols_per_row = 4
    cols = st.columns(cols_per_row)
    size_price_map: dict[str, float] = {}

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
        "country_of_origin": "United Kingdom",
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

    values.update(data.get("extra_fields", {}))

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
    variant_combos = build_variant_combinations(selected_variants)

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
            "country_of_origin": "United Kingdom",

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

        values.update(data.get("extra_fields", {}))

        values.update(variant_field_values)

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

def get_extra_fields(profile: dict[str, Any]) -> dict[str, Any]:
    return profile.get("extra_fields", {})

def debug_find_headers(header_map: dict[str, int], patterns: list[str]) -> None:
    st.write("Header matches:")
    for pattern in patterns:
        matches = [key for key in header_map.keys() if pattern.lower() in key.lower()]
        st.write(f"{pattern}: {matches}")



def build_workbook(profile: dict[str, Any], payload: dict[str, Any]) -> tuple[Path, dict[str, float]]:
    template_file = profile.get("template_file", "")
    template_path = (BASE_DIR / "templates" / template_file).resolve()

    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    t0 = time.perf_counter()
    wb = load_workbook(template_path, keep_vba=True)
    t1 = time.perf_counter()

    ws = wb[SHEET_NAME]
    header_map = build_header_map(ws, HEADER_ROW)

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
        st.error("No template profiles found. Create folders under templates/ with a config.json and base .xlsm file.")
        st.stop()

    labels = [profile.get("label", profile["_slug"]) for profile in profiles]
    selected_label = st.sidebar.selectbox(
        "Listing template",
        labels,
        key="listing_template_select",
    )

    st.subheader("Recovery tools")

    with st.expander("Re-stage finished folder", expanded=False):
        if not finished_folder_names:
            st.caption("No finished folders available.")
        else:
            selected_finished_folder = st.selectbox(
                "Finished folder to move back to stage",
                finished_folder_names,
                index=None,
                placeholder="Select a finished folder",
                key="restage_finished_folder",
            )

            if st.button("Move finished folder back to stage", key="restage_button"):
                if not selected_finished_folder:
                    st.error("Select a finished folder first.")
                else:
                    try:
                        moved_path = restage_finished_dropbox_folder(
                            dropbox_cfg=dropbox_cfg,
                            finished_folder_name=selected_finished_folder,
                        )

                        st.session_state.pop("finalized_stage_folder", None)
                        st.session_state.pop("finalized_finished_folder_path", None)
                        st.session_state.pop("finalized_sku", None)

                        st.success(f"Finished folder moved back to stage: {moved_path}")
                    except Exception as exc:
                        st.error(f"Could not re-stage finished folder: {exc}")

    profile = profiles[labels.index(selected_label)]

    st.sidebar.markdown("### Active template")
    st.sidebar.write(f"Folder: `{profile['_slug']}`")
    st.sidebar.write(f"Workbook: `{profile.get('template_file', '')}`")
    st.sidebar.write(f"Variation theme: `{profile.get('variation_theme', '')}`")
    st.sidebar.checkbox("Show troubleshooting debug", key="show_header_debug", value=False)
    st.sidebar.checkbox("Copy row styles", key="copy_row_styles", value=True)

    colors_available = profile.get("colors", [])
    sizes_available = profile.get("sizes", [])
    dropbox_overview = build_dropbox_overview(profile, dropbox_cfg)

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

        staged_folder_name = st.selectbox(
            "Staged Dropbox folder",
            staged_folder_names,
            index=None,
            placeholder="Select a staged folder",
        )

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

    st.subheader("Description and search terms")

    product_description = st.text_area(
        "Product description",
        height=120,
        key="product_description",
        value=listing_memory.get("product_description", ""),
    )

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

            selected_variants[dim_name] = st.multiselect(
                dim_label,
                dim_options,
                default=default_options,
                key=f"variant_{dim_name}",
            )
    else:
        saved_selected_variants = listing_memory.get("selected_variants", {})

        selected_colors = st.multiselect(
            "Colours",
            colors_available,
            default=saved_selected_variants.get("color", colors_available),
            key="selected_colours",
        )
        selected_sizes = st.multiselect(
            "Sizes",
            sizes_available,
            default=saved_selected_variants.get("size", sizes_available),
            key="selected_sizes",
        )
        selected_variants = {
            "color": selected_colors,
            "size": selected_sizes,
        }
        
    design_color_preview_rows = build_design_color_preview_paths(
        profile=profile,
        dropbox_cfg=dropbox_cfg,
        selected_variants=selected_variants,
    )

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

            tab_names = ["Staged images", "Shared resources", "Colour variants", "Variant combinations"]
            stage_tab, resources_tab, colours_tab, combos_tab = st.tabs(tab_names)

            with stage_tab:
                if not staged_folder_name:
                    st.caption("Select a staged Dropbox folder to preview its images.")
                else:
                    st.write(f"Stage folder: `{staged_folder_name}`")
                    render_path_grid(
                        "Selected staged images",
                        staged_preview_paths,
                        cols_per_row=5,
                        image_width=150,
                    )

            with resources_tab:
                render_path_grid(
                    "Shared resource images",
                    dropbox_overview["shared_resource_images"],
                    cols_per_row=5,
                    image_width=150,
                )

            with colours_tab:
                render_color_grid(
                    colors_available,
                    dropbox_overview.get("color_paths", {}),
                    cols_per_row=5,
                    image_width=150,
                )

            with combos_tab:
                render_design_color_grid(
                    design_color_preview_rows,
                    cols_per_row=5,
                    image_width=150,
                )    

    submitted = st.button("Generate workbook")

    if not submitted:
        return

    product_description = st.session_state.get("product_description", "").strip()
    generic_keywords = st.session_state.get("generic_keywords", "").strip()

    if not title.strip():
        st.error("Title is required.")
        st.stop()

    variation_theme = profile.get("variation_theme", "SizeColor")

    variant_dimension_errors = validate_variant_dimensions(selected_variants)
    if variant_dimension_errors:
        for err in variant_dimension_errors:
            st.error(err)
        st.stop()

    if any(not bullet.strip() for bullet in bullets):
        st.error("All five bullet points are required.")
        st.stop()

    variation_theme = profile.get("variation_theme", "SizeColor")

    selected_sizes = selected_variants.get("size", [])

    if "Size" in variation_theme:
        invalid_prices = [size for size in selected_sizes if size_price_map.get(size, 0) <= 0]
        if invalid_prices:
            st.error(f"Prices must be greater than 0 for sizes: {', '.join(invalid_prices)}")
            st.stop()
    else:
        if not size_price_map or all(price <= 0 for price in size_price_map.values()):
            st.error("At least one valid price is required.")
            st.stop()

    if not staged_folder_name:
        st.error("Select a staged Dropbox folder.")
        st.stop()

    parent_sku_from_config = str(get_default(profile, "parent_sku", "")).strip()

    if not parent_sku_from_config:
        st.error("This template is missing parent_sku in its config.")
        st.stop()

    selected_colors = selected_variants.get("color", [])
    selected_sizes = selected_variants.get("size", [])

    # Build a pre-validation payload first, before moving anything
    preview_parent_sku = parent_sku_from_config

    payload = {
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
        "material_type": profile.get("material_type", ""),
        "style_name": profile.get("style_name", ""),
        "care_instructions": profile.get("care_instructions", ""),
        "theme": profile.get("theme", ""),
        "extra_fields": get_extra_fields(profile),
        "parent_main_image_url": "",
        "product_description": product_description.strip(),
        "generic_keywords": generic_keywords.strip(),
        "bullet_points": [bullet.strip() for bullet in bullets],
        "selected_variants": selected_variants,
        "colors": selected_colors,
        "sizes": selected_sizes,
        "other_images": [],
        "color_image_map": {},
        "design_color_image_url_map": {},
            }

    payload_errors = validate_payload(payload)
    if payload_errors:
        for err in payload_errors:
            st.error(err)
        st.stop()

    variant_errors = validate_variants(
        selected_variants,
        size_price_map,
        quantity,
    )
    if variant_errors:
        for err in variant_errors:
            st.error(err)
        st.stop()

    structure_errors = validate_parent_child_structure(payload)
    if structure_errors:
        for err in structure_errors:
            st.error(err)
        st.stop()         

    try:
        progress_text = st.empty()
        progress_bar = st.progress(0)

        t0 = time.perf_counter()

        if st.session_state.get("finalized_stage_folder") == staged_folder_name:
            progress_text.error("This staged folder was already finalized in the current session.")
            st.stop()

        progress_text.write("Moving staged folder into finished...")
        progress_bar.progress(10)

        final_sku, finished_folder_path = finalize_staged_dropbox_folder(
            dropbox_cfg=dropbox_cfg,
            staged_folder_name=staged_folder_name,
            parent_sku=parent_sku_from_config,
        )
        t1 = time.perf_counter()

        st.session_state["finalized_stage_folder"] = staged_folder_name
        st.session_state["finalized_finished_folder_path"] = finished_folder_path
        st.session_state["finalized_sku"] = final_sku

        progress_text.write("Fetching Dropbox image links...")
        progress_bar.progress(35)

        parent_main_image_url, other_images, color_image_map, design_color_image_url_map = resolve_workbook_image_urls(
            selected_colors,
            dropbox_overview,
            finished_folder_path,
        )
        t2 = time.perf_counter()

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

        t3 = time.perf_counter()

        progress_text.write("Finalizing output...")
        progress_bar.progress(95)

        variant_combos = build_variant_combinations(selected_variants)
        child_count = len(variant_combos)

        progress_bar.progress(100)
        progress_text.success("Workbook generated successfully.")

        st.success(f"Workbook generated successfully: {output_path.name}")
        st.info(f"Generated 1 parent row and {child_count} child variants.")

        with st.expander("Performance breakdown", expanded=False):
            st.write(f"Move staged folder: {t1 - t0:.2f}s")
            st.write(f"Resolve Dropbox image URLs: {t2 - t1:.2f}s")
            st.write(f"Build workbook: {t3 - t2:.2f}s")
            st.write(f"Total: {t3 - t0:.2f}s")
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