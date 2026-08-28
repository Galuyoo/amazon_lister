from __future__ import annotations

import sys
from unittest.mock import Mock

import pytest
from dropbox.exceptions import ApiError
from requests.exceptions import ConnectionError

from utils import dropbox_client


@pytest.fixture(scope="module", autouse=True)
def clean_up_client_module_after_tests():
    yield
    dropbox_client.reset_dropbox_client()
    sys.modules.pop("utils.dropbox_client", None)


def test_public_dropbox_helper_api_remains_importable() -> None:
    from utils.dropbox_client import (
        copy_dropbox_file,
        create_folder_exclusive,
        create_folder_if_missing,
        format_dropbox_error,
        list_folder_names,
        move_dropbox_folder,
        path_exists,
        upload_text_file,
    )

    assert all(callable(helper) for helper in (
        format_dropbox_error,
        list_folder_names,
        create_folder_if_missing,
        move_dropbox_folder,
        path_exists,
        upload_text_file,
        create_folder_exclusive,
        copy_dropbox_file,
    ))


def test_server_side_file_copy_disables_autorename(monkeypatch) -> None:
    client = Mock()
    client.files_copy_v2.return_value.metadata.path_display = "/ready/child/image.png"
    monkeypatch.setattr(dropbox_client, "get_dropbox_client", Mock(return_value=client))

    result = dropbox_client.copy_dropbox_file("/_stage/source/image.png", "/ready/child/image.png")

    assert result == "/ready/child/image.png"
    client.files_copy_v2.assert_called_once_with(
        from_path="/_stage/source/image.png",
        to_path="/ready/child/image.png",
        autorename=False,
    )


def test_dropbox_client_has_bounded_timeout_and_sdk_retries(monkeypatch) -> None:
    client = Mock()
    client.users_get_current_account.return_value = object()
    constructor = Mock(return_value=client)
    monkeypatch.setattr(dropbox_client.dropbox, "Dropbox", constructor)
    monkeypatch.setattr(dropbox_client, "get_secret_value", lambda _key: "configured")
    dropbox_client.reset_dropbox_client()

    assert dropbox_client.get_dropbox_client() is client

    assert constructor.call_args.kwargs["timeout"] == 30
    assert constructor.call_args.kwargs["max_retries_on_error"] == 4
    assert constructor.call_args.kwargs["max_retries_on_rate_limit"] == 4
    dropbox_client.reset_dropbox_client()


def test_folder_list_rebuilds_client_and_retries_transient_failure(monkeypatch) -> None:
    read_once = Mock(side_effect=[ConnectionError("temporary"), ["Folder A"]])
    reset_client = Mock()
    sleep = Mock()
    monkeypatch.setattr(dropbox_client, "_list_folder_names_once", read_once)
    monkeypatch.setattr(dropbox_client, "reset_dropbox_client", reset_client)
    monkeypatch.setattr(dropbox_client.time, "sleep", sleep)

    assert dropbox_client.list_folder_names("/Amazon/_stage") == ["Folder A"]
    assert read_once.call_count == 2
    reset_client.assert_called_once_with()
    sleep.assert_called_once_with(0.75)


def test_folder_list_retries_dropbox_api_error_without_route_details(monkeypatch) -> None:
    incomplete_response = ApiError("request-id", None, None, None)
    read_once = Mock(side_effect=[incomplete_response, ["Folder A"]])
    reset_client = Mock()
    monkeypatch.setattr(dropbox_client, "_list_folder_names_once", read_once)
    monkeypatch.setattr(dropbox_client, "reset_dropbox_client", reset_client)
    monkeypatch.setattr(dropbox_client.time, "sleep", Mock())

    assert dropbox_client.list_folder_names("/Amazon/_stage") == ["Folder A"]
    assert read_once.call_count == 2
    reset_client.assert_called_once_with()
    assert "temporary API response" in dropbox_client.format_dropbox_error(incomplete_response)


def test_folder_list_does_not_retry_configuration_error(monkeypatch) -> None:
    read_once = Mock(side_effect=ValueError("Missing Dropbox credentials"))
    reset_client = Mock()
    monkeypatch.setattr(dropbox_client, "_list_folder_names_once", read_once)
    monkeypatch.setattr(dropbox_client, "reset_dropbox_client", reset_client)

    with pytest.raises(ValueError, match="Missing Dropbox credentials"):
        dropbox_client.list_folder_names("/Amazon/_stage")

    read_once.assert_called_once_with("/Amazon/_stage")
    reset_client.assert_not_called()


def test_dropbox_error_messages_distinguish_auth_and_network_failures() -> None:
    assert "authentication failed" in dropbox_client.format_dropbox_error(
        ValueError("Dropbox authentication failed.")
    ).lower()
    assert "network" in dropbox_client.format_dropbox_error(
        ConnectionError("connection timed out")
    ).lower()


def test_exclusive_folder_create_raises_on_existing_destination(monkeypatch) -> None:
    client = Mock()
    client.files_create_folder_v2.side_effect = ApiError(
        "request-id",
        "path/conflict/folder",
        None,
        None,
    )
    monkeypatch.setattr(dropbox_client, "get_dropbox_client", Mock(return_value=client))

    with pytest.raises(FileExistsError, match="already exists"):
        dropbox_client.create_folder_exclusive("/Amazon/_stage/ADMIN-MPN-001")

    client.files_create_folder_v2.assert_called_once_with(
        "/Amazon/_stage/ADMIN-MPN-001",
        autorename=False,
    )


def test_strict_path_check_only_treats_not_found_as_missing(monkeypatch) -> None:
    client = Mock()
    client.files_get_metadata.side_effect = ApiError("request-id", "path/not_found", None, None)
    monkeypatch.setattr(dropbox_client, "get_dropbox_client", Mock(return_value=client))

    assert dropbox_client.path_exists_strict("/Amazon/_stage/NEW-MPN") is False

    client.files_get_metadata.side_effect = ApiError("request-id", None, None, None)
    with pytest.raises(ValueError, match="path check failed"):
        dropbox_client.path_exists_strict("/Amazon/_stage/NEW-MPN")
