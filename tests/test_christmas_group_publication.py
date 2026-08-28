from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path, PurePosixPath
import sys
from typing import Any

import pytest

from services.christmas_group_publication import (
    ChristmasGroupPublicationStorage,
    build_christmas_group_publication_plan,
    is_group_submission_locked,
    is_ready_listing_visible,
    preflight_christmas_group_publication,
    publish_christmas_group,
)
from services.christmas_group_submission import compute_christmas_child_materialization_hash
from services.christmas_project_grouping import (
    build_christmas_group_image_manifest,
    derive_christmas_group_members,
    normalize_christmas_grouped_draft,
)
from services.christmas_grouped_content_import import parse_christmas_grouped_content_json
from services.listing_memory import build_listing_memory_payload
from services.staged_listing_tasks import build_grouped_christmas_staged_task_payload


ROOT = Path(__file__).parents[1]
CP_CONFIG_PATH = ROOT / "templates" / "Special Projects" / "CP" / "config.json"
SAMPLE_CONTENT_PATH = ROOT / "samples" / "christmas_grouped_listing_content_test.json"
TARGET_CONFIG_PATHS = {
    "tshirt": ROOT / "templates" / "SHIRT" / "Generic Shirts" / "config.json",
    "sweatshirt": ROOT / "templates" / "HOODIE" / "Generic Sweatshirts" / "config.json",
    "hoodie": ROOT / "templates" / "HOODIE" / "Generic Hoodies" / "config.json",
}
SOURCE_PATH = "/Amazon/_stage/CHRTST"
PREPARATION_ROOT = "/Amazon/_grouped_preparation"
READY_ROOT = "/Amazon/ready"
ARCHIVE_ROOT = "/Amazon/_grouped_archive"


def load_cp_profile() -> dict[str, Any]:
    profile = json.loads(CP_CONFIG_PATH.read_text(encoding="utf-8"))
    profile.update({"_slug": "CP", "_family_slug": "Special Projects"})
    return profile


def add_target_profiles(profile: dict[str, Any]) -> dict[str, Any]:
    enriched = copy.deepcopy(profile)
    targets = {}
    for member_key, config_path in TARGET_CONFIG_PATHS.items():
        target = json.loads(config_path.read_text(encoding="utf-8"))
        schema = json.loads((config_path.parent.parent / "schema.json").read_text(encoding="utf-8"))
        target.update({
            "_slug": config_path.parent.name,
            "_family_slug": config_path.parent.parent.name,
            "_schema": schema,
            "template_file": schema["workbook_file"],
        })
        targets[member_key] = target
    enriched["_group_target_profiles"] = targets
    return enriched


def build_source() -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    profile = load_cp_profile()
    task = build_grouped_christmas_staged_task_payload(
        profile=profile,
        staged_folder_name="CHRTST",
        mpn="D12345",
        quantity=100,
        merchant_shipping_group_name="",
        sku_decoration_code="DTG",
        manual_sku_listing_code="",
        generated_sku_listing_code="D12345",
        sku_listing_code="D12345",
        base_parent_sku="CP",
        parent_sku="DTG-D12345",
        assets_prepared_by="Sal",
        task_id="task-chrtst-1",
    )
    content = parse_christmas_grouped_content_json(SAMPLE_CONTENT_PATH.read_text(encoding="utf-8"))
    source = normalize_christmas_grouped_draft(profile, task["payload"], content["members"])
    source["content_prepared_by"] = "Sal"
    source["workflow_events"] = [{"action": "draft_saved"}]
    prices: dict[str, float] = {}
    for member in derive_christmas_group_members(profile).values():
        for design in member["designs"]:
            for size in member["sizes_by_design"][design]:
                prices[f"{design}||{size}"] = 10.0 + len(prices)
    source["size_price_map"] = prices
    source = build_listing_memory_payload(profile, source)
    colours = ["Black", "Navy", "Heather Grey", "Kelly Green", "Red", "Royal", "White"]
    image_paths = [
        *[f"{SOURCE_PATH}/T01 T02 {colour}.png" for colour in colours],
        *[f"{SOURCE_PATH}/S01 S02 {colour}.png" for colour in colours],
        f"{SOURCE_PATH}/H01 H02 Black.png",
        f"{SOURCE_PATH}/H01 H02 Navy.png",
    ]
    return profile, source, image_paths


