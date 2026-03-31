# utils/dropbox_client.py
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import dropbox
from dropbox.exceptions import ApiError, AuthError
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


@lru_cache(maxsize=1)
def get_dropbox_client() -> dropbox.Dropbox:
    app_key = os.getenv("DROPBOX_APP_KEY")
    app_secret = os.getenv("DROPBOX_APP_SECRET")
    refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN")

    if not all([app_key, app_secret, refresh_token]):
        raise ValueError("Missing Dropbox OAuth credentials in .env")

    dbx = dropbox.Dropbox(
        oauth2_refresh_token=refresh_token,
        app_key=app_key,
        app_secret=app_secret,
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
        dbx.files_get_metadata(path)
        return True
    except ApiError as exc:
        raise ValueError(f"Dropbox metadata lookup failed for {path}: {exc}") from exc


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