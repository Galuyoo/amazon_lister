from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Callable

from services.christmas_group_submission import (
    MEMBER_KEYS,
    build_christmas_group_child_payloads,
    compute_christmas_child_materialization_hash,
)
from services.christmas_project_grouping import build_christmas_group_image_manifest


LEDGER_SCHEMA_VERSION = 1
PENDING = "pending"
RELEASED = "released"
LOCKED_LEDGER_STATES = {"preparing", "publishing", "released", "failed"}


class PublicationConflictError(ValueError):
    pass


@dataclass(frozen=True)
class ChristmasGroupPublicationStorage:
    path_exists: Callable[[str], bool]
    ensure_folder: Callable[[str], None]
    create_folder: Callable[[str], None]
    load_memory: Callable[[str], dict[str, Any]]
    save_memory: Callable[[dict[str, Any], str], str]
    list_files: Callable[[str], list[str]]
    copy_file: Callable[[str, str], str]
    move_folder: Callable[[str, str], str]


def is_ready_listing_visible(listing_memory: dict[str, Any]) -> bool:
    source_group = listing_memory.get("source_group")
    if not isinstance(source_group, dict):
        return True
    if source_group.get("group_type") != "christmas_project":
        return True
    return source_group.get("release_status") == RELEASED


def is_group_submission_locked(source_memory: dict[str, Any]) -> bool:
    ledger = source_memory.get("group_submission")
    if not isinstance(ledger, dict):
        return False
    children = ledger.get("children")
    return (
        bool(ledger)
        and (
            ledger.get("state") in LOCKED_LEDGER_STATES
            or isinstance(children, dict) and bool(children)
            or bool(ledger.get("task_id"))
        )
    )


def build_christmas_group_publication_plan(
    profile: dict[str, Any],
    source_memory: dict[str, Any],
    image_manifest: dict[str, Any],
    *,
    source_folder_name: str,
    preparation_root: str,
    ready_root: str,
    archive_root: str,
) -> dict[str, Any]:
    source_folder_name = _folder_name(source_folder_name)
    roots = {
        "preparation": _root(preparation_root, "Grouped preparation root"),
        "ready": _root(ready_root, "Ready root"),
        "archive": _root(archive_root, "Grouped archive root"),
    }
    materialized = build_christmas_group_child_payloads(profile, source_memory, image_manifest)
    if not materialized["valid"]:
        return {**materialized, "source_folder_name": source_folder_name, "children": {}}

    children: dict[str, dict[str, Any]] = {}
    for member_key in MEMBER_KEYS:
        child = deepcopy(materialized["children"][member_key])
        destination_folder = f"{source_folder_name}-{child['folder_suffix']}"
        child.update({
            "destination_folder": destination_folder,
            "preparation_path": f"{roots['preparation']}/{destination_folder}",
            "ready_path": f"{roots['ready']}/{destination_folder}",
        })
        children[member_key] = child

    return {
        "valid": True,
        "errors": [],
        "warnings": list(materialized.get("warnings", [])),
        "source_folder_name": source_folder_name,
        "archive_path": f"{roots['archive']}/{source_folder_name}",
        "children": children,
    }