class FakeStorage:
    def __init__(self, source: dict[str, Any], image_paths: list[str]) -> None:
        self.directories = {SOURCE_PATH}
        self.memories = {SOURCE_PATH: copy.deepcopy(source)}
        self.files = {SOURCE_PATH: {_name(path) for path in image_paths}}
        self.log: list[tuple[Any, ...]] = []
        self.failure: tuple[str, str] | None = None
        self.after_failure: tuple[str, str] | None = None

    def adapter(self) -> ChristmasGroupPublicationStorage:
        return ChristmasGroupPublicationStorage(
            path_exists=self.path_exists,
            ensure_folder=self.ensure_folder,
            create_folder=self.create_folder,
            load_memory=self.load_memory,
            save_memory=self.save_memory,
            list_files=self.list_files,
            copy_file=self.copy_file,
            move_folder=self.move_folder,
        )

    def path_exists(self, path: str) -> bool:
        self.log.append(("exists", path))
        return path in self.directories

    def ensure_folder(self, path: str) -> None:
        self._fail("ensure", path)
        self.log.append(("ensure", path))
        self.directories.add(path)
        self.files.setdefault(path, set())

    def create_folder(self, path: str) -> None:
        self._fail("create", path)
        self.log.append(("create", path))
        if path in self.directories:
            raise FileExistsError(path)
        self.directories.add(path)
        self.files[path] = set()

    def load_memory(self, path: str) -> dict[str, Any]:
        self._fail("load", path)
        self.log.append(("load", path))
        if path not in self.memories:
            raise FileNotFoundError(f"{path}/listing_inputs.json")
        return copy.deepcopy(self.memories[path])

    def save_memory(self, payload: dict[str, Any], path: str) -> str:
        status = str(payload.get("source_group", {}).get("release_status", ""))
        operation = f"save_{status}" if status else "save"
        self._fail(operation, path)
        self.log.append(("save", path, status))
        if path not in self.directories:
            raise FileNotFoundError(path)
        self.memories[path] = copy.deepcopy(payload)
        self.files.setdefault(path, set()).add("listing_inputs.json")
        self._fail_after(operation, path)
        return f"{path}/listing_inputs.json"

    def list_files(self, path: str) -> list[str]:
        self._fail("list", path)
        self.log.append(("list", path))
        return [f"{path}/{name}" for name in sorted(self.files.get(path, set()))]

    def copy_file(self, source: str, destination: str) -> str:
        self._fail("copy", destination)
        self.log.append(("copy", source, destination))
        self.files[destination.rsplit("/", 1)[0]].add(_name(destination))
        self._fail_after("copy", destination)
        return destination

    def move_folder(self, source: str, destination: str) -> str:
        self._fail("move", destination)
        self.log.append(("move", source, destination))
        if destination in self.directories:
            raise FileExistsError(destination)
        self.directories.remove(source)
        self.directories.add(destination)
        self.files[destination] = self.files.pop(source)
        if source in self.memories:
            self.memories[destination] = self.memories.pop(source)
        self._fail_after("move", destination)
        return destination

    def _fail(self, operation: str, path: str) -> None:
        if self.failure == (operation, path):
            raise RuntimeError(f"injected {operation} failure: {path}")

    def _fail_after(self, operation: str, path: str) -> None:
        if self.after_failure == (operation, path):
            self.after_failure = None
            raise RuntimeError(f"injected lost {operation} response: {path}")


def _name(path: str) -> str:
    return PurePosixPath(path).name


