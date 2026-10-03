"""Independent HTTPS material, durable staging and atomic preparation without launch."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError
from test_native_output_transport import _transport

from llm_research_os.artifacts.store import LocalArtifactStore, storage_key_for
from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.execution.errors import NativeReviewedPreparationError, NativeTransferError
from llm_research_os.execution.native_reviewed import execution_object
from llm_research_os.execution.native_reviewed_documents import NativeReviewedExecutionRequest
from llm_research_os.workers import native_preparation
from llm_research_os.workers.client import WorkerClient
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.native_material_documents import NativeMaterialIndex
from llm_research_os.workers.native_preparation import prepare_remote_native

ROOT = Path(__file__).parents[1]


def _worker(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = tmp_path / "remote-worker"
    root.mkdir(mode=0o700)
    cas = root / "cas"
    cas.mkdir(mode=0o700)
    return LocalArtifactStore(cas), root / "workspace", root / "staging"


def test_remote_material_preparation_and_worker_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, plane, _, _, server, client = _transport(tmp_path)
    artifacts, workspace, staging = _worker(tmp_path)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("preparation spawned"))
    try:
        before = plane.store.last_sequence()
        index = NativeMaterialIndex.model_validate(client.fetch_native_material_index())
        assert index.request == world.request
        assert index.launch_allowed is False
        jsonschema.validate(
            index.model_dump(mode="json", by_alias=True, exclude_none=True),
            json.loads((ROOT / "schemas/native-material-index/v0alpha1.schema.json").read_text()),
        )
        receipt = prepare_remote_native(
            client, artifacts=artifacts, workspace=workspace, staging_root=staging
        )
        assert receipt.launch_allowed is False
        assert set(receipt.side_effects.model_dump().values()) == {0}
        assert (workspace / "material/code/brick/task.py").read_bytes() == world.code
        assert (workspace / "material/config.json").read_bytes() == canonical_json(
            execution_object(world.request)
        ).encode()
        assert not list(workspace.rglob("*.sqlite"))
        for item in index.files:
            assert artifacts.verify(item.byte_digest).size_bytes == item.size_bytes
            assert (workspace / item.relative_path).stat().st_mode & 0o777 == 0o600
        journals = list(staging.glob("*/journal-*.json"))
        assert len(journals) == 1
        initial = json.loads(journals[0].read_text())
        assert initial["starts"] == 0 and initial["attempts"] == 1
        assert initial["status"] == "complete"
        fetch_input = WorkerClient.fetch_native_input
        monkeypatch.setattr(
            WorkerClient, "fetch_native_input", lambda *a, **kw: pytest.fail("replay downloaded")
        )
        # A new client/cache instance resumes durable state without allocating temporary disk.
        monkeypatch.setattr(
            native_preparation, "_require_disk", lambda *a: pytest.fail("replay needed disk")
        )
        assert (
            prepare_remote_native(
                replace(client),
                artifacts=LocalArtifactStore(artifacts.root),
                workspace=workspace,
                staging_root=staging,
            )
            == receipt
        )
        assert json.loads(journals[0].read_text()) == initial
        assert plane.store.last_sequence() == before
        assert plane.rebuild().grant("grant.native").consumed_lease_id is None
        # Interpreter document can be fetched; its inner host executable is not exported.
        identity = json.loads((workspace / "material/environment/interpreter").read_text())
        with pytest.raises(WorkerError, match="refused"):
            fetch_input(client, digest=identity["executableDigest"], size_bytes=1)
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize("resume", [True, False])
def test_interrupted_stage_retains_verified_files_and_retry_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resume: bool
) -> None:
    _, plane, _, _, server, client = _transport(tmp_path)
    artifacts, workspace, staging = _worker(tmp_path)
    original = WorkerClient.fetch_native_input
    calls = []

    def fetch(self, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(kwargs["digest"])
        if len(calls) != 1:
            raise WorkerError("lost response", code="http-disconnect")
        return original(self, **kwargs)

    monkeypatch.setattr(WorkerClient, "fetch_native_input", fetch)
    try:
        before = plane.store.last_sequence()
        with pytest.raises(NativeTransferError) as exc:
            prepare_remote_native(
                client, artifacts=artifacts, workspace=workspace, staging_root=staging
            )
        assert exc.value.code == "transfer-interrupted"
        assert not workspace.exists()
        journal = next(staging.glob("*/journal-*.json"))
        body = json.loads(journal.read_text())
        assert body["status"] == "incomplete" and body["starts"] == 0
        assert len(body["completed"]) == 1
        if resume:
            first = calls[0]

            def recovered(self, **kwargs):  # type: ignore[no-untyped-def]
                assert kwargs["digest"] != first
                return original(self, **kwargs)

            monkeypatch.setattr(WorkerClient, "fetch_native_input", recovered)
            prepare_remote_native(
                client,
                artifacts=LocalArtifactStore(artifacts.root),
                workspace=workspace,
                staging_root=staging,
            )
            assert json.loads(journal.read_text())["attempts"] == 2
            assert workspace.exists()
        else:
            for _ in range(2):
                with pytest.raises(NativeTransferError) as exc:
                    prepare_remote_native(
                        client, artifacts=artifacts, workspace=workspace, staging_root=staging
                    )
                assert exc.value.code == "transfer-interrupted"
            with pytest.raises(NativeTransferError) as exc:
                prepare_remote_native(
                    client, artifacts=artifacts, workspace=workspace, staging_root=staging
                )
            assert exc.value.code == "transfer-retry-exhausted"
            assert json.loads(journal.read_text())["attempts"] == 3
        assert plane.store.last_sequence() == before
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize(
    "fault",
    [
        "workspace",
        "stage",
        "symlink",
        "ancestor",
        "overlap",
        "private",
        "cache-private",
        "stage-parent",
        "disk",
        "host",
        "revoke",
    ],
)
def test_refusal_does_not_publish_or_consume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    world, plane, _, _, server, client = _transport(tmp_path)
    artifacts, workspace, staging = _worker(tmp_path)
    try:
        if fault in {"workspace", "stage"}:
            prepare_remote_native(
                client, artifacts=artifacts, workspace=workspace, staging_root=staging
            )
            if fault == "workspace":
                (workspace / "material/code/brick/task.py").write_bytes(b"tampered")
            else:
                target = next(staging.glob("*/batch-*/objects/*"))
                target.write_bytes(b"tampered")
        elif fault == "symlink":
            workspace.symlink_to(world.root, target_is_directory=True)
        elif fault == "ancestor":
            link = tmp_path / "linked-worker"
            link.symlink_to(workspace.parent, target_is_directory=True)
            workspace = link / "workspace"
        elif fault == "overlap":
            staging = artifacts.root / "staging"
        elif fault == "private":
            workspace.parent.chmod(0o755)
        elif fault == "cache-private":
            artifacts.root.chmod(0o755)
        elif fault == "stage-parent":
            public = tmp_path / "public"
            public.mkdir(mode=0o755)
            staging = public / "staging"
        elif fault == "disk":
            monkeypatch.setattr(
                native_preparation,
                "_require_disk",
                lambda *a: (_ for _ in ()).throw(
                    NativeTransferError("no disk", code="transfer-disk-exhausted")
                ),
            )
        elif fault == "host":
            monkeypatch.setattr(
                native_preparation,
                "_require_host",
                lambda *a: (_ for _ in ()).throw(
                    NativeReviewedPreparationError(
                        "foreign interpreter", code="environment-identity-mismatch"
                    )
                ),
            )
        elif fault == "revoke":
            original = WorkerClient.fetch_native_material_index
            calls = []

            def fetch(self):  # type: ignore[no-untyped-def]
                calls.append(1)
                if len(calls) == 2:
                    plane.revoke_grant(
                        grant_id="grant.native",
                        actor_id=world.request.actor_id,
                        event_id="evt.material.revoke",
                    )
                return original(self)

            monkeypatch.setattr(WorkerClient, "fetch_native_material_index", fetch)
        before = plane.store.last_sequence()
        with pytest.raises((NativeTransferError, NativeReviewedPreparationError, WorkerError)):
            prepare_remote_native(
                client, artifacts=artifacts, workspace=workspace, staging_root=staging
            )
        assert plane.store.last_sequence() == before + (fault == "revoke")
        assert plane.rebuild().grant("grant.native").consumed_lease_id is None
        if fault not in {"workspace", "stage", "symlink"}:
            assert not workspace.exists()
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize(
    "fault", ["extra", "digest", "path", "role", "size", "bool", "launch", "request", "duplicate"]
)
def test_index_is_closed_and_request_bound(tmp_path: Path, fault: str) -> None:
    _, plane, _, _, server, client = _transport(tmp_path)
    try:
        document = client.fetch_native_material_index()
        if fault == "extra":
            document["authority"] = True
        elif fault == "digest":
            document["files"][0]["byteDigest"] = "sha256:" + "0" * 64
        elif fault == "path":
            document["files"][0]["relativePath"] = "material/../outside"
        elif fault == "role":
            document["files"][0]["role"] = "input"
        elif fault == "size":
            document["files"][0]["sizeBytes"] = 1048577
        elif fault == "bool":
            document["files"][0]["sizeBytes"] = True
        elif fault == "launch":
            document["launchAllowed"] = True
        elif fault == "request":
            document["requestDigest"] = "jcs-sha256:" + "0" * 64
        else:
            document["files"].append(document["files"][0])
        with pytest.raises(ValidationError):
            NativeMaterialIndex.model_validate(document)
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize("fault", ["missing", "corrupt", "oversize", "identity", "review"])
def test_controller_material_refuses_bad_bytes(tmp_path: Path, fault: str) -> None:
    world, plane, _, _, server, client = _transport(tmp_path)
    try:
        digest = (
            world.request.environment.interpreter_digest
            if fault == "identity"
            else "sha256:" + world.request.code.review.citation_digest.split(":", 1)[1]
            if fault == "review"
            else world.request.code.bundle_digest
        )
        path = plane.artifacts.root / storage_key_for(digest)
        if fault == "missing":
            path.unlink()
        else:
            path.write_bytes(b"x" * (1048577 if fault == "oversize" else 1))
        before = plane.store.last_sequence()
        with pytest.raises(WorkerError, match="refused"):
            client.fetch_native_material_index()
        assert plane.store.last_sequence() == before
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize("fault", ["bytes", "size", "symlink"])
def test_corrupt_cache_is_not_repaired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    _, plane, _, _, server, client = _transport(tmp_path)
    artifacts, workspace, staging = _worker(tmp_path)
    try:
        index = NativeMaterialIndex.model_validate(client.fetch_native_material_index())
        first = min(index.files, key=lambda item: item.relative_path)
        artifacts.put_bytes(
            client.fetch_native_input(digest=first.byte_digest, size_bytes=first.size_bytes)
        )
        path = artifacts.root / storage_key_for(first.byte_digest)
        if fault == "symlink":
            path.unlink()
            path.symlink_to(tmp_path / "foreign")
        else:
            path.write_bytes(b"x" * (first.size_bytes if fault == "bytes" else 1048577))
        fetch_input = WorkerClient.fetch_native_input

        def fetch(self, **kwargs):  # type: ignore[no-untyped-def]
            assert kwargs["digest"] != first.byte_digest, "damaged cache repaired"
            return fetch_input(self, **kwargs)

        monkeypatch.setattr(WorkerClient, "fetch_native_input", fetch)
        with pytest.raises(NativeTransferError):
            prepare_remote_native(
                client, artifacts=artifacts, workspace=workspace, staging_root=staging
            )
        assert not workspace.exists()
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize("fault", ["checkpoint", "isolation"])
def test_remote_preparation_refuses_unimplemented_requirements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    _, plane, _, _, server, client = _transport(tmp_path)
    artifacts, workspace, staging = _worker(tmp_path)
    try:
        document = client.fetch_native_material_index()
        request = document["request"]
        if fault == "checkpoint":
            request["inputs"][0]["purpose"] = "checkpoint"
        else:
            request["restrictions"]["network"]["required"] = True
        document["requestDigest"] = content_digest(request)
        monkeypatch.setattr(WorkerClient, "fetch_native_material_index", lambda *a: document)
        monkeypatch.setattr(
            WorkerClient,
            "fetch_native_input",
            lambda *a, **kw: pytest.fail("unsupported requirement downloaded"),
        )
        with pytest.raises((NativeTransferError, NativeReviewedPreparationError)) as exc:
            prepare_remote_native(
                client, artifacts=artifacts, workspace=workspace, staging_root=staging
            )
        assert exc.value.code == (
            "transfer-restore-unsupported"
            if fault == "checkpoint"
            else "required-network-unenforced"
        )
        assert not staging.exists() and not workspace.exists()
    finally:
        server.stop()
        plane.store.close()


def test_atomic_workspace_crash_can_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, plane, _, _, server, client = _transport(tmp_path)
    artifacts, workspace, staging = _worker(tmp_path)
    original = native_preparation._write_relative
    try:

        def crash(*args):  # type: ignore[no-untyped-def]
            original(*args)
            raise OSError("power loss")

        monkeypatch.setattr(native_preparation, "_write_relative", crash)
        with pytest.raises(OSError, match="power loss"):
            prepare_remote_native(
                client, artifacts=artifacts, workspace=workspace, staging_root=staging
            )
        assert not workspace.exists()
        assert len(list(workspace.parent.glob(".prepare-candidate-*"))) == 1
        monkeypatch.setattr(native_preparation, "_write_relative", original)
        assert (
            prepare_remote_native(
                client, artifacts=artifacts, workspace=workspace, staging_root=staging
            ).launch_allowed
            is False
        )
        assert len(list(workspace.parent.glob(".prepare-candidate-*"))) == 1
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize("extra_code", [False, True])
def test_two_batches_preserve_native_paths_and_exact_code_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra_code: bool
) -> None:
    _, plane, _, _, server, client = _transport(tmp_path)
    artifacts, workspace, staging = _worker(tmp_path)
    try:
        document = client.fetch_native_material_index()
        payloads = {
            item["relativePath"]: client.fetch_native_input(
                digest=item["byteDigest"], size_bytes=item["sizeBytes"]
            )
            for item in document["files"]
        }

        def sha(payload: bytes) -> str:
            return "sha256:" + hashlib.sha256(payload).hexdigest()

        bundle = json.loads(payloads["material/bundle"])
        for number in range(30):
            path = "brick/__init__.py" if number == 0 else f"brick/module_{number}.py"
            payload = f"# reviewed module {number}\n".encode()
            bundle["files"].append({"path": path, "digest": sha(payload)})
            payloads[f"material/code/{path}"] = payload
        payloads["material/bundle"] = canonical_json(bundle).encode()
        request = document["request"]
        request["code"]["bundleDigest"] = sha(payloads["material/bundle"])
        review = json.loads(payloads["material/environment/review"])
        review["bundleDigest"] = request["code"]["bundleDigest"]
        payloads["material/environment/review"] = canonical_json(review).encode()
        request["code"]["review"]["citationDigest"] = content_digest(review)
        request["code"]["review"]["bundleDigest"] = request["code"]["bundleDigest"]
        request["inputs"][0]["name"] = "input:one"
        payloads["material/inputs/input:one"] = payloads.pop("material/inputs/corpus")
        payloads["material/config.json"] = canonical_json(
            execution_object(NativeReviewedExecutionRequest.model_validate(request))
        ).encode()
        request["configDigest"] = content_digest(json.loads(payloads["material/config.json"]))
        document["requestDigest"] = content_digest(request)
        if extra_code:
            payloads["material/code/undeclared.py"] = b"# unplanned\n"
        rows = []
        for path, payload in payloads.items():
            old = next((item for item in document["files"] if item["relativePath"] == path), None)
            role = (
                old["role"] if old else "input" if path.startswith("material/inputs/") else "code"
            )
            digest = (
                content_digest(json.loads(payload))
                if role in {"config", "review"}
                else sha(payload)
            )
            row = {
                "relativePath": path,
                "role": role,
                "digest": digest,
                "byteDigest": sha(payload),
                "sizeBytes": len(payload),
            }
            if role == "input":
                row["name"] = "input:one"
            rows.append(row)
        document["files"] = rows
        NativeMaterialIndex.model_validate(document)
        downloads = {sha(payload): payload for payload in payloads.values()}
        monkeypatch.setattr(WorkerClient, "fetch_native_material_index", lambda *a: document)
        monkeypatch.setattr(
            WorkerClient, "fetch_native_input", lambda self, digest, size_bytes: downloads[digest]
        )
        if extra_code:
            with pytest.raises(NativeReviewedPreparationError) as exc:
                prepare_remote_native(
                    client, artifacts=artifacts, workspace=workspace, staging_root=staging
                )
            assert exc.value.code == "code-digest-mismatch"
            assert not workspace.exists()
        else:
            prepare_remote_native(
                client, artifacts=artifacts, workspace=workspace, staging_root=staging
            )
            assert (workspace / "material/code/brick/__init__.py").read_bytes() == payloads[
                "material/code/brick/__init__.py"
            ]
            assert (workspace / "material/inputs/input:one").exists()
        journals = list(staging.glob("*/journal-*.json"))
        assert len(journals) == 2
        assert all(json.loads(path.read_text())["starts"] == 0 for path in journals)
    finally:
        server.stop()
        plane.store.close()


def test_published_material_examples() -> None:
    schema = json.loads((ROOT / "schemas/native-material-index/v0alpha1.schema.json").read_text())
    valid = json.loads((ROOT / "examples/native-material-index/valid/linux-index.json").read_text())
    jsonschema.validate(valid, schema)
    NativeMaterialIndex.model_validate(valid)
    for path in (ROOT / "examples/native-material-index/invalid").glob("*.json"):
        document = json.loads(path.read_text())
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(document, schema)
        with pytest.raises(ValidationError):
            NativeMaterialIndex.model_validate(document)
