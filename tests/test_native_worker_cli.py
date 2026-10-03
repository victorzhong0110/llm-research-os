"""Existing Worker CLI composes the reviewed TLS runtime without new authority."""

from __future__ import annotations

import json
import os
import shutil

import pytest
from test_native_remote_executor import _setup
from test_native_remote_executor import live_host as live_host
from test_native_reviewed_preparation import PROJECT, SOURCE
from test_native_reviewed_runtime import _world

from llm_research_os.canonical import canonical_json
from llm_research_os.cli import main
from llm_research_os.workers import native_worker, serve
from llm_research_os.workers.credentials import (
    WorkerCredential,
    write_hmac_key,
    write_worker_credential,
)
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.native_claim import NativeControllerContext


def _credential(client, kwargs):  # type: ignore[no-untyped-def]
    root = kwargs["workspace"].parent
    ca = root / "worker-ca.pem"
    shutil.copyfile(client.ca_path, ca)
    path = root / "credential.json"
    write_worker_credential(
        path,
        WorkerCredential(
            client.base_url,
            client.worker_id,
            client.session,
            client.grant_token,
            ca,
            client.tls_fingerprint,
        ),
    )
    return path


def _argv(command, credential, kwargs):  # type: ignore[no-untyped-def]
    return [
        "workers",
        command,
        str(credential),
        "--artifacts",
        str(kwargs["artifacts"].root),
        "--state",
        str(kwargs["state_root"]),
    ]


@pytest.mark.native_remote_live
@pytest.mark.usefixtures("live_host")
def test_real_cli_cpu_execution_and_saved_receipt_replay(tmp_path, capsys, monkeypatch):  # type: ignore[no-untyped-def]
    world, plane, server, client, kwargs = _setup(tmp_path)
    credential = _credential(client, kwargs)
    try:
        args = [
            *_argv("run-native", credential, kwargs),
            "--workspace",
            str(kwargs["workspace"]),
            "--staging",
            str(kwargs["staging_root"]),
        ]
        assert main(args) == 0
        receipt = json.loads(capsys.readouterr().out)
        assert receipt["kind"] == "NativeOutcomeReceipt" and receipt["disposition"] == "completed"
        assert receipt["launchAllowed"] is False
        request = credential.parent / "request.json"
        request.write_text(
            canonical_json(world.request.model_dump(mode="json", by_alias=True, exclude_none=True))
        )
        monkeypatch.setattr(
            native_worker,
            "execute_remote_native",
            lambda *a, **k: pytest.fail("recovery entered launch service"),
        )
        before = plane.store.last_sequence()
        assert (
            main([*_argv("reconcile-native", credential, kwargs), "--request", str(request)]) == 0
        )
        assert json.loads(capsys.readouterr().out) == receipt
        assert plane.store.last_sequence() == before
        all_state = "".join(
            p.read_text() for p in kwargs["state_root"].iterdir() if p.stat().st_size
        )
        assert client.grant_token not in all_state and client.session not in all_state
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize(
    "fault", ["mode", "link", "hardlink", "large", "parent", "corrupt", "duplicate"]
)
def test_private_credential_refusal_before_network_or_launch(tmp_path, capsys, monkeypatch, fault):  # type: ignore[no-untyped-def]
    _, plane, server, client, kwargs = _setup(tmp_path)
    credential = _credential(client, kwargs)
    if fault == "mode":
        credential.chmod(0o644)
    elif fault == "link":
        moved = credential.with_suffix(".saved")
        credential.rename(moved)
        credential.symlink_to(moved)
    elif fault == "hardlink":
        os.link(credential, credential.with_suffix(".linked"))
    elif fault == "large":
        credential.write_bytes(b"x" * 65537)
    elif fault == "parent":
        credential.parent.chmod(0o755)
    elif fault == "duplicate":
        credential.write_text(
            credential.read_text().rstrip()[:-1]
            + ', "session": '
            + json.dumps(client.session)
            + "}"
        )
    else:
        credential.write_text(client.grant_token)
    monkeypatch.setattr(
        native_worker,
        "execute_remote_native",
        lambda *a, **k: pytest.fail("unsafe credential launched"),
    )
    try:
        before = plane.store.last_sequence()
        args = [
            *_argv("run-native", credential, kwargs),
            "--workspace",
            str(kwargs["workspace"]),
            "--staging",
            str(kwargs["staging_root"]),
        ]
        assert main(args) == 1
        printed = capsys.readouterr()
        assert client.grant_token not in printed.out + printed.err
        assert client.session not in printed.out + printed.err
        assert plane.store.last_sequence() == before
    finally:
        server.stop()
        plane.store.close()