def child_path(member: str, root: str = READY_ROOT) -> str:
    suffix = {"tshirt": "TSHIRT", "sweatshirt": "SWEATSHIRT", "hoodie": "HOODIE"}[member]
    return f"{root}/CHRTST-{suffix}"


def _add_workflow_event(payload: dict[str, Any], source_path: str, ready_path: str) -> dict[str, Any]:
    prepared = copy.deepcopy(payload)
    prepared["workflow_events"] = [
        *prepared.get("workflow_events", []),
        {"action": "submit_for_review", "from_state": "_stage", "to_state": "ready"},
    ]
    prepared["review_snapshot"] = {"listing_folder_path": ready_path}
    return prepared


def publish(storage: FakeStorage, profile: dict[str, Any]) -> dict[str, Any]:
    return publish_christmas_group(
        profile,
        source_folder_name="CHRTST",
        source_folder_path=SOURCE_PATH,
        preparation_root=PREPARATION_ROOT,
        ready_root=READY_ROOT,
        archive_root=ARCHIVE_ROOT,
        storage=storage.adapter(),
        prepare_child_payload=_add_workflow_event,
    )


def test_plan_has_exact_three_destinations_and_772_images() -> None:
    profile, source, images = build_source()
    manifest = build_christmas_group_image_manifest(images, profile)
    plan = build_christmas_group_publication_plan(
        profile, source, manifest,
        source_folder_name="CHRTST", preparation_root=PREPARATION_ROOT,
        ready_root=READY_ROOT, archive_root=ARCHIVE_ROOT,
    )
    assert [child["destination_folder"] for child in plan["children"].values()] == [
        "CHRTST-TSHIRT", "CHRTST-SWEATSHIRT", "CHRTST-HOODIE",
    ]
    assert [len(child["source_image_files"]) for child in plan["children"].values()] == [7, 7, 2]


def test_new_generic_profile_publication_releases_and_reconciles_idempotently() -> None:
    profile, source, images = build_source()
    profile = add_target_profiles(profile)
    source.update({
        "mpn": "CHRTST",
        "sku_decoration_code": "PRINT",
        "manual_sku_listing_code": "CHRTST",
        "generated_sku_listing_code": "",
        "sku_listing_code": "CHRTST",
    })
    storage = FakeStorage(source, images)

    first = publish(storage, profile)

    assert first["success"] is True
    archived = storage.memories[f"{ARCHIVE_ROOT}/CHRTST"]
    assert archived["group_submission"]["materialization_mode"] == "generic_profiles"
    expected = {
        "tshirt": ("GENERIC_SHIRTS", "PRINT-CHRTST-T"),
        "sweatshirt": ("GENERIC_SWEATSHIRTS", "PRINT-CHRTST-S"),
        "hoodie": ("GENERIC_HOODIES", "PRINT-CHRTST-H"),
    }
    for member_key, (template_key, parent_sku) in expected.items():
        memory = storage.memories[child_path(member_key)]
        assert memory["template_key"] == template_key
        assert memory["sku_listing_code"] == "CHRTST"
        assert memory["parent_sku_override"] == parent_sku
        assert memory["source_group"]["release_status"] == "released"

    second = publish(storage, profile)

    assert second["success"] is True
    assert second["state"] == "released"


