from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return value
        return decoded if isinstance(decoded, str) else value
    return value


def parse_sku_replace_rules(raw_rules: str) -> dict[str, Any]:
    rules: list[dict[str, str]] = []
    errors: list[str] = []
    seen_sources: set[str] = set()
    for line_number, raw_line in enumerate(str(raw_rules or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.count("=>") != 1:
            errors.append(f"Line {line_number} must contain exactly one => separator.")
            continue
        source, replacement = (_unquote(part) for part in line.split("=>", 1))
        if not source:
            errors.append(f"Line {line_number} has an empty value to replace.")
            continue
        source_key = source.casefold()
        if source_key in seen_sources:
            errors.append(f"Line {line_number} repeats replacement source {source!r}.")
            continue
        seen_sources.add(source_key)
        rules.append({"source": source, "replacement": replacement})

    return {"valid": not errors, "rules": rules, "errors": errors}


def apply_sku_replace_rules(value: str, rules: list[dict[str, str]]) -> str:
    result = str(value or "")
    for rule in rules:
        source = str(rule.get("source", "") or "")
        replacement = str(rule.get("replacement", "") or "")
        if source:
            result = re.sub(re.escape(source), lambda _match: replacement, result, flags=re.IGNORECASE)
    return result


def apply_sku_component_replace_rules(value: str, rules: list[dict[str, str]]) -> str:
    direct_result = apply_sku_replace_rules(value, rules)
    delimited_result = apply_sku_replace_rules(f"{value}-", rules)
    if delimited_result != f"{value}-" and delimited_result.endswith("-"):
        return delimited_result[:-1]
    return direct_result


def build_sku_replacement_fingerprint(rows: list[dict[str, Any]], rules: list[dict[str, str]]) -> str:
    encoded = json.dumps(
        {"rows": rows, "rules": rules},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
