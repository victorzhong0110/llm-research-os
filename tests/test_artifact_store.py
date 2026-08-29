from __future__ import annotations

import hashlib
import os
import socket
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Barrier

import pytest

import llm_research_os.artifacts.store as artifact_store
from llm_research_os.artifacts import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactPathError,
    ArtifactStoreError,
    LocalArtifactStore,
    parse_artifact_digest,
)
from llm_research_os.artifacts.store import CHUNK_SIZE, storage_key_for
from llm_research_os.canonical import content_digest


def _sha256_digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _store(tmp_path: Path) -> tuple[LocalArtifactStore, Path]:
    root = tmp_path / "artifacts"
    root.mkdir()
    return LocalArtifactStore(root), root


def test_put_empty_and_ordinary_files(tmp_path: Path) -> None:
    store, root = _store(tmp_path)
    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")
    payload = tmp_path / "hello.bin"
    payload.write_bytes(b"hello artifacts")

    empty_record = store.put(empty)
    hello_record = store.put(payload)

    assert empty_record.digest == _sha256_digest(b"")
    assert empty_record.size_bytes == 0
    assert hello_record.digest == _sha256_digest(b"hello artifacts")
    assert hello_record.size_bytes == 15
    assert empty_record.storage_key == (
        f"objects/sha256/{empty_record.digest[7:9]}/{empty_record.digest[9:]}"
    )
    assert (root / hello_record.storage_key).read_bytes() == b"hello artifacts"
    assert store.exists(empty_record.digest)
    assert store.verify(hello_record.digest) == hello_record
    with store.open(hello_record.digest) as handle:
        assert handle.read() == b"hello artifacts"