def test_new_group_uses_staging_name_only_for_fanout_folders() -> None:
    profile, source, images = build_source()
    profile = add_target_profiles(profile)
    source.update({
        "staged_folder_name": "TSTGP",
        "mpn": "D304VG",
        "sku_decoration_code": "PRINT",
        "manual_sku_listing_code": "D304VG",
        "generated_sku_listing_code": "",
        "sku_listing_code": "D304VG",
    })
    manifest = build_christmas_group_image_manifest(images, profile)

    plan = build_christmas_group_publication_plan(
        profile,
        source,
        manifest,
        source_folder_name="TSTGP",
        preparation_root=PREPARATION_ROOT,
        ready_root=READY_ROOT,
        archive_root=ARCHIVE_ROOT,
    )

    assert plan["valid"] is True
    assert [child["destination_folder"] for child in plan["children"].values()] == [
        "TSTGP-TSHIRT",
        "TSTGP-SWEATSHIRT",
        "TSTGP-HOODIE",
    ]
    expected_parents = {
        "tshirt": "PRINT-D304VG-T",
        "sweatshirt": "PRINT-D304VG-S",
        "hoodie": "PRINT-D304VG-H",
    }
    for member_key, child in plan["children"].items():
        payload = child["payload"]
        assert payload["staged_folder_name"] == "TSTGP"
        assert payload["mpn"] == "D304VG"
        assert payload["sku_listing_code"] == "D304VG"
        assert payload["parent_sku"] == expected_parents[member_key]
        assert payload["source_group"]["source_mpn"] == "D304VG"
        assert payload["source_group"]["source_listing_code"] == "D304VG"


def test_live_preflight_is_read_only() -> None:
    profile, source, images = build_source()
    storage = FakeStorage(source, images)
    result = preflight_christmas_group_publication(
        profile, source_folder_name="CHRTST", source_folder_path=SOURCE_PATH,
        preparation_root=PREPARATION_ROOT, ready_root=READY_ROOT,
        archive_root=ARCHIVE_ROOT, storage=storage.adapter(),
    )
    assert result["valid"] is True
    assert not any(entry[0] in {"save", "create", "copy", "move", "ensure"} for entry in storage.log)


def test_valid_source_publishes_three_ordinary_released_children_then_archives_source() -> None:
    profile, source, images = build_source()
    storage = FakeStorage(source, images)
    result = publish(storage, profile)
    assert result["success"] is True
    assert SOURCE_PATH not in storage.directories
    assert f"{ARCHIVE_ROOT}/CHRTST" in storage.directories
    for member in ("tshirt", "sweatshirt", "hoodie"):
        memory = storage.memories[child_path(member)]
        assert memory["source_group"]["release_status"] == "released"
        assert memory["source_group"]["member_key"] == member
        assert "listing_group" not in memory
        assert "group_submission" not in memory
        assert any(event["action"] == "submit_for_review" for event in memory["workflow_events"])


def test_all_children_are_prepared_before_first_ready_move() -> None:
    profile, source, images = build_source()
    storage = FakeStorage(source, images)
    assert publish(storage, profile)["success"] is True
    first_ready_move = next(i for i, entry in enumerate(storage.log) if entry[:2] == ("move", child_path("tshirt", PREPARATION_ROOT)))
    for member in ("tshirt", "sweatshirt", "hoodie"):
        prepared_save = next(i for i, entry in enumerate(storage.log) if entry[:2] == ("save", child_path(member, PREPARATION_ROOT)))
        assert prepared_save < first_ready_move


def test_all_conflicts_are_checked_before_first_write() -> None:
    profile, source, images = build_source()
    storage = FakeStorage(source, images)
    conflict_path = child_path("hoodie")
    storage.directories.add(conflict_path)
    storage.files[conflict_path] = {"listing_inputs.json"}
    storage.memories[conflict_path] = {"source_group": {"task_id": "other"}}
    result = publish(storage, profile)
    assert result["state"] == "blocked"
    assert not any(entry[0] in {"save", "create", "copy", "move", "ensure"} for entry in storage.log)
    checked = {entry[1] for entry in storage.log if entry[0] == "exists"}
    assert all(child_path(member, root) in checked for member in ("tshirt", "sweatshirt", "hoodie") for root in (PREPARATION_ROOT, READY_ROOT))