def preflight_christmas_group_publication(
    profile: dict[str, Any],
    *,
    source_folder_name: str,
    source_folder_path: str,
    preparation_root: str,
    ready_root: str,
    archive_root: str,
    storage: ChristmasGroupPublicationStorage,
) -> dict[str, Any]:
    source_memory = storage.load_memory(source_folder_path)
    image_manifest = build_christmas_group_image_manifest(
        storage.list_files(source_folder_path),
        profile,
    )
    plan = build_christmas_group_publication_plan(
        profile,
        source_memory,
        image_manifest,
        source_folder_name=source_folder_name,
        preparation_root=preparation_root,
        ready_root=ready_root,
        archive_root=archive_root,
    )
    plan["source_memory"] = source_memory
    plan["image_manifest"] = image_manifest
    if not plan["valid"]:
        return plan

    conflicts: list[dict[str, str]] = []
    conflicts.extend(_ledger_plan_conflicts(source_memory, plan))
    archive_only = _ledger_children_released(
        source_memory.get("group_submission", {})
    )
    if not archive_only:
        for member_key, child in plan["children"].items():
            preparation_exists = storage.path_exists(child["preparation_path"])
            ready_exists = storage.path_exists(child["ready_path"])
            if preparation_exists and ready_exists:
                conflicts.append(_conflict(member_key, "Both preparation and ready folders exist."))
                continue
            for location, exists in (("preparation", preparation_exists), ("ready", ready_exists)):
                if not exists:
                    continue
                path = child[f"{location}_path"]
                try:
                    existing = storage.load_memory(path)
                except Exception as exc:
                    if (
                        location == "preparation"
                        and _empty_preparation_folder(storage, path)
                        and _ledger_matches_child(source_memory, child)
                    ):
                        continue
                    conflicts.append(_conflict(member_key, f"Could not verify existing {location} folder: {exc}"))
                    continue
                if not _matching_child(existing, child):
                    conflicts.append(_child_identity_conflict(member_key, location, existing, child))
                    continue
                integrity_error = _existing_child_integrity_error(
                    storage,
                    child,
                    path,
                    location=location,
                    memory=existing,
                )
                if integrity_error:
                    conflicts.append(_conflict(member_key, integrity_error))

    archive_path = plan["archive_path"]
    if storage.path_exists(archive_path):
        conflicts.append(_conflict("source", "Grouped archive destination already exists."))

    if conflicts:
        plan["valid"] = False
        plan["errors"] = [*plan.get("errors", []), *conflicts]
    return plan


