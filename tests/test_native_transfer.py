"""Grant-scoped transfer, fault observations, and checkpoint delivery."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from test_native_reviewed_runtime import _world

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.canonical import content_digest
from llm_research_os.cli.native_commands import run_native
from llm_research_os.cli.parser import build_parser
from llm_research_os.execution import native_transfer as transfer_module
from llm_research_os.execution.errors import NativeTransferError
from llm_research_os.execution.native_reviewed import execution_object
from llm_research_os.execution.native_reviewed_checkpoint import NativeRestoreClaim
from llm_research_os.execution.native_reviewed_runtime import execute_reviewed_native
from llm_research_os.execution.native_transfer import (
    INTERRUPTED,
    MAX_TRANSFER_FILE_BYTES,
    MAX_TRANSFER_FILES,
    TransferHooks,
    TransferReceipt,
    attach_process_observation,
    claim_for_transfer,
    classify_two_host_fault,
    deliver_verified_checkpoint,
    export_scoped_outputs,
    fault_kinds,
    gpu_profile_evidence,
    load_manifest,
    manifest_digest,
    manifest_from_document,
    record_fault,
    record_observation,
    stage_scoped_inputs,
)
from llm_research_os.workers.supervise import ExecutionIdentity, load_execution_identity


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _store(path: Path) -> LocalArtifactStore:
    path.mkdir(parents=True, exist_ok=True)
    return LocalArtifactStore(path)


def _manifest(files: list[dict[str, object]], *, direction: str = "input") -> object:
    return manifest_from_document(
        {
            "grantId": "grant.1",
            "taskId": "task.1",
            "runId": "run.1",
            "attemptId": "attempt.1",
            "direction": direction,
            "files": files,
        }
    )


def _file(path: str, payload: bytes) -> dict[str, object]:
    return {"path": path, "digest": _digest(payload), "sizeBytes": len(payload)}


def test_stage_copies_only_named_objects_and_rejects_the_rest(tmp_path: Path) -> None:
    source = _store(tmp_path / "source")
    wanted = b"wanted"
    secret = b"secret-not-in-manifest"
    source.put_bytes(wanted)
    source.put_bytes(secret)
    manifest = _manifest([_file("inputs/corpus", wanted)])
    receipt = stage_scoped_inputs(
        manifest=manifest,
        source=source,
        destination=tmp_path / "stage",
        journal_path=tmp_path / "journal.json",
        lease_id="lease.1",
    )
    assert receipt.status == "complete"
    assert receipt.observation == "unknown"
    assert receipt.starts == 0
    assert receipt.lease_id == "lease.1"
    assert (tmp_path / "stage" / "inputs" / "corpus").read_bytes() == wanted
    staged = [path.name for path in (tmp_path / "stage").rglob("*") if path.is_file()]
    assert staged == ["corpus"]
    assert receipt.as_json()["gpuProfile"] == "pending-live"
    assert secret not in (tmp_path / "stage" / "inputs" / "corpus").read_bytes()


def test_export_resume_and_lost_completion_keep_one_lease(tmp_path: Path) -> None:
    first = b"alpha"
    second = b"beta"
    source = tmp_path / "out"
    (source / "nested").mkdir(parents=True)
    (source / "a.bin").write_bytes(first)
    (source / "nested" / "b.bin").write_bytes(second)
    manifest = _manifest(
        [_file("nested/b.bin", second), _file("a.bin", first)],
        direction="output",
    )
    destination = _store(tmp_path / "dest")
    journal = tmp_path / "journal.json"

    class _Stop(TransferHooks):
        def before_file(self, relative_path: str) -> None:
            if relative_path == "nested/b.bin":
                raise NativeTransferError("interrupted", code=INTERRUPTED)

    partial = export_scoped_outputs(
        manifest=manifest,
        source_dir=source,
        destination=destination,
        journal_path=journal,
        lease_id="lease.9",
        hooks=_Stop(),
    )
    assert partial.status == "incomplete"
    assert partial.observation == "unknown"
    assert partial.completed == ("a.bin",)
    assert partial.attempts == 1
    assert partial.starts == 0
    finished = export_scoped_outputs(
        manifest=manifest,
        source_dir=source,
        destination=destination,
        journal_path=journal,
        lease_id="lease.9",
    )
    assert finished.status == "complete"
    assert finished.attempts == 2
    assert finished.starts == 0
    assert finished.lease_id == "lease.9"
    destination.verify(_digest(second))
    repeated = export_scoped_outputs(
        manifest=manifest,
        source_dir=source,
        destination=destination,
        journal_path=journal,
        lease_id="lease.9",
    )
    assert repeated.attempts == 2
    assert repeated.starts == 0
    assert record_fault(journal, manifest, "lost-completion").attempts == 2


def test_claim_and_faults_do_not_start_a_second_task(tmp_path: Path) -> None:
    payload = b"x"
    manifest = _manifest([_file("blob", payload)])
    journal = tmp_path / "journal.json"
    first = claim_for_transfer(journal, manifest, lease_id="lease.1")
    assert first.starts == 1
    again = claim_for_transfer(journal, manifest, lease_id="lease.1")
    assert again.starts == 1
    with pytest.raises(NativeTransferError, match="second task") as captured:
        claim_for_transfer(journal, manifest, lease_id="lease.2")
    assert captured.value.code == "transfer-duplicate-start"
    for kind in fault_kinds():
        observed = record_fault(journal, manifest, kind)
        assert observed.starts == 1
        assert classify_two_host_fault(kind).starts_task is False
        assert classify_two_host_fault(kind).observation == observed.observation
    assert record_fault(journal, manifest, "disconnected-cancel").observation == "cancel-requested"
    assert record_fault(journal, manifest, "tunnel-loss").observation == "unknown"
    observations = {
        record_observation(first, name).observation
        for name in ("success", "failure", "stopped", "unknown", "cancel-requested")
    }
    assert observations == {"success", "failure", "stopped", "unknown", "cancel-requested"}
    with pytest.raises(NativeTransferError, match="observation"):
        record_observation(first, "success ")


def test_disconnect_before_claim_leaves_starts_at_zero(tmp_path: Path) -> None:
    manifest = _manifest([_file("blob", b"x")])
    journal = tmp_path / "fresh.json"
    receipt = record_fault(journal, manifest, "disconnect-before-claim")
    assert receipt.starts == 0
    assert receipt.observation == "unknown"
    assert receipt.lease_id is None


def test_corruption_symlink_and_bounds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"stable"
    source = _store(tmp_path / "cas")
    source.put_bytes(payload)
    manifest = _manifest([_file("inputs/corpus", payload)])
    destination = tmp_path / "stage"
    journal = tmp_path / "journal.json"
    stage_scoped_inputs(
        manifest=manifest,
        source=source,
        destination=destination,
        journal_path=journal,
        lease_id="lease.1",
    )
    (destination / "inputs" / "corpus").write_bytes(b"tamper")
    with pytest.raises(NativeTransferError, match="do not match") as mismatch:
        stage_scoped_inputs(
            manifest=manifest,
            source=source,
            destination=destination,
            journal_path=journal,
            lease_id="lease.1",
        )
    assert mismatch.value.code == "transfer-integrity-mismatch"
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / "inputs").symlink_to(outside, target_is_directory=True)
    with pytest.raises(NativeTransferError, match="symlink") as link_error:
        stage_scoped_inputs(
            manifest=manifest,
            source=source,
            destination=linked,
            journal_path=tmp_path / "other.json",
            lease_id="lease.1",
        )
    assert link_error.value.code == "transfer-symlink-forbidden"
    with pytest.raises(NativeTransferError, match="not authorized"):
        manifest_from_document(
            {
                "grantId": "grant.1",
                "taskId": "task.1",
                "runId": "run.1",
                "attemptId": "attempt.1",
                "direction": "input",
                "files": [{"path": "../secret", "digest": _digest(b"a"), "sizeBytes": 1}],
            }
        )
    with pytest.raises(NativeTransferError, match="count"):
        manifest_from_document(
            {
                "grantId": "grant.1",
                "taskId": "task.1",
                "runId": "run.1",
                "attemptId": "attempt.1",
                "direction": "input",
                "files": [
                    {"path": f"f{index}", "digest": _digest(b"a"), "sizeBytes": 1}
                    for index in range(MAX_TRANSFER_FILES + 1)
                ],
            }
        )
    with pytest.raises(NativeTransferError, match="byte total"):
        manifest_from_document(
            {
                "grantId": "grant.1",
                "taskId": "task.1",
                "runId": "run.1",
                "attemptId": "attempt.1",
                "direction": "input",
                "files": [
                    {
                        "path": "left",
                        "digest": "sha256:" + "ab" * 32,
                        "sizeBytes": MAX_TRANSFER_FILE_BYTES,
                    },
                    {
                        "path": "right",
                        "digest": "sha256:" + "cd" * 32,
                        "sizeBytes": 1,
                    },
                ],
            }
        )
    monkeypatch.setattr(
        "llm_research_os.execution.native_transfer.shutil.disk_usage",
        lambda _path: type("Usage", (), {"free": 0})(),
    )
    with pytest.raises(NativeTransferError, match="disk") as disk_error:
        stage_scoped_inputs(
            manifest=manifest,
            source=source,
            destination=tmp_path / "tight",
            journal_path=tmp_path / "tight.json",
            lease_id="lease.1",
        )
    assert disk_error.value.code == "transfer-disk-exhausted"


def test_unauthorized_output_and_missing_object(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    (output / "extra").write_bytes(b"nope")
    manifest = _manifest([_file("wanted", b"yes")], direction="output")
    with pytest.raises(NativeTransferError, match="not authorized") as extra:
        export_scoped_outputs(
            manifest=manifest,
            source_dir=output,
            destination=_store(tmp_path / "cas"),
            journal_path=tmp_path / "journal.json",
            lease_id="lease.1",
        )
    assert extra.value.code == "transfer-path-unauthorized"
    fifo = tmp_path / "fifo-out"
    fifo.mkdir()
    os.mkfifo(fifo / "wanted")
    with pytest.raises(NativeTransferError, match="not authorized"):
        export_scoped_outputs(
            manifest=_manifest([_file("wanted", b"yes")], direction="output"),
            source_dir=fifo,
            destination=_store(tmp_path / "cas2"),
            journal_path=tmp_path / "fifo.json",
            lease_id="lease.1",
        )
    with pytest.raises(NativeTransferError, match="not available") as missing:
        stage_scoped_inputs(
            manifest=_manifest([_file("blob", b"absent")]),
            source=_store(tmp_path / "empty"),
            destination=tmp_path / "stage",
            journal_path=tmp_path / "missing.json",
            lease_id="lease.1",
        )
    assert missing.value.code == "transfer-object-missing"
    with pytest.raises(NativeTransferError, match="direction"):
        stage_scoped_inputs(
            manifest=_manifest([_file("blob", b"a")], direction="output"),
            source=_store(tmp_path / "empty2"),
            destination=tmp_path / "stage2",
            journal_path=tmp_path / "direction.json",
        )


def test_manifest_and_journal_rejection(tmp_path: Path) -> None:
    with pytest.raises(NativeTransferError, match="invalid"):
        manifest_from_document([])
    with pytest.raises(NativeTransferError, match="invalid"):
        manifest_from_document(
            {
                "grantId": "",
                "taskId": "task.1",
                "runId": "run.1",
                "attemptId": "attempt.1",
                "direction": "input",
                "files": [_file("blob", b"a")],
            }
        )
    path = tmp_path / "manifest.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(NativeTransferError, match="invalid"):
        load_manifest(path)
    path.unlink()
    path.symlink_to(tmp_path / "missing")
    with pytest.raises(NativeTransferError, match="invalid"):
        load_manifest(path)
    huge = tmp_path / "huge.json"
    huge.write_bytes(b'{"direction": "input"}' + b" " * 70_000)
    with pytest.raises(NativeTransferError, match="invalid"):
        load_manifest(huge)
    journal = tmp_path / "journal.json"
    journal.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(NativeTransferError, match="journal"):
        claim_for_transfer(journal, _manifest([_file("blob", b"a")]), lease_id="lease.1")
    stored = tmp_path / "stored.json"
    stored.write_text(json.dumps({"status": "nope"}), encoding="utf-8")
    with pytest.raises(NativeTransferError, match="journal"):
        claim_for_transfer(stored, _manifest([_file("blob", b"a")]), lease_id="lease.1")


def test_retry_exhaustion_and_defensive_faults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"once"
    source = _store(tmp_path / "cas")
    source.put_bytes(payload)
    manifest = _manifest([_file("blob", payload)])
    journal = tmp_path / "journal.json"

    class _Always(TransferHooks):
        def before_file(self, relative_path: str) -> None:
            raise NativeTransferError("interrupted", code=INTERRUPTED)

    for _ in range(3):
        receipt = stage_scoped_inputs(
            manifest=manifest,
            source=source,
            destination=tmp_path / "stage",
            journal_path=journal,
            hooks=_Always(),
        )
        assert receipt.status == "incomplete"
    with pytest.raises(NativeTransferError, match="retries") as exhausted:
        stage_scoped_inputs(
            manifest=manifest,
            source=source,
            destination=tmp_path / "stage",
            journal_path=journal,
        )
    assert exhausted.value.code == "transfer-retry-exhausted"
    with pytest.raises(NativeTransferError, match="not recognized"):
        classify_two_host_fault("success")
    monkeypatch.setitem(transfer_module._FAULTS, "disconnect-before-claim", "success")
    with pytest.raises(NativeTransferError, match="collapsed") as collapsed:
        classify_two_host_fault("disconnect-before-claim")
    assert collapsed.value.code == "transfer-fault-collapsed"
    assert gpu_profile_evidence("gpu-oci") == "pending-live"
    assert gpu_profile_evidence("macos-mps") == "pending-live"
    with pytest.raises(NativeTransferError, match="GPU"):
        gpu_profile_evidence("cuda.11")
    monkeypatch.setattr(
        "llm_research_os.execution.native_transfer._existing_file_digest",
        lambda *_args, **_kwargs: None,
    )
    precreated = tmp_path / "pre"
    precreated.mkdir()
    (precreated / "blob").write_bytes(payload)
    with pytest.raises(NativeTransferError, match="do not match"):
        stage_scoped_inputs(
            manifest=manifest,
            source=source,
            destination=precreated,
            journal_path=tmp_path / "pre.json",
        )


def test_process_observation_missing_stays_unknown() -> None:
    receipt = record_observation(_memory_receipt(), "success")
    missing = attach_process_observation(receipt, None)
    assert missing.observation == "unknown"
    assert missing.process_observation == "unavailable"
    present = attach_process_observation(
        receipt,
        ExecutionIdentity(
            lease_id="lease.1",
            kind="posix-pg",
            pid=4,
            pgid=4,
            start_token="token",
            container_id=None,
            docker_executable=None,
        ),
    )
    assert present.observation == "success"
    assert present.process_observation == "present"
    assert present.process_pid == 4
    absent = attach_process_observation(
        receipt,
        ExecutionIdentity(
            lease_id="lease.1",
            kind="posix-pg",
            pid=None,
            pgid=None,
            start_token=None,
            container_id=None,
            docker_executable=None,
        ),
    )
    assert absent.observation == "unknown"


def _memory_receipt() -> TransferReceipt:
    payload = b"a"
    source_manifest = _manifest([_file("blob", payload)])
    digest = manifest_digest(source_manifest)
    return TransferReceipt(
        manifest_digest=digest,
        grant_id="grant.1",
        task_id="task.1",
        run_id="run.1",
        attempt_id="attempt.1",
        direction="input",
        lease_id="lease.1",
        status="complete",
        observation="unknown",
        completed=("blob",),
        attempts=1,
        starts=1,
        runtime="test/test",
        process_observation="unavailable",
        process_pid=None,
    )


def test_cli_stage_and_classify(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    payload = b"cli"
    cas = _store(tmp_path / "cas")
    cas.put_bytes(payload)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "grantId": "grant.1",
                "taskId": "task.1",
                "runId": "run.1",
                "attemptId": "attempt.1",
                "direction": "input",
                "files": [_file("inputs/corpus", payload)],
            }
        ),
        encoding="utf-8",
    )
    parser = build_parser()
    args = parser.parse_args(
        [
            "native",
            "transfer",
            "stage",
            str(manifest),
            str(tmp_path / "cas"),
            str(tmp_path / "stage"),
            "--journal",
            str(tmp_path / "journal.json"),
            "--lease-id",
            "lease.cli",
            "--format",
            "json",
        ]
    )
    assert run_native(args) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["status"] == "complete"
    assert document["starts"] == 0
    assert document["leaseId"] == "lease.cli"
    fault = parser.parse_args(
        ["native", "transfer", "classify", "disconnected-cancel", "--format", "text"]
    )
    assert run_native(fault) == 0
    assert "cancel-requested" in capsys.readouterr().out
    output = tmp_path / "output"
    output.mkdir()
    (output / "inputs").mkdir()
    (output / "inputs" / "corpus").write_bytes(payload)
    (tmp_path / "exported").mkdir()
    exported = manifest.with_name("export.json")
    body = json.loads(manifest.read_text(encoding="utf-8"))
    body["direction"] = "output"
    exported.write_text(json.dumps(body), encoding="utf-8")
    export_args = parser.parse_args(
        [
            "native",
            "transfer",
            "export",
            str(exported),
            str(output),
            str(tmp_path / "exported"),
            "--journal",
            str(tmp_path / "export-journal.json"),
            "--lease-id",
            "lease.cli",
            "--format",
            "text",
        ]
    )
    assert run_native(export_args) == 0
    assert "unknown" in capsys.readouterr().out
    broken = parser.parse_args(
        [
            "native",
            "transfer",
            "stage",
            str(tmp_path / "missing.json"),
            str(tmp_path / "cas"),
            str(tmp_path / "stage2"),
            "--journal",
            str(tmp_path / "bad.json"),
            "--lease-id",
            "lease.cli",
            "--format",
            "json",
        ]
    )
    assert run_native(broken) == 2
    assert "transfer-manifest-invalid" in capsys.readouterr().err


def test_manifest_journal_and_resume_edges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = {
        "grantId": "grant.1",
        "taskId": "task.1",
        "runId": "run.1",
        "attemptId": "attempt.1",
        "direction": "input",
    }
    with pytest.raises(NativeTransferError, match="invalid"):
        manifest_from_document({**base, "direction": "both", "files": [_file("blob", b"a")]})
    with pytest.raises(NativeTransferError, match="count"):
        manifest_from_document({**base, "files": []})
    with pytest.raises(NativeTransferError, match="not authorized"):
        manifest_from_document({**base, "files": [_file("blob", b"a"), _file("blob", b"a")]})
    with pytest.raises(NativeTransferError, match="invalid"):
        manifest_from_document({**base, "files": ["blob"]})
    with pytest.raises(NativeTransferError, match="invalid"):
        manifest_from_document(
            {**base, "files": [{"path": "blob", "digest": "sha256:zz", "sizeBytes": 1}]}
        )
    with pytest.raises(NativeTransferError, match="invalid"):
        manifest_from_document(
            {**base, "files": [{"path": "blob", "digest": _digest(b"a"), "sizeBytes": True}]}
        )
    with pytest.raises(NativeTransferError, match="size"):
        manifest_from_document(
            {**base, "files": [{"path": "blob", "digest": _digest(b"a"), "sizeBytes": -1}]}
        )
    payload = b"ab"
    source = _store(tmp_path / "cas")
    source.put_bytes(payload)
    declared = _file("blob", payload)
    declared["sizeBytes"] = 1
    with pytest.raises(NativeTransferError, match="do not match"):
        stage_scoped_inputs(
            manifest=_manifest([declared]),
            source=source,
            destination=tmp_path / "short",
            journal_path=tmp_path / "short.json",
        )
    blocked = tmp_path / "blocked"
    blocked.write_text("file", encoding="utf-8")
    with pytest.raises(NativeTransferError, match="not authorized"):
        stage_scoped_inputs(
            manifest=_manifest([_file("blob", payload)]),
            source=source,
            destination=blocked,
            journal_path=tmp_path / "blocked.json",
        )
    parent = tmp_path / "parent"
    parent.mkdir()
    (parent / "inputs").write_text("not-dir", encoding="utf-8")
    with pytest.raises(NativeTransferError, match="not authorized"):
        stage_scoped_inputs(
            manifest=_manifest([_file("inputs/corpus", payload)]),
            source=source,
            destination=parent,
            journal_path=tmp_path / "parent.json",
        )
    with pytest.raises(NativeTransferError, match="direction"):
        export_scoped_outputs(
            manifest=_manifest([_file("blob", payload)]),
            source_dir=tmp_path / "unused",
            destination=source,
            journal_path=tmp_path / "export-direction.json",
        )
    manifest = _manifest([_file("blob", payload)])
    journal = tmp_path / "lease.json"
    claim_for_transfer(journal, manifest, lease_id="lease.1")
    with pytest.raises(NativeTransferError, match="second task"):
        stage_scoped_inputs(
            manifest=manifest,
            source=source,
            destination=tmp_path / "other-lease",
            journal_path=journal,
            lease_id="lease.2",
        )
    stored = json.loads(journal.read_text(encoding="utf-8"))
    stored["starts"] = 2
    journal.write_text(json.dumps(stored), encoding="utf-8")
    with pytest.raises(NativeTransferError, match="second task"):
        claim_for_transfer(journal, manifest, lease_id="lease.1")
    stored["manifestDigest"] = "jcs-sha256:" + "ab" * 32
    journal.write_text(json.dumps(stored), encoding="utf-8")
    with pytest.raises(NativeTransferError, match="another manifest"):
        claim_for_transfer(journal, manifest, lease_id="lease.1")
    for field, value in (
        ("status", "done"),
        ("observation", "maybe"),
        ("direction", "sideways"),
        ("processObservation", "partial"),
        ("completed", [1]),
        ("attempts", True),
        ("leaseId", 4),
        ("processPid", "4"),
        ("manifestDigest", "sha256:" + "ab" * 32),
    ):
        broken = tmp_path / f"bad-{field}.json"
        body = json.loads((tmp_path / "lease.json").read_text(encoding="utf-8"))
        body[field] = value
        broken.write_text(json.dumps(body), encoding="utf-8")
        with pytest.raises(NativeTransferError, match="journal"):
            claim_for_transfer(broken, manifest, lease_id="lease.1")
    folder = tmp_path / "folder-journal"
    folder.mkdir()
    with pytest.raises(NativeTransferError, match="journal"):
        claim_for_transfer(folder, manifest, lease_id="lease.1")
    (tmp_path / "not-object.json").write_text("[]", encoding="utf-8")
    with pytest.raises(NativeTransferError, match="journal"):
        claim_for_transfer(tmp_path / "not-object.json", manifest, lease_id="lease.1")

    def _starts(kind: str) -> transfer_module.FaultRecord:
        return transfer_module.FaultRecord(kind=kind, observation="unknown", starts_task=True)

    monkeypatch.setattr(transfer_module, "classify_two_host_fault", _starts)
    with pytest.raises(NativeTransferError, match="second task"):
        record_fault(tmp_path / "fault.json", manifest, "tunnel-loss")
    output = tmp_path / "linked-out"
    output.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (output / "nested").symlink_to(outside, target_is_directory=True)
    with pytest.raises(NativeTransferError, match="symlink"):
        export_scoped_outputs(
            manifest=_manifest([_file("nested/blob", b"a")], direction="output"),
            source_dir=output,
            destination=_store(tmp_path / "out-cas"),
            journal_path=tmp_path / "linked-out.json",
        )


def test_checkpoint_delivery_copies_one_verified_object(tmp_path: Path) -> None:
    task = (
        b"def main():\n"
        b" return {'restoreMode': 'full-state', 'state': "
        b"{'model': 1, 'optimizer': 2, 'scheduler': 3, 'rng': 4}}\n"
    )
    world, plane, spec, registry = _world(tmp_path, task_source=task)
    world.prepare()
    result = execute_reviewed_native(
        request=world.request,
        spec=spec,
        registry=registry,
        plane=plane,
        workspace=world.workspace,
        state_dir=tmp_path / "source",
        grant_token=world.token,
    )
    artifact = plane.artifacts.verify(result.artifact_digest)
    identity = load_execution_identity(tmp_path / "source" / "identities", result.lease_id)
    target = world.request.model_copy(
        update={
            "run_id": "run.2",
            "attempt_id": "attempt.2",
            "inputs": (
                world.request.inputs[0].model_copy(
                    update={
                        "name": "prior",
                        "purpose": "checkpoint",
                        "digest": result.artifact_digest,
                        "size_bytes": artifact.size_bytes,
                    }
                ),
            ),
        }
    )
    target = target.model_copy(update={"config_digest": content_digest(execution_object(target))})
    claim = NativeRestoreClaim.model_validate(
        {
            "apiVersion": "researchos.dev/v0alpha1",
            "kind": "NativeRestoreClaim",
            "mode": "full-state",
            "sourceRunId": world.request.run_id,
            "sourceAttemptId": world.request.attempt_id,
            "targetRunId": target.run_id,
            "targetAttemptId": target.attempt_id,
            "checkpointInput": "prior",
            "artifactDigest": result.artifact_digest,
        }
    )
    with pytest.raises(NativeTransferError, match="unsupported") as refused:
        deliver_verified_checkpoint(
            claim=None,
            source=None,
            target=None,
            plane=None,
            destination=tmp_path / "none",
            journal_path=tmp_path / "none.json",
        )
    assert refused.value.code == "transfer-restore-unsupported"
    bogus = NativeRestoreClaim.model_construct(
        api_version="researchos.dev/v0alpha1",
        kind="NativeRestoreClaim",
        mode="weights-only",
        source_run_id="run.1",
        source_attempt_id="attempt.1",
        target_run_id="run.2",
        target_attempt_id="attempt.2",
        checkpoint_input="prior",
        artifact_digest=result.artifact_digest,
    )
    with pytest.raises(NativeTransferError, match="unsupported"):
        deliver_verified_checkpoint(
            claim=bogus,
            source=world.request,
            target=target,
            plane=plane,
            destination=tmp_path / "bad-mode",
            journal_path=tmp_path / "bad-mode.json",
        )
    delivered = deliver_verified_checkpoint(
        claim=claim,
        source=world.request,
        target=target,
        plane=plane,
        destination=tmp_path / "target",
        journal_path=tmp_path / "target.json",
    )
    assert delivered.status == "complete"
    assert delivered.run_id == "run.2"
    assert delivered.attempt_id == "attempt.2"
    copied = tmp_path / "target" / "prior"
    with plane.artifacts.open(result.artifact_digest) as handle:
        assert copied.read_bytes() == handle.read()
    names = [path.name for path in (tmp_path / "target").rglob("*") if path.is_file()]
    assert names == ["prior"]
    assert identity is not None and identity.pid is not None
    observed = attach_process_observation(delivered, identity)
    assert observed.process_observation == "present"
    assert observed.process_pid == identity.pid
    wrong = claim.model_copy(update={"artifact_digest": "sha256:" + "0" * 64})
    with pytest.raises(NativeTransferError, match="unsupported"):
        deliver_verified_checkpoint(
            claim=wrong,
            source=world.request,
            target=target,
            plane=plane,
            destination=tmp_path / "wrong",
            journal_path=tmp_path / "wrong.json",
        )