@pytest.mark.parametrize("member", ["tshirt", "sweatshirt", "hoodie"])
def test_prepare_failure_keeps_source_and_no_ready_children_then_retry_resumes(member: str) -> None:
    profile, source, images = build_source()
    storage = FakeStorage(source, images)
    prefix = {"tshirt": "T01", "sweatshirt": "S01", "hoodie": "H01"}[member]
    target_name = next(name for name in storage.files[SOURCE_PATH] if name.startswith(prefix))
    storage.failure = ("copy", f"{child_path(member, PREPARATION_ROOT)}/{target_name}")
    failed = publish(storage, profile)
    assert failed["success"] is False
    assert SOURCE_PATH in storage.directories
    assert not any(child_path(key) in storage.directories for key in ("tshirt", "sweatshirt", "hoodie"))
    assert storage.memories[SOURCE_PATH]["group_submission"]["state"] == "failed"
    storage.failure = None
    before = len([entry for entry in storage.log if entry[:2] == ("create", child_path(member, PREPARATION_ROOT))])
    assert publish(storage, profile)["success"] is True
    after = len([entry for entry in storage.log if entry[:2] == ("create", child_path(member, PREPARATION_ROOT))])
    assert after == before


@pytest.mark.parametrize("member", ["tshirt", "sweatshirt", "hoodie"])
def test_failure_saving_initial_child_memory_resumes_empty_preparation_folder(member: str) -> None:
    profile, source, images = build_source()
    storage = FakeStorage(source, images)
    preparation_path = child_path(member, PREPARATION_ROOT)
    storage.failure = ("save_pending", preparation_path)

    failed = publish(storage, profile)

    assert failed["success"] is False
    assert preparation_path in storage.directories
    assert storage.files[preparation_path] == set()
    storage.failure = None
    assert publish(storage, profile)["success"] is True


@pytest.mark.parametrize("member", ["tshirt", "sweatshirt", "hoodie"])
def test_ready_publish_failure_leaves_existing_children_pending_and_retry_is_idempotent(member: str) -> None:
    profile, source, images = build_source()
    storage = FakeStorage(source, images)
    storage.failure = ("move", child_path(member))
    failed = publish(storage, profile)
    assert failed["success"] is False
    assert SOURCE_PATH in storage.directories
    for key in ("tshirt", "sweatshirt", "hoodie"):
        if child_path(key) in storage.memories:
            assert storage.memories[child_path(key)]["source_group"]["release_status"] == "pending"
            assert is_ready_listing_visible(storage.memories[child_path(key)]) is False
    storage.failure = None
    existing_ready = {path for path in storage.directories if path.startswith(f"{READY_ROOT}/")}
    assert publish(storage, profile)["success"] is True
    for path in existing_ready:
        assert len([entry for entry in storage.log if entry[0] == "move" and entry[2] == path]) == 1


def test_mismatched_existing_preparation_folder_blocks_without_overwrite() -> None:
    profile, source, images = build_source()
    storage = FakeStorage(source, images)
    path = child_path("tshirt", PREPARATION_ROOT)
    storage.directories.add(path)
    storage.files[path] = {"listing_inputs.json"}
    storage.memories[path] = {"source_group": {"task_id": "someone-else"}}
    result = publish(storage, profile)
    assert result["state"] == "blocked"
    assert any(error.get("member_key") == "tshirt" for error in result["errors"])
    assert not any(entry[0] in {"save", "create", "copy", "move", "ensure"} for entry in storage.log)


def test_release_failure_is_resumable_and_source_is_not_archived_early() -> None:
    profile, source, images = build_source()
    storage = FakeStorage(source, images)
    storage.failure = ("save_released", child_path("sweatshirt"))
    failed = publish(storage, profile)
    assert failed["success"] is False
    assert SOURCE_PATH in storage.directories
    assert f"{ARCHIVE_ROOT}/CHRTST" not in storage.directories
    assert storage.memories[child_path("sweatshirt")]["source_group"]["release_status"] == "pending"
    storage.failure = None
    assert publish(storage, profile)["success"] is True