def test_recovery_request_refuses_parser_secret_and_unknown_state(tmp_path, capsys, monkeypatch):  # type: ignore[no-untyped-def]
    _, plane, server, client, kwargs = _setup(tmp_path)
    credential = _credential(client, kwargs)
    request = credential.parent / "bad.json"
    request.write_text(client.grant_token)
    monkeypatch.setattr(
        native_worker, "execute_remote_native", lambda *a, **k: pytest.fail("bad recovery launched")
    )
    try:
        before = plane.store.last_sequence()
        assert (
            main([*_argv("reconcile-native", credential, kwargs), "--request", str(request)]) == 2
        )
        printed = capsys.readouterr()
        assert client.grant_token not in printed.out + printed.err
        assert plane.store.last_sequence() == before
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize("fault", ["spec-only", "registry-only", "project"])
def test_controller_native_context_refuses_incomplete_or_foreign_input(
    tmp_path, capsys, monkeypatch, fault
):  # type: ignore[no-untyped-def]
    world, plane, spec, _ = _world(tmp_path)
    spec_path = tmp_path / "controller-spec.json"
    spec_path.write_text(spec.model_dump_json(by_alias=True))
    args = [
        "workers",
        "serve",
        str(world.database),
        "--artifacts",
        str(plane.artifacts.root),
        "--state",
        str(tmp_path / "new-controller-state"),
        "--project",
        PROJECT,
        "--source",
        SOURCE,
    ]
    if fault != "registry-only":
        args += ["--native-spec", str(spec_path)]
    if fault != "spec-only":
        args += ["--native-registry", str(tmp_path / "native-block.json")]
    if fault == "project":
        args[args.index("--project") + 1] = "project.other"
    monkeypatch.setattr(
        serve,
        "serve_isolated_control_plane",
        lambda **kw: pytest.fail("invalid native context bound a listener"),
    )
    try:
        assert main(args) == 1
        assert json.loads(capsys.readouterr().err)["errors"][0]["type"] == "native-context-invalid"
        assert not (tmp_path / "new-controller-state").exists()
    finally:
        plane.store.close()


def test_controller_cli_loads_actual_native_context_and_bind_keeps_it(
    tmp_path, capsys, monkeypatch
):  # type: ignore[no-untyped-def]
    world, plane, spec, registry = _world(tmp_path)
    spec_path = tmp_path / "controller-spec.json"
    spec_path.write_text(spec.model_dump_json(by_alias=True))
    captured = []

    def capture(**kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs["native_context"])

    monkeypatch.setattr(serve, "serve_isolated_control_plane", capture)
    try:
        assert (
            main(
                [
                    "workers",
                    "serve",
                    str(world.database),
                    "--artifacts",
                    str(plane.artifacts.root),
                    "--state",
                    str(tmp_path / "controller-state"),
                    "--project",
                    PROJECT,
                    "--source",
                    SOURCE,
                    "--native-spec",
                    str(spec_path),
                    "--native-registry",
                    str(tmp_path / "native-block.json"),
                ]
            )
            == 0
        )
        assert len(captured) == 1 and captured[0].spec == spec
        assert captured[0].registry.digest() == registry.digest()
        state = tmp_path / "bound-state"
        write_hmac_key(state / "hmac.key", world.hmac_key)
        server, _ = serve.bind_isolated_control_plane(
            database=world.database,
            artifacts_root=plane.artifacts.root,
            state_dir=state,
            project_id=PROJECT,
            source=SOURCE,
            native_context=NativeControllerContext(spec, registry),
        )
        try:
            assert server._native_context == NativeControllerContext(spec, registry)
        finally:
            server.close_listener()
        assert not capsys.readouterr().err
    finally:
        plane.store.close()


def test_unrecorded_outcome_and_ambiguous_mode_do_not_create_launch_authority(
    tmp_path, capsys, monkeypatch
):  # type: ignore[no-untyped-def]
    from llm_research_os.workers.native_executor import RemoteNativeResult

    _, plane, server, client, kwargs = _setup(tmp_path)
    credential = _credential(client, kwargs)
    try:
        monkeypatch.setattr(
            native_worker,
            "execute_remote_native",
            lambda *a, **k: RemoteNativeResult("unknown", "lease.grant.native"),
        )
        assert (
            main(
                [
                    *_argv("run-native", credential, kwargs),
                    "--workspace",
                    str(kwargs["workspace"]),
                    "--staging",
                    str(kwargs["staging_root"]),
                ]
            )
            == 1
        )
        assert (
            json.loads(capsys.readouterr().err)["errors"][0]["type"] == "native-outcome-unrecorded"
        )
        with pytest.raises(WorkerError, match="ambiguous"):
            native_worker.run_native_worker(
                credential_path=credential,
                artifacts_root=kwargs["artifacts"].root,
                state_root=kwargs["state_root"],
            )
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.native_remote_live
@pytest.mark.usefixtures("live_host")
def test_separate_cli_worker_process_reopens_existing_execution(tmp_path):  # type: ignore[no-untyped-def]
    import subprocess
    import sys

    world, plane, server, client, kwargs = _setup(tmp_path)
    credential = _credential(client, kwargs)
    request = credential.parent / "request.json"
    request.write_text(
        canonical_json(world.request.model_dump(mode="json", by_alias=True, exclude_none=True))
    )
    try:
        args = [
            *_argv("run-native", credential, kwargs),
            "--workspace",
            str(kwargs["workspace"]),
            "--staging",
            str(kwargs["staging_root"]),
        ]
        completed = subprocess.run(
            [sys.executable, "-I", "-m", "llm_research_os", *args],
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, "separate Worker CLI did not complete its CPU task"
        receipt = json.loads(completed.stdout)
        assert receipt["disposition"] == "completed" and not completed.stderr
        before = plane.store.last_sequence()
        replay = subprocess.run(
            [
                sys.executable,
                "-I",
                "-m",
                "llm_research_os",
                *_argv("reconcile-native", credential, kwargs),
                "--request",
                str(request),
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert replay.returncode == 0 and not replay.stderr
        assert json.loads(replay.stdout) == receipt
        assert plane.store.last_sequence() == before
        assert client.grant_token.encode() not in completed.stdout + replay.stdout
        assert not list(credential.parent.rglob("*.sqlite"))
        assert not list(credential.parent.rglob("hmac.key"))
    finally:
        server.stop()
        plane.store.close()


def test_artifact_error_is_structured_and_never_echoes_credential(tmp_path, capsys, monkeypatch):  # type: ignore[no-untyped-def]
    from llm_research_os.artifacts.errors import ArtifactStoreError

    _, plane, server, client, kwargs = _setup(tmp_path)
    credential = _credential(client, kwargs)

    def corrupt(*a, **k):  # type: ignore[no-untyped-def]
        raise ArtifactStoreError(client.grant_token)

    monkeypatch.setattr(native_worker, "execute_remote_native", corrupt)
    try:
        assert (
            main(
                [
                    *_argv("run-native", credential, kwargs),
                    "--workspace",
                    str(kwargs["workspace"]),
                    "--staging",
                    str(kwargs["staging_root"]),
                ]
            )
            == 1
        )
        printed = capsys.readouterr()
        assert not printed.out and client.grant_token not in printed.err
        assert json.loads(printed.err)["errors"][0]["type"] == "native-worker-artifact-invalid"
    finally:
        server.stop()
        plane.store.close()