def publish_christmas_group(
    profile: dict[str, Any],
    *,
    source_folder_name: str,
    source_folder_path: str,
    preparation_root: str,
    ready_root: str,
    archive_root: str,
    storage: ChristmasGroupPublicationStorage,
    prepare_child_payload: Callable[[dict[str, Any], str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    plan: dict[str, Any] = {}
    source_memory: dict[str, Any] = {}
    ledger: dict[str, Any] = {}
    try:
        if not storage.path_exists(source_folder_path):
            return _reconcile_archived_publication(
                profile,
                source_folder_name=source_folder_name,
                preparation_root=preparation_root,
                ready_root=ready_root,
                archive_root=archive_root,
                storage=storage,
            )
        plan = preflight_christmas_group_publication(
            profile,
            source_folder_name=source_folder_name,
            source_folder_path=source_folder_path,
            preparation_root=preparation_root,
            ready_root=ready_root,
            archive_root=archive_root,
            storage=storage,
        )
        source_memory = deepcopy(plan.get("source_memory", {}))
        if not plan.get("valid"):
            return {
                "success": False,
                "state": "blocked",
                "errors": list(plan.get("errors", [])),
                "children": _child_summary(plan.get("children", {})),
            }

        ledger = _build_ledger(source_memory, plan)
        if _ledger_children_released(ledger):
            return _finish_source_archive(
                profile,
                plan,
                source_memory,
                ledger,
                source_folder_path,
                archive_root,
                storage,
            )

        _set_ledger_state(source_memory, ledger, "preparing")
        storage.save_memory(source_memory, source_folder_path)

        storage.ensure_folder(_root(preparation_root, "Grouped preparation root"))
        storage.ensure_folder(_root(ready_root, "Ready root"))
        storage.ensure_folder(_root(archive_root, "Grouped archive root"))

        for member_key in MEMBER_KEYS:
            child = plan["children"][member_key]
            ready_exists = storage.path_exists(child["ready_path"])
            if ready_exists:
                ledger["children"][member_key]["status"] = "published_pending"
                _persist_ledger(storage, source_memory, ledger, source_folder_path)
                continue

            preparation_path = child["preparation_path"]
            if not storage.path_exists(preparation_path):
                storage.create_folder(preparation_path)
            if not _folder_has_listing_memory(storage, preparation_path):
                payload = _pending_payload(child["payload"])
                if prepare_child_payload is not None:
                    payload = prepare_child_payload(
                        payload,
                        source_folder_path,
                        child["ready_path"],
                    )
                storage.save_memory(payload, preparation_path)

            _prepare_child_files(storage, child)
            _verify_child(storage, child, preparation_path, allowed_statuses={PENDING})
            ledger["children"][member_key]["status"] = "prepared"
            _persist_ledger(storage, source_memory, ledger, source_folder_path)

        _set_ledger_state(source_memory, ledger, "publishing")
        storage.save_memory(source_memory, source_folder_path)

        for member_key in MEMBER_KEYS:
            child = plan["children"][member_key]
            if not storage.path_exists(child["ready_path"]):
                try:
                    storage.move_folder(child["preparation_path"], child["ready_path"])
                except Exception:
                    if (
                        not storage.path_exists(child["preparation_path"])
                        and storage.path_exists(child["ready_path"])
                    ):
                        try:
                            _verify_child(
                                storage,
                                child,
                                child["ready_path"],
                                allowed_statuses={PENDING, RELEASED},
                            )
                        except Exception as verification_error:
                            raise PublicationConflictError(
                                f"Ambiguous ready move produced a conflicting destination for {member_key}: "
                                f"{verification_error}"
                            ) from verification_error
                    else:
                        raise
            _verify_child(storage, child, child["ready_path"], allowed_statuses={PENDING, RELEASED})
            ledger["children"][member_key]["status"] = "published_pending"
            _persist_ledger(storage, source_memory, ledger, source_folder_path)

        for member_key in MEMBER_KEYS:
            child = plan["children"][member_key]
            payload = storage.load_memory(child["ready_path"])
            if payload.get("source_group", {}).get("release_status") != RELEASED:
                payload = deepcopy(payload)
                payload["source_group"]["release_status"] = RELEASED
                storage.save_memory(payload, child["ready_path"])
            _verify_child(storage, child, child["ready_path"], allowed_statuses={RELEASED})
            ledger["children"][member_key]["status"] = RELEASED
            _persist_ledger(storage, source_memory, ledger, source_folder_path)

        if any(entry["status"] != RELEASED for entry in ledger["children"].values()):
            raise RuntimeError("All grouped children must be released before source archive.")

        return _finish_source_archive(
            profile,
            plan,
            source_memory,
            ledger,
            source_folder_path,
            archive_root,
            storage,
        )
    except PublicationConflictError as exc:
        _record_failure(storage, source_memory, ledger, source_folder_path, exc)
        return {
            "success": False,
            "state": "blocked",
            "error": str(exc),
            "errors": [{"code": "destination.conflict", "message": str(exc)}],
            "children": _child_summary(plan.get("children", {})),
        }
    except Exception as exc:
        _record_failure(storage, source_memory, ledger, source_folder_path, exc)
        return {
            "success": False,
            "state": "failed",
            "error": str(exc),
            "errors": [{"code": "publication.failed", "message": str(exc)}],
            "children": _child_summary(plan.get("children", {})),
        }


def _build_ledger(source_memory: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    existing = source_memory.get("group_submission")
    existing_children = existing.get("children", {}) if isinstance(existing, dict) else {}
    task_id = str(source_memory.get("listing_group", {}).get("task_id", "") or "")
    children = {}
    for member_key, child in plan["children"].items():
        previous = existing_children.get(member_key, {}) if isinstance(existing_children, dict) else {}
        children[member_key] = {
            "destination_folder": child["destination_folder"],
            "materialization_hash": child["materialization_hash"],
            "status": str(previous.get("status", "pending") or "pending"),
        }
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "task_id": task_id,
        "materialization_mode": str(
            existing.get("materialization_mode", "") if isinstance(existing, dict) else ""
        ) or (
            "generic_profiles"
            if all(
                child.get("payload", {}).get("template_key") != "CP"
                for child in plan["children"].values()
            )
            else "legacy_cp"
        ),
        "state": str(existing.get("state", "preparing") if isinstance(existing, dict) else "preparing"),
        "children": children,
        "last_error": "",
    }


def _set_ledger_state(source_memory: dict[str, Any], ledger: dict[str, Any], state: str) -> None:
    ledger["state"] = state
    ledger["last_error"] = ""
    source_memory["group_submission"] = deepcopy(ledger)


def _persist_ledger(
    storage: ChristmasGroupPublicationStorage,
    source_memory: dict[str, Any],
    ledger: dict[str, Any],
    source_folder_path: str,
) -> None:
    source_memory["group_submission"] = deepcopy(ledger)
    storage.save_memory(source_memory, source_folder_path)


def _pending_payload(payload: dict[str, Any]) -> dict[str, Any]:
    pending = deepcopy(payload)
    pending["source_group"] = dict(pending.get("source_group", {}))
    pending["source_group"]["release_status"] = PENDING
    return pending


def _prepare_child_files(storage: ChristmasGroupPublicationStorage, child: dict[str, Any]) -> None:
    preparation_path = child["preparation_path"]
    existing_names = {_basename(path).casefold() for path in storage.list_files(preparation_path)}
    for source_path in child["source_image_files"]:
        filename = _basename(source_path)
        if filename.casefold() in existing_names:
            continue
        destination = f"{preparation_path}/{filename}"
        try:
            storage.copy_file(source_path, destination)
        except Exception:
            reconciled_names = {
                _basename(path).casefold()
                for path in storage.list_files(preparation_path)
            }
            if filename.casefold() not in reconciled_names:
                raise
        existing_names.add(filename.casefold())


def _verify_child(
    storage: ChristmasGroupPublicationStorage,
    child: dict[str, Any],
    path: str,
    *,
    allowed_statuses: set[str],
) -> None:
    memory = storage.load_memory(path)
    if not _matching_child(memory, child):
        raise ValueError(f"Grouped child verification failed for {path}: provenance mismatch.")
    release_status = memory.get("source_group", {}).get("release_status")
    if release_status not in allowed_statuses:
        raise ValueError(f"Grouped child verification failed for {path}: invalid release status.")
    expected = {_basename(source).casefold() for source in child["source_image_files"]}
    actual = {
        _basename(file_path).casefold()
        for file_path in storage.list_files(path)
        if _basename(file_path).casefold() != "listing_inputs.json"
    }
    if actual != expected:
        raise ValueError(f"Grouped child verification failed for {path}: image files differ.")


def _matching_child(memory: dict[str, Any], child: dict[str, Any]) -> bool:
    source_group = memory.get("source_group")
    expected_group = child["payload"].get("source_group", {})
    if not isinstance(source_group, dict):
        return False
    for field in ("task_id", "member_key", "materialization_hash"):
        if source_group.get(field) != expected_group.get(field):
            return False
    calculated = compute_christmas_child_materialization_hash(
        memory,
        child["source_images_by_colour"],
    )
    return calculated == child["materialization_hash"]


def _ledger_matches_child(source_memory: dict[str, Any], child: dict[str, Any]) -> bool:
    ledger = source_memory.get("group_submission")
    if not isinstance(ledger, dict):
        return False
    task_id = child["payload"].get("source_group", {}).get("task_id")
    member_key = child["member_key"]
    entry = ledger.get("children", {}).get(member_key, {})
    return (
        ledger.get("task_id") == task_id
        and entry.get("destination_folder") == child["destination_folder"]
        and entry.get("materialization_hash") == child["materialization_hash"]
    )


def _folder_has_listing_memory(storage: ChristmasGroupPublicationStorage, path: str) -> bool:
    return any(_basename(file_path).casefold() == "listing_inputs.json" for file_path in storage.list_files(path))


def _empty_preparation_folder(storage: ChristmasGroupPublicationStorage, path: str) -> bool:
    try:
        return not storage.list_files(path)
    except Exception:
        return False


def _ledger_plan_conflicts(
    source_memory: dict[str, Any],
    plan: dict[str, Any],
) -> list[dict[str, str]]:
    if not is_group_submission_locked(source_memory):
        return []
    ledger = source_memory["group_submission"]
    conflicts: list[dict[str, str]] = []
    if ledger.get("schema_version") != LEDGER_SCHEMA_VERSION:
        conflicts.append({
            "code": "ledger.invalid",
            "member_key": "source",
            "message": "Grouped source publication ledger schema is invalid.",
        })
    if ledger.get("state") not in LOCKED_LEDGER_STATES:
        conflicts.append({
            "code": "ledger.invalid",
            "member_key": "source",
            "message": "Grouped source publication ledger state is invalid.",
        })
    task_id = str(source_memory.get("listing_group", {}).get("task_id", "") or "")
    if ledger.get("task_id") != task_id:
        conflicts.append({
            "code": "source.drift",
            "member_key": "source",
            "message": "Grouped source task identity changed after publication began.",
        })
    ledger_children = ledger.get("children")
    if not isinstance(ledger_children, dict):
        return [*conflicts, {
            "code": "ledger.invalid",
            "member_key": "source",
            "message": "Grouped source publication ledger children are missing.",
        }]
    for member_key, child in plan["children"].items():
        entry = ledger_children.get(member_key)
        if not isinstance(entry, dict):
            conflicts.append({
                "code": "ledger.invalid",
                "member_key": member_key,
                "message": "Grouped source publication ledger child is missing.",
            })
            continue
        if (
            entry.get("destination_folder") != child["destination_folder"]
            or entry.get("materialization_hash") != child["materialization_hash"]
        ):
            conflicts.append({
                "code": "source.drift",
                "member_key": member_key,
                "message": (
                    "Grouped source changed after publication began; the existing child "
                    "cannot be reused or overwritten."
                ),
            })
        if entry.get("status") not in {PENDING, "prepared", "published_pending", RELEASED}:
            conflicts.append({
                "code": "ledger.invalid",
                "member_key": member_key,
                "message": "Grouped source publication child status is invalid.",
            })
    if ledger.get("state") == RELEASED and not _ledger_children_released(ledger):
        conflicts.append({
            "code": "ledger.inconsistent",
            "member_key": "source",
            "message": "Grouped source ledger claims released while a child is not released.",
        })
    return conflicts


def _child_identity_conflict(
    member_key: str,
    location: str,
    existing: dict[str, Any],
    child: dict[str, Any],
) -> dict[str, str]:
    existing_group = existing.get("source_group")
    expected_group = child["payload"].get("source_group", {})
    if isinstance(existing_group, dict) and all(
        existing_group.get(field) == expected_group.get(field)
        for field in ("task_id", "member_key")
    ) and existing_group.get("materialization_hash") != expected_group.get("materialization_hash"):
        return {
            "code": "source.drift",
            "member_key": member_key,
            "message": f"Existing {location} child was materialized from an older grouped source.",
        }
    return _conflict(member_key, f"Existing {location} folder has different provenance.")


def _existing_child_integrity_error(
    storage: ChristmasGroupPublicationStorage,
    child: dict[str, Any],
    path: str,
    *,
    location: str,
    memory: dict[str, Any],
) -> str:
    file_names = {_basename(file_path).casefold() for file_path in storage.list_files(path)}
    if "listing_inputs.json" not in file_names:
        return f"Existing {location} folder is missing listing_inputs.json."
    expected_images = {
        _basename(source_path).casefold()
        for source_path in child["source_image_files"]
    }
    actual_images = file_names - {"listing_inputs.json"}
    if not actual_images.issubset(expected_images):
        return f"Existing {location} folder contains unexpected image files."
    if location == "ready" and actual_images != expected_images:
        return "Existing ready folder does not contain the exact expected image set."
    release_status = memory.get("source_group", {}).get("release_status")
    allowed_statuses = {PENDING} if location == "preparation" else {PENDING, RELEASED}
    if release_status not in allowed_statuses:
        return f"Existing {location} folder has an invalid release status."
    return ""


def _ledger_children_released(ledger: dict[str, Any]) -> bool:
    children = ledger.get("children")
    return (
        isinstance(children, dict)
        and set(children) == set(MEMBER_KEYS)
        and all(
            isinstance(children.get(member_key), dict)
            and children[member_key].get("status") == RELEASED
            for member_key in MEMBER_KEYS
        )
    )


def _finish_source_archive(
    profile: dict[str, Any],
    plan: dict[str, Any],
    source_memory: dict[str, Any],
    ledger: dict[str, Any],
    source_folder_path: str,
    archive_root: str,
    storage: ChristmasGroupPublicationStorage,
) -> dict[str, Any]:
    if not _ledger_children_released(ledger):
        raise RuntimeError("All grouped children must be released before source archive.")

    _set_ledger_state(source_memory, ledger, RELEASED)
    storage.save_memory(source_memory, source_folder_path)
    storage.ensure_folder(_root(archive_root, "Grouped archive root"))
    try:
        storage.move_folder(source_folder_path, plan["archive_path"])
    except Exception:
        if (
            not storage.path_exists(source_folder_path)
            and storage.path_exists(plan["archive_path"])
        ):
            _verify_archived_against_plan(storage, plan)
        else:
            raise
    return {
        "success": True,
        "state": RELEASED,
        "archive_path": plan["archive_path"],
        "children": _child_summary(plan["children"]),
        "errors": [],
    }


def _reconcile_archived_publication(
    profile: dict[str, Any],
    *,
    source_folder_name: str,
    preparation_root: str,
    ready_root: str,
    archive_root: str,
    storage: ChristmasGroupPublicationStorage,
) -> dict[str, Any]:
    archive_path = f"{_root(archive_root, 'Grouped archive root')}/{_folder_name(source_folder_name)}"
    if not storage.path_exists(archive_path):
        return {
            "success": False,
            "state": "blocked",
            "errors": [{
                "code": "source.missing",
                "message": "Grouped source is missing from both staging and the grouped archive.",
            }],
            "children": {},
        }
    try:
        archived_memory = storage.load_memory(archive_path)
        archived_manifest = build_christmas_group_image_manifest(
            storage.list_files(archive_path),
            profile,
        )
        plan = build_christmas_group_publication_plan(
            profile,
            archived_memory,
            archived_manifest,
            source_folder_name=source_folder_name,
            preparation_root=preparation_root,
            ready_root=ready_root,
            archive_root=archive_root,
        )
        if not plan.get("valid"):
            raise PublicationConflictError("Archived grouped source cannot be validated.")
        ledger_conflicts = _ledger_plan_conflicts(archived_memory, plan)
        if ledger_conflicts or not _ledger_children_released(
            archived_memory.get("group_submission", {})
        ):
            raise PublicationConflictError(
                "Archived grouped source does not match a fully released publication."
            )
        _verify_archived_against_plan(storage, plan)
    except Exception as exc:
        return {
            "success": False,
            "state": "blocked",
            "errors": [{
                "code": "destination.conflict",
                "message": f"Could not reconcile grouped archive destination: {exc}",
            }],
            "children": {},
        }
    return {
        "success": True,
        "state": RELEASED,
        "archive_path": archive_path,
        "children": _child_summary(plan["children"]),
        "errors": [],
        "reconciled": True,
    }


def _verify_archived_against_plan(
    storage: ChristmasGroupPublicationStorage,
    plan: dict[str, Any],
) -> None:
    archived_memory = storage.load_memory(plan["archive_path"])
    if _ledger_plan_conflicts(archived_memory, plan):
        raise PublicationConflictError("Archived source ledger does not match the publication plan.")
    if not _ledger_children_released(archived_memory.get("group_submission", {})):
        raise PublicationConflictError("Archived source ledger is not fully released.")


def _record_failure(
    storage: ChristmasGroupPublicationStorage,
    source_memory: dict[str, Any],
    ledger: dict[str, Any],
    source_folder_path: str,
    exc: Exception,
) -> None:
    if not source_memory or not ledger:
        return
    ledger["state"] = "failed"
    ledger["last_error"] = str(exc)
    source_memory["group_submission"] = deepcopy(ledger)
    try:
        storage.save_memory(source_memory, source_folder_path)
    except Exception:
        pass


def _child_summary(children: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        member_key: {
            "label": child.get("label", ""),
            "destination_folder": child.get("destination_folder", ""),
            "image_count": len(child.get("source_image_files", [])),
            "materialization_hash": child.get("materialization_hash", ""),
        }
        for member_key, child in children.items()
    }


def _conflict(member_key: str, message: str) -> dict[str, str]:
    return {"code": "destination.conflict", "member_key": member_key, "message": message}


def _root(value: str, label: str) -> str:
    normalized = str(value or "").rstrip("/")
    if not normalized:
        raise ValueError(f"{label} is not configured.")
    return normalized


def _folder_name(value: str) -> str:
    normalized = str(value or "").strip().strip("/\\")
    if not normalized or "/" in normalized or "\\" in normalized:
        raise ValueError("Grouped source folder name is invalid.")
    return normalized


def _basename(path: str) -> str:
    return PurePosixPath(str(path or "").replace("\\", "/")).name