def test_archive_failure_does_not_republish_and_retry_only_archives() -> None:
    profile, source, images = build_source()
    storage = FakeStorage(source, images)
    archive_path = f"{ARCHIVE_ROOT}/CHRTST"
    storage.failure = ("move", archive_path)
    failed = publish(storage, profile)
    assert failed["success"] is False
    assert all(storage.memories[child_path(member)]["source_group"]["release_status"] == "released" for member in ("tshirt", "sweatshirt", "hoodie"))
    assert SOURCE_PATH in storage.directories
    ready_moves = len([entry for entry in storage.log if entry[0] == "move" and entry[2].startswith(f"{READY_ROOT}/")])
    copies = len([entry for entry in storage.log if entry[0] == "copy"])
    storage.failure = None
    assert publish(storage, profile)["success"] is True
    assert len([entry for entry in storage.log if entry[0] == "move" and entry[2].startswith(f"{READY_ROOT}/")]) == ready_moves
    assert len([entry for entry in storage.log if entry[0] == "copy"]) == copies


def test_archive_retry_does_not_require_released_children_to_remain_in_ready() -> None:
    profile, source, images = build_source()
    storage = FakeStorage(source, images)
    archive_path = f"{ARCHIVE_ROOT}/CHRTST"
    storage.failure = ("move", archive_path)
    assert publish(storage, profile)["success"] is False

    for member in ("tshirt", "sweatshirt", "hoodie"):
        ready_path = child_path(member)
        approved_path = ready_path.replace("/ready/", "/approved/")
        storage.directories.remove(ready_path)
        storage.directories.add(approved_path)
        storage.files[approved_path] = storage.files.pop(ready_path)
        storage.memories[approved_path] = storage.memories.pop(ready_path)
    storage.failure = None

    result = publish(storage, profile)

    assert result["success"] is True
    assert archive_path in storage.directories
    assert not any(path.startswith(f"{READY_ROOT}/") for path in storage.directories)


def test_release_status_does_not_change_materialization_hash() -> None:
    profile, source, images = build_source()
    manifest = build_christmas_group_image_manifest(images, profile)
    plan = build_christmas_group_publication_plan(
        profile, source, manifest, source_folder_name="CHRTST",
        preparation_root=PREPARATION_ROOT, ready_root=READY_ROOT, archive_root=ARCHIVE_ROOT,
    )
    child = plan["children"]["hoodie"]
    payload = copy.deepcopy(child["payload"])
    payload["source_group"]["release_status"] = "pending"
    pending_hash = compute_christmas_child_materialization_hash(payload, child["source_images_by_colour"])
    payload["source_group"]["release_status"] = "released"
    released_hash = compute_christmas_child_materialization_hash(payload, child["source_images_by_colour"])
    assert pending_hash == released_hash == child["materialization_hash"]


def test_queue_visibility_only_hides_pending_group_children() -> None:
    assert is_ready_listing_visible({}) is True
    assert is_ready_listing_visible({"source_group": {"group_type": "other"}}) is True
    assert is_ready_listing_visible({"source_group": {"group_type": "christmas_project", "release_status": "released"}}) is True
    for release_status in ("pending", "", "unknown", None):
        memory = {"source_group": {"group_type": "christmas_project"}}
        if release_status is not None:
            memory["source_group"]["release_status"] = release_status
        assert is_ready_listing_visible(memory) is False


def test_source_is_unlocked_before_publication_and_locked_after_ledger_write() -> None:
    _profile, source, _images = build_source()
    assert is_group_submission_locked(source) is False
    source["group_submission"] = {
        "schema_version": 1,
        "task_id": "task-chrtst-1",
        "state": "preparing",
        "children": {"tshirt": {"status": "pending"}},
    }
    assert is_group_submission_locked(source) is True


