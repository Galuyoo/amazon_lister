from __future__ import annotations

from pathlib import Path
import shutil


APP_PATH = Path("app.py")
BACKUP_PATH = Path("app_before_staged_folder_context_fix.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one {label} anchor, found {count}. "
            "The app may already