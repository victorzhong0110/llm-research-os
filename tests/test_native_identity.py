from __future__ import annotations

import sys
from pathlib import Path

import pytest

from llm_research_os.execution import (
    NativeProcessRuntimeError,
    environment_identity,
    is_native_runtime_profile,
    resolve_interpreter_identity,
    verify_interpreter_identity,
)
from llm_research_os.execution.native_identity import (
    NATIVE_RUNTIME_PROFILE_V1,
    NATIVE_RUNTIME_PROFILE_V2,
    NATIVE_RUNTIME_PROFILES,
    NativeInterpreterIdentity,
)


def test_profile_registry_accepts_both_restricted_profiles() -> None:
    assert NATIVE_RUNTIME_PROFILES == ("restricted-v0alpha1", "restricted-v0alpha2")
    assert NATIVE_RUNTIME_PROFILE_V1 == "restricted-v0alpha1"
    assert NATIVE_RUNTIME_PROFILE_V2 == "restricted-v0alpha2"
    assert is_native_runtime_profile("restricted-v0alpha1") is True
    assert is_native_runtime_profile("restricted-v0alpha2") is True
    for bad in ("", "default", "restricted", "restricted-v0alpha3", None, 123, True):
        assert is_native_runtime_profile(bad) is False


def test_resolve_is_deterministic_and_content_bound(tmp_path: Path) -> None:
    first = resolve_interpreter_identity()
    second = resolve_interpreter_identity()
    assert first == second
    assert first.python_version == sys.version.split()[0]
    assert first.digest.startswith("sha256:")
    assert len(first.digest) == len("sha256:") + 64
    fixture = tmp_path / "python-fixture"
    fixture.write_bytes(b"fake-interpreter-bytes")
    other = resolve_interpreter_identity(str(fixture))
    assert other.digest != first.digest
    assert other.python_version == first.python_version


def test_resolve_missing_or_empty_binary_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(NativeProcessRuntimeError, match="not pinned") as captured:
        resolve_interpreter_identity(str(tmp_path / "does-not-exist"))
    assert captured.value.code == "native-interpreter-unpinned"
    empty = tmp_path / "empty-binary"
    empty.write_bytes(b"")
    with pytest.raises(NativeProcessRuntimeError, match="not pinned") as captured_empty:
        resolve_interpreter_identity(str(empty))
    assert captured_empty.value.code == "native-interpreter-unpinned"


def test_resolve_rejects_empty_or_non_string_executable() -> None:
    for bad in ("", 123, True):
        with pytest.raises(NativeProcessRuntimeError, match="not pinned") as captured:
            resolve_interpreter_identity(bad)  # type: ignore[arg-type]
        assert captured.value.code == "native-interpreter-unpinned"
    assert resolve_interpreter_identity(None) == resolve_interpreter_identity()


def test_resolve_error_carries_no_paths() -> None:
    sentinel = "/secret-interpreter-path-xyz/binary"
    with pytest.raises(NativeProcessRuntimeError) as captured:
        resolve_interpreter_identity(sentinel)
    assert captured.value.code == "native-interpreter-unpinned"
    assert "secret-interpreter" not in str(captured.value)


def test_verify_accepts_same_and_refuses_drift(tmp_path: Path) -> None:
    identity = resolve_interpreter_identity()
    assert verify_interpreter_identity(identity) == identity
    fixture = tmp_path / "other-binary"
    fixture.write_bytes(b"other-bytes")
    foreign = resolve_interpreter_identity(str(fixture))
    assert foreign != identity
    drifted = NativeInterpreterIdentity(
        python_version=identity.python_version,
        digest=foreign.digest,
    )
    with pytest.raises(NativeProcessRuntimeError, match="changed") as captured:
        verify_interpreter_identity(drifted)
    assert captured.value.code == "native-interpreter-changed"


def test_verify_rejects_non_identity() -> None:
    with pytest.raises(NativeProcessRuntimeError, match="not pinned") as captured:
        verify_interpreter_identity("sha256:deadbeef")  # type: ignore[arg-type]
    assert captured.value.code == "native-interpreter-unpinned"


def test_environment_identity_is_deterministic_digest() -> None:
    env = {"HOME": "/tmp/x", "PATH": "/usr/bin", "PYTHONUTF8": "1"}
    first = environment_identity(dict(env))
    assert first == environment_identity(dict(env))
    assert first.startswith("jcs-sha256:")
    assert environment_identity({**env, "EXTRA": "1"}) != first


def test_environment_identity_refuses_empty_or_non_string() -> None:
    with pytest.raises(NativeProcessRuntimeError, match="not pinned") as captured:
        environment_identity({})
    assert captured.value.code == "native-environment-unpinned"
    with pytest.raises(NativeProcessRuntimeError, match="not pinned") as captured_two:
        environment_identity({"HOME": 123})  # type: ignore[dict-item]
    assert captured_two.value.code == "native-environment-unpinned"
