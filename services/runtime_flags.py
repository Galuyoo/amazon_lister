from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any


DEV_TOOLS_ENV_KEY = "AMAZON_LISTER_ENABLE_DEV_TOOLS"
DEV_TOOLS_SECRET_KEY = "ENABLE_DEV_TOOLS"
TRUE_VALUES = {"1", "true", "yes", "on"}


def _is_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in TRUE_VALUES


def dev_tools_enabled(
    environment: Mapping[str, str] | None = None,
    secrets: Any = None,
) -> bool:
    environment = os.environ if environment is None else environment
    if DEV_TOOLS_ENV_KEY in environment:
        return _is_enabled(environment.get(DEV_TOOLS_ENV_KEY))

    try:
        return _is_enabled(secrets.get(DEV_TOOLS_SECRET_KEY, False)) if secrets is not None else False
    except Exception:
        return False
