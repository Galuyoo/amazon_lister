# utils/dropbox_client.py
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from dropbox.files import WriteMode

import dropbox
from dropbox.exceptions import ApiError, AuthError
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


REQUIRED_DROPBOX_KEYS = (
    "DROPBOX_APP_KEY",
    "DROPBOX_APP_SECRET",
    "DROPBOX_REFRESH_TOKEN",
)


def get_secret_value(key: str) -> str:
    env_value = os.getenv(key)
    if env_value:
        return env_value

    try:
        import streamlit as st
    except Exception:
        return ""

    try:
        if key in st.secrets:
            secret_value = st.secrets[key]
            return str(secret_value) if secret_value else ""
    except Exception:
        return ""

    return ""


@lru_cache(maxsize=1)
def get_dropbox_client() -> dropbox.Dropbox:
    credentials = {key: get_secret_value(key) for key in REQUIRED_DROPBOX_KEYS}
    missing_keys = [key for key, value in credentials.items() if not value]

    if missing_keys:
        missing_keys_text = ", ".join(missing_keys)
        raise ValueError(
            f"Missing Dropbox credentials: {missing_keys_text}. "
            "Add them to .env locally or Streamlit secrets in deployment."
        )

    dbx = dropbox.Dropbox(
        oauth2_refresh_token=credentials["DROPBOX_REFRESH_TOKEN"],
        app_key=credentials["DROPBOX_APP_KEY"],
        app_secret=credentials["DROPBOX_APP_SECRET"],
    )

    try:
        dbx.users_get_current_account()
    except AuthError as exc:
        raise ValueError("Dropbox authentication failed.") from exc

    return dbx

def list_folder_files(path: str) -> list[str]:
    dbx = get_dropbox_client()
    entries = []

    result = dbx.files_list_folder(path)
    entries.extend(result.entries)

    while result.has_more:
        result = dbx.files_list_folder_continue(result.cursor)
        entries.extend(result.entries)

    files = []
    for entry in entries:
        if isinstance(entry, dropbox.files.FileMetadata):
            files.append(entry.path_display)

    return files

def list_folder_names(path: str) -> list[str]:
    dbx = get_dropbox_client()
    entries = []

    result = dbx.files_list_folder(path)
    entries.extend(result.entries)

    while result.has_more:
        result = dbx.files_list_folder_continue(result.cursor)
        entries.extend(result.entries)

    folders = []
    for entry in entries:
        if isinstance(entry, dropbox.files.FolderMetadata):
            folders.append(entry.name)

    return sorted(folders)


def create_folder_if_missing(path: str) -> None:
    dbx = get_dropbox_client()
    try:
        dbx.files_get_metadata(path)
    except ApiError:
        dbx.files_create_folder_v2(path)


def move_dropbox_folder(from_path: str, to_path: str) -> str:
    dbx = get_dropbox_client()
    try:
        result = dbx.files_move_v2(from_path=from_path, to_path=to_path, autorename=False)
        return result.metadata.path_display
    except ApiError as exc:
        raise ValueError(f"Dropbox folder move failed from {from_path} to {to_path}: {exc}") from exc

def path_exists(path: str) -> bool:
    dbx = get_dropbox_client()
    try:
        dbx.files_get_metadata(path)
        return True
    except ApiError:
        return False

def file_exists(path: str) -> bool:
    dbx = get_dropbox_client()
    try:
        metadata = dbx.files_get_metadata(path)
        return isinstance(metadata, dropbox.files.FileMetadata)
    except ApiError:
        return False


def get_or_create_shared_link(path: str) -> str:
    dbx = get_dropbox_client()

    try:
        links = dbx.sharing_list_shared_links(path=path, direct_only=True).links
        if links:
            return links[0].url

        settings = dropbox.sharing.SharedLinkSettings(
            requested_visibility=dropbox.sharing.RequestedVisibility.public
        )
        link = dbx.sharing_create_shared_link_with_settings(path, settings=settings)
        return link.url

    except ApiError as exc:
        raise FileNotFoundError(f"Dropbox shared link failed for {path}: {exc}") from exc


def to_direct_url(shared_url: str) -> str:
    if "?dl=0" in shared_url:
        return shared_url.replace("?dl=0", "?raw=1")
    if "&dl=0" in shared_url:
        return shared_url.replace("&dl=0", "&raw=1")
    if "?dl=1" in shared_url:
        return shared_url.replace("?dl=1", "?raw=1")
    return shared_url + ("&raw=1" if "?" in shared_url else "?raw=1")

def upload_text_file(path: str, content: str) -> str:
    dbx = get_dropbox_client()
    try:
        result = dbx.files_upload(
            content.encode("utf-8"),
            path,
            mode=WriteMode.overwrite,
        )
        return result.path_display
    except ApiError as exc:
        raise ValueError(f"Dropbox text upload failed for {path}: {exc}") from exc



def upload_binary_file(path: str, content: bytes) -> str:
    dbx = get_dropbox_client()
    try:
        result = dbx.files_upload(
            content,
            path,
            mode=WriteMode("overwrite"),
        )
        return result.path_display
    except ApiError as exc:
        raise ValueError(f"Dropbox binary upload failed for {path}: {exc}") from exc


def download_text_file(path: str) -> str:
    dbx = get_dropbox_client()
    try:
        _, response = dbx.files_download(path)
        return response.content.decode("utf-8")
    except ApiError as exc:
        raise ValueError(f"Dropbox text download failed for {path}: {exc}") from exc
