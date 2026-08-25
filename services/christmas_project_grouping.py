from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any


SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
GARMENT_CODE_PATTERN = re.compile(r"^[A-Za-z]+\d+$")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _filename_parts(file_path: str) -> tuple[str, str, str]:
    filename = str(file_path or "").replace("\\", "/").rsplit("/", 1)[-1]
    if "." not in filename:
        return filename, filename, ""
    stem, extension = filename.rsplit(".", 1)
    return filename, stem, f".{extension.lower()}"


def validate_christmas_group_config(profile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    grouped_listing = profile.get("grouped_listing")
    if not isinstance(grouped_listing, dict):
        return ["grouped_listing must be an object."]

    if type(grouped_listing.get("schema_version")) is not int or grouped_listing.get("schema_version") != 1:
        errors.append("grouped_listing.schema_version must equal 1.")
    if grouped_listing.get("group_type") != "christmas_project":
        errors.append("grouped_listing.group_type must equal 'christmas_project'.")

    members = grouped_listing.get("members")
    if not isinstance(members, list) or not members:
        errors.append("grouped_listing.members must be a non-empty list.")
        return errors

    design_sku_map = profile.get("design_sku_map")
    design_color_map = profile.get("design_color_map")
    design_size_map = profile.get("design_size_map")
    for field_name, field_value in [
        ("design_sku_map", design_sku_map),
        ("design_color_map", design_color_map),
        ("design_size_map", design_size_map),
    ]:
        if not isinstance(field_value, dict):
            errors.append(f"{field_name} must be an object.")

    design_sku_map = design_sku_map if isinstance(design_sku_map, dict) else {}
    design_color_map = design_color_map if isinstance(design_color_map, dict) else {}
    design_size_map = design_size_map if isinstance(design_size_map, dict) else {}

    seen_keys: dict[str, str] = {}
    seen_suffixes: dict[str, str] = {}
    seen_designs: dict[str, str] = {}
    seen_codes: dict[str, str] = {}
    code_sequences: list[tuple[str, tuple[str, ...]]] = []

    for index, member in enumerate(members):
        location = f"grouped_listing.members[{index}]"
        if not isinstance(member, dict):
            errors.append(f"{location} must be an object.")
            continue

        member_values: dict[str, str] = {}
        for field_name in ["key", "label", "folder_suffix"]:
            value = _text(member.get(field_name))
            member_values[field_name] = value
            if not value:
                errors.append(f"{location}.{field_name} must be a non-empty string.")

        member_key = member_values["key"] or f"member {index + 1}"
        key_token = member_values["key"].casefold()
        if key_token:
            if key_token in seen_keys:
                errors.append(
                    f"Duplicate grouped member key '{member_values['key']}' conflicts with '{seen_keys[key_token]}'."
                )
            else:
                seen_keys[key_token] = member_values["key"]

        suffix_token = member_values["folder_suffix"].casefold()
        if suffix_token:
            if suffix_token in seen_suffixes:
                errors.append(
                    "Duplicate grouped member folder_suffix "
                    f"'{member_values['folder_suffix']}' conflicts with '{seen_suffixes[suffix_token]}'."
                )
            else:
                seen_suffixes[suffix_token] = member_values["folder_suffix"]

        designs = member.get("designs")
        if not isinstance(designs, list) or not designs:
            errors.append(f"{location}.designs must be a non-empty list.")
            continue

        member_designs: list[str] = []
        local_designs: set[str] = set()
        member_codes: list[str] = []
        for design_index, raw_design in enumerate(designs):
            design = _text(raw_design)
            if not design:
                errors.append(f"{location}.designs[{design_index}] must be a non-empty string.")
                continue

            design_token = design.casefold()
            if design_token in local_designs:
                errors.append(f"Member '{member_key}' contains duplicate design '{design}'.")
                continue
            local_designs.add(design_token)
            member_designs.append(design)

            if design_token in seen_designs:
                errors.append(
                    f"Design '{design}' is owned by both '{seen_designs[design_token]}' and '{member_key}'."
                )
            else:
                seen_designs[design_token] = member_key

            code = _text(design_sku_map.get(design))
            if not code:
                errors.append(f"Design '{design}' is missing a garment code in design_sku_map.")
            else:
                code_token = code.casefold()
                if code_token in seen_codes and seen_codes[code_token] != design:
                    errors.append(
                        f"Garment code '{code}' is ambiguously owned by '{seen_codes[code_token]}' and '{design}'."
                    )
                else:
                    seen_codes[code_token] = design
                member_codes.append(code)

            colours = design_color_map.get(design)
            if not isinstance(colours, list) or not colours:
                errors.append(f"Design '{design}' must have a non-empty list in design_color_map.")
            else:
                seen_colours: set[str] = set()
                for colour in colours:
                    canonical_colour = _text(colour)
                    colour_token = canonical_colour.casefold()
                    if not canonical_colour:
                        errors.append(f"Design '{design}' contains an empty colour.")
                    elif colour_token in seen_colours:
                        errors.append(f"Design '{design}' contains duplicate colour '{canonical_colour}'.")
                    else:
                        seen_colours.add(colour_token)

            sizes = design_size_map.get(design)
            if not isinstance(sizes, list) or not sizes:
                errors.append(f"Design '{design}' must have a non-empty list in design_size_map.")

        if member_designs and len(member_codes) == len(member_designs):
            code_sequences.append((member_key, tuple(code.casefold() for code in member_codes)))

    for index, (member_key, sequence) in enumerate(code_sequences):
        for other_key, other_sequence in code_sequences[index + 1:]:
            if sequence == other_sequence:
                errors.append(
                    f"Grouped members '{member_key}' and '{other_key}' own the same garment-code sequence."
                )
            elif sequence[: len(other_sequence)] == other_sequence or other_sequence[: len(sequence)] == sequence:
                errors.append(
                    f"Grouped members '{member_key}' and '{other_key}' have ambiguous garment-code sequences."
                )

    return errors


def derive_christmas_group_members(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    errors = validate_christmas_group_config(profile)
    if errors:
        raise ValueError("Invalid Christmas grouped listing config: " + "; ".join(errors))

    grouped_listing = profile["grouped_listing"]
    design_sku_map = profile["design_sku_map"]
    design_color_map = profile["design_color_map"]
    design_size_map = profile["design_size_map"]
    derived: dict[str, dict[str, Any]] = {}

    for member in grouped_listing["members"]:
        designs = [_text(design) for design in member["designs"]]
        first_colours = [_text(colour) for colour in design_color_map[designs[0]]]
        remaining_colour_sets = [
            {_text(colour).casefold() for colour in design_color_map[design]}
            for design in designs[1:]
        ]
        allowed_colours = [
            colour
            for colour in first_colours
            if all(colour.casefold() in colour_set for colour_set in remaining_colour_sets)
        ]
        key = _text(member["key"])
        derived[key] = {
            "key": key,
            "label": _text(member["label"]),
            "folder_suffix": _text(member["folder_suffix"]),
            "designs": list(designs),
            "garment_codes": [_text(design_sku_map[design]) for design in designs],
            "allowed_colours": allowed_colours,
            "sizes_by_design": {
                design: list(design_size_map[design])
                for design in designs
            },
        }

    return derived


def parse_christmas_group_image_filename(
    file_path: str,
    profile: dict[str, Any],
) -> dict[str, Any]:
    original_path = str(file_path or "")
    filename, stem, extension = _filename_parts(original_path)
    result: dict[str, Any] = {
        "file_path": original_path,
        "filename": filename,
        "valid": True,
        "ignored": False,
        "member_key": "",
        "designs": [],
        "garment_codes": [],
        "colour": "",
        "errors": [],
        "warnings": [],
    }

    try:
        members = derive_christmas_group_members(profile)
    except ValueError as exc:
        result["valid"] = False
        result["errors"].append(str(exc))
        return result

    if extension not in SUPPORTED_IMAGE_EXTENSIONS:
        result["ignored"] = True
        return result

    matches: list[tuple[dict[str, Any], str]] = []
    for member in members.values():
        code_pattern = r"\s+".join(re.escape(code) for code in member["garment_codes"])
        match = re.fullmatch(
            rf"\s*{code_pattern}(?:\s+(.*?))?\s*",
            stem,
            flags=re.IGNORECASE,
        )
        if match:
            matches.append((member, _text(match.group(1))))

    if len(matches) > 1:
        result["valid"] = False
        result["errors"].append(f"Ambiguous grouped garment-code prefix in '{filename}'.")
        return result

    if not matches:
        tokens = stem.strip().split()
        first_token = tokens[0] if tokens else ""
        matching_members = [
            member
            for member in members.values()
            if first_token.casefold() in {code.casefold() for code in member["garment_codes"]}
        ]
        if matching_members:
            expected = [" ".join(member["garment_codes"]) for member in matching_members]
            result["valid"] = False
            result["errors"].append(
                f"Incomplete or invalid garment-code sequence in '{filename}'. Expected: {', '.join(expected)}."
            )
        elif GARMENT_CODE_PATTERN.fullmatch(first_token):
            result["valid"] = False
            result["errors"].append(f"Unknown grouped garment-code prefix '{first_token}' in '{filename}'.")
        else:
            result["ignored"] = True
            result["warnings"].append(f"Ignored unrelated image '{filename}'.")
        return result

    member, raw_colour = matches[0]
    result["member_key"] = member["key"]
    result["designs"] = list(member["designs"])
    result["garment_codes"] = list(member["garment_codes"])
    if not raw_colour:
        result["valid"] = False
        result["errors"].append(f"Grouped image '{filename}' is missing a colour after the garment codes.")
        return result

    canonical_colours = {
        colour.casefold(): colour
        for colour in member["allowed_colours"]
    }
    canonical_colour = canonical_colours.get(raw_colour.casefold())
    if canonical_colour is None:
        result["valid"] = False
        result["errors"].append(
            f"Unknown colour '{raw_colour}' for grouped member '{member['key']}' in '{filename}'."
        )
        return result

    result["colour"] = canonical_colour
    return result


def build_christmas_group_image_manifest(
    file_paths: Iterable[str],
    profile: dict[str, Any],
) -> dict[str, Any]:
    config_errors = validate_christmas_group_config(profile)
    if config_errors:
        return {
            "valid": False,
            "complete": False,
            "members": {},
            "errors": list(config_errors),
            "warnings": [],
            "ignored_files": [],
        }

    derived_members = derive_christmas_group_members(profile)
    manifest_members: dict[str, dict[str, Any]] = {
        key: {
            "designs": list(member["designs"]),
            "garment_codes": list(member["garment_codes"]),
            "allowed_colours": list(member["allowed_colours"]),
            "sizes_by_design": {
                design: list(sizes)
                for design, sizes in member["sizes_by_design"].items()
            },
            "images_by_colour": {},
            "missing_colours": [],
        }
        for key, member in derived_members.items()
    }
    errors: list[str] = []
    warnings: list[str] = []
    ignored_files: list[str] = []

    for raw_path in file_paths:
        file_path = str(raw_path)
        parsed = parse_christmas_group_image_filename(file_path, profile)
        if parsed["ignored"]:
            ignored_files.append(file_path)
            warnings.extend(parsed["warnings"])
            continue
        if not parsed["valid"]:
            errors.extend(parsed["errors"])
            continue

        member_images = manifest_members[parsed["member_key"]]["images_by_colour"]
        existing_path = member_images.get(parsed["colour"])
        if existing_path is not None:
            errors.append(
                f"Duplicate grouped image mapping for {parsed['member_key']} / {parsed['colour']}: "
                f"'{existing_path}' and '{file_path}'."
            )
            continue
        member_images[parsed["colour"]] = file_path

    has_missing_colours = False
    for member in manifest_members.values():
        member["missing_colours"] = [
            colour
            for colour in member["allowed_colours"]
            if colour not in member["images_by_colour"]
        ]
        has_missing_colours = has_missing_colours or bool(member["missing_colours"])

    valid = not errors
    return {
        "valid": valid,
        "complete": valid and not has_missing_colours,
        "members": manifest_members,
        "errors": errors,
        "warnings": warnings,
        "ignored_files": ignored_files,
    }
