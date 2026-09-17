"""Pinned interpreter and environment identity for native profiles (M3 slice 2).

Slice 1 records the host interpreter by version only
(``host-recorded-not-pinned``). This module adds a content-bound identity:
the interpreter binary is resolved and digested, and the exact spawn
environment is digested, before any child process starts. Digests bind one
spawn; they are not a sandbox and they do not authorize anything by
themselves. Error messages never carry interpreter or host paths.
"""

from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from llm_research_os.canonical import content_digest
from llm_research_os.execution.errors import NativeProcessRuntimeError

NATIVE_RUNTIME_PROFILE_V1: str = "restricted-v0alpha1"
NATIVE_RUNTIME_PROFILE_V2: str = "restricted-v0alpha2"
NATIVE_RUNTIME_PROFILES: tuple[str, ...] = (
    NATIVE_RUNTIME_PROFILE_V1,
    NATIVE_RUNTIME_PROFILE_V2,
)
NATIVE_RUNTIME_INTERPRETER_RECORDED: str = "host-recorded-not-pinned"
NATIVE_RUNTIME_INTERPRETER_PINNED: str = "pinned-reverified"

_INTERPRETER_DIGEST_DOMAIN = b"researchos-native-interpreter-v1\x00"


@dataclass(frozen=True, slots=True)
class NativeInterpreterIdentity:
    """Content-bound identity of one interpreter binary, without paths."""

    python_version: str
    digest: str


def is_native_runtime_profile(profile: object) -> bool:
    """Return True for an executable local profile name (exact match only)."""

    return type(profile) is str and profile in NATIVE_RUNTIME_PROFILES


def resolve_interpreter_identity(executable: str | None = None) -> NativeInterpreterIdentity:
    """Digest the interpreter binary for this spawn, failing closed.

    Args:
        executable: explicit binary to digest; ``None`` resolves the host
            ``sys.executable``. The parameter exists so tests can pin a
            fixture binary without touching process-global state.
    """

    candidate = executable if executable is not None else sys.executable
    if type(candidate) is not str or candidate == "":
        raise NativeProcessRuntimeError(
            "native runtime interpreter is not pinned",
            code="native-interpreter-unpinned",
        )
    try:
        realpath = os.path.realpath(candidate)
        raw = _interpreter_bytes(realpath)
    except OSError:
        raise NativeProcessRuntimeError(
            "native runtime interpreter is not pinned",
            code="native-interpreter-unpinned",
        ) from None
    if not raw:
        raise NativeProcessRuntimeError(
            "native runtime interpreter is not pinned",
            code="native-interpreter-unpinned",
        )
    version = sys.version.split()[0]
    fingerprint = hashlib.sha256(
        _INTERPRETER_DIGEST_DOMAIN
        + realpath.encode("utf-8")
        + b"\x00"
        + version.encode("utf-8")
        + b"\x00"
        + raw
    ).hexdigest()
    return NativeInterpreterIdentity(python_version=version, digest=f"sha256:{fingerprint}")


def verify_interpreter_identity(
    expected: NativeInterpreterIdentity,
) -> NativeInterpreterIdentity:
    """Re-resolve the interpreter and refuse on any drift before spawn."""

    if type(expected) is not NativeInterpreterIdentity:
        raise NativeProcessRuntimeError(
            "native runtime interpreter is not pinned",
            code="native-interpreter-unpinned",
        )
    actual = resolve_interpreter_identity()
    if actual != expected:
        raise NativeProcessRuntimeError(
            "native runtime interpreter changed before spawn",
            code="native-interpreter-changed",
        )
    return actual


def environment_identity(env: dict[str, str]) -> str:
    """Digest the exact spawn environment mapping (sorted JCS SHA-256)."""

    if type(env) is not dict or not env:
        raise NativeProcessRuntimeError(
            "native runtime environment is not pinned",
            code="native-environment-unpinned",
        )
    for key, value in env.items():
        if type(key) is not str or type(value) is not str:
            raise NativeProcessRuntimeError(
                "native runtime environment is not pinned",
                code="native-environment-unpinned",
            )
    return content_digest(env)


def _interpreter_bytes(realpath: str) -> bytes:
    """Read one interpreter binary (small seam so tests can fault reads)."""

    return Path(realpath).read_bytes()
