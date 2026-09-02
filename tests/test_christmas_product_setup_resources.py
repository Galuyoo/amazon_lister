from __future__ import annotations

import inspect
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import app
from ui import product_setup


PNG_BYTES = b"\x89PNG\r\n\x1a\nimage-data"
JPG_BYTES = b"\xff\xd8\xffimage-data"


def load_dropbox_config() -> dict:
    return json.loads(Path("config/dropbox_templates.json").read_text(encoding="utf-8"))


def test_christmas_resource_group_config_matches_dropbox_folders() -> None:
    cp_config = load_dropbox_config()["templates"]["CP"]

    assert cp_config["variant_folder"] == "CP"
    assert cp_config["resource_groups_folder"] == "Christmas Project"
    assert cp_config["resource_groups"] == [
        {"key": "tshirt", "label": "Shirt", "folder": "Shirt"},
        {"key": "sweatshirt", "label": "Sweatshirt", "folder": "Sweatshirt"},
        {"key": "hoodie", "label": "Hoodie", "folder": "Hoodie"},
    ]


def test_dropbox_overview_loads_christmas_shared_and_group_resources(monkeypatch) -> None:
    config = load_dropbox_config()
    resource_root = config["resource_root"].rstrip("/")
    christmas_root = f"{resource_root}/Christmas Project"
    files_by_folder = {
        f"{resource_root}/CP": [f"{resource_root}/CP/T01 T02 Black.png"],
        christmas_root: [f"{christmas_root}/Options Note.png", f"{christmas_root}/ignore.txt"],
        f"{christmas_root}/Shirt": [f"{christmas_root}/Shirt/shirt.jpg"],
        f"{christmas_root}/Sweatshirt": [f"{christmas_root}/Sweatshirt/sweatshirt.PNG"],
        f"{christmas_root}/Hoodie": [f"{christmas_root}/Hoodie/hoodie.jpeg"],
    }
    list_files = Mock(side_effect=lambda folder: files_by_folder[folder])
    monkeypatch.setattr(app, "list_folder_files", list_files)

    overview = app.build_dropbox_overview({"template_key": "CP"}, config)

    assert overview["garment_resource_group_root_images"] == [
        f"{christmas_root}/Options Note.png"
    ]
    assert overview["garment_resource_images"] == [
        f"{resource_root}/CP/T01 T02 Black.png"
    ]
    assert [group["key"] for group in overview["garment_resource_groups"]] == [
        "tshirt",
        "sweatshirt",
        "hoodie",
    ]
    assert [group["path"] for group in overview["garment_resource_groups"]] == [
        f"{christmas_root}/Shirt",
        f"{christmas_root}/Sweatshirt",
        f"{christmas_root}/Hoodie",
    ]
    assert [group["images"] for group in overview["garment_resource_groups"]] == [
        [f"{christmas_root}/Shirt/shirt.jpg"],
        [f"{christmas_root}/Sweatshirt/sweatshirt.PNG"],
        [f"{christmas_root}/Hoodie/hoodie.jpeg"],
    ]
    assert list_files.call_count == 5


def test_christmas_resource_upload_accepts_png_and_jpg(monkeypatch) -> None:
    create_folder = Mock()
    upload_binary = Mock(side_effect=lambda path, _content: path)
    monkeypatch.setattr(app, "create_folder_if_missing", create_folder)
    monkeypatch.setattr(app, "upload_binary_file", upload_binary)

    result = app.upload_resource_images_to_folder(
        "/resources/Christmas Project/Shirt",
        [("front.png", PNG_BYTES), ("back.JPG", JPG_BYTES)],
    )

    assert result == [
        "/resources/Christmas Project/Shirt/front.png",
        "/resources/Christmas Project/Shirt/back.JPG",
    ]
    create_folder.assert_called_once_with("/resources/Christmas Project/Shirt")
    assert upload_binary.call_count == 2


@pytest.mark.parametrize(
    "images",
    [
        [("invalid.png", JPG_BYTES)],
        [("same.png", PNG_BYTES), ("SAME.PNG", PNG_BYTES)],
    ],
)
def test_christmas_resource_upload_validates_all_files_before_writing(
    monkeypatch,
    images,
) -> None:
    create_folder = Mock()
    upload_binary = Mock()
    monkeypatch.setattr(app, "create_folder_if_missing", create_folder)
    monkeypatch.setattr(app, "upload_binary_file", upload_binary)

    with pytest.raises(ValueError):
        app.upload_resource_images_to_folder(
            "/resources/Christmas Project/Hoodie",
            images,
        )

    create_folder.assert_not_called()
    upload_binary.assert_not_called()


def test_product_setup_has_grouped_resource_upload_contract_and_normal_fallback() -> None:
    source = inspect.getsource(product_setup.render_product_setup)

    assert "if garment_resource_group_entries:" in source
    assert 'type=["png", "jpg", "jpeg"]' in source
    assert "accept_multiple_files=True" in source
    assert 'key=f"christmas_resource_{group_key}_upload"' in source
    assert 'key=f"christmas_resource_{group_key}_upload_btn"' in source
    assert "upload_resource_images_to_folder(" in source
    assert '"Christmas Project shared resources"' in source
    assert '"Fallback garment support images"' in source
    assert '"Fallback global resource images"' in source