def test_put_large_file_is_chunked_and_matches_hashlib(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _root = _store(tmp_path)
    payload = os.urandom(CHUNK_SIZE * 3 + 17)
    source = tmp_path / "large.bin"
    source.write_bytes(payload)

    requested: list[int] = []
    original_read = os.read

    def tracking_read(descriptor: int, n: int) -> bytes:
        requested.append(n)
        return original_read(descriptor, n)

    monkeypatch.setattr("llm_research_os.artifacts.store.os.read", tracking_read)
    record = store.put(source)

    assert record.digest == _sha256_digest(payload)
    assert record.size_bytes == len(payload)
    assert requested
    assert max(requested) <= CHUNK_SIZE
    assert store.verify(record.digest).size_bytes == len(payload)


def test_identical_content_is_deduplicated_and_distinct_content_differs(tmp_path: Path) -> None:
    store, root = _store(tmp_path)
    first = tmp_path / "a.bin"
    second = tmp_path / "b.bin"
    other = tmp_path / "c.bin"
    first.write_bytes(b"same-bytes")
    second.write_bytes(b"same-bytes")
    other.write_bytes(b"other-bytes")

    first_record = store.put(first)
    second_record = store.put(second)
    other_record = store.put(other)

    assert first_record == second_record
    assert first_record.digest != other_record.digest
    objects = [path for path in (root / "objects").rglob("*") if path.is_file()]
    assert len(objects) == 2


def test_put_hashes_raw_bytes_not_canonical_json(tmp_path: Path) -> None:
    store, _root = _store(tmp_path)
    payload = b'{"z":1,"a":true}'
    source = tmp_path / "raw.json"
    source.write_bytes(payload)
    record = store.put(source)
    assert record.digest == _sha256_digest(payload)
    assert record.digest != content_digest({"z": 1, "a": True})


def test_source_symlink_directory_and_special_files_are_rejected(tmp_path: Path) -> None:
    store, _root = _store(tmp_path)
    target = tmp_path / "target.bin"
    target.write_bytes(b"target")
    link = tmp_path / "link.bin"
    link.symlink_to(target)
    directory = tmp_path / "dir"
    directory.mkdir()

    with pytest.raises(ArtifactPathError, match="symbolic link"):
        store.put(link)
    with pytest.raises(ArtifactPathError, match="directory"):
        store.put(directory)

    if hasattr(os, "mkfifo"):
        fifo = tmp_path / "fifo"
        os.mkfifo(fifo)
        with pytest.raises(ArtifactPathError, match="FIFO"):
            store.put(fifo)

    sock_dir = Path("/tmp") / f"lros{os.getpid()}"
    sock_dir.mkdir()
    sock_path = sock_dir / "s"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind(str(sock_path))
        with pytest.raises(ArtifactPathError, match="socket"):
            store.put(sock_path)
    finally:
        listener.close()
        sock_path.unlink(missing_ok=True)
        sock_dir.rmdir()

    device = Path("/dev/null")
    if device.exists():
        with pytest.raises(ArtifactPathError, match="device"):
            store.put(device)


def test_root_symlink_and_non_directory_are_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    file_root = tmp_path / "file"
    file_root.write_bytes(b"nope")

    with pytest.raises(ArtifactPathError, match="symbolic link"):
        LocalArtifactStore(link)
    with pytest.raises(ArtifactPathError, match="must be a directory"):
        LocalArtifactStore(file_root)
    with pytest.raises(ArtifactPathError, match="does not exist"):
        LocalArtifactStore(tmp_path / "missing")


def test_illegal_digests_and_path_traversal_are_rejected(tmp_path: Path) -> None:
    store, _root = _store(tmp_path)
    valid = "sha256:" + "a" * 64
    illegal = [
        "SHA256:" + "a" * 64,
        "sha256:" + "A" * 64,
        "sha256:" + "a" * 63,
        "sha256:" + "a" * 65,
        "sha256:" + "a" * 62 + "/.",
        "sha256:../" + "a" * 61,
        "sha256:ab/" + "c" * 61,
        " sha256:" + "a" * 64,
        "sha256:" + "a" * 64 + "\n",
        "sha256:" + "a" * 64 + " ",
        "../objects/sha256/" + "a" * 64,
        "",
        "sha256:",
    ]
    for digest in illegal:
        with pytest.raises(ArtifactPathError, match="sha256"):
            parse_artifact_digest(digest)
        with pytest.raises(ArtifactPathError):
            store.exists(digest)
        with pytest.raises(ArtifactPathError):
            store.verify(digest)
        with pytest.raises(ArtifactPathError):
            store.open(digest)
    assert store.exists(valid) is False
    with pytest.raises(ArtifactNotFoundError):
        store.verify(valid)
    with pytest.raises(ArtifactNotFoundError):
        store.open(valid)


def test_truncated_or_tampered_object_fails_verify_and_is_not_overwritten(tmp_path: Path) -> None:
    store, root = _store(tmp_path)
    source = tmp_path / "payload.bin"
    original = b"immutable-bytes"
    source.write_bytes(original)
    record = store.put(source)
    object_path = root / record.storage_key
    object_path.write_bytes(original[:-1])

    with pytest.raises(ArtifactIntegrityError, match="digest mismatch"):
        store.verify(record.digest)
    with pytest.raises(ArtifactIntegrityError, match="does not match"):
        store.put(source)
    assert object_path.read_bytes() == original[:-1]
    assert store.exists(record.digest) is True


def test_interrupted_write_does_not_leave_final_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, root = _store(tmp_path)
    source = tmp_path / "payload.bin"
    source.write_bytes(b"x" * (CHUNK_SIZE + 8))
    original_write = os.write
    calls = {"count": 0}

    def fail_write(descriptor: int, data: bytes | memoryview) -> int:
        calls["count"] += 1
        if calls["count"] > 1:
            raise OSError("simulated write interrupt")
        return original_write(descriptor, data)

    monkeypatch.setattr("llm_research_os.artifacts.store.os.write", fail_write)
    with pytest.raises(ArtifactStoreError, match="could not write"):
        store.put(source)

    objects = root / "objects"
    if objects.exists():
        assert not any(path.is_file() for path in objects.rglob("*"))
    tmp_dir = root / "tmp"
    if tmp_dir.exists():
        leftover = [path for path in tmp_dir.iterdir() if path.is_file()]
        assert leftover == []


def test_concurrent_puts_of_the_same_content_publish_one_object(tmp_path: Path) -> None:
    store, root = _store(tmp_path)
    payload = b"concurrent-artifact"
    sources = []
    for index in range(8):
        path = tmp_path / f"source-{index}.bin"
        path.write_bytes(payload)
        sources.append(path)
    start = Barrier(len(sources))

    def import_one(path: Path) -> str:
        start.wait()
        return store.put(path).digest

    with ThreadPoolExecutor(max_workers=len(sources)) as executor:
        digests = list(executor.map(import_one, sources))

    expected = _sha256_digest(payload)
    assert digests == [expected] * len(sources)
    objects = [path for path in (root / "objects").rglob("*") if path.is_file()]
    assert len(objects) == 1
    assert store.verify(expected).size_bytes == len(payload)


def test_artifact_record_is_immutable(tmp_path: Path) -> None:
    store, _root = _store(tmp_path)
    source = tmp_path / "payload.bin"
    source.write_bytes(b"frozen")
    record = store.put(source)
    with pytest.raises(FrozenInstanceError):
        record.digest = "sha256:" + "0" * 64  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        record.size_bytes = 0  # type: ignore[misc]


def test_created_directories_and_objects_use_private_permissions(tmp_path: Path) -> None:
    store, root = _store(tmp_path)
    existing_objects = root / "objects"
    existing_objects.mkdir(mode=0o750)
    os.chmod(existing_objects, 0o750)
    source = tmp_path / "payload.bin"
    source.write_bytes(b"permissions")
    record = store.put(source)

    assert stat.S_IMODE(existing_objects.stat().st_mode) == 0o750
    shard = root / record.storage_key
    algorithm_dir = shard.parent.parent
    digest_dir = shard.parent
    tmp_dir = root / "tmp"
    assert stat.S_IMODE(algorithm_dir.stat().st_mode) == stat.S_IRWXU
    assert stat.S_IMODE(digest_dir.stat().st_mode) == stat.S_IRWXU
    assert stat.S_IMODE(tmp_dir.stat().st_mode) == stat.S_IRWXU
    assert stat.S_IMODE(shard.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR


def _plant_escaped_object(outside: Path, digest: str, payload: bytes, component: str) -> None:
    hex_digest = digest[7:]
    shard, name = hex_digest[:2], hex_digest[2:]
    if component == "objects":
        planted = outside / "sha256" / shard / name
    elif component == "sha256":
        planted = outside / shard / name
    else:
        planted = outside / name
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_bytes(payload)


def _install_intermediate_symlink(root: Path, outside: Path, digest: str, component: str) -> None:
    hex_digest = digest[7:]
    shard = hex_digest[:2]
    if component == "objects":
        (root / "objects").symlink_to(outside)
        return
    (root / "objects").mkdir(exist_ok=True)
    if component == "sha256":
        (root / "objects" / "sha256").symlink_to(outside)
        return
    (root / "objects" / "sha256").mkdir(exist_ok=True)
    (root / "objects" / "sha256" / shard).symlink_to(outside)


@pytest.mark.parametrize("component", ["objects", "sha256", "shard"])
def test_intermediate_directory_symlink_does_not_escape_store(
    tmp_path: Path,
    component: str,
) -> None:
    store, root = _store(tmp_path)
    payload = b"secret-outside"
    digest = _sha256_digest(payload)
    outside = tmp_path / "outside"
    outside.mkdir()
    _install_intermediate_symlink(root, outside, digest, component)
    _plant_escaped_object(outside, digest, payload, component)

    with pytest.raises(ArtifactStoreError) as exists_error:
        store.exists(digest)
    with pytest.raises(ArtifactStoreError) as verify_error:
        store.verify(digest)
    with pytest.raises(ArtifactStoreError) as open_error:
        store.open(digest)
    for error in (exists_error.value, verify_error.value, open_error.value):
        assert isinstance(
            error,
            (ArtifactPathError, ArtifactIntegrityError, ArtifactNotFoundError),
        )
        assert not isinstance(error, OSError) or isinstance(error, ArtifactStoreError)

    source = tmp_path / "payload.bin"
    source.write_bytes(payload)
    with pytest.raises(ArtifactStoreError):
        store.put(source)
    leaked = [path.read_bytes() for path in outside.rglob("*") if path.is_file()]
    assert leaked == [payload]


def test_object_symlink_is_rejected(tmp_path: Path) -> None:
    store, root = _store(tmp_path)
    source = tmp_path / "payload.bin"
    payload = b"real-object"
    source.write_bytes(payload)
    record = store.put(source)
    object_path = root / record.storage_key
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"escaped-object")
    object_path.unlink()
    object_path.symlink_to(outside)

    with pytest.raises(ArtifactIntegrityError, match="regular file"):
        store.exists(record.digest)
    with pytest.raises(ArtifactIntegrityError, match="regular file"):
        store.verify(record.digest)
    with pytest.raises(ArtifactIntegrityError, match="regular file"):
        store.open(record.digest)
    with pytest.raises(ArtifactIntegrityError):
        store.put(source)
    assert outside.read_bytes() == b"escaped-object"


def test_root_identity_change_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    store = LocalArtifactStore(root)
    source = tmp_path / "payload.bin"
    source.write_bytes(b"after-swap")
    digest = "sha256:" + "a" * 64

    relocated = tmp_path / "relocated"
    root.rename(relocated)
    imposter = tmp_path / "artifacts"
    imposter.mkdir()
    (imposter / "trap.bin").write_bytes(b"imposter")

    with pytest.raises(ArtifactPathError, match="identity"):
        store.put(source)
    with pytest.raises(ArtifactPathError, match="identity"):
        store.exists(digest)
    with pytest.raises(ArtifactPathError, match="identity"):
        store.verify(digest)
    with pytest.raises(ArtifactPathError, match="identity"):
        store.open(digest)
    assert not (imposter / "objects").exists()
    assert (imposter / "trap.bin").read_bytes() == b"imposter"


def test_objects_replaced_after_root_open_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, root = _store(tmp_path)
    payload = b"race-secret"
    digest = _sha256_digest(payload)
    outside = tmp_path / "outside"
    outside.mkdir()
    _plant_escaped_object(outside, digest, payload, "objects")
    source = tmp_path / "payload.bin"
    source.write_bytes(payload)

    def swap_objects() -> None:
        objects = root / "objects"
        if objects.exists() or objects.is_symlink():
            objects.rename(root / "objects.moved")
        objects.symlink_to(outside)

    monkeypatch.setattr(artifact_store, "_hook_after_trusted_root_open", swap_objects)
    with pytest.raises(ArtifactStoreError):
        store.put(source)
    with pytest.raises(ArtifactStoreError):
        store.exists(digest)
    with pytest.raises(ArtifactStoreError):
        store.verify(digest)
    with pytest.raises(ArtifactStoreError):
        store.open(digest)
    planted = [path.read_bytes() for path in outside.rglob("*") if path.is_file()]
    assert planted == [payload]


def test_put_uses_anchored_dirfd_if_objects_replaced_after_shard_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, root = _store(tmp_path)
    payload = b"anchored-bytes"
    source = tmp_path / "payload.bin"
    source.write_bytes(payload)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "marker").write_bytes(b"marker")

    def swap_after_shard() -> None:
        objects = root / "objects"
        objects.rename(root / "objects.real")
        objects.symlink_to(outside)

    monkeypatch.setattr(artifact_store, "_hook_after_shard_dir_open", swap_after_shard)
    record = store.put(source)
    relocated = root / "objects.real" / "sha256" / record.digest[7:9] / record.digest[9:]
    assert relocated.read_bytes() == payload
    for path in outside.rglob("*"):
        if path.is_file():
            assert path.read_bytes() != payload