def test_source_drift_after_partial_publication_blocks_existing_children() -> None:
    profile, source, images = build_source()
    storage = FakeStorage(source, images)
    storage.failure = ("move", child_path("sweatshirt"))
    assert publish(storage, profile)["success"] is False
    old_hash = storage.memories[SOURCE_PATH]["group_submission"]["children"]["tshirt"]["materialization_hash"]

    storage.failure = None
    storage.memories[SOURCE_PATH]["quantity"] += 1
    result = publish(storage, profile)

    assert result["state"] == "blocked"
    assert any(error["code"] == "source.drift" for error in result["errors"])
    assert storage.memories[child_path("tshirt")]["source_group"]["materialization_hash"] == old_hash


def test_copy_succeeds_then_response_is_lost_and_is_reconciled() -> None:
    profile, source, images = build_source()
    storage = FakeStorage(source, images)
    filename = "T01 T02 Black.png"
    destination = f"{child_path('tshirt', PREPARATION_ROOT)}/{filename}"
    storage.after_failure = ("copy", destination)

    result = publish(storage, profile)

    assert result["success"] is True
    assert filename in storage.files[child_path("tshirt")]
    assert len([entry for entry in storage.log if entry[:3] == ("copy", f"{SOURCE_PATH}/{filename}", destination)]) == 1


def test_pending_memory_write_succeeds_then_response_is_lost_and_retry_reuses_it() -> None:
    profile, source, images = build_source()
    storage = FakeStorage(source, images)
    preparation_path = child_path("tshirt", PREPARATION_ROOT)
    storage.after_failure = ("save_pending", preparation_path)

    first = publish(storage, profile)
    second = publish(storage, profile)

    assert first["success"] is False
    assert second["success"] is True
    assert len([
        entry for entry in storage.log
        if entry[:3] == ("save", preparation_path, "pending")
    ]) == 1


def test_release_memory_write_succeeds_then_response_is_lost_and_retry_reconciles() -> None:
    profile, source, images = build_source()
    storage = FakeStorage(source, images)
    ready_path = child_path("tshirt")
    storage.after_failure = ("save_released", ready_path)

    first = publish(storage, profile)
    assert first["success"] is False
    assert storage.memories[ready_path]["source_group"]["release_status"] == "released"
    second = publish(storage, profile)

    assert second["success"] is True
    assert len([
        entry for entry in storage.log
        if entry[:3] == ("save", ready_path, "released")
    ]) == 1


def test_ready_move_succeeds_then_response_is_lost_and_is_reconciled() -> None:
    profile, source, images = build_source()
    storage = FakeStorage(source, images)
    storage.after_failure = ("move", child_path("sweatshirt"))

    result = publish(storage, profile)

    assert result["success"] is True
    assert child_path("sweatshirt") in storage.directories
    assert child_path("sweatshirt", PREPARATION_ROOT) not in storage.directories


def test_archive_move_succeeds_then_response_is_lost_and_retry_recognizes_archive() -> None:
    profile, source, images = build_source()
    storage = FakeStorage(source, images)
    archive_path = f"{ARCHIVE_ROOT}/CHRTST"
    storage.after_failure = ("move", archive_path)

    first = publish(storage, profile)
    second = publish(storage, profile)

    assert first["success"] is True
    assert second["success"] is True
    assert second["reconciled"] is True
    assert len([entry for entry in storage.log if entry[:3] == ("move", SOURCE_PATH, archive_path)]) == 1


def test_ambiguous_ready_move_with_mismatched_destination_blocks() -> None:
    profile, source, images = build_source()

    class MismatchingMoveStorage(FakeStorage):
        def move_folder(self, source_path: str, destination: str) -> str:
            result = super().move_folder(source_path, destination)
            if destination == child_path("tshirt"):
                self.memories[destination]["source_group"]["materialization_hash"] = "wrong"
                raise RuntimeError("lost move response")
            return result

    storage = MismatchingMoveStorage(source, images)
    result = publish(storage, profile)

    assert result["state"] == "blocked"
    assert result["errors"][0]["code"] == "destination.conflict"


