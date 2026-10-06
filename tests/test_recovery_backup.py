"""R15 backup and restore: consistent prefixes, verified images, honest restore."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from llm_research_os.application.workspace import Workspace, init_workspace, load_workspace
from llm_research_os.artifacts import LocalArtifactStore
from llm_research_os.blocks.registry import build_registry
from llm_research_os.execution import TrustedKernel
from llm_research_os.projections.replay import replay_events
from llm_research_os.recovery import (
    BackupIntegrityError,
    RecoveryError,
    create_backup,
    load_manifest,
    restore_backup,
    verify_backup,
)
from llm_research_os.recovery import backup as backup_module
from llm_research_os.recovery.models import EVENTS_SNAPSHOT_NAME, MANIFEST_NAME
from llm_research_os.spec.io import load_spec
from llm_research_os.storage import EventStore
from llm_research_os.storage.store import (
    control_store_marker_path,
    control_store_was_removed,
)

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples"
PROJECT = "example-minimal"
RUN = "run.recovery.1"
SOURCE = "researchos.dev/recovery"
SCHEMA = "https://researchos.dev/schemas/research-event/v0alpha1.schema.json"
NOW = datetime(2026, 10, 5, 2, 0, tzinfo=UTC)


def _workspace(tmp_path: Path, project_id: str = PROJECT) -> Workspace:
    return init_workspace(
        tmp_path / "workspace",
        project_id=project_id,
        control_db=Path("control/events.sqlite"),
        cas_root=Path("cas"),
        worker_root=Path("worker"),
    )


def _seed_checkpoint(workspace: Workspace) -> None:
    """Append real research and execution facts through the public CLI."""

    for arguments in (
        [
            "m1",
            "prove",
            str(EXAMPLES / "m1-checkpoint"),
            str(workspace.control_db),
            "--decision",
            "accept",
            "--format",
            "json",
        ],
        [
            "evidence",
            "import",
            str(EXAMPLES / "evidence" / "valid" / "import-markdown.json"),
            str(workspace.control_db),
            "--source",
            str(EXAMPLES / "evidence" / "sources" / "eval-split.md"),
            "--artifacts",
            str(workspace.cas_root),
            "--format",
            "json",
        ],
    ):
        result = subprocess.run(
            [sys.executable, "-m", "llm_research_os", *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr


def _append_in_flight_run(workspace: Workspace) -> None:
    """Leave one Run started and never finished, as a crash would."""

    report = TrustedKernel(build_registry()).dry_run(
        load_spec(EXAMPLES / "valid" / "minimal.yaml"), workflow_id="workflow.simulation"
    )
    if report.digests.plan is None:
        raise AssertionError("the in-flight Run fixture requires a ready plan")
    with EventStore(workspace.control_db, require_existing=True) as store:
        for event in (
            {
                "specversion": "1.0",
                "id": "evt.recovery.run.queued",
                "source": SOURCE,
                "type": "run.queued",
                "time": "2026-10-05T01:00:00Z",
                "subject": RUN,
                "dataschema": SCHEMA,
                "datacontenttype": "application/json",
                "streamid": "stream.recovery",
                "data": {
                    "schemaVersion": "v0alpha1",
                    "actor": {"id": "researcher.alice"},
                    "projectId": PROJECT,
                    "experimentRevision": 1,
                    "payload": {
                        "workflowId": "workflow.simulation",
                        "specDigest": report.digests.spec,
                        "registryDigest": report.digests.registry,
                        "planDigest": report.digests.plan,
                        "maxAttempts": 1,
                    },
                    "evidenceRefs": [],
                    "runId": RUN,
                },
            },
            {
                "specversion": "1.0",
                "id": "evt.recovery.run.started",
                "source": SOURCE,
                "type": "run.started",
                "time": "2026-10-05T01:00:01Z",
                "subject": RUN,
                "dataschema": SCHEMA,
                "datacontenttype": "application/json",
                "streamid": "stream.recovery",
                "data": {
                    "schemaVersion": "v0alpha1",
                    "actor": {"id": "researcher.alice"},
                    "projectId": PROJECT,
                    "experimentRevision": 1,
                    "payload": {},
                    "evidenceRefs": [],
                    "runId": RUN,
                },
            },
        ):
            store.append(event)


def _event_digests(database: Path) -> tuple[tuple[int, str], ...]:
    with EventStore(database, create=False) as store:
        return tuple(
            (stored.sequence, stored.digest)
            for stored in replay_events(store, freeze_high_water=True)
        )


def _cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "llm_research_os", *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_backup_captures_a_verified_prefix_and_its_referenced_objects(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    source_digests = _event_digests(workspace.control_db)
    assert source_digests

    image = tmp_path / "image"
    report = create_backup(workspace, image, now=NOW)

    manifest = load_manifest(image)
    assert manifest.project_id == PROJECT
    assert manifest.high_water == len(source_digests)
    assert manifest.event_count == len(source_digests)
    assert manifest.objects, "the seeded evidence import references a CAS object"
    assert manifest.relaunch_policy == "not-relaunched"
    assert report.verified is True
    assert report.object_count == len(manifest.objects)
    assert verify_backup(image).high_water == manifest.high_water


def test_backup_uses_a_snapshot_not_the_live_database_file(tmp_path: Path) -> None:
    """A live file copy would keep the WAL sidecar; a snapshot must be standalone."""

    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)

    snapshot = image / EVENTS_SNAPSHOT_NAME
    assert snapshot.is_file()
    assert not (image / f"{EVENTS_SNAPSHOT_NAME}-wal").exists()
    assert not (image / f"{EVENTS_SNAPSHOT_NAME}-shm").exists()
    # Every committed event lives in the single file the manifest covers, so a
    # copy of that file alone still verifies.
    assert verify_backup(image).event_count == len(_event_digests(workspace.control_db))


def test_verify_rejects_a_tampered_snapshot(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)

    snapshot = image / EVENTS_SNAPSHOT_NAME
    payload = bytearray(snapshot.read_bytes())
    payload[-64] ^= 0xFF
    snapshot.write_bytes(bytes(payload))

    with pytest.raises(BackupIntegrityError) as info:
        verify_backup(image)
    assert info.value.code == "backup-snapshot-mismatch"


def test_verify_rejects_a_tampered_object(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)
    manifest = load_manifest(image)
    entry = manifest.objects[0]

    target = image / "cas" / entry.storage_key
    target.write_bytes(b"tampered\n")

    with pytest.raises(BackupIntegrityError) as info:
        verify_backup(image)
    assert info.value.code == "backup-object-mismatch"


def test_verify_rejects_a_manifest_that_names_an_escaping_key(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)
    manifest_path = image / MANIFEST_NAME
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["objects"][0]["storageKey"] = "../../escaped"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RecoveryError) as info:
        verify_backup(image)
    assert info.value.code == "backup-object-path-invalid"


def test_verify_rejects_an_image_without_a_manifest(tmp_path: Path) -> None:
    image = tmp_path / "empty"
    image.mkdir()
    with pytest.raises(RecoveryError) as info:
        verify_backup(image)
    assert info.value.code == "backup-manifest-missing"


def test_backup_fails_closed_when_a_referenced_object_is_missing(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    manifest_digests = _referenced_digests(workspace)
    assert manifest_digests

    store = LocalArtifactStore(workspace.cas_root)
    first = manifest_digests[0]
    key = (
        store.root
        / "objects"
        / "sha256"
        / first.removeprefix("sha256:")[:2]
        / first.removeprefix("sha256:")[2:]
    )
    key.unlink()

    with pytest.raises(BackupIntegrityError) as info:
        create_backup(workspace, tmp_path / "image", now=NOW)
    assert info.value.code == "backup-object-missing"


def test_interrupted_backup_leaves_no_usable_image(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"

    original = LocalArtifactStore.verify

    def _explode(self: LocalArtifactStore, digest: str) -> Any:
        raise OSError("simulated disk failure mid-copy")

    LocalArtifactStore.verify = _explode  # type: ignore[method-assign]
    try:
        with pytest.raises(OSError, match="simulated disk failure"):
            create_backup(workspace, image, now=NOW)
    finally:
        LocalArtifactStore.verify = original  # type: ignore[method-assign]

    assert not image.exists()
    assert list(tmp_path.glob(".image.partial*")) == []


def test_backup_refuses_a_non_empty_destination(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    image.mkdir()
    (image / "stray.txt").write_text("occupied", encoding="utf-8")

    with pytest.raises(RecoveryError) as info:
        create_backup(workspace, image, now=NOW)
    assert info.value.code == "backup-path-occupied"


def test_restore_reproduces_event_digests_and_research_ledger(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    source_digests = _event_digests(workspace.control_db)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)

    target = tmp_path / "restored"
    report = restore_backup(image, target)

    assert report.restored_high_water == len(source_digests)
    assert report.restored_event_count == len(source_digests)
    assert report.ledger_matches is True
    assert report.appended_events == 0
    assert report.relaunch_policy == "not-relaunched"
    assert _event_digests(load_workspace(target).control_db) == source_digests
    restored = load_workspace(target)
    assert restored.project_id == PROJECT
    assert restored.worker_root.is_dir()
    assert restored.worker_root != restored.control_db.parent


def test_restore_marks_the_control_store_as_present(tmp_path: Path) -> None:
    """A restored workspace must be able to tell its store was removed later.

    The restore path does not go through EventStore's create branch, so without
    this the marker would be missing and a restored workspace whose store was
    later deleted would read as never-populated -- the precise ambiguity the
    marker exists to remove.
    """
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)

    target = tmp_path / "restored"
    restore_backup(image, target)

    restored = load_workspace(target)
    assert control_store_marker_path(restored.control_db).exists()
    assert control_store_was_removed(restored.control_db) is False

    restored.control_db.unlink()
    assert control_store_was_removed(restored.control_db) is True


def test_restore_copies_referenced_objects_into_the_workspace_cas(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    manifest = create_backup(workspace, image, now=NOW)
    target = tmp_path / "restored"

    restore_backup(image, target)

    restored = LocalArtifactStore(load_workspace(target).cas_root)
    for entry in load_manifest(image).objects:
        assert restored.verify(entry.digest).size_bytes == entry.size_bytes
    assert manifest.object_count > 0


def test_restore_never_relaunches_an_in_flight_run(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    _append_in_flight_run(workspace)
    before = _event_digests(workspace.control_db)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)

    target = tmp_path / "restored"
    report = restore_backup(image, target)

    assert [item.run_id for item in report.reconciled_runs] == [RUN]
    assert report.reconciled_runs[0].last_state == "running"
    assert report.reconciled_runs[0].observation == "unknown"
    assert report.reconciled_runs[0].next_action == "reconcile-manually"
    assert report.appended_events == 0
    assert _event_digests(load_workspace(target).control_db) == before


def test_interrupted_restore_leaves_no_half_workspace_and_can_be_retried(
    tmp_path: Path,
) -> None:
    """A failed restore must not leave a directory a retry would refuse as existing."""

    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)
    target = tmp_path / "restored"

    original = LocalArtifactStore.verify

    def _explode(self: LocalArtifactStore, digest: str) -> Any:
        raise OSError("simulated disk failure mid-restore")

    LocalArtifactStore.verify = _explode  # type: ignore[method-assign]
    try:
        with pytest.raises(OSError, match="simulated disk failure mid-restore"):
            restore_backup(image, target)
    finally:
        LocalArtifactStore.verify = original  # type: ignore[method-assign]

    assert not target.exists()
    assert list(tmp_path.glob(".restored.partial*")) == []

    report = restore_backup(image, target)
    assert report.ledger_matches is True
    assert load_workspace(target).control_db.is_file()


def test_restore_refuses_an_occupied_destination_without_touching_it(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)

    target = tmp_path / "restored"
    target.mkdir()
    (target / "keep.txt").write_text("mine", encoding="utf-8")

    with pytest.raises(RecoveryError) as info:
        restore_backup(image, target)
    assert info.value.code == "restore-path-occupied"
    assert (target / "keep.txt").read_text(encoding="utf-8") == "mine"


def test_restore_refuses_a_damaged_image_before_writing_anything(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)
    manifest = load_manifest(image)
    (image / "cas" / manifest.objects[0].storage_key).write_bytes(b"corrupt\n")

    target = tmp_path / "restored"
    with pytest.raises(BackupIntegrityError):
        restore_backup(image, target)
    assert not target.exists()


def test_cli_round_trips_backup_verify_restore(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    target = tmp_path / "restored"

    created = _cli("backup", "create", "--root", str(workspace.root), "--out", str(image))
    assert created.returncode == 0, created.stderr
    assert json.loads(created.stdout)["verified"] is True

    verified = _cli("backup", "verify", "--image", str(image))
    assert verified.returncode == 0, verified.stderr

    restored = _cli("backup", "restore", "--image", str(image), "--root", str(target))
    assert restored.returncode == 0, restored.stderr
    report = json.loads(restored.stdout)
    assert report["ledgerMatches"] is True
    assert report["appendedEvents"] == 0
    assert report["relaunchPolicy"] == "not-relaunched"


def test_cli_backup_failure_uses_a_closed_error_code(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    result = _cli("backup", "create", "--root", str(workspace.root), "--out", str(tmp_path / "no"))
    assert result.returncode == 0
    again = _cli("backup", "create", "--root", str(workspace.root), "--out", str(tmp_path / "no"))
    assert again.returncode == 2
    assert json.loads(again.stderr)["code"] == "backup-path-occupied"


def _referenced_digests(workspace: Workspace) -> list[str]:
    with EventStore(workspace.control_db, create=False) as store:
        high_water = store.freeze_high_water()
        from llm_research_os.projections.sqlite import referenced_digests

        found = {
            digest
            for stored in replay_events(store, until_sequence=high_water, freeze_high_water=False)
            for digest, _role in referenced_digests(stored.event)
            if digest.startswith("sha256:")
        }
    return sorted(found)


def test_verify_rejects_a_manifest_that_drops_a_referenced_object(tmp_path: Path) -> None:
    """The object set is re-derived from the events, not read from the manifest.

    A manifest that quietly omits an entry would otherwise verify and then
    restore a project that references a content object it does not hold.
    """

    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)
    assert load_manifest(image).objects, "the fixture must reference a CAS object"

    _edit_manifest(image, lambda payload: payload["objects"].pop())

    with pytest.raises(BackupIntegrityError) as info:
        verify_backup(image)
    assert info.value.code == "backup-object-set-mismatch"


def test_verify_rejects_forged_manifest_metadata(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)
    manifest = load_manifest(image)

    cases: tuple[tuple[str, dict[str, object], str], ...] = (
        (
            "snapshotBytes",
            {"snapshotBytes": manifest.snapshot_bytes + 1},
            "backup-snapshot-mismatch",
        ),
        ("totalObjectBytes", {"totalObjectBytes": 1}, "backup-object-mismatch"),
        (
            "lastEventDigest",
            {"lastEventDigest": "sha256:" + "0" * 64},
            "backup-event-digest-mismatch",
        ),
        ("schemaVersion", {"schemaVersion": 99}, "backup-schema-mismatch"),
        ("schemaDigest", {"schemaDigest": "sha256:" + "0" * 64}, "backup-schema-mismatch"),
    )
    for label, override, expected in cases:
        fresh = tmp_path / f"image-{label}"
        shutil.copytree(image, fresh)
        _edit_manifest(fresh, lambda payload, o=override: payload.update(o))
        with pytest.raises(BackupIntegrityError) as info:
            verify_backup(fresh)
        assert info.value.code == expected, label


def test_verify_rejects_an_object_key_not_derived_from_its_digest(tmp_path: Path) -> None:
    """A non-canonical key would make restore read or write an arbitrary path."""

    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)
    manifest = load_manifest(image)
    entry = manifest.objects[0]
    elsewhere = image / "cas" / "elsewhere.bin"
    elsewhere.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(image / "cas" / entry.storage_key), elsewhere)

    _edit_manifest(
        image, lambda payload: payload["objects"][0].update({"storageKey": "elsewhere.bin"})
    )

    with pytest.raises(RecoveryError) as info:
        verify_backup(image)
    assert info.value.code == "backup-object-path-invalid"


def test_verify_rejects_a_truncated_snapshot(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)
    snapshot = image / EVENTS_SNAPSHOT_NAME
    snapshot.write_bytes(snapshot.read_bytes()[: snapshot.stat().st_size // 2])

    with pytest.raises(BackupIntegrityError) as info:
        verify_backup(image)
    assert info.value.code == "backup-snapshot-mismatch"


def test_verify_reports_a_missing_snapshot_distinctly(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)
    (image / EVENTS_SNAPSHOT_NAME).unlink()

    with pytest.raises(BackupIntegrityError) as info:
        verify_backup(image)
    assert info.value.code == "backup-snapshot-missing"


def test_verify_rejects_an_oversized_manifest(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)
    (image / MANIFEST_NAME).write_text("x" * (9 << 20), encoding="utf-8")

    with pytest.raises(RecoveryError) as info:
        verify_backup(image)
    assert info.value.code == "backup-manifest-too-large"


def test_verify_rejects_a_manifest_that_is_not_the_contract(tmp_path: Path) -> None:
    image = tmp_path / "image"
    image.mkdir()
    (image / MANIFEST_NAME).write_text('{"apiVersion": "nope"}', encoding="utf-8")

    with pytest.raises(RecoveryError) as info:
        verify_backup(image)
    assert info.value.code == "backup-manifest-invalid"


def test_backup_refuses_a_control_store_that_is_too_large(tmp_path: Path, monkeypatch: Any) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    monkeypatch.setattr(backup_module, "_MAX_SNAPSHOT_BYTES", 1024)

    with pytest.raises(RecoveryError) as info:
        create_backup(workspace, tmp_path / "image", now=NOW)
    assert info.value.code == "backup-too-large"


def test_backup_of_an_empty_workspace_has_no_last_digest(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    with EventStore(workspace.control_db):
        pass
    image = tmp_path / "image"

    report = create_backup(workspace, image, now=NOW)

    assert report.high_water == 0
    assert report.event_count == 0
    manifest = load_manifest(image)
    assert manifest.last_event_digest is None
    assert verify_backup(image).high_water == 0


def test_backup_refuses_a_missing_control_store(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    with EventStore(workspace.control_db):
        pass
    workspace.control_db.unlink()

    with pytest.raises(RecoveryError) as info:
        create_backup(workspace, tmp_path / "image", now=NOW)
    assert info.value.code == "control-store-missing"


def test_restore_refuses_a_destination_that_is_a_file(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)
    target = tmp_path / "restored"
    target.write_text("not a directory", encoding="utf-8")

    with pytest.raises(RecoveryError) as info:
        restore_backup(image, target)
    assert info.value.code == "restore-path-invalid"


def test_restore_under_a_different_project_id_is_refused(tmp_path: Path) -> None:
    """An override naming a project the events do not carry must not "match"."""

    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)

    with pytest.raises(BackupIntegrityError) as info:
        restore_backup(image, tmp_path / "restored", project_id="some-other-project")
    assert info.value.code == "restore-ledger-mismatch"
    assert not (tmp_path / "restored").exists()


def test_restore_uses_the_manifest_it_verified(tmp_path: Path, monkeypatch: Any) -> None:
    """A manifest swapped between verify and use must not be the one that is applied."""

    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)
    verified = load_manifest(image)
    original = backup_module._verify_image
    calls = {"n": 0}

    def _swap_once(candidate: Path) -> Any:
        calls["n"] += 1
        manifest, report = original(candidate)
        if calls["n"] == 1:
            _edit_manifest(candidate, lambda payload: payload.update({"projectId": "swapped"}))
        return manifest, report

    monkeypatch.setattr(backup_module, "_verify_image", _swap_once)

    report = restore_backup(image, tmp_path / "restored")

    assert report.project_id == verified.project_id
    assert calls["n"] == 1


def test_restore_reports_a_truncated_object_copy(tmp_path: Path, monkeypatch: Any) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)
    entry = load_manifest(image).objects[0]
    real_copy = backup_module._copy_file

    def _truncate(source: Path, destination: Path) -> None:
        real_copy(source, destination)
        if destination.name == Path(entry.storage_key).name:
            destination.write_bytes(destination.read_bytes()[:-1])

    monkeypatch.setattr(backup_module, "_copy_file", _truncate)

    with pytest.raises(BackupIntegrityError) as info:
        restore_backup(image, tmp_path / "restored")
    assert info.value.code == "restore-object-mismatch"
    assert not (tmp_path / "restored").exists()


def test_restore_uses_the_verified_store_for_its_own_comparison(tmp_path: Path) -> None:
    """A restored store that disagrees with the image is refused, not reported."""

    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)
    target = tmp_path / "restored"
    real_copy = backup_module._copy_file

    def _append_event(source: Path, destination: Path) -> None:
        # Target only the restore's staged control store, not the verify probe.
        real_copy(source, destination)
        if destination.name.startswith(".events.sqlite"):
            with EventStore(destination, require_existing=True) as store:
                store.append(
                    {
                        "specversion": "1.0",
                        "id": "evt.recovery.injected",
                        "source": SOURCE,
                        "type": "spec.revised",
                        "time": "2026-10-05T05:00:00Z",
                        "subject": "spec.injected",
                        "dataschema": SCHEMA,
                        "datacontenttype": "application/json",
                        "streamid": "stream.recovery",
                        "data": {
                            "schemaVersion": "v0alpha1",
                            "actor": {"id": "researcher.alice"},
                            "projectId": PROJECT,
                            "experimentRevision": 1,
                            "payload": {},
                            "evidenceRefs": [],
                        },
                    }
                )

    backup_module._copy_file = _append_event
    try:
        with pytest.raises(BackupIntegrityError) as info:
            restore_backup(image, target)
    finally:
        backup_module._copy_file = real_copy
    assert info.value.code in {
        "restore-event-mismatch",
        "restore-ledger-mismatch",
        "restore-snapshot-mismatch",
    }
    assert not target.exists()


def test_backup_and_verify_handle_a_path_containing_uri_delimiters(tmp_path: Path) -> None:
    """'#' and '?' are legal filename characters and must not truncate the URI."""

    root = tmp_path / "ws#frag?ment"
    root.mkdir()
    workspace = init_workspace(
        root,
        project_id=PROJECT,
        control_db=Path("control/events.sqlite"),
        cas_root=Path("cas"),
        worker_root=Path("worker"),
    )
    with EventStore(workspace.control_db):
        pass
    subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_research_os",
            "m1",
            "prove",
            str(EXAMPLES / "m1-checkpoint"),
            str(workspace.control_db),
            "--decision",
            "accept",
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    expected = len(_event_digests(workspace.control_db))

    image = tmp_path / "image"
    report = create_backup(workspace, image, now=NOW)

    assert report.high_water == expected
    assert verify_backup(image).high_water == expected
    assert restore_backup(image, tmp_path / "restored").restored_event_count == expected


def _edit_manifest(image: Path, mutate: Any) -> None:
    path = image / MANIFEST_NAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_restore_rejects_snapshot_replacement_after_verification(
    tmp_path: Path, monkeypatch: Any
) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)
    original = backup_module._verify_image

    def swap(candidate: Path) -> Any:
        result = original(candidate)
        snapshot = candidate / EVENTS_SNAPSHOT_NAME
        # Change only an unused SQLite header byte: event count and ledger remain identical.
        data = bytearray(snapshot.read_bytes())
        data[72] ^= 1
        snapshot.write_bytes(data)
        return result

    monkeypatch.setattr(backup_module, "_verify_image", swap)
    with pytest.raises(BackupIntegrityError) as info:
        restore_backup(image, tmp_path / "restored")
    assert info.value.code == "restore-snapshot-mismatch"
    assert not (tmp_path / "restored").exists()


@pytest.mark.parametrize("field", ("control_db", "cas_root", "worker_root"))
def test_restore_refuses_external_layout_without_writing(tmp_path: Path, field: str) -> None:
    workspace = _workspace(tmp_path)
    _seed_checkpoint(workspace)
    image = tmp_path / "image"
    create_backup(workspace, image, now=NOW)
    outside = tmp_path / "outside"
    with pytest.raises(RecoveryError) as info:
        restore_backup(image, tmp_path / "restored", **{field: outside})
    assert info.value.code == "restore-layout-invalid"
    assert not outside.exists()
    assert not (tmp_path / "restored").exists()


def test_verify_refuses_fifo_manifest_without_waiting(tmp_path: Path) -> None:
    import os

    image = tmp_path / "image"
    image.mkdir()
    os.mkfifo(image / MANIFEST_NAME)
    with pytest.raises(RecoveryError) as info:
        verify_backup(image)
    assert info.value.code == "backup-file-invalid"