def test_first_shard_fsync_failure_is_recovered_on_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, root = _store(tmp_path)
    payload = b"durable-object"
    source = tmp_path / "payload.bin"
    source.write_bytes(payload)
    digest = _sha256_digest(payload)
    original = artifact_store._fsync_fd
    real_fsync = artifact_store.os.fsync
    publish_attempts = {"count": 0}

    def fail_first_publish(descriptor: int, *, reason: str) -> None:
        if reason == "publish":
            publish_attempts["count"] += 1
            if publish_attempts["count"] == 1:

                def boom(_fd: int) -> None:
                    raise OSError("simulated shard fsync failure")

                monkeypatch.setattr(artifact_store.os, "fsync", boom)
                try:
                    original(descriptor, reason=reason)
                finally:
                    monkeypatch.setattr(artifact_store.os, "fsync", real_fsync)
                return
        original(descriptor, reason=reason)

    monkeypatch.setattr(artifact_store, "_fsync_fd", fail_first_publish)
    with pytest.raises(ArtifactStoreError, match="persist directory") as first:
        store.put(source)
    assert first.value.__cause__ is not None
    object_path = root / storage_key_for(digest)
    assert object_path.read_bytes() == payload
    record = store.put(source)
    assert record.digest == digest
    assert publish_attempts["count"] == 2


