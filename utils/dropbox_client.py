# utils/dropbox_client.py
from __future__ import annotations

import os
import time
from functools import lru_cache
from pathlib import Path
from dropbox.files import WriteMode

import dropbox
from dropbox.exceptions import ApiError, AuthError, InternalServerError, RateLimitError
from dotenv import load_dotenv
from requests.exceptions import RequestException

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


REQUIRED_DROPBOX_KEYS = (
    "DROPBOX_APP_KEY",
    "DROPBOX_APP_SECRET",
    "DROPBOX_REFRESH_TOKEN",
)
DROPBOX_REQUEST_TIMEOUT_SECONDS = 30
DROPBOX_READ_ATTEMPTS = 3


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
        timeout=DROPBOX_REQUEST_TIMEOUT_SECONDS,
        max_retries_on_error=4,
        max_retries_on_rate_limit=4,
    )

    try:
        dbx.users_get_current_account()
    except AuthError as exc:
        raise ValueError("Dropbox authentication failed.") from exc

    return dbx


def reset_dropbox_client() -> None:
    get_dropbox_client.cache_clear()


def format_dropbox_error(exc: Exception) -> str:
    error_chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in error_chain:
        error_chain.append(current)
        current = current.__cause__ or current.__context__

    error_text = " ".join(str(error) for error in error_chain).lower()
    if any(isinstance(error, AuthError) for error in error_chain) or any(
        marker in error_text
        for marker in ("authentication failed", "invalid_grant", "missing dropbox credentials")
    ):
        return "Dropbox authentication failed. Check the deployed Dropbox app credentials and refresh token."
    if any(isinstance(error, RateLimitError) for error in error_chain) or "too_many_requests" in error_text:
        return "Dropbox temporarily rate-limited this request. Retry the folder list shortly."
    if any(isinstance(error, InternalServerError) for error in error_chain):
        return "Dropbox returned a temporary server error. Retry the folder list shortly."
    if any(isinstance(error, RequestException) for error in error_chain):
        return "The app could not reach Dropbox over the network. Retry the folder list shortly."
    if any(isinstance(error, ApiError) for error in error_chain):
        return f"Dropbox rejected the folder request: {exc}"
    return f"{type(exc).__name__}: {exc}"


def _is_retryable_dropbox_read_error(exc: Exception) -> bool:
    if isinstance(exc, (AuthError, ApiError, ValueError)):
        return False
    return True

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

def _list_folder_names_once(path: str) -> list[str]:
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


def list_folder_names(path: str) -> list[str]:
    last_error: Exception | None = None
    for attempt in range(DROPBOX_READ_ATTEMPTS):
        try:
            return _list_folder_names_once(path)
        except Exception as exc:
            last_error = exc
            if not _is_retryable_dropbox_read_error(exc) or attempt == DROPBOX_READ_ATTEMPTS - 1:
                raise
            reset_dropbox_client()
            time.sleep(0.75 * (2 ** attempt))

    raise RuntimeError(f"Dropbox folder listing failed: {last_error}")


def create_folder_if_missing(path: str) -> None:
    dbx = get_dropbox_client()
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            dbx.files_get_metadata(path)
            return
        except ApiError as metadata_error:
            last_error = metadata_error
            try:
                dbx.files_create_folder_v2(path)
                return
            except ApiError as create_error:
                if "conflict" in str(create_error).lower():
                    return
                last_error = create_error
            except Exception as create_error:
                last_error = create_error
                try:
                    dbx.files_get_metadata(path)
                    return
                except Exception:
                    pass
        except Exception as metadata_error:
            last_error = metadata_error

        if attempt < 2:
            time.sleep(0.8 * (attempt + 1))

    raise ValueError(f"Dropbox folder create failed for {path}: {last_error}")


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
