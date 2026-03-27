from __future__ import annotations

import json
from copy import copy
from pathlib import Path
from typing import Any
from utils.image_resolver import resolve_one
import streamlit as st
from openpyxl import load_workbook

from utils.dropbox_client import get_or_create_shared_link, to_direct_url, list_folder_files

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

    if missing_fields:
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

def slugify_part(value: str) -> str:
    safe = value.strip().replace(" ", "-").replace("/", "-")
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe


def build_child_sku(profile: dict[str, Any], color: str, size: str) -> str:
    color_sku_map = profile.get("color_sku_map", {})
    size_code_map = profile.get("size_code_map", {})
    variation_theme = profile.get("variation_theme", "SizeColor")

    color_base = color_sku_map.get(color)
    size_code = size_code_map.get(size)

    if variation_theme == "Color":
        if color_base:
            return color_base
        parent_sku = str(profile.get("parent_sku", "PARENT"))
        return f"{parent_sku}-{slugify_part(color)}"

    if variation_theme == "Size":
        parent_sku = str(profile.get("parent_sku", "PARENT"))
        if size_code:
            return f"{parent_sku}-{size_code}"
        return f"{parent_sku}-{slugify_part(size)}"

    if color_base and size_code:
        return f"{color_base}{size_code}"

    if color_base:
        return f"{color_base}-{slugify_part(size)}"

    parent_sku = str(profile.get("parent_sku", "PARENT"))
    return f"{parent_sku}-{slugify_part(color)}-{slugify_part(size)}"


def padded_list(values: list[str], target_len: int = 8) -> list[str]:
    trimmed = values[:target_len]
    return trimmed + [""] * (target_len - len(trimmed))

def is_image_file(path: str) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in {".png", ".jpg", ".jpeg", ".webp"}

def build_dropbox_overview(profile: dict[str, Any], dropbox_cfg: dict[str, Any]) -> dict[str, Any]:
    if not dropbox_cfg:
        return {}

    template_key = profile.get("template_key", "")
    templates_map = dropbox_cfg.get("templates", {})
    template_block = templates_map.get(template_key, {})

    root_folder = dropbox_cfg.get("root_folder", "")
    resource_root = dropbox_cfg.get("template_resource_root", "1_Resources")
    variant_folder = template_block.get("variant_folder", template_key)

    all_root_files = list_folder_files(root_folder)

    root_image_files = []
    for path in all_root_files:
        relative = path[len(root_folder):].lstrip("/")
        if "/" in relative:
            continue
        if is_image_file(path):
            root_image_files.append(path)

    parent_main_image = ""
    parent_other_images: list[str] = []

    for path in sorted(root_image_files):
        name = Path(path).name.lower()
        stem = Path(path).stem.lower()

        if stem == "main":
            parent_main_image = path
        else:
            parent_other_images.append(path)

    parent_images = [parent_main_image] + parent_other_images if parent_main_image else parent_other_images

    shared_resource_images = [
        f"{root_folder}/{name}"
        for name in dropbox_cfg.get("general_resource_images", [])
    ]

    color_paths: dict[str, str] = {}
    for color, filename in template_block.get("main_image_map", {}).items():
        color_paths[color] = f"{root_folder}/{resource_root}/{variant_folder}/{filename}"

    return {
        "root_folder": root_folder,
        "template_key": template_key,
        "variant_folder": variant_folder,
        "parent_images": parent_images,
        "shared_resource_images": shared_resource_images,
        "color_paths": color_paths,
        "main_image_map": template_block.get("main_image_map", {}),
    }


def resolve_workbook_image_urls(
    selected_colors: list[str],
    dropbox_overview: dict[str, Any],
) -> tuple[str, list[str], dict[str, str]]:
    parent_images = dropbox_overview.get("parent_images", [])
    shared_resource_images = dropbox_overview.get("shared_resource_images", [])
    color_paths = dropbox_overview.get("color_paths", {})

    parent_main_image_url = dropbox_preview_url(parent_images[0]) if parent_images else ""

    other_image_candidates = parent_images[1:] + shared_resource_images
    other_images: list[str] = []
    for path in other_image_candidates:
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

    return parent_main_image_url, other_images, color_image_map


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

    # Split on commas first, since Amazon search terms are usually entered that way
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