def test_new_directory_chain_fsyncs_each_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _root = _store(tmp_path)
    source = tmp_path / "payload.bin"
    source.write_bytes(b"chain")
    reasons: list[str] = []
    original = artifact_store._fsync_fd

    def record(descriptor: int, *, reason: str) -> None:
        reasons.append(reason)
        original(descriptor, reason=reason)

    monkeypatch.setattr(artifact_store, "_fsync_fd", record)
    store.put(source)
    assert reasons == ["tmp", "objects", "sha256", "shard", "publish"]


@pytest.mark.parametrize("fail_reason", ["tmp", "objects", "sha256", "shard", "publish"])
def test_directory_fsync_failure_is_retried_before_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_reason: str,
) -> None:
    store, root = _store(tmp_path)
    source = tmp_path / "payload.bin"
    payload = b"retry-fsync"
    source.write_bytes(payload)
    original = artifact_store._fsync_fd
    real_fsync = artifact_store.os.fsync
    seen: dict[str, int | list[str]] = {"count": 0, "reasons": []}

    def fail_once(descriptor: int, *, reason: str) -> None:
        if reason == fail_reason:
            seen["count"] = int(seen["count"]) + 1
            if seen["count"] == 1:

                def boom(_fd: int) -> None:
                    raise OSError(f"simulated {reason} fsync failure")

                monkeypatch.setattr(artifact_store.os, "fsync", boom)
                try:
                    original(descriptor, reason=reason)
                finally:
                    monkeypatch.setattr(artifact_store.os, "fsync", real_fsync)
                return
        reasons = seen["reasons"]
        assert isinstance(reasons, list)
        reasons.append(reason)
        original(descriptor, reason=reason)

    monkeypatch.setattr(artifact_store, "_fsync_fd", fail_once)
    with pytest.raises(ArtifactStoreError, match="persist directory") as failed:
        store.put(source)
    assert failed.value.__cause__ is not None
    record = store.put(source)
    assert record.digest == _sha256_digest(payload)
    assert seen["count"] >= 2
    assert fail_reason in seen["reasons"]
    if fail_reason == "publish":
        assert (root / record.storage_key).read_bytes() == payload


