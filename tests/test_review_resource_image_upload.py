from __future__ import annotations

import inspect
from unittest.mock import Mock

import pytest

import app


PNG_BYTES = b"\x89PNG\r\n\x1a\nimage-data"
JPG_BYTES = b"\xff\xd8\xffimage-data"


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("support.png", PNG_BYTES),
        ("support.jpg", JPG_BYTES),
        ("support.JPEG", JPG_BYTES),
    ],
)
def test_review_resource_image_accepts_png_and_jpg(filename, content) -> None:
    assert app.validate_review_resource_image(filename, content) == filename


@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        ("support.webp", b"image", "must be PNG or JPG"),
        ("support.png", b"", "is empty"),
        ("support.png", JPG_BYTES, "not a valid PNG"),
        ("support.jpg", PNG_BYTES, "not a valid JPG"),
    ],
)
def test_review_resource_image_rejects_invalid_uploads(
    filename,
    content,
    message,
) -> None:
    with pytest.raises(ValueError, match=message):
        app.validate_review_resource_image(filename, content)


def test_review_resource_upload_targets_selected_ready_listing(monkeypatch) -> None:
    create_folder = Mock()
    upload_binary = Mock(return_value="/Amazon/ready/LISTING-1/resources/support.jpg")
    monkeypatch.setattr(app, "create_folder_if_missing", create_folder)
    monkeypatch.setattr(app, "upload_binary_file", upload_binary)

    result = app.upload_ready_review_resource_image(
        "/Amazon/ready/LISTING-1",
        "nested/path/support.jpg",
        JPG_BYTES,
    )

    assert result == "/Amazon/ready/LISTING-1/resources/support.jpg"
    create_folder.assert_called_once_with("/Amazon/ready/LISTING-1/resources")
    upload_binary.assert_called_once_with(
        "/Amazon/ready/LISTING-1/resources/support.jpg",
        JPG_BYTES,
    )


def test_review_images_tab_has_per_listing_resource_uploader_contract() -> None:
    source = inspect.getsource(app.render_ready_review_panel)

    assert '"Resource image"' in source
    assert 'type=["png", "jpg", "jpeg"]' in source
    assert 'key=f"{review_key_prefix}_resource_image_upload"' in source
    assert '"Upload resource image"' in source
    assert 'key=f"{review_key_prefix}_resource_image_upload_btn"' in source
    assert "upload_ready_review_resource_image(" in source
    assert "save_listing_inputs_json_to_dropbox" not in source[source.index('if active_review_section == "Images":'):source.index('if active_review_section == "Quality":')]
