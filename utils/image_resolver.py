# utils/image_resolver.py

from __future__ import annotations

from typing import Any

from utils.dropbox_client import file_exists, get_or_create_shared_link, to_direct_url


def build_full_path(root: str, relative: str) -> str:
    return f"{root.rstrip('/')}/{relative.lstrip('/')}"


def resolve_one(path: str, label: str) -> dict[str, Any]:
    exists = file_exists(path)
    if not exists:
        return {
            "label": label,
            "path": path,
            "exists": False,
            "shared_url": "",
            "direct_url": "",
        }

    shared_url = get_or_create_shared_link(path)
    direct_url = to_direct_url(shared_url)

    return {
        "label": label,
        "path": path,
        "exists": True,
        "shared_url": shared_url,
        "direct_url": direct_url,
    }


def resolve_dropbox_images(profile: dict[str, Any], dropbox_cfg: dict[str, Any]) -> dict[str, Any]:
    template_key = profile.get("template_key", "")
    template_block = dropbox_cfg.get("templates", {}).get(template_key, {})

    root_folder = dropbox_cfg.get("root_folder", "")
    resource_root = dropbox_cfg.get("template_resource_root", "1_Resources")
    variant_folder = template_block.get("variant_folder", template_key)

    parent_images = []
    for name in dropbox_cfg.get("general_parent_images", []):
        path = build_full_path(root_folder, name)
        parent_images.append(resolve_one(path, label=name))

    shared_resource_images = []
    for name in dropbox_cfg.get("general_resource_images", []):
        path = build_full_path(root_folder, name)
        shared_resource_images.append(resolve_one(path, label=name))

    color_images: dict[str, dict[str, Any]] = {}
    for color, filename in template_block.get("main_image_map", {}).items():
        rel = f"{resource_root}/{variant_folder}/{filename}"
        path = build_full_path(root_folder, rel)
        color_images[color] = resolve_one(path, label=filename)

    return {
        "parent_images": parent_images,
        "shared_resource_images": shared_resource_images,
        "color_images": color_images,
    }