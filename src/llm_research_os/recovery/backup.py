"""Consistent prefix backup and verified restore for one project workspace.

The unit of a backup is a *verified high-water prefix* of the EventStore plus
the immutable CAS objects that prefix references. Three properties are load
bearing and each fails closed:

* the SQLite copy uses the online backup API, so a live database is never
  copied as a file (R15 out of scope explicitly forbids the naive copy);
* the manifest describes the snapshot that was actually written, and the
  snapshot is re-verified before any workspace is touched, so a damaged image
  can never become the new head of a project;
* restore appends nothing and starts nothing, so a historical task is reported
  as ``unknown`` for operator reconciliation instead of being relaunched
  (ADR-0054).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import quote

from llm_research_os.application.workspace import Workspace, init_workspace
from llm_research_os.artifacts.store import LocalArtifactStore, storage_key_for
from llm_research_os.canonical import content_digest
from llm_research_os.projections.replay import replay_events
from llm_research_os.projections.sqlite import referenced_digests
from llm_research_os.recovery.errors import BackupIntegrityError, RecoveryError
from llm_research_os.recovery.models import (
    EVENTS_SNAPSHOT_NAME,
    MANIFEST_NAME,
    OBJECT_ROOT_NAME,
    BackupManifest,
    BackupObject,
    BackupReport,
    ReconciledRun,
    RestoreReport,
)
from llm_research_os.research.ledger import build_research_ledger
from llm_research_os.research.models import research_ledger_document
from llm_research_os.runs.models import TERMINAL_RUN_STATUSES
from llm_research_os.storage.schema import SCHEMA_DEFINITION_DIGEST, SCHEMA_VERSION
from llm_research_os.storage.store import EventStore, write_control_store_marker

_CHUNK = 1 << 20
_MAX_SNAPSHOT_BYTES = 1 << 34  # 16 GiB guard on a single snapshot file.
_MAX_MANIFEST_BYTES = 8 << 20  # 8 MiB guard on an untrusted manifest read.


def create_backup(workspace: Workspace, destination: Path, *, now: datetime) -> BackupReport:
    """Write a verified prefix backup image and return its report.

    The image is assembled in a sibling directory and renamed into place, so an
    interrupted run leaves a ``.partial`` directory that is not a valid image
    rather than a half-written one that verifies as far as it got.
    """

    image = destination.absolute()
    if image.exists():
        if not image.is_dir():
            raise RecoveryError("backup-path-invalid", "backup destination is not a directory")
        if any(image.iterdir()):
            raise RecoveryError("backup-path-occupied", "backup destination is not empty")
    image.parent.mkdir(parents=True, exist_ok=True)
    staging = image.parent / f".{image.name}.partial-{os.getpid()}"
    if staging.exists():
        _remove_tree(staging)
    staging.mkdir(parents=True)
    try:
        report = _build_image(workspace, staging, now=now)
    except BaseException:
        _remove_tree(staging)
        raise
    staging.rename(image)
    return report


def verify_backup(image: Path) -> BackupReport:
    """Re-verify a backup image from its own bytes and return its report.

    Verification is read-only with respect to the image: opening the snapshot
    in place would put it back into WAL mode and change the bytes the manifest
    just described, so the event re-verification runs on a copy.
    """

    manifest, report = _verify_image(image)
    del manifest
    return report


def _verify_image(image: Path) -> tuple[BackupManifest, BackupReport]:
    """Verify an image and return the manifest that was actually verified.

    The caller receives the *same* manifest object the checks ran against.
    Re-reading the file afterwards would be a time-of-check/time-of-use gap on
    exactly the artifact an operator restores from a mounted archive.
    """

    manifest = load_manifest(image)
    snapshot = image / EVENTS_SNAPSHOT_NAME
    observed = _file_digest(snapshot, missing_code="backup-snapshot-missing")
    if observed != manifest.snapshot_digest:
        raise BackupIntegrityError(
            "backup-snapshot-mismatch", "the event snapshot does not match its manifest digest"
        )
    if snapshot.stat().st_size != manifest.snapshot_bytes:
        raise BackupIntegrityError(
            "backup-snapshot-mismatch", "the event snapshot does not match its recorded size"
        )
    if manifest.schema_version != SCHEMA_VERSION:
        raise BackupIntegrityError(
            "backup-schema-mismatch",
            "the image was written at a schema this build does not support",
        )
    if manifest.schema_digest != SCHEMA_DEFINITION_DIGEST:
        raise BackupIntegrityError(
            "backup-schema-mismatch", "the image records a different store schema"
        )
    for entry in manifest.objects:
        if entry.storage_key != storage_key_for(entry.digest):
            # A key that is not the one derived from the digest is a hand-edited
            # manifest, and following it would read or write an arbitrary path.
            raise RecoveryError(
                "backup-object-path-invalid", "a backup object key is not derived from its digest"
            )
        path = _image_object_path(image, entry.storage_key)
        if _file_digest(path) != entry.digest:
            raise BackupIntegrityError(
                "backup-object-mismatch", "a backup object does not match its manifest digest"
            )
        if path.stat().st_size != entry.size_bytes:
            raise BackupIntegrityError(
                "backup-object-mismatch", "a backup object does not match its recorded size"
            )
    with _snapshot_copy(snapshot) as store:
        count = store.verify_integrity()
        head = store.last_sequence()
        referenced, last_digest = _prefix_object_state(store, head)
    if count != manifest.event_count or head != manifest.high_water:
        raise BackupIntegrityError(
            "backup-event-count-mismatch",
            "the event snapshot does not contain the manifest event count",
        )
    if last_digest != manifest.last_event_digest:
        raise BackupIntegrityError(
            "backup-event-digest-mismatch",
            "the event snapshot head does not match the manifest digest",
        )
    # The object *set* is re-derived from the events, not read from the
    # manifest. A manifest that quietly drops an entry would otherwise verify
    # and then restore a project that references an object it does not hold.
    if referenced != tuple(entry.digest for entry in manifest.objects):
        raise BackupIntegrityError(
            "backup-object-set-mismatch",
            "the image objects do not match the objects its events reference",
        )
    if sum(entry.size_bytes for entry in manifest.objects) != manifest.total_object_bytes:
        raise BackupIntegrityError(
            "backup-object-mismatch", "the image objects do not match the recorded total size"
        )
    return manifest, BackupReport(
        projectId=manifest.project_id,
        verified=True,
        highWater=manifest.high_water,
        eventCount=manifest.event_count,
        objectCount=manifest.object_count(),
        totalObjectBytes=manifest.total_object_bytes,
        snapshotBytes=manifest.snapshot_bytes,
    )


@contextmanager
def _snapshot_copy(snapshot: Path) -> Iterator[EventStore]:
    """Open a throwaway writable copy of a collapsed snapshot.

    Two facts make the copy necessary rather than incidental. ``EventStore``
    always opens in WAL mode, so opening the image file in place would rewrite
    the bytes the manifest just described. And a collapsed snapshot is in
    DELETE mode, which ``EventStore`` can only convert from a writable
    connection. A discarded copy satisfies both without touching the image.
    """

    with tempfile.TemporaryDirectory(prefix="researchos-snapshot-") as directory:
        probe = Path(directory) / EVENTS_SNAPSHOT_NAME
        _copy_file(snapshot, probe)
        for suffix in ("-wal", "-shm"):
            probe.with_name(probe.name + suffix).unlink(missing_ok=True)
        with EventStore(probe, require_existing=True) as store:
            yield store


def restore_backup(
    image: Path,
    destination_root: Path,
    *,
    project_id: str | None = None,
    control_db: Path | None = None,
    cas_root: Path | None = None,
    worker_root: Path | None = None,
    now: datetime | None = None,
) -> RestoreReport:
    """Verify an image, then materialize it as a new workspace.

    Nothing is written until :func:`verify_backup` has re-derived the manifest
    from the image bytes. The workspace is assembled in a sibling ``.partial``
    directory and renamed into place, so an interrupted restore leaves no
    half-workspace that a retry would refuse as ``workspace-exists``. The
    restored store is compared to the image by recomputed event and ledger
    digests rather than by trusting the copy.
    """

    source = image.absolute()
    # The manifest used below is the one just verified, not a second read.
    manifest, _report = _verify_image(source)
    target = destination_root.absolute()
    if target.exists():
        if not target.is_dir():
            raise RecoveryError("restore-path-invalid", "restore destination is not a directory")
        if any(target.iterdir()):
            raise RecoveryError("restore-path-occupied", "restore destination is not empty")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".{target.name}.partial-{os.getpid()}"
    if staging.exists():
        _remove_tree(staging)
    try:
        report = _materialize(
            source,
            manifest,
            staging,
            project_id=project_id,
            control_db=control_db,
            cas_root=cas_root,
            worker_root=worker_root,
            now=now or datetime.now(UTC),
        )
    except BaseException:
        _remove_tree(staging)
        raise
    staging.rename(target)
    return report


def _materialize(
    source: Path,
    manifest: BackupManifest,
    staging: Path,
    *,
    project_id: str | None,
    control_db: Path | None,
    cas_root: Path | None,
    worker_root: Path | None,
    now: datetime,
) -> RestoreReport:
    project = project_id or manifest.project_id
    workspace = init_workspace(
        staging,
        project_id=project,
        control_db=control_db or Path("control/events.sqlite"),
        cas_root=cas_root or Path("cas"),
        worker_root=worker_root or Path("worker"),
    )
    snapshot = source / EVENTS_SNAPSHOT_NAME
    staged = workspace.control_db.parent / f".{workspace.control_db.name}.partial"
    _copy_file(snapshot, staged)
    staged.replace(workspace.control_db)
    # The restore path does not go through EventStore's create branch, so the
    # lifecycle marker is written here. Without it a restored workspace whose
    # store was later deleted would read as never-populated, which is the exact
    # ambiguity the marker exists to remove.
    write_control_store_marker(workspace.control_db, now=now)

    restored = LocalArtifactStore(workspace.cas_root)
    for entry in manifest.objects:
        target = _cas_object_path(workspace.cas_root, entry.storage_key)
        _copy_file(_image_object_path(source, entry.storage_key), target)
        # Check the copy before trusting the store, so a truncated transfer is
        # reported against this step rather than surfacing later as a missing
        # object in someone else's workspace.
        if target.stat().st_size != entry.size_bytes:
            raise BackupIntegrityError(
                "restore-object-mismatch", "a restored object does not match its recorded size"
            )
        restored.verify(entry.digest)

    with _snapshot_copy(snapshot) as image_store:
        source_ledger, source_events = _ledger_state(image_store, project, manifest.high_water)
    with EventStore(workspace.control_db, require_existing=True) as store:
        restored_count = store.verify_integrity()
        restored_high_water = store.last_sequence()
        restored_ledger, restored_events = _ledger_state(store, project, restored_high_water)
    reconciled = _reconcile_runs(workspace, project, restored_high_water)
    if restored_high_water != manifest.high_water or restored_count != manifest.event_count:
        raise BackupIntegrityError(
            "restore-event-mismatch", "the restored store does not match the backup prefix"
        )
    # A ledger comparison only means something if the requested project actually
    # appears in the prefix. Without the event count, an override naming a
    # project the events do not carry would fold an empty ledger on both sides
    # and report a match. An empty image legitimately has no such events.
    vacuous = manifest.high_water > 0 and source_events == 0
    if vacuous or source_events != restored_events or source_ledger != restored_ledger:
        raise BackupIntegrityError(
            "restore-ledger-mismatch", "the restored research ledger does not match the image"
        )
    return RestoreReport(
        projectId=project,
        restoredHighWater=restored_high_water,
        restoredEventCount=restored_count,
        restoredObjectCount=manifest.object_count(),
        ledgerMatches=True,
        reconciledRuns=list(reconciled),
    )


def load_manifest(image: Path) -> BackupManifest:
    """Read and validate a backup manifest, refusing an unreadable image.

    An image can arrive from a mounted archive or another host, so the read is
    size-bounded rather than trusted to be small. Rejecting by declared size
    before the read keeps a crafted manifest from allocating on demand.
    """

    path = image / MANIFEST_NAME
    try:
        if path.stat().st_size > _MAX_MANIFEST_BYTES:
            raise RecoveryError("backup-manifest-too-large", "backup manifest is too large")
        payload = path.read_text(encoding="utf-8")
    except RecoveryError:
        raise
    except OSError as exc:
        raise RecoveryError("backup-manifest-missing", "backup manifest could not be read") from exc
    try:
        return BackupManifest.model_validate_json(payload)
    except ValueError as exc:
        raise RecoveryError(
            "backup-manifest-invalid", "backup manifest is not a valid contract"
        ) from exc


def _build_image(workspace: Workspace, staging: Path, *, now: datetime) -> BackupReport:
    snapshot = staging / EVENTS_SNAPSHOT_NAME
    _snapshot_database(workspace.control_db, snapshot)
    with EventStore(snapshot, create=False) as store:
        event_count = store.verify_integrity()
        high_water = store.last_sequence()
        digests, last_digest = _prefix_object_state(store, high_water)
    source_store = LocalArtifactStore(workspace.cas_root)
    objects = _copy_objects(source_store, staging, digests)
    # Reading the snapshot above put it back into WAL mode, so committed pages
    # can still sit in a sidecar the manifest digest does not cover. Collapse
    # it to one standalone file before the digest is taken, then re-verify a
    # copy so the image is verified in the shape it will actually be restored.
    _collapse_snapshot(snapshot)
    _assert_snapshot_standalone(snapshot, high_water=high_water, event_count=event_count)
    manifest = BackupManifest(
        projectId=workspace.project_id,
        createdAt=now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        highWater=high_water,
        eventCount=event_count,
        lastEventDigest=last_digest,
        schemaVersion=SCHEMA_VERSION,
        schemaDigest=SCHEMA_DEFINITION_DIGEST,
        snapshotDigest=_file_digest(snapshot),
        snapshotBytes=snapshot.stat().st_size,
        objects=list(objects),
        totalObjectBytes=sum(entry.size_bytes for entry in objects),
    )
    _write_manifest(staging, manifest)
    return BackupReport(
        projectId=manifest.project_id,
        verified=True,
        highWater=manifest.high_water,
        eventCount=manifest.event_count,
        objectCount=manifest.object_count(),
        totalObjectBytes=manifest.total_object_bytes,
        snapshotBytes=manifest.snapshot_bytes,
    )


def _collapse_snapshot(snapshot: Path) -> None:
    """Fold the snapshot's WAL back into the main file and drop the sidecars.

    ``EventStore`` always opens in WAL mode, so simply reading the snapshot
    leaves committed events in ``-wal``. An image whose manifest covers only
    the main file would then verify here and lose events in a restore that
    copies just that file.
    """

    connection = sqlite3.connect(snapshot)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        mode = cast(str, connection.execute("PRAGMA journal_mode = DELETE").fetchone()[0])
        if mode.lower() != "delete":  # pragma: no cover - requires a read-only image dir
            raise BackupIntegrityError(
                "backup-snapshot-not-standalone", "the event snapshot could not be collapsed"
            )
    except sqlite3.Error as exc:
        raise RecoveryError(
            "backup-snapshot-failed", "the event snapshot could not be collapsed"
        ) from exc
    finally:
        connection.close()
    for suffix in ("-wal", "-shm"):
        snapshot.with_name(snapshot.name + suffix).unlink(missing_ok=True)


def _assert_snapshot_standalone(snapshot: Path, *, high_water: int, event_count: int) -> None:
    """Re-verify a copy of the collapsed snapshot against the prefix just read.

    The copy is deliberate: verifying the file in place would put it back into
    WAL mode and defeat the collapse.
    """

    with _snapshot_copy(snapshot) as store:
        verified = store.verify_integrity()
        observed_high_water = store.last_sequence()
    if verified != event_count or observed_high_water != high_water:
        raise BackupIntegrityError(
            "backup-snapshot-incomplete",
            "the collapsed event snapshot does not contain the verified prefix",
        )


def _snapshot_database(source: Path, destination: Path) -> None:
    """Copy a live database through the SQLite online backup API.

    Copying the file itself would capture a torn page set under concurrent
    writes and would miss committed WAL content.
    """

    if not source.exists():
        raise RecoveryError("control-store-missing", "the workspace control store is missing")
    # The path is percent-encoded before it becomes a URI. SQLite treats '#' as
    # a fragment terminator and '?' as a query terminator, and both are legal
    # POSIX filename characters, so an unencoded path would silently open a
    # different database and produce an internally consistent image of the
    # wrong workspace.
    encoded = quote(source.absolute().as_posix(), safe="/")
    uri = f"file:{encoded}?mode=ro"
    target = sqlite3.connect(destination)
    try:
        origin = sqlite3.connect(uri, uri=True, timeout=30.0)
        try:
            origin.backup(target)
        finally:
            origin.close()
    except sqlite3.Error as exc:
        raise RecoveryError(
            "backup-snapshot-failed", "the control store could not be snapshotted"
        ) from exc
    finally:
        target.close()
    if destination.stat().st_size > _MAX_SNAPSHOT_BYTES:
        raise RecoveryError(
            "backup-too-large", "the control store exceeds the supported backup size"
        )


def _prefix_object_state(store: EventStore, high_water: int) -> tuple[tuple[str, ...], str | None]:
    """Return the CAS digests a prefix references and its last event digest, in one pass.

    A backup needs both, and replaying the prefix three times to get them made
    the operation cost three times what it needed.
    """

    digests: set[str] = set()
    last: str | None = None
    for stored in replay_events(store, until_sequence=high_water, freeze_high_water=False):
        for digest, _role in referenced_digests(stored.event):
            if digest.startswith("sha256:"):
                digests.add(digest)
        last = stored.digest
    return tuple(sorted(digests)), last


def _copy_objects(
    store: LocalArtifactStore, staging: Path, digests: tuple[str, ...]
) -> tuple[BackupObject, ...]:
    copied: list[BackupObject] = []
    for digest in digests:
        if not store.exists(digest):
            raise BackupIntegrityError(
                "backup-object-missing",
                "the workspace references a content object it does not hold",
            )
        record = store.verify(digest)
        key = storage_key_for(digest)
        target = _image_object_path(staging, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        with store.open(digest) as source:
            _copy_stream(source, target)
        if _file_digest(target) != digest:
            raise BackupIntegrityError(
                "backup-object-mismatch", "a copied object does not match its content digest"
            )
        copied.append(BackupObject(digest=digest, sizeBytes=record.size_bytes, storageKey=key))
    return tuple(copied)


def _image_object_path(image: Path, storage_key: str) -> Path:
    # An image keeps objects under its own ``cas/`` prefix so a moved or mounted
    # image cannot be mistaken for a live workspace CAS root.
    return image / OBJECT_ROOT_NAME / _safe_storage_key(storage_key)


def _cas_object_path(cas_root: Path, storage_key: str) -> Path:
    return cas_root / _safe_storage_key(storage_key)


def _safe_storage_key(storage_key: str) -> Path:
    """Refuse a manifest-supplied key that is absolute or escapes its root.

    A manifest is untrusted input on restore. ``storage_key_for`` already
    derives a safe key from a verified digest, but a hand-edited manifest could
    name anything, so the key is re-checked before it becomes a path.
    """

    if not isinstance(storage_key, str) or not storage_key:
        raise RecoveryError("backup-object-path-invalid", "a backup object key is empty")
    parts = Path(storage_key).parts
    if Path(storage_key).is_absolute() or ".." in parts or storage_key.startswith("/"):
        raise RecoveryError("backup-object-path-invalid", "a backup object key escaped its root")
    return Path(storage_key)


def _write_manifest(image: Path, manifest: BackupManifest) -> None:
    path = image / MANIFEST_NAME
    payload = manifest.model_dump(mode="json", by_alias=True, exclude_none=True)
    staged = image / f".{MANIFEST_NAME}.partial"
    staged.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    _fsync_path(staged)
    staged.replace(path)
    _fsync_dir(image)


def _file_digest(path: Path, *, missing_code: str = "backup-object-missing") -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(_CHUNK):
                digest.update(chunk)
    except FileNotFoundError as exc:
        raise BackupIntegrityError(missing_code, "a backup file is missing") from exc
    except OSError as exc:
        raise BackupIntegrityError(missing_code, "a backup file could not be read") from exc
    return f"sha256:{digest.hexdigest()}"


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as handle:
        _copy_stream(handle, destination)
    _fsync_path(destination)


def _copy_stream(source: object, destination: Path) -> None:
    with destination.open("wb") as handle:
        while chunk := source.read(_CHUNK):  # type: ignore[attr-defined]
            handle.write(chunk)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_path(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return
    for child in path.rglob("*"):
        if child.is_file() or child.is_symlink():
            child.unlink(missing_ok=True)
    for child in sorted(path.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if child.is_dir():
            child.rmdir()
    path.rmdir()


def _ledger_state(store: EventStore, project_id: str, last_sequence: int) -> tuple[str, int]:
    """Return the research-ledger content digest and how many events carried the project.

    The count is returned alongside the digest because a digest over an empty
    event set is a legitimate value *and* the value a wrong project id produces.
    """

    events = tuple(
        stored.event
        for stored in replay_events(store, until_sequence=last_sequence, freeze_high_water=False)
        if stored.event.data.project_id == project_id
    )
    ledger = build_research_ledger(events, project_id=project_id, last_sequence=last_sequence)
    return content_digest(research_ledger_document(ledger)), len(events)


def _reconcile_runs(
    workspace: Workspace,
    project_id: str,
    last_sequence: int,
) -> tuple[ReconciledRun, ...]:
    """Report Runs left non-terminal by the image as ``unknown``.

    The previous machine's process cannot be observed from here, so a Run that
    was still in flight stays ``unknown`` (ADR-0054). It is listed for the
    operator and never restarted by this call.
    """

    states: dict[str, str] = {}
    with EventStore(workspace.control_db, require_existing=True) as store:
        for stored in replay_events(store, until_sequence=last_sequence, freeze_high_water=False):
            event = stored.event
            run_id = event.data.run_id
            if run_id is None or event.data.project_id != project_id:
                continue
            states[run_id] = _run_status_for(event.type, states.get(run_id))
    return tuple(
        ReconciledRun(runId=run_id, lastState=state)
        for run_id, state in sorted(states.items())
        if state not in TERMINAL_RUN_STATUSES
    )


def _run_status_for(event_type: str, previous: str | None) -> str:
    mapping = {
        "run.queued": "queued",
        "run.started": "running",
        "run.cancel.requested": "cancel-requested",
        "run.completed": "completed",
        "run.failed": "failed",
        "run.cancelled": "cancelled",
    }
    return mapping.get(event_type, previous or "unknown")
