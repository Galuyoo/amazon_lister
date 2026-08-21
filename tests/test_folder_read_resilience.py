from __future__ import annotations

import sys
from unittest.mock import Mock

import pytest
from requests.exceptions import ConnectionError

from utils import dropbox_client


@pytest.fixture(scope="module", autouse=True)
def clean_up_client_module_after_tests():
    yield
    dropbox_client.reset_dropbox_client()
    sys.modules.pop("utils.dropbox_client", None)


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
