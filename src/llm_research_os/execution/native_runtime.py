"""Local restricted NativeProcessRuntime over a sealed preflight (M3 slice 1).

This module executes a fixed noop helper in a supervised host process after
recomputing the sealed preflight and consuming one local authorization fact.
It does not import the manifest entrypoint, enforce network denial, provide
OCI isolation, append lifecycle facts, or dial SSH. ``transport="ssh"`` is a
validated but unimplemented shape and always fails closed.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO

from llm_research_os.blocks.registry import BlockRegistry
from llm_research_os.canonical import content_digest
from llm_research_os.execution.authorization import (
    PlanAuthorizationPolicy,
    PlanAuthorizationResult,
    authorize_plan,
)
from llm_research_os.execution.consume import consume_local_authorization
from llm_research_os.execution.errors import (
    NativeProcessRuntimeError,
    PlanAuthorizationError,
    SimulationError,
)
from llm_research_os.execution.models import DryRunReport
from llm_research_os.execution.native_preflight import (
    NativeProcessPreflightPolicy,
    NativeProcessPreflightResult,
    preflight_native_process,
)
from llm_research_os.secrets.redaction import message_without_secrets
from llm_research_os.storage.store import EventStore

NATIVE_RUNTIME_PROFILE: str = "restricted-v0alpha1"
NATIVE_RUNTIME_TRANSPORT_LOCAL: str = "local"
NATIVE_RUNTIME_TRANSPORT_SSH: str = "ssh"
NATIVE_RUNTIME_ISOLATION: str = "process-group"
NATIVE_RUNTIME_NETWORK_ENFORCEMENT: str = "not-enforced"
NATIVE_RUNTIME_INTERPRETER: str = "host-recorded-not-pinned"

_PASSTHROUGH = ("PATH", "SYSTEMROOT", "WINDIR")
_READ_CHUNK = 4_096
_REAP_WAIT_SECONDS = 2
_CANCEL_POLL_SECONDS = 0.2
_MAX_DIAGNOSTICS_CHARS = 2_048
_HELPER_SCRIPT = (
    "import json,sys\n"
    "def main():\n"
    "    try:\n"
    "        raw=sys.stdin.read()\n"
    "    except Exception:\n"
    "        sys.stdout.write(json.dumps("
    '{"kind":"NativeProcessReport","status":"error"},sort_keys=True))\n'
    "        return 1\n"
    "    try:\n"
    "        doc=json.loads(raw) if raw else {}\n"
    "    except Exception:\n"
    "        sys.stdout.write(json.dumps("
    '{"kind":"NativeProcessReport","status":"error"},sort_keys=True))\n'
    "        return 1\n"
    '    if type(doc) is not dict or type(doc.get("preflightDigest")) is not str:\n'
    "        sys.stdout.write(json.dumps("
    '{"kind":"NativeProcessReport","status":"error"},sort_keys=True))\n'
    "        return 1\n"
    '    sys.stdout.write(json.dumps({"kind":"NativeProcessReport","status":"ok",'
    '"preflightDigest":doc["preflightDigest"]},sort_keys=True))\n'
    "    return 0\n"
    "raise SystemExit(main())\n"
)


class NativeProcessDisposition(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class NativeProcessRuntimeResult:
    """Bounded local execution receipt bound to one sealed preflight."""

    disposition: NativeProcessDisposition
    stdout: bytes
    result_digest: str | None
    reason_code: str
    diagnostics: str | None
    preflight_digest: str
    transport: str
    profile: str
    entrypoint_executed: bool
    isolation: str
    network_enforcement: str
    observation: str
    python_version: str


def execute_native_process(
    store: EventStore,
    report: DryRunReport,
    registry: BlockRegistry,
    authorization_policy: PlanAuthorizationPolicy,
    preflight_policy: NativeProcessPreflightPolicy,
    *,
    authorization_event_id: str,
    authorization_sequence: str,
    project_id: str,
    transport: str = NATIVE_RUNTIME_TRANSPORT_LOCAL,
    profile: str = NATIVE_RUNTIME_PROFILE,
    should_cancel: Callable[[], bool] | None = None,
) -> NativeProcessRuntimeResult:
    """Recompute preflight, consume local authorization, then run the helper.

    Fail closed before spawning on any binding, authorization, or transport
    error. ``transport="ssh"`` is validated past authorization and then
    refused without opening a socket. The manifest entrypoint is never
    imported; only the fixed noop helper runs.
    """

    _require_transport_shape(transport)
    _require_profile_shape(profile)
    if type(authorization_event_id) is not str or type(authorization_sequence) is not str:
        raise NativeProcessRuntimeError(
            "native runtime authorization citation is invalid",
            code="native-citation-invalid",
        )
    if type(project_id) is not str or project_id == "":
        raise NativeProcessRuntimeError(
            "native runtime project is invalid",
            code="native-project-invalid",
        )
    if should_cancel is not None and not callable(should_cancel):
        raise NativeProcessRuntimeError(
            "native runtime cancel probe is invalid",
            code="native-cancel-invalid",
        )
    preflight = preflight_native_process(report, registry, authorization_policy, preflight_policy)
    authorization = _require_authorized(report, authorization_policy)
    _consume_binding(
        store,
        report=report,
        authorization=authorization,
        event_id=authorization_event_id,
        sequence=authorization_sequence,
        project_id=project_id,
    )
    if transport == NATIVE_RUNTIME_TRANSPORT_SSH:
        raise NativeProcessRuntimeError(
            "ssh transport is not implemented in this slice",
            code="ssh-transport-not-implemented",
        )
    return _run_helper(preflight, should_cancel=should_cancel)


def native_runtime_receipt(result: NativeProcessRuntimeResult) -> dict[str, object]:
    """Return the digest-only CLI receipt for a runtime result."""

    return {
        "preflightDigest": result.preflight_digest,
        "disposition": result.disposition.value,
        "reasonCode": result.reason_code,
        "resultDigest": result.result_digest,
        "transport": result.transport,
        "profile": result.profile,
        "entrypointExecuted": result.entrypoint_executed,
        "isolation": result.isolation,
        "networkEnforcement": result.network_enforcement,
        "observation": result.observation,
        "pythonVersion": result.python_version,
        "stdoutBytes": len(result.stdout),
    }


def _require_transport_shape(transport: object) -> None:
    if type(transport) is not str:
        raise NativeProcessRuntimeError(
            "native runtime transport is invalid",
            code="native-transport-invalid",
        )
    if transport not in (NATIVE_RUNTIME_TRANSPORT_LOCAL, NATIVE_RUNTIME_TRANSPORT_SSH):
        raise NativeProcessRuntimeError(
            "native runtime transport is invalid",
            code="native-transport-invalid",
        )


def _require_profile_shape(profile: object) -> None:
    if type(profile) is not str or profile != NATIVE_RUNTIME_PROFILE:
        raise NativeProcessRuntimeError(
            "native runtime profile is invalid",
            code="native-profile-invalid",
        )


def _require_authorized(
    report: DryRunReport,
    policy: PlanAuthorizationPolicy,
) -> PlanAuthorizationResult:
    try:
        authorization = authorize_plan(report, policy)
    except PlanAuthorizationError:
        raise NativeProcessRuntimeError(
            "native runtime authorization failed",
            code="native-authorization-failed",
        ) from None
    if not authorization.authorized:
        raise NativeProcessRuntimeError(
            "native runtime requires an authorized exact plan",
            code="native-authorization-not-authorized",
        )
    return authorization


def _consume_binding(
    store: EventStore,
    *,
    report: DryRunReport,
    authorization: PlanAuthorizationResult,
    event_id: str,
    sequence: str,
    project_id: str,
) -> None:
    try:
        consume_local_authorization(
            store,
            event_id=event_id,
            sequence=sequence,
            report=report,
            authorization=authorization,
            project_id=project_id,
        )
    except SimulationError as exc:
        raise NativeProcessRuntimeError(str(exc), code=exc.code) from None


def _run_helper(
    preflight: NativeProcessPreflightResult,
    *,
    should_cancel: Callable[[], bool] | None,
) -> NativeProcessRuntimeResult:
    payload = json.dumps(
        {"preflightDigest": preflight.preflight_digest},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    workspace = Path(tempfile.mkdtemp(prefix="researchos-native-"))
    process: subprocess.Popen[bytes] | None = None
    pgid: int | None = None
    try:
        try:
            process = subprocess.Popen(  # noqa: S603
                [sys.executable, "-B", "-I", "-c", _HELPER_SCRIPT],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_runtime_env(workspace),
                cwd=workspace,
                close_fds=True,
                start_new_session=os.name == "posix",
            )
        except OSError:
            return _result(
                preflight,
                disposition=NativeProcessDisposition.UNKNOWN,
                stdout=b"",
                result_digest=None,
                reason_code="native.process.lost",
                diagnostics=None,
                observation="unknown",
            )
        pgid = _process_group(process)
        return _run_bounded(process, payload, preflight, pgid, should_cancel=should_cancel)
    finally:
        if process is not None:
            _reap_process_group(process, pgid)
        shutil.rmtree(workspace, ignore_errors=True)


def _run_bounded(
    process: subprocess.Popen[bytes],
    payload: bytes,
    preflight: NativeProcessPreflightResult,
    pgid: int | None,
    *,
    should_cancel: Callable[[], bool] | None,
) -> NativeProcessRuntimeResult:
    overflow = threading.Event()
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    try:
        if process.stdin is not None:
            process.stdin.write(payload)
            process.stdin.close()
    except OSError:
        _reap_process_group(process, pgid)
        return _result(
            preflight,
            disposition=NativeProcessDisposition.UNKNOWN,
            stdout=b"",
            result_digest=None,
            reason_code="native.process.lost",
            diagnostics=None,
            observation="unknown",
        )
    stdout_thread = threading.Thread(
        target=_read_bounded,
        args=(
            process.stdout,
            stdout_chunks,
            overflow,
            process,
            pgid,
            preflight.limits.stdout_bytes,
        ),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_read_bounded,
        args=(
            process.stderr,
            stderr_chunks,
            overflow,
            process,
            pgid,
            preflight.limits.stderr_bytes,
        ),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    timed_out = False
    cancelled = False
    if should_cancel is None:
        try:
            process.wait(timeout=preflight.limits.wall_time_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
    else:
        deadline = time.monotonic() + preflight.limits.wall_time_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            if should_cancel():
                cancelled = True
                break
            try:
                process.wait(timeout=min(_CANCEL_POLL_SECONDS, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
    if cancelled:
        return _finish_cancelled(process, pgid, preflight, stdout_thread, stderr_thread)
    _reap_process_group(process, pgid)
    stdout_thread.join(timeout=_REAP_WAIT_SECONDS)
    stderr_thread.join(timeout=_REAP_WAIT_SECONDS)
    stdout = b"".join(stdout_chunks)
    diagnostics = _redacted_diagnostics(stderr_chunks)
    if timed_out:
        return _result(
            preflight,
            disposition=NativeProcessDisposition.UNKNOWN,
            stdout=b"",
            result_digest=None,
            reason_code="native.process.timeout",
            diagnostics=diagnostics,
            observation="unknown",
        )
    if overflow.is_set():
        return _result(
            preflight,
            disposition=NativeProcessDisposition.FAILED,
            stdout=stdout,
            result_digest=None,
            reason_code="native.brick.output-too-large",
            diagnostics=diagnostics,
            observation="exited",
        )
    returncode = process.poll()
    if returncode is None or returncode < 0:
        return _result(
            preflight,
            disposition=NativeProcessDisposition.UNKNOWN,
            stdout=b"",
            result_digest=None,
            reason_code="native.process.lost",
            diagnostics=diagnostics,
            observation="unknown",
        )
    if returncode != 0:
        return _result(
            preflight,
            disposition=NativeProcessDisposition.FAILED,
            stdout=stdout,
            result_digest=None,
            reason_code="native.brick.failed",
            diagnostics=diagnostics,
            observation="exited",
        )
    return _parse_report(stdout, preflight, diagnostics)


def _finish_cancelled(
    process: subprocess.Popen[bytes],
    pgid: int | None,
    preflight: NativeProcessPreflightResult,
    stdout_thread: threading.Thread,
    stderr_thread: threading.Thread,
) -> NativeProcessRuntimeResult:
    _reap_process_group(process, pgid)
    stdout_thread.join(timeout=_REAP_WAIT_SECONDS)
    stderr_thread.join(timeout=_REAP_WAIT_SECONDS)
    if process.poll() is not None:
        return _result(
            preflight,
            disposition=NativeProcessDisposition.FAILED,
            stdout=b"",
            result_digest=None,
            reason_code="cancel-observed",
            diagnostics=None,
            observation="exited",
        )
    return _result(
        preflight,
        disposition=NativeProcessDisposition.UNKNOWN,
        stdout=b"",
        result_digest=None,
        reason_code="execution-unobserved",
        diagnostics=None,
        observation="unknown",
    )


def _parse_report(
    stdout: bytes,
    preflight: NativeProcessPreflightResult,
    diagnostics: str | None,
) -> NativeProcessRuntimeResult:
    try:
        document = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _result(
            preflight,
            disposition=NativeProcessDisposition.FAILED,
            stdout=stdout,
            result_digest=None,
            reason_code="native.brick.invalid-report",
            diagnostics=diagnostics,
            observation="exited",
        )
    if (
        type(document) is not dict
        or document.get("kind") != "NativeProcessReport"
        or document.get("status") != "ok"
        or document.get("preflightDigest") != preflight.preflight_digest
    ):
        return _result(
            preflight,
            disposition=NativeProcessDisposition.FAILED,
            stdout=stdout,
            result_digest=None,
            reason_code="native.brick.invalid-report",
            diagnostics=diagnostics,
            observation="exited",
        )
    return _result(
        preflight,
        disposition=NativeProcessDisposition.SUCCEEDED,
        stdout=stdout,
        result_digest=content_digest(document),
        reason_code="native.process.ok",
        diagnostics=diagnostics,
        observation="exited",
    )


def _result(
    preflight: NativeProcessPreflightResult,
    *,
    disposition: NativeProcessDisposition,
    stdout: bytes,
    result_digest: str | None,
    reason_code: str,
    diagnostics: str | None,
    observation: str,
) -> NativeProcessRuntimeResult:
    return NativeProcessRuntimeResult(
        disposition=disposition,
        stdout=stdout,
        result_digest=result_digest,
        reason_code=reason_code,
        diagnostics=diagnostics,
        preflight_digest=preflight.preflight_digest,
        transport=NATIVE_RUNTIME_TRANSPORT_LOCAL,
        profile=NATIVE_RUNTIME_PROFILE,
        entrypoint_executed=False,
        isolation=NATIVE_RUNTIME_ISOLATION,
        network_enforcement=NATIVE_RUNTIME_NETWORK_ENFORCEMENT,
        observation=observation,
        python_version=sys.version.split()[0],
    )


def _redacted_diagnostics(chunks: list[bytes]) -> str | None:
    if not chunks:
        return None
    text = b"".join(chunks).decode("utf-8", errors="replace")[:_MAX_DIAGNOSTICS_CHARS]
    if text == "":
        return None
    return message_without_secrets(text)


def _read_bounded(
    stream: BinaryIO | None,
    chunks: list[bytes],
    overflow: threading.Event,
    process: subprocess.Popen[bytes],
    pgid: int | None,
    cap_bytes: int,
) -> None:
    if stream is None:
        return
    total = 0
    try:
        while True:
            data = stream.read(_READ_CHUNK)
            if not data:
                break
            if overflow.is_set():
                continue
            if total + len(data) > cap_bytes:
                remain = cap_bytes - total
                if remain > 0:
                    chunks.append(data[:remain])
                overflow.set()
                _reap_process_group(process, pgid)
                break
            chunks.append(data)
            total += len(data)
    except OSError:
        return


def _process_group(process: subprocess.Popen[bytes]) -> int | None:
    if os.name != "posix" or process.pid is None:
        return None
    try:
        return os.getpgid(process.pid)
    except OSError:
        return process.pid


def _reap_process_group(process: subprocess.Popen[bytes], pgid: int | None) -> None:
    target = pgid
    if target is None:
        target = _process_group(process)
    caller_pgid: int | None = None
    if os.name == "posix":
        with contextlib.suppress(OSError):
            caller_pgid = os.getpgid(0)
    # A child without start_new_session shares the caller's group; killpg
    # would SIGKILL the test runner and leave CI hanging until the cap.
    if os.name == "posix" and target is not None and target != caller_pgid:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(target, signal.SIGKILL)
    elif process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=_REAP_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            process.kill()


def _runtime_env(workspace: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for key in _PASSTHROUGH:
        value = os.environ.get(key)
        if type(value) is str and value != "":
            env[key] = value
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env["HOME"] = str(workspace)
    env["TMPDIR"] = str(workspace)
    return env
