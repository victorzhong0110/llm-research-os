from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, NoReturn

import pytest
from test_native_process_runtime import (
    AUTHORIZATION_REQUEST,
    MANIFEST,
    PREFLIGHT_REQUEST,
    SPEC,
    _case,
    _record_native_auth,
    _run,
)

import llm_research_os.execution.native_identity as identity_module
import llm_research_os.execution.native_runtime as runtime_module
from llm_research_os.cli import main
from llm_research_os.execution import (
    NativeProcessDisposition,
    NativeProcessRuntimeError,
    execute_native_process,
    native_runtime_receipt,
    resolve_interpreter_identity,
)
from llm_research_os.storage import EventStore

PROFILE_V2 = "restricted-v0alpha2"


def test_v2_run_pins_interpreter_and_environment(tmp_path: Path) -> None:
    registry, report, authorization_policy, policy = _case()
    with EventStore(tmp_path / "events.db") as store:
        stored = _record_native_auth(store, report, authorization_policy)
        result = _run(
            store, report, registry, authorization_policy, policy, stored, profile=PROFILE_V2
        )
    assert result.disposition is NativeProcessDisposition.SUCCEEDED
    assert result.reason_code == "native.process.ok"
    assert result.profile == PROFILE_V2
    assert result.interpreter_pinned is True
    expected_identity = resolve_interpreter_identity()
    assert result.interpreter_digest == expected_identity.digest
    assert result.python_version == expected_identity.python_version
    assert result.environment_digest.startswith("jcs-sha256:")
    receipt = native_runtime_receipt(result)
    assert receipt["profile"] == PROFILE_V2
    assert receipt["interpreterPinned"] is True
    assert receipt["interpreterDigest"] == result.interpreter_digest
    assert receipt["environmentDigest"] == result.environment_digest


def test_v1_run_records_without_pinning(tmp_path: Path) -> None:
    registry, report, authorization_policy, policy = _case()
    with EventStore(tmp_path / "events.db") as store:
        stored = _record_native_auth(store, report, authorization_policy)
        result = _run(store, report, registry, authorization_policy, policy, stored)
    assert result.profile == "restricted-v0alpha1"
    assert result.interpreter_pinned is False
    assert result.interpreter_digest == resolve_interpreter_identity().digest
    receipt = native_runtime_receipt(result)
    assert receipt["interpreterPinned"] is False


def test_v2_interpreter_drift_refuses_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, report, authorization_policy, policy = _case()
    # First resolve pins the host interpreter; the second resolve observes a
    # different file, so v0alpha2 reverification must refuse before spawn.
    identities = iter([resolve_interpreter_identity(), resolve_interpreter_identity(__file__)])

    def fake_resolve(executable: str | None = None) -> Any:
        return next(identities)

    def tripwire(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError(f"spawn called: {args!r} {kwargs!r}")

    # Both resolution sites must observe the fake: _run_helper resolves once
    # and verify_interpreter_identity resolves again inside its own module.
    monkeypatch.setattr(runtime_module, "resolve_interpreter_identity", fake_resolve)
    monkeypatch.setattr(identity_module, "resolve_interpreter_identity", fake_resolve)
    monkeypatch.setattr(subprocess, "Popen", tripwire)
    with EventStore(tmp_path / "events.db") as store:
        stored = _record_native_auth(store, report, authorization_policy)
        with pytest.raises(NativeProcessRuntimeError, match="changed") as captured:
            _run(
                store,
                report,
                registry,
                authorization_policy,
                policy,
                stored,
                profile=PROFILE_V2,
            )
        assert captured.value.code == "native-interpreter-changed"
        assert store.last_sequence() == 1


def test_v1_drift_does_not_block_recorded_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, report, authorization_policy, policy = _case()
    identities = iter(
        [
            resolve_interpreter_identity(),
            resolve_interpreter_identity(__file__),
        ]
    )

    def fake_resolve(executable: str | None = None) -> Any:
        return next(identities)

    monkeypatch.setattr(runtime_module, "resolve_interpreter_identity", fake_resolve)
    with EventStore(tmp_path / "events.db") as store:
        stored = _record_native_auth(store, report, authorization_policy)
        result = _run(store, report, registry, authorization_policy, policy, stored)
    assert result.disposition is NativeProcessDisposition.SUCCEEDED
    assert result.interpreter_pinned is False


def test_unknown_profile_still_fails_closed(tmp_path: Path) -> None:
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
                project_id="example-native-process-preflight",
                profile="restricted-v0alpha3",
            )
        assert captured.value.code == "native-profile-invalid"


def test_v2_cli_run_succeeds_with_pinned_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _registry, report, authorization_policy, _ = _case()
    database = tmp_path / "native-v2.db"
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
                "--profile",
                PROFILE_V2,
                "--format",
                "json",
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    assert output.err == ""
    receipt = json.loads(output.out)
    assert receipt["profile"] == PROFILE_V2
    assert receipt["interpreterPinned"] is True
    assert receipt["interpreterDigest"].startswith("sha256:")
    assert receipt["environmentDigest"].startswith("jcs-sha256:")