def test_ambiguous_archive_destination_with_mismatched_ledger_blocks() -> None:
    profile, source, images = build_source()

    class MismatchingArchiveStorage(FakeStorage):
        def move_folder(self, source_path: str, destination: str) -> str:
            result = super().move_folder(source_path, destination)
            if destination == f"{ARCHIVE_ROOT}/CHRTST":
                self.memories[destination]["group_submission"]["task_id"] = "wrong-task"
                raise RuntimeError("lost archive response")
            return result

    storage = MismatchingArchiveStorage(source, images)
    result = publish(storage, profile)

    assert result["state"] == "blocked"
    assert result["errors"][0]["code"] == "destination.conflict"


def test_released_ledger_cannot_claim_a_pending_child() -> None:
    profile, source, images = build_source()
    storage = FakeStorage(source, images)
    storage.failure = ("move", child_path("tshirt"))
    assert publish(storage, profile)["success"] is False
    ledger = storage.memories[SOURCE_PATH]["group_submission"]
    ledger["state"] = "released"
    ledger["children"]["tshirt"]["status"] = "published_pending"
    storage.failure = None

    result = publish(storage, profile)

    assert result["state"] == "blocked"
    assert any(error["code"] == "ledger.inconsistent" for error in result["errors"])


def test_unexpected_file_in_matching_pending_child_blocks_reuse() -> None:
    profile, source, images = build_source()
    storage = FakeStorage(source, images)
    storage.failure = ("move", child_path("tshirt"))
    assert publish(storage, profile)["success"] is False
    preparation_path = child_path("tshirt", PREPARATION_ROOT)
    storage.files[preparation_path].add("unexpected.png")
    storage.failure = None

    result = publish(storage, profile)

    assert result["state"] == "blocked"
    assert any("unexpected image" in error["message"] for error in result["errors"])


def test_source_ledger_is_additive_and_preserves_metadata() -> None:
    profile, source, images = build_source()
    storage = FakeStorage(source, images)
    storage.failure = ("move", child_path("tshirt"))
    publish(storage, profile)
    saved = storage.memories[SOURCE_PATH]
    assert saved["workflow_events"] == [{"action": "draft_saved"}]
    assert saved["group_submission"]["schema_version"] == 1
    assert saved["group_submission"]["task_id"] == "task-chrtst-1"
    assert list(saved["group_submission"]["children"]) == ["tshirt", "sweatshirt", "hoodie"]
    assert saved["group_submission"]["last_error"]


def test_storage_contract_has_no_delete_or_workbook_operation() -> None:
    fields = set(ChristmasGroupPublicationStorage.__dataclass_fields__)
    assert fields == {
        "path_exists", "ensure_folder", "create_folder", "load_memory", "save_memory",
        "list_files", "copy_file", "move_folder",
    }
    assert not any("delete" in field or "workbook" in field for field in fields)


def test_publication_service_imports_no_streamlit_dropbox_openpyxl_or_network_client() -> None:
    sys.modules.pop("services.christmas_group_publication", None)
    before = set(sys.modules)
    module = importlib.import_module("services.christmas_group_publication")
    imported = set(sys.modules) - before
    assert module.__name__ == "services.christmas_group_publication"
    assert not any(name.startswith("streamlit") for name in imported)
    assert not any("dropbox" in name.casefold() for name in imported)
    assert not any(name.startswith("openpyxl") for name in imported)
    assert not any(name.startswith(("requests", "httpx", "urllib3")) for name in imported)


def test_configured_roots_are_explicit_sibling_non_queue_locations() -> None:
    config = json.loads((ROOT / "config" / "dropbox_templates.json").read_text(encoding="utf-8"))
    assert config["grouped_preparation_root"].endswith("/_grouped_preparation")
    assert config["grouped_archive_root"].endswith("/_grouped_archive")
    assert config["grouped_preparation_root"] not in {
        config["stage_root"], config["ready_root"], config["approved_root"], config["finished_root"],
    }
    assert config["grouped_archive_root"] not in {
        config["stage_root"], config["ready_root"], config["approved_root"], config["finished_root"],
    }
