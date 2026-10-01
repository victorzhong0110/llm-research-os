"""Transfer publication, journal and path-race regressions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from test_native_transfer import _file, _manifest, _store

from llm_research_os.execution import native_transfer as transfer
from llm_research_os.execution.errors import NativeTransferError


def test_journal_temporary_symlink_cannot_overwrite_other_file(tmp_path: Path) -> None:
    victim = tmp_path / "victim"
    victim.write_bytes(b"preserve")
    journal = tmp_path / "journal.json"
    journal.with_suffix(".json.tmp").symlink_to(victim)
    transfer.claim_for_transfer(journal, _manifest([_file("blob", b"a")]), lease_id="lease.1")
    assert victim.read_bytes() == b"preserve"
    assert journal.stat().st_mode & 0o777 == 0o600


def test_parallel_claims_cannot_replace_the_winning_lease(tmp_path: Path) -> None:
    manifest = _manifest([_file("blob", b"a")])
    journal = tmp_path / "journal.json"

    def claim(lease: str) -> str:
        try:
            return transfer.claim_for_transfer(journal, manifest, lease_id=lease).lease_id
        except NativeTransferError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(claim, ["lease.1", "lease.2"]))
    assert result.count("transfer-duplicate-start") == 1
    winner = next(item for item in result if item != "transfer-duplicate-start")
    assert transfer.claim_for_transfer(journal, manifest, lease_id=winner).starts == 1


def test_short_writes_publish_complete_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"complete payload"
    source = _store(tmp_path / "cas")
    source.put_bytes(payload)
    write = os.write
    monkeypatch.setattr(transfer.os, "write", lambda fd, data: write(fd, data[:2]))
    receipt = transfer.stage_scoped_inputs(
        manifest=_manifest([_file("blob", payload)]),
        source=source,
        destination=tmp_path / "stage",
        journal_path=tmp_path / "journal.json",
    )
    assert receipt.status == "complete"
    assert (tmp_path / "stage" / "blob").read_bytes() == payload


def test_failed_write_resumes_without_a_partial_final_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"complete payload"
    source = _store(tmp_path / "cas")
    source.put_bytes(payload)
    write = os.write
    calls = 0

    def interrupted(fd: int, data: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            return write(fd, data[:2])
        if calls == 2:
            raise OSError("disk interrupted")
        return write(fd, data)

    monkeypatch.setattr(transfer.os, "write", interrupted)
    args = dict(
        manifest=_manifest([_file("blob", payload)]),
        source=source,
        destination=tmp_path / "stage",
        journal_path=tmp_path / "journal.json",
    )
    receipt = transfer.stage_scoped_inputs(**args)
    assert receipt.status == "incomplete" and receipt.observation == "unknown"
    assert not (tmp_path / "stage" / "blob").exists()
    assert list((tmp_path / "stage").iterdir()) == []
    assert transfer.stage_scoped_inputs(**args).status == "complete"
    assert (tmp_path / "stage" / "blob").read_bytes() == payload


def test_destination_root_swap_never_writes_through_symlink(tmp_path: Path) -> None:
    payload = b"scoped"
    source = _store(tmp_path / "cas")
    source.put_bytes(payload)
    stage = tmp_path / "stage"
    outside = tmp_path / "outside"
    outside.mkdir()

    class Swap(transfer.TransferHooks):
        def before_file(self, relative_path: str) -> None:
            stage.rename(tmp_path / "held-root")
            stage.symlink_to(outside, target_is_directory=True)

    receipt = transfer.stage_scoped_inputs(
        manifest=_manifest([_file("nested/blob", payload)]),
        source=source,
        destination=stage,
        journal_path=tmp_path / "journal.json",
        hooks=Swap(),
    )
    assert receipt.status == "complete"
    assert list(outside.iterdir()) == []
    assert (tmp_path / "held-root" / "nested" / "blob").read_bytes() == payload


@pytest.mark.parametrize("kind", ["journal", "manifest"])
def test_fifo_is_refused_without_blocking(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "pipe"
    os.mkfifo(path)

    def operation() -> None:
        if kind == "journal":
            transfer.claim_for_transfer(path, _manifest([_file("blob", b"a")]), lease_id="lease.1")
        else:
            transfer.load_manifest(path)

    with pytest.raises(NativeTransferError, match="invalid"):
        operation()


def test_journal_parent_swap_keeps_lock_and_publication_on_same_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "controller"
    parent.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    original = transfer._load_or_create

    def swapped(path: Path, manifest: transfer.TransferManifest) -> transfer._Journal:
        journal = original(path, manifest)
        parent.rename(tmp_path / "held-controller")
        parent.symlink_to(outside, target_is_directory=True)
        return journal

    monkeypatch.setattr(transfer, "_load_or_create", swapped)
    receipt = transfer.claim_for_transfer(
        parent / "journal.json", _manifest([_file("blob", b"a")]), lease_id="lease.1"
    )
    assert receipt.starts == 1
    assert list(outside.iterdir()) == []
    assert (tmp_path / "held-controller" / "journal.json").is_file()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_unsafe_lock_files_are_refused(tmp_path: Path, kind: str) -> None:
    lock = tmp_path / "journal.json.lock"
    victim = tmp_path / "victim"
    victim.write_bytes(b"preserve")
    if kind == "symlink":
        lock.symlink_to(victim)
    elif kind == "hardlink":
        os.link(victim, lock)
    else:
        os.mkfifo(lock)
    with pytest.raises(NativeTransferError, match="journal"):
        transfer.claim_for_transfer(
            tmp_path / "journal.json", _manifest([_file("blob", b"a")]), lease_id="lease.1"
        )
    assert victim.read_bytes() == b"preserve"


def test_oversized_journal_is_refused(tmp_path: Path) -> None:
    journal = tmp_path / "journal.json"
    journal.write_bytes(b" " * (transfer.MAX_TRANSFER_MANIFEST_BYTES + 1))
    with pytest.raises(NativeTransferError, match="journal"):
        transfer.claim_for_transfer(journal, _manifest([_file("blob", b"a")]), lease_id="lease.1")


def test_manifest_direction_must_be_a_string() -> None:
    with pytest.raises(NativeTransferError, match="invalid"):
        transfer.manifest_from_document({"direction": []})


@pytest.mark.parametrize("root", ["cas", "stage"])
def test_journal_cannot_overwrite_an_artifact_tree(tmp_path: Path, root: str) -> None:
    source = _store(tmp_path / "cas")
    source.put_bytes(b"a")
    with pytest.raises(NativeTransferError, match="outside artifact"):
        transfer.stage_scoped_inputs(
            manifest=_manifest([_file("journal.json", b"a")]),
            source=source,
            destination=tmp_path / "stage",
            journal_path=tmp_path / root / "journal.json",
        )
    assert not (tmp_path / "stage").exists()


def test_completed_replay_needs_no_additional_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _store(tmp_path / "cas")
    source.put_bytes(b"a")
    args = dict(
        manifest=_manifest([_file("blob", b"a")]),
        source=source,
        destination=tmp_path / "stage",
        journal_path=tmp_path / "journal.json",
    )
    assert transfer.stage_scoped_inputs(**args).status == "complete"
    monkeypatch.setattr(transfer.shutil, "disk_usage", lambda _: type("Usage", (), {"free": 0})())
    receipt = transfer.stage_scoped_inputs(**args)
    assert receipt.status == "complete" and receipt.attempts == 1


def test_parallel_process_claims_keep_one_lease(tmp_path: Path) -> None:
    journal = tmp_path / "journal.json"
    script = """
import sys
from pathlib import Path
from llm_research_os.execution.native_transfer import claim_for_transfer, manifest_from_document
from llm_research_os.execution.errors import NativeTransferError
manifest = manifest_from_document({
    "grantId": "grant.1", "taskId": "task.1", "runId": "run.1", "attemptId": "attempt.1",
    "direction": "input",
    "files": [{"path": "blob", "digest": "sha256:" + "0" * 64, "sizeBytes": 1}]
})
try:
    print(claim_for_transfer(Path(sys.argv[1]), manifest, lease_id=sys.argv[2]).lease_id)
except NativeTransferError as exc:
    print(exc.code)
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(journal), lease],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for lease in ("lease.1", "lease.2")
    ]
    try:
        outputs = [process.communicate(timeout=15) for process in processes]
        assert all(process.returncode == 0 for process in processes), outputs
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    result = [stdout.strip() for stdout, _stderr in outputs]
    assert result.count("transfer-duplicate-start") == 1
    stored = json.loads(journal.read_text())
    assert stored["starts"] == 1 and stored["leaseId"] in result