def test_reuse_of_matching_object_fsyncs_shard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _root = _store(tmp_path)
    source = tmp_path / "payload.bin"
    source.write_bytes(b"reuse-me")
    store.put(source)
    reasons: list[str] = []
    original = artifact_store._fsync_fd

    def record(descriptor: int, *, reason: str) -> None:
        reasons.append(reason)
        original(descriptor, reason=reason)

    monkeypatch.setattr(artifact_store, "_fsync_fd", record)
    store.put(source)
    assert "publish" in reasons


def test_fsync_failure_does_not_leak_partial_objects_or_prevent_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, root = _store(tmp_path)
    source = tmp_path / "payload.bin"
    source.write_bytes(b"no-leak")
    original = artifact_store._fsync_fd
    real_fsync = artifact_store.os.fsync

    def always_fail_tmp(descriptor: int, *, reason: str) -> None:
        if reason == "tmp":

            def boom(_fd: int) -> None:
                raise OSError("simulated tmp parent fsync failure")

            monkeypatch.setattr(artifact_store.os, "fsync", boom)
            try:
                original(descriptor, reason=reason)
            finally:
                monkeypatch.setattr(artifact_store.os, "fsync", real_fsync)
            return
        original(descriptor, reason=reason)

    monkeypatch.setattr(artifact_store, "_fsync_fd", always_fail_tmp)
    for _ in range(8):
        with pytest.raises(ArtifactStoreError, match="persist directory"):
            store.put(source)
    objects = root / "objects"
    if objects.exists() and not objects.is_symlink():
        assert not any(path.is_file() for path in objects.rglob("*"))
    monkeypatch.setattr(artifact_store, "_fsync_fd", original)
    record = store.put(source)
    assert (root / record.storage_key).read_bytes() == b"no-leak"