def build_size_price_inputs(sizes: list[str]) -> dict[str, float]:
    st.markdown("**Price by size**")
    if not sizes:
        st.caption("No sizes configured.")
        return {}

    cols_per_row = 4
    cols = st.columns(cols_per_row)
    size_price_map: dict[str, float] = {}

    for idx, size in enumerate(sizes):
        with cols[idx % cols_per_row]:
            size_price_map[size] = st.number_input(
                f"{size} price",
                min_value=0.0,
                value=29.99,
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
    has_size = "Size" in variation_theme
    has_color = "Color" in variation_theme

    for color in data["colors"]:
        image_url = data.get("color_image_map", {}).get(color, "")
        for size in data["sizes"]:
            if row_idx != template_row:
                copy_row_format(ws, template_row, row_idx)
            clear_row_values(ws, row_idx)

            normalized_size = normalize_size(size)
            price = data["size_price_map"].get(size, 0)

            values = {
                "item_sku": build_child_sku(profile, color, size),
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

                "color_name": color if has_color else "",
                "size_name": normalized_size if has_size else "",
                "apparel_size": normalized_size if has_size and is_apparel else "",

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

                "apparel_size_system": "UK" if has_size and is_apparel else "",
                "apparel_size_class": "Alpha" if has_size and is_apparel else "",
                "apparel_body_type": "Regular" if is_apparel else "",
                "apparel_height_type": "Regular" if is_apparel else "",

                "item_type_name": data["item_type_name"],
                "country_of_origin": "United Kingdom",

                "fulfillment_availability#1.fulfillment_channel_code": "DEFAULT",
                "fulfillment_availability#1.quantity": data["quantity"],
                "fulfillment_availability#1.lead_time_to_ship_max_days": 5,
                "purchasable_offer[marketplace_id=A1F83G8C2ARO7P]#1.our_price#1.schedule#1.value_with_tax": price,

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

            if "dangerous_goods_regulation" in header_map:
                values["dangerous_goods_regulation"] = "Not Applicable"

            if "search_terms" in header_map:
                values["search_terms"] = trim_search_terms(data["generic_keywords"])

            write_values_with_debug(
                ws,
                row_idx,
                header_map,
                values,
                f"Child row {row_idx} ({color} / {size})",
            )

            row_idx += 1
            variants_written += 1

    return variants_written



def debug_find_headers(header_map: dict[str, int], patterns: list[str]) -> None:
    st.write("Header matches:")
    for pattern in patterns:
        matches = [key for key in header_map.keys() if pattern.lower() in key.lower()]
        st.write(f"{pattern}: {matches}")

def build_workbook(profile: dict[str, Any], payload: dict[str, Any]) -> Path:
    template_file = profile.get("template_file", "")
    template_path = (BASE_DIR / "templates" / template_file).resolve()

    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    wb = load_workbook(template_path, keep_vba=True)
    ws = wb[SHEET_NAME]
    header_map = build_header_map(ws, HEADER_ROW)

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
    variants_written = write_child_rows(ws, header_map, profile, payload)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_name = f"{payload['parent_sku']}_{profile['_slug']}_amazon_listing.xlsm"
    output_path = OUTPUT_DIR / output_name
    wb.save(output_path)

    if variants_written == 0:
        raise ValueError("No child variants were generated.")

    return output_path

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

    allowed_variation_themes = {"SizeColor", "Color", "Size", ""}
    if payload.get("variation_theme", "") not in allowed_variation_themes:
        errors.append("variation_theme must be one of: SizeColor, Color, Size, or empty.")

    allowed_product_categories = {"apparel", "accessory"}
    if payload.get("product_category", "") not in allowed_product_categories:
        errors.append("product_category must be either 'apparel' or 'accessory'.")

    return errors

def validate_variants(
    colors: list[str],
    sizes: list[str],
    size_price_map: dict[str, float],
    quantity: int,
    variation_theme: str,
) -> list[str]:
    errors: list[str] = []

    has_color = "Color" in variation_theme
    has_size = "Size" in variation_theme

    if has_color and not colors:
        errors.append("At least one colour is required.")

    if has_size and not sizes:
        errors.append("At least one size is required.")

    if quantity < 0:
        errors.append("Quantity cannot be negative.")

    if has_size:
        for size in sizes:
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

    allowed_variation_themes = {"SizeColor", "Color", "Size", ""}
    if payload.get("variation_theme", "") not in allowed_variation_themes:
        errors.append("variation_theme must be one of: SizeColor, Color, Size, or empty.")

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

    if not profiles:
        st.error("No template profiles found. Create folders under templates/ with a config.json and base .xlsm file.")
        st.stop()

    labels = [profile.get("label", profile["_slug"]) for profile in profiles]
    selected_label = st.sidebar.selectbox(
        "Listing template",
        labels,
        key="listing_template_select",
    )
    profile = profiles[labels.index(selected_label)]

    st.sidebar.markdown("### Active template")
    st.sidebar.write(f"Folder: `{profile['_slug']}`")
    st.sidebar.write(f"Workbook: `{profile.get('template_file', '')}`")
    st.sidebar.write(f"Variation theme: `{profile.get('variation_theme', '')}`")

    colors_available = profile.get("colors", [])
    sizes_available = profile.get("sizes", [])
    dropbox_overview = build_dropbox_overview(profile, dropbox_cfg)

    with st.sidebar.expander("Dropbox debug"):
        try:
            test_path = dropbox_overview["parent_images"][0] if dropbox_overview.get("parent_images") else ""
            st.write("Test path:", test_path)
            if test_path:
                st.write("Preview URL:", dropbox_preview_url(test_path))
        except Exception as exc:
            st.error(f"Dropbox debug failed: {exc}")

    col1, col2 = st.columns(2)

    with col1:
        parent_sku = st.text_input(
            "Parent SKU",
            value=str(get_default(profile, "parent_sku", "JH001")),
            disabled=True,
        )
        title = st.text_input("Product title")

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
    bullets = [
        st.text_input("Bullet 1"),
        st.text_input("Bullet 2"),
        st.text_input("Bullet 3"),
        st.text_input("Bullet 4"),
        st.text_input("Bullet 5"),
    ]

    st.subheader("Description and search terms")
    product_description = st.text_area("Product description", height=120, key="product_description")
    generic_keywords = st.text_area("Search terms", height=100, key="generic_keywords")

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
    selected_colors = st.multiselect(
        "Colours",
        colors_available,
        default=colors_available,
        key="selected_colours",
    )
    selected_sizes = st.multiselect(
        "Sizes",
        sizes_available,
        default=sizes_available,
        key="selected_sizes",
    )

    st.caption("Child SKUs are generated from config.json using color_sku_map + size_code_map.")
    size_price_map = build_size_price_inputs(selected_sizes)

    st.subheader("Inventory setup")
    quantity = st.number_input(
        "Quantity for all child variants",
        min_value=0,
        value=100,
        step=1,
        key="variant_quantity",
    )

    with st.expander("Dropbox image overview", expanded=True):
        if not dropbox_overview:
            st.warning("No shared Dropbox config loaded yet.")
        else:
            st.write(f"Root: `{dropbox_overview['root_folder']}`")
            st.write(f"Variant folder: `{dropbox_overview['variant_folder']}`")

            parent_tab, resources_tab, colours_tab = st.tabs(
                ["Parent images", "Shared resources", "Colour variants"]
            )

            with parent_tab:
                render_path_grid(
                    "Parent / general images",
                    dropbox_overview["parent_images"],
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

    submitted = st.button("Generate workbook")

    if not submitted:
        return

    product_description = st.session_state.get("product_description", "").strip()
    generic_keywords = st.session_state.get("generic_keywords", "").strip()

    if not title.strip():
        st.error("Title is required.")
        st.stop()

    variation_theme = profile.get("variation_theme", "SizeColor")

    if "Color" in variation_theme and not selected_colors:
        st.error("Select at least one colour.")
        st.stop()

    if "Size" in variation_theme and not selected_sizes:
        st.error("Select at least one size.")
        st.stop()

    if any(not bullet.strip() for bullet in bullets):
        st.error("All five bullet points are required.")
        st.stop()

    variation_theme = profile.get("variation_theme", "SizeColor")

    if "Size" in variation_theme:
        invalid_prices = [size for size in selected_sizes if size_price_map.get(size, 0) <= 0]
        if invalid_prices:
            st.error(f"Prices must be greater than 0 for sizes: {', '.join(invalid_prices)}")
            st.stop()
    else:
        if not size_price_map or all(price <= 0 for price in size_price_map.values()):
            st.error("At least one valid price is required.")
            st.stop()

    parent_main_image_url, other_images, color_image_map = resolve_workbook_image_urls(
        selected_colors,
        dropbox_overview,
    )

    payload = {
        "parent_sku": parent_sku.strip(),
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
        "parent_main_image_url": parent_main_image_url,
        "product_description": product_description.strip(),
        "generic_keywords": generic_keywords.strip(),
        "bullet_points": [bullet.strip() for bullet in bullets],
        "colors": selected_colors,
        "sizes": selected_sizes,
        "other_images": other_images,
        "color_image_map": color_image_map,
    }

    payload_errors = validate_payload(payload)
    if payload_errors:
        for err in payload_errors:
            st.error(err)
        st.stop()
        
    variant_errors = validate_variants(
        selected_colors,
        selected_sizes,
        size_price_map,
        quantity,
        payload["variation_theme"],
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
        output_path = build_workbook(profile, payload)
        variation_theme = payload["variation_theme"]
        color_count = len(selected_colors) if "Color" in variation_theme else 1
        size_count = len(selected_sizes) if "Size" in variation_theme else 1
        child_count = color_count * size_count

        st.success(f"Workbook generated successfully: {output_path.name}")
        st.info(f"Generated 1 parent row and {child_count} child variants.")

        with output_path.open("rb") as f:
            st.download_button(
                label="Download Amazon workbook",
                data=f.read(),
                file_name=output_path.name,
                mime="application/vnd.ms-excel.sheet.macroEnabled.12",
            )
    except Exception as exc:
        st.exception(exc)

if __name__ == "__main__":
    main()