from __future__ import annotations

import builtins
import contextlib
import importlib
import json
import os
import signal
import socket
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any, NoReturn

import pytest

import llm_research_os.execution.native_runtime as runtime_module
from llm_research_os.blocks.builtins import builtin_manifests
from llm_research_os.blocks.models import BlockManifest
from llm_research_os.blocks.registry import BlockRegistry
from llm_research_os.canonical import content_digest
from llm_research_os.cli import main
from llm_research_os.execution import (
    NativeProcessLimits,
    NativeProcessPreflightError,
    NativeProcessPreflightPolicy,
    NativeProcessRuntimeError,
    PlanAuthorizationPolicy,
    TrustedKernel,
    authorize_plan,
    execute_native_process,
    native_runtime_receipt,
    record_plan_authorization_event,
    validate_plan_authorization_event_request_document,
)
from llm_research_os.execution.native_runtime import NativeProcessDisposition
from llm_research_os.spec.io import load_document
from llm_research_os.spec.models import ResearchSpec
from llm_research_os.storage import EventStore

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples" / "native-process-preflight"
SPEC = EXAMPLES / "spec.yaml"
MANIFEST = EXAMPLES / "manifest.yaml"
AUTHORIZATION_REQUEST = EXAMPLES / "authorization-request.json"
PREFLIGHT_REQUEST = EXAMPLES / "preflight-request.json"
PROJECT = "example-native-process-preflight"
WORKFLOW = "workflow.native"
SOURCE = "https://researchos.dev/projects/example-native-process-preflight"
ZERO_DIGEST = "jcs-sha256:" + "0" * 64


def _case(
    *,
    limits: NativeProcessLimits | None = None,
    manifest_document: dict[str, Any] | None = None,
    spec_document: dict[str, Any] | None = None,
) -> tuple[
    BlockRegistry,
    Any,
    PlanAuthorizationPolicy,
    NativeProcessPreflightPolicy,
]:
    manifest = BlockManifest.model_validate(manifest_document or load_document(MANIFEST))
    registry = BlockRegistry()
    for builtin in builtin_manifests():
        registry.register(builtin, source="builtin")
    registry.register(manifest)
    registry.seal()
    spec = ResearchSpec.model_validate(spec_document or load_document(SPEC))
    report = TrustedKernel(registry).dry_run(spec)
    assert report.digests.plan is not None
    authorization_policy = PlanAuthorizationPolicy(
        spec_digest=report.digests.spec,
        registry_digest=report.digests.registry,
        plan_digest=report.digests.plan,
        granted_capabilities=tuple(sorted(manifest.capabilities)),
        granted_permissions=tuple(sorted(manifest.permissions)),
    )
    authorization = authorize_plan(report, authorization_policy)
    chosen = limits or NativeProcessLimits(
        wall_time_seconds=10,
        stdout_bytes=65_536,
        stderr_bytes=65_536,
        termination_grace_seconds=2,
    )
    policy = NativeProcessPreflightPolicy(
        spec_digest=report.digests.spec,
        registry_digest=report.digests.registry,
        plan_digest=report.digests.plan,
        authorization_decision_digest=authorization.decision_digest,
        task_path=("workflow", "workflow.native", "invoke"),
        runner="researchos.python-worker/v0alpha1",
        shell=False,
        network="denied",
        workspace="isolated-temporary",
        environment_allowlist=(),
        limits=chosen,
    )
    return registry, report, authorization_policy, policy


def _record_native_auth(
    store: EventStore,
    report: Any,
    policy: PlanAuthorizationPolicy,
    *,
    event_id: str = "evt.auth.native.1",
) -> Any:
    document = {
        "apiVersion": "researchos.dev/v0alpha1",
        "kind": "PlanAuthorizationEventRequest",
        "projectId": PROJECT,
        "experimentRevision": 1,
        "workflowId": WORKFLOW,
        "binding": {
            "specDigest": policy.spec_digest,
            "registryDigest": policy.registry_digest,
            "planDigest": policy.plan_digest,
            "decisionDigest": authorize_plan(report, policy).decision_digest,
        },
        "source": SOURCE,
        "subject": "authorization.example-native-process-preflight.revision-1",
        "streamid": "authorization.example-native-process-preflight",
        "actor": {"id": "researcher.alice"},
        "event": {"id": event_id, "time": "2026-09-02T05:00:00Z"},
        "evidenceRefs": [],
    }
    request = validate_plan_authorization_event_request_document(document)
    return record_plan_authorization_event(store, report, policy, request).stored


def _run(
    store: EventStore,
    report: Any,
    registry: BlockRegistry,
    authorization_policy: PlanAuthorizationPolicy,
    policy: NativeProcessPreflightPolicy,
    stored: Any,
    **kwargs: Any,
) -> Any:
    return execute_native_process(
        store,
        report,
        registry,
        authorization_policy,
        policy,
        authorization_event_id=stored.event.id,
        authorization_sequence=stored.event.sequence,
        project_id=PROJECT,
        **kwargs,
    )


def test_exact_authorized_local_run_succeeds_and_binds_preflight(tmp_path: Path) -> None:
    registry, report, authorization_policy, policy = _case()
    with EventStore(tmp_path / "events.db") as store:
        stored = _record_native_auth(store, report, authorization_policy)
        first = _run(store, report, registry, authorization_policy, policy, stored)
        second = _run(store, report, registry, authorization_policy, policy, stored)
    assert first.disposition is NativeProcessDisposition.SUCCEEDED
    assert first.reason_code == "native.process.ok"
    assert first.result_digest is not None and first.result_digest.startswith("jcs-sha256:")
    assert first.preflight_digest.startswith("jcs-sha256:")
    assert first.transport == "local"
    assert first.profile == "restricted-v0alpha1"
    assert first.entrypoint_executed is False
    assert first.isolation == "process-group"
    assert first.network_enforcement == "not-enforced"
    assert first.observation == "exited"
    assert first.stdout == second.stdout
    assert first.result_digest == second.result_digest
    parsed = json.loads(first.stdout.decode("utf-8"))
    assert parsed["preflightDigest"] == first.preflight_digest
    assert first.result_digest == content_digest(parsed)
    assert "example_native_worker:run" not in repr(first)
    assert "example_native_worker:run" not in first.stdout.decode("utf-8")
    with EventStore(tmp_path / "events.db", create=False) as reopened:
        assert reopened.last_sequence() == 1


def test_receipt_is_digest_only_and_deterministic(tmp_path: Path) -> None:
    registry, report, authorization_policy, policy = _case()
    with EventStore(tmp_path / "events.db") as store:
        stored = _record_native_auth(store, report, authorization_policy)
        result = _run(store, report, registry, authorization_policy, policy, stored)
    receipt = native_runtime_receipt(result)
    assert receipt["preflightDigest"] == result.preflight_digest
    assert receipt["disposition"] == "succeeded"
    assert receipt["reasonCode"] == "native.process.ok"
    assert receipt["entrypointExecuted"] is False
    assert receipt["stdoutBytes"] == len(result.stdout)
    assert "example_native_worker:run" not in json.dumps(receipt)


def test_ssh_transport_is_checked_past_authorization_then_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, report, authorization_policy, policy = _case()

    def tripwire(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError(f"spawn called: {args!r} {kwargs!r}")

    monkeypatch.setattr(subprocess, "Popen", tripwire)
    with EventStore(tmp_path / "events.db") as store:
        stored = _record_native_auth(store, report, authorization_policy)
        with pytest.raises(NativeProcessRuntimeError, match="ssh transport") as captured:
            _run(
                store,
                report,
                registry,
                authorization_policy,
                policy,
                stored,
                transport="ssh",
            )
        assert captured.value.code == "ssh-transport-not-implemented"


@pytest.mark.parametrize("transport", ["", "SSH", "tls", "local-ssh", None, 123, True])
def test_unknown_transport_fails_closed(tmp_path: Path, transport: object) -> None:
    registry, report, authorization_policy, policy = _case()
    with EventStore(tmp_path / "events.db") as store:
        stored = _record_native_auth(store, report, authorization_policy)
        with pytest.raises(NativeProcessRuntimeError, match="transport is invalid") as captured:
            execute_native_process(
                store,
                report,
                registry,
                authorization_policy,
                policy,
                authorization_event_id=stored.event.id,
                authorization_sequence=stored.event.sequence,
                project_id=PROJECT,
                transport=transport,  # type: ignore[arg-type]
            )
        assert captured.value.code == "native-transport-invalid"


@pytest.mark.parametrize("profile", ["", "default", "restricted", None, 123, True])
def test_unknown_profile_fails_closed(tmp_path: Path, profile: object) -> None:
    registry, report, authorization_policy, policy = _case()
    with EventStore(tmp_path / "events.db") as store:
        stored = _record_native_auth(store, report, authorization_policy)
        with pytest.raises(NativeProcessRuntimeError, match="profile is invalid") as captured:
            execute_native_process(
                store,
                report,
                registry,
                authorization_policy,
                policy,
                authorization_event_id=stored.event.id,
                authorization_sequence=stored.event.sequence,
                project_id=PROJECT,
                profile=profile,  # type: ignore[arg-type]
            )
        assert captured.value.code == "native-profile-invalid"


@pytest.mark.parametrize(
    ("event_id", "sequence", "code", "message"),
    (
        ("evt.missing", "1", "authorization-event-not-found", "not found"),
        ("evt.auth.native.1", "2", "authorization-sequence-mismatch", "sequence"),
    ),
)
def test_missing_or_swapped_citation_fails_before_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_id: str,
    sequence: str,
    code: str,
    message: str,
) -> None:
    registry, report, authorization_policy, policy = _case()

    def tripwire(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError(f"spawn called: {args!r} {kwargs!r}")

    monkeypatch.setattr(subprocess, "Popen", tripwire)
    with EventStore(tmp_path / "events.db") as store:
        _record_native_auth(store, report, authorization_policy)
        with pytest.raises(NativeProcessRuntimeError, match=message) as captured:
            execute_native_process(
                store,
                report,
                registry,
                authorization_policy,
                policy,
                authorization_event_id=event_id,
                authorization_sequence=sequence,
                project_id=PROJECT,
            )
        assert captured.value.code == code
        assert store.last_sequence() == 1


def test_denied_or_mismatched_authorization_cannot_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, report, authorization_policy, policy = _case()

    def tripwire(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError(f"spawn called: {args!r} {kwargs!r}")

    monkeypatch.setattr(subprocess, "Popen", tripwire)
    with EventStore(tmp_path / "events.db") as store:
        stored = _record_native_auth(store, report, authorization_policy)
        denied = replace(authorization_policy, granted_capabilities=())
        with pytest.raises(NativeProcessPreflightError, match="authorized exact plan"):
            execute_native_process(
                store,
                report,
                registry,
                denied,
                policy,
                authorization_event_id=stored.event.id,
                authorization_sequence=stored.event.sequence,
                project_id=PROJECT,
            )
        foreign = load_document(SPEC)
        foreign["metadata"]["title"] = "Other title for binding mismatch"
        _, foreign_report, foreign_auth, foreign_preflight = _case(spec_document=foreign)
        with pytest.raises(NativeProcessRuntimeError) as captured:
            execute_native_process(
                store,
                foreign_report,
                registry,
                foreign_auth,
                foreign_preflight,
                authorization_event_id=stored.event.id,
                authorization_sequence=stored.event.sequence,
                project_id=PROJECT,
            )
        assert captured.value.code == "authorization-binding-mismatch"


def test_preflight_binding_errors_propagate_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, report, authorization_policy, policy = _case()

    def tripwire(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError(f"spawn called: {args!r} {kwargs!r}")

    monkeypatch.setattr(subprocess, "Popen", tripwire)
    with EventStore(tmp_path / "events.db") as store:
        stored = _record_native_auth(store, report, authorization_policy)
        with pytest.raises(NativeProcessPreflightError, match="authorization binding"):
            execute_native_process(
                store,
                report,
                registry,
                authorization_policy,
                replace(policy, plan_digest=ZERO_DIGEST),
                authorization_event_id=stored.event.id,
                authorization_sequence=stored.event.sequence,
                project_id=PROJECT,
            )
        unsealed = BlockRegistry()
        for builtin in builtin_manifests():
            unsealed.register(builtin, source="builtin")
        unsealed.register(BlockManifest.model_validate(load_document(MANIFEST)))
        with pytest.raises(NativeProcessPreflightError, match="sealed registry"):
            execute_native_process(
                store,
                report,
                unsealed,
                authorization_policy,
                policy,
                authorization_event_id=stored.event.id,
                authorization_sequence=stored.event.sequence,
                project_id=PROJECT,
            )


@pytest.mark.parametrize(
    ("kwargs", "code"),
    (
        (
            {"authorization_event_id": None, "authorization_sequence": "1"},
            "native-citation-invalid",
        ),
        (
            {"authorization_event_id": "evt.x", "authorization_sequence": None},
            "native-citation-invalid",
        ),
        (
            {"authorization_event_id": "evt.x", "authorization_sequence": "1", "project_id": ""},
            "native-project-invalid",
        ),
        (
            {"authorization_event_id": "evt.x", "authorization_sequence": "1", "project_id": None},
            "native-project-invalid",
        ),
    ),
)
def test_malformed_runtime_inputs_fail_closed(
    tmp_path: Path, kwargs: dict[str, Any], code: str
) -> None:
    registry, report, authorization_policy, policy = _case()
    with EventStore(tmp_path / "events.db") as store:
        stored = _record_native_auth(store, report, authorization_policy)
        merged = {
            "authorization_event_id": stored.event.id,
            "authorization_sequence": stored.event.sequence,
            "project_id": PROJECT,
        }
        merged.update(kwargs)
        with pytest.raises(NativeProcessRuntimeError, match="invalid") as captured:
            execute_native_process(
                store,
                report,
                registry,
                authorization_policy,
                policy,
                **merged,  # type: ignore[arg-type]
            )
        assert captured.value.code == code


def test_invalid_cancel_probe_fails_closed(tmp_path: Path) -> None:
    registry, report, authorization_policy, policy = _case()
    with EventStore(tmp_path / "events.db") as store:
        stored = _record_native_auth(store, report, authorization_policy)
        with pytest.raises(NativeProcessRuntimeError, match="cancel probe") as captured:
            execute_native_process(
                store,
                report,
                registry,
                authorization_policy,
                policy,
                authorization_event_id=stored.event.id,
                authorization_sequence=stored.event.sequence,
                project_id=PROJECT,
                should_cancel="yes",  # type: ignore[arg-type]
            )
        assert captured.value.code == "native-cancel-invalid"


def test_wall_timeout_reports_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry, report, authorization_policy, policy = _case(
        limits=NativeProcessLimits(
            wall_time_seconds=1,
            stdout_bytes=65_536,
            stderr_bytes=65_536,
            termination_grace_seconds=1,
        )
    )
    monkeypatch.setattr(runtime_module, "_HELPER_SCRIPT", "import time\ntime.sleep(30)\n")
    with EventStore(tmp_path / "events.db") as store:
        stored = _record_native_auth(store, report, authorization_policy)
        result = _run(store, report, registry, authorization_policy, policy, stored)
    assert result.disposition is NativeProcessDisposition.UNKNOWN
    assert result.reason_code == "native.process.timeout"
    assert result.result_digest is None
    assert result.observation == "unknown"


def test_output_overflow_fails_closed(tmp_path: Path) -> None:
    registry, report, authorization_policy, policy = _case(
        limits=NativeProcessLimits(
            wall_time_seconds=10,
            stdout_bytes=10,
            stderr_bytes=65_536,
            termination_grace_seconds=2,
        )
    )
    with EventStore(tmp_path / "events.db") as store:
        stored = _record_native_auth(store, report, authorization_policy)
        result = _run(store, report, registry, authorization_policy, policy, stored)
    assert result.disposition is NativeProcessDisposition.FAILED
    assert result.reason_code == "native.brick.output-too-large"
    assert len(result.stdout) == 10


def test_helper_failure_modes_map_to_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, report, authorization_policy, policy = _case()
    with EventStore(tmp_path / "events.db") as store:
        stored = _record_native_auth(store, report, authorization_policy)
        monkeypatch.setattr(runtime_module, "_HELPER_SCRIPT", "import sys\nsys.exit(3)\n")
        failed = _run(store, report, registry, authorization_policy, policy, stored)
        assert failed.disposition is NativeProcessDisposition.FAILED
        assert failed.reason_code == "native.brick.failed"

        monkeypatch.setattr(runtime_module, "_HELPER_SCRIPT", "print('not-json')\n")
        invalid = _run(store, report, registry, authorization_policy, policy, stored)
        assert invalid.disposition is NativeProcessDisposition.FAILED
        assert invalid.reason_code == "native.brick.invalid-report"


def test_cancel_observed_requires_reaped_exit(tmp_path: Path) -> None:
    registry, report, authorization_policy, policy = _case()
    with EventStore(tmp_path / "events.db") as store:
        stored = _record_native_auth(store, report, authorization_policy)
        result = execute_native_process(
            store,
            report,
            registry,
            authorization_policy,
            policy,
            authorization_event_id=stored.event.id,
            authorization_sequence=stored.event.sequence,
            project_id=PROJECT,
            should_cancel=lambda: True,
        )
    assert result.disposition is NativeProcessDisposition.FAILED
    assert result.reason_code == "cancel-observed"
    assert result.observation == "exited"


def test_unobserved_cancel_when_reap_is_suppressed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, report, authorization_policy, policy = _case()
    monkeypatch.setattr(runtime_module, "_HELPER_SCRIPT", "import time\ntime.sleep(30)\n")
    monkeypatch.setattr(runtime_module, "_reap_process_group", lambda *a, **k: None)
    with EventStore(tmp_path / "events.db") as store:
        stored = _record_native_auth(store, report, authorization_policy)
        result = execute_native_process(
            store,
            report,
            registry,
            authorization_policy,
            policy,
            authorization_event_id=stored.event.id,
            authorization_sequence=stored.event.sequence,
            project_id=PROJECT,
            should_cancel=lambda: True,
        )
    assert result.disposition is NativeProcessDisposition.UNKNOWN
    assert result.reason_code == "execution-unobserved"


def test_runtime_never_imports_entrypoint_or_dials_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, report, authorization_policy, policy = _case()

    def tripwire(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError(f"side effect called: {args!r} {kwargs!r}")

    monkeypatch.setattr(importlib, "import_module", tripwire)
    monkeypatch.setattr(socket, "create_connection", tripwire)
    monkeypatch.setattr(subprocess, "run", tripwire)
    monkeypatch.setattr(os, "system", tripwire)
    monkeypatch.setattr(builtins, "eval", tripwire)
    monkeypatch.setattr(builtins, "exec", tripwire)
    with EventStore(tmp_path / "events.db") as store:
        stored = _record_native_auth(store, report, authorization_policy)
        result = _run(store, report, registry, authorization_policy, policy, stored)
    assert result.disposition is NativeProcessDisposition.SUCCEEDED


def test_native_run_cli_succeeds_and_ssh_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _registry, report, authorization_policy, _ = _case()
    database = tmp_path / "native.db"
    with EventStore(database) as store:
        stored = _record_native_auth(store, report, authorization_policy)
        event_id = stored.event.id
        sequence = stored.event.sequence
    assert (
        main(
            [
                "native",
                "run",
                str(SPEC),
                str(AUTHORIZATION_REQUEST),
                str(PREFLIGHT_REQUEST),
                str(database),
                "--registry",
                str(MANIFEST),
                "--authorization-event-id",
                event_id,
                "--authorization-sequence",
                sequence,
                "--format",
                "json",
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    assert output.err == ""
    receipt = json.loads(output.out)
    assert receipt["disposition"] == "succeeded"
    assert receipt["reasonCode"] == "native.process.ok"
    assert receipt["entrypointExecuted"] is False
    assert "example_native_worker:run" not in output.out
    assert (
        main(
            [
                "native",
                "run",
                str(SPEC),
                str(AUTHORIZATION_REQUEST),
                str(PREFLIGHT_REQUEST),
                str(database),
                "--registry",
                str(MANIFEST),
                "--authorization-event-id",
                event_id,
                "--authorization-sequence",
                sequence,
                "--transport",
                "ssh",
                "--format",
                "json",
            ]
        )
        == 2
    )
    refused = capsys.readouterr()
    assert refused.out == ""
    assert "ssh-transport-not-implemented" in refused.err


def test_native_run_cli_missing_citation_is_input_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _registry, report, authorization_policy, _ = _case()
    database = tmp_path / "native-missing.db"
    with EventStore(database) as store:
        _record_native_auth(store, report, authorization_policy)
    assert (
        main(
            [
                "native",
                "run",
                str(SPEC),
                str(AUTHORIZATION_REQUEST),
                str(PREFLIGHT_REQUEST),
                str(database),
                "--registry",
                str(MANIFEST),
                "--authorization-event-id",
                "evt.missing",
                "--authorization-sequence",
                "1",
                "--format",
                "json",
            ]
        )
        == 2
    )
    output = capsys.readouterr()
    assert output.out == ""
    assert "authorization-event-not-found" in output.err


def test_cancel_unobserved_when_process_group_still_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, report, authorization_policy, policy = _case()
    monkeypatch.setattr(runtime_module, "_HELPER_SCRIPT", "import time\ntime.sleep(30)\n")
    monkeypatch.setattr(runtime_module, "_process_group_alive", lambda pgid: True)

    def reap_without_confirming(
        process: subprocess.Popen[bytes],
        pgid: int | None,
        *,
        grace_seconds: float = 0,
    ) -> None:
        # Simulate main appearing reaped while the group stays alive.
        if process.poll() is None:
            process.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=2)

    monkeypatch.setattr(runtime_module, "_reap_process_group", reap_without_confirming)
    with EventStore(tmp_path / "events.db") as store:
        stored = _record_native_auth(store, report, authorization_policy)
        result = execute_native_process(
            store,
            report,
            registry,
            authorization_policy,
            policy,
            authorization_event_id=stored.event.id,
            authorization_sequence=stored.event.sequence,
            project_id=PROJECT,
            should_cancel=lambda: True,
        )
    assert result.disposition is NativeProcessDisposition.UNKNOWN
    assert result.reason_code == "execution-unobserved"
    assert result.observation == "unknown"


def test_wall_timeout_sends_sigterm_before_sigkill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, report, authorization_policy, policy = _case(
        limits=NativeProcessLimits(
            wall_time_seconds=1,
            stdout_bytes=65_536,
            stderr_bytes=65_536,
            termination_grace_seconds=5,
        )
    )
    # Ignore SIGTERM so grace must escalate to SIGKILL.
    monkeypatch.setattr(
        runtime_module,
        "_HELPER_SCRIPT",
        "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(30)\n",
    )
    signals: list[int] = []
    real_killpg = os.killpg

    def spy_killpg(pgid: int, sig: int) -> None:
        if sig != 0:
            signals.append(sig)
        real_killpg(pgid, sig)

    monkeypatch.setattr(os, "killpg", spy_killpg)
    with EventStore(tmp_path / "events.db") as store:
        stored = _record_native_auth(store, report, authorization_policy)
        result = _run(store, report, registry, authorization_policy, policy, stored)
    assert result.disposition is NativeProcessDisposition.UNKNOWN
    assert result.reason_code == "native.process.timeout"
    assert signals, "expected process-group signals"
    assert signals[0] == signal.SIGTERM
    assert signal.SIGKILL in signals
    assert signals.index(signal.SIGTERM) < signals.index(signal.SIGKILL)


def test_cancel_with_grace_sends_sigterm_before_sigkill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, report, authorization_policy, policy = _case(
        limits=NativeProcessLimits(
            wall_time_seconds=10,
            stdout_bytes=65_536,
            stderr_bytes=65_536,
            termination_grace_seconds=1,
        )
    )
    # Ignore SIGTERM so grace must escalate to SIGKILL, same as timeout.
    monkeypatch.setattr(
        runtime_module,
        "_HELPER_SCRIPT",
        "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(30)\n",
    )
    signals: list[int] = []
    real_killpg = os.killpg

    def spy_killpg(pgid: int, sig: int) -> None:
        if sig != 0:
            signals.append(sig)
        real_killpg(pgid, sig)

    monkeypatch.setattr(os, "killpg", spy_killpg)
    with EventStore(tmp_path / "events.db") as store:
        stored = _record_native_auth(store, report, authorization_policy)
        result = execute_native_process(
            store,
            report,
            registry,
            authorization_policy,
            policy,
            authorization_event_id=stored.event.id,
            authorization_sequence=stored.event.sequence,
            project_id=PROJECT,
            should_cancel=lambda: True,
        )
    assert result.disposition is NativeProcessDisposition.FAILED
    assert result.reason_code == "cancel-observed"
    assert signals, "expected process-group signals"
    assert signals[0] == signal.SIGTERM
    assert signal.SIGKILL in signals
    assert signals.index(signal.SIGTERM) < signals.index(signal.SIGKILL)


def test_reap_process_group_grace_zero_is_immediate_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signals: list[int] = []

    class FakeProcess:
        def __init__(self) -> None:
            self._alive = True
            self.pid = 4242

        def poll(self) -> int | None:
            return None if self._alive else 0

        def kill(self) -> None:
            self._alive = False

        def wait(self, timeout: float | None = None) -> int:
            self._alive = False
            return 0

    fake = FakeProcess()
    monkeypatch.setattr(runtime_module, "_process_group", lambda process: 9999)
    monkeypatch.setattr(runtime_module.os, "getpgid", lambda pid: 1 if pid == 0 else 9999)

    def fake_killpg(pgid: int, sig: int) -> None:
        if sig == 0:
            if fake._alive:
                return
            raise ProcessLookupError
        signals.append(sig)
        if sig == signal.SIGKILL:
            fake._alive = False

    monkeypatch.setattr(runtime_module.os, "killpg", fake_killpg)
    monkeypatch.setattr(runtime_module.os, "name", "posix")
    runtime_module._reap_process_group(fake, 9999, grace_seconds=0)  # type: ignore[arg-type]
    assert signals == [signal.SIGKILL]
