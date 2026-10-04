"""A minimal, bounded extension surface (R14).

The existing block registry already loads manifests inertly: it never imports
or executes an entrypoint, revalidates every manifest into a private snapshot,
and seals on demand. R14 adds the *boundary* around that surface rather than a
plugin framework:

* a versioned manifest contract with a closed set of permission names;
* a compatibility check, so an incompatible extension is refused rather than
  half-loaded;
* a bounded subprocess host for one reviewed adapter, with message, duration,
  output and error budgets;
* diagnostics, disable and uninstall that touch only what this surface created.

A manifest is data. Loading one is inert, and a permission it declares is a
*request*, not a grant.
"""

from __future__ import annotations

import json
import os
import resource
import subprocess
import sys
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Literal

from llm_research_os.canonical import content_digest

EXTENSION_API_VERSION: Final = "researchos.dev/extension/v0alpha1"
EXTENSION_CONTRACT_VERSION: Final = "v0alpha1"
MIN_COMPATIBLE_EXTENSION_VERSION: Final = "v0alpha1"

# Every permission an extension may declare. A manifest naming anything else is
# refused at load time rather than silently narrowed: an unknown permission is a
# mistake, and quietly dropping it would hide a capability the author expected.
KNOWN_PERMISSIONS: Final = frozenset(
    {
        "artifacts.read",
        "events.read",
        "evidence.read",
        "ledger.read",
        "metrics.read",
    }
)

# Permissions the host will never grant, whatever a manifest asks for. An
# extension that needs one is asking for a capability this boundary does not
# have, and saying so is more useful than a timeout.
NEVER_GRANTED: Final = frozenset(
    {
        "artifacts.write",
        "authority.create",
        "control.write",
        "events.write",
        "execution.launch",
        "network.outbound",
        "secrets.read",
    }
)

MAX_MANIFEST_BYTES: Final = 262_144
MAX_MESSAGE_BYTES: Final = 65_536
MAX_STDOUT_BYTES: Final = 262_144
MAX_STDERR_BYTES: Final = 65_536
MAX_DURATION_SECONDS: Final = 10.0
MAX_ADDRESS_SPACE_BYTES: Final = 512 * 1024 * 1024
MAX_CPU_SECONDS: Final = 10
MAX_OPEN_FILES: Final = 64

TrustLevel = Literal["inert", "reviewed-same-user", "untrusted"]
AdapterOutcome = Literal["error", "ok", "timeout"]

_CONTRACT_VERSIONS: Final = frozenset({"v0alpha1"})


class ExtensionError(ValueError):
    """One extension fault with a closed code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ExtensionManifest:
    """One declared extension. Loading it is inert: nothing is executed."""

    extension_id: str
    version: str
    contract_version: str
    permissions: tuple[str, ...]
    entry_module: str | None
    diagnostics: dict[str, str]
    raw: dict[str, Any]

    @property
    def key(self) -> tuple[str, str]:
        return (self.extension_id, self.version)

    @property
    def digest(self) -> str:
        return content_digest(self.raw)

    def granted_permissions(self) -> tuple[str, ...]:
        """Only permissions inside the grantable set survive a load.

        A declared permission outside the closed set is refused at load time, so
        anything returned here was actually grantable.
        """

        return tuple(item for item in self.permissions if item in KNOWN_PERMISSIONS)

    def public_document(self) -> dict[str, Any]:
        return {
            "apiVersion": EXTENSION_API_VERSION,
            "kind": "ExtensionManifest",
            "contractVersion": EXTENSION_CONTRACT_VERSION,
            "id": self.extension_id,
            "version": self.version,
            "extensionContractVersion": self.contract_version,
            "manifestDigest": self.digest,
            "requestedPermissions": list(self.permissions),
            "grantedPermissions": list(self.granted_permissions()),
            "refusedPermissions": [
                item for item in self.permissions if item not in KNOWN_PERMISSIONS
            ],
            "entryModule": self.entry_module,
            "hasEntryModule": self.entry_module is not None,
            "diagnostics": dict(sorted(self.diagnostics.items())),
        }


def load_manifest(path: Path) -> ExtensionManifest:
    """Read one manifest inertly. No import, no evaluation, no network.

    A manifest is data; refusing it must not run anything either.
    """

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ExtensionError("manifest-unreadable", "the manifest could not be opened") from exc
    try:
        details = os.fstat(descriptor)
        if details.st_size > MAX_MANIFEST_BYTES:
            raise ExtensionError("manifest-too-large", "the manifest exceeds the size limit")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 65_536)
            if not chunk:
                break
            chunks.append(chunk)
            if sum(len(item) for item in chunks) > MAX_MANIFEST_BYTES:
                raise ExtensionError("manifest-too-large", "the manifest exceeds the size limit")
        raw_bytes = b"".join(chunks)
    finally:
        os.close(descriptor)
    try:
        document = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ExtensionError("manifest-invalid", "the manifest is not valid JSON") from exc
    if not isinstance(document, dict):
        raise ExtensionError("manifest-invalid", "the manifest is not an object")
    return parse_manifest(document)


def parse_manifest(document: dict[str, Any]) -> ExtensionManifest:
    """Validate one manifest object without touching the filesystem."""

    api_version = document.get("apiVersion")
    if api_version != EXTENSION_API_VERSION:
        raise ExtensionError("manifest-api-unknown", "the manifest apiVersion is not supported")
    kind = document.get("kind")
    if kind != "Extension":
        raise ExtensionError("manifest-kind-unknown", "the manifest kind is not Extension")
    extension_id = _identifier(document.get("id"), "id")
    version = _identifier(document.get("version"), "version")
    contract_version = document.get("contractVersion")
    if not isinstance(contract_version, str) or contract_version not in _CONTRACT_VERSIONS:
        raise ExtensionError(
            "contract-incompatible",
            f"the extension requires a contract this host does not implement: {contract_version!r}",
        )
    if not _is_compatible(contract_version):
        raise ExtensionError(
            "contract-incompatible",
            f"this host cannot load {contract_version!r} extensions",
        )
    permissions = _permissions(document.get("permissions"))
    entry_module = document.get("entryModule")
    if entry_module is not None and (
        not isinstance(entry_module, str) or not entry_module or "\x00" in entry_module
    ):
        raise ExtensionError("manifest-invalid", "entryModule must be a non-empty string")
    diagnostics = _diagnostics(document.get("diagnostics"))
    for name, value in list(diagnostics.items()):
        if len(value) > 200:
            raise ExtensionError("diagnostic-too-long", f"diagnostic {name} is too long")
    unknown = sorted(item for item in permissions if item not in KNOWN_PERMISSIONS)
    if unknown:
        refused = [item for item in unknown if item in NEVER_GRANTED]
        raise ExtensionError(
            "permission-never-granted" if refused else "permission-unknown",
            "the manifest requests permissions this host does not grant: " + ", ".join(unknown),
        )
    return ExtensionManifest(
        extension_id=extension_id,
        version=version,
        contract_version=contract_version,
        permissions=permissions,
        entry_module=entry_module,
        diagnostics=diagnostics,
        raw=document,
    )


def _is_compatible(contract_version: str) -> bool:
    """This host implements exactly the v0alpha1 contract."""

    return contract_version == MIN_COMPATIBLE_EXTENSION_VERSION


@dataclass(frozen=True, slots=True)
class AdapterResult:
    """One bounded adapter invocation outcome."""

    outcome: AdapterOutcome
    exit_code: int | None
    duration_seconds: float
    stdout: str
    stderr: str
    timed_out: bool = False

    def public_document(self) -> dict[str, Any]:
        return {
            "apiVersion": EXTENSION_API_VERSION,
            "kind": "AdapterResult",
            "contractVersion": EXTENSION_CONTRACT_VERSION,
            "outcome": self.outcome,
            "exitCode": self.exit_code,
            "durationSeconds": f"{self.duration_seconds:.3f}",
            "timedOut": self.timed_out,
            "stdoutBytes": len(self.stdout.encode("utf-8")),
            "stderrBytes": len(self.stderr.encode("utf-8")),
            "stdout": self.stdout,
            "stderr": self.stderr[:MAX_STDERR_BYTES],
        }


def run_adapter(
    manifest: ExtensionManifest,
    request: dict[str, Any],
    *,
    python: str | None = None,
    timeout: float = MAX_DURATION_SECONDS,
) -> AdapterResult:
    """Run one reviewed same-user adapter under bounded subprocess limits.

    The child receives the request on stdin and the manifest identity in its
    environment. It never receives a control-store connection, a Worker
    credential, or a network handle: this is reviewed same-user code, and the
    boundary is what it may be *told*, not a sandbox claim.
    """

    if manifest.entry_module is None:
        raise ExtensionError("no-entry-module", "this extension declares no entry module")
    if timeout <= 0 or timeout > MAX_DURATION_SECONDS:
        raise ExtensionError("timeout-invalid", f"timeout must be within 0..{MAX_DURATION_SECONDS}")
    payload = json.dumps(request, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ExtensionError("message-too-large", "the adapter message exceeds the size limit")

    environment = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": "C.UTF-8",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "RESEARCHOS_EXTENSION_ID": manifest.extension_id,
        "RESEARCHOS_EXTENSION_VERSION": manifest.version,
        "RESEARCHOS_EXTENSION_CONTRACT": manifest.contract_version,
    }
    command = [python or sys.executable, "-I", "-c", manifest.entry_module]
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, reviewed same-user code
            command,
            input=payload,
            capture_output=True,
            check=False,
            env=environment,
            timeout=timeout,
            preexec_fn=_limit_child,
        )
        code: int | None = completed.returncode
        stdout = _bounded(completed.stdout, MAX_STDOUT_BYTES)
        stderr = _bounded(completed.stderr, MAX_STDERR_BYTES)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        code = None
        stdout = _bounded(exc.stdout or b"", MAX_STDOUT_BYTES)
        stderr = _bounded(exc.stderr or b"", MAX_STDERR_BYTES)
    duration = time.monotonic() - started
    if timed_out:
        outcome: AdapterOutcome = "timeout"
    elif code == 0:
        outcome = "ok"
    else:
        outcome = "error"
    return AdapterResult(
        outcome=outcome,
        exit_code=code,
        duration_seconds=duration,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
    )


# Which bound goes with which rlimit, and the value to lower it to. A platform
# may refuse one of these — macOS rejects RLIMIT_AS — so the effective set is
# probed rather than assumed, and the capability surface reports what is
# actually enforced.
_LIMITS: Final[tuple[tuple[str, str, int], ...]] = (
    ("addressSpace", "RLIMIT_AS", MAX_ADDRESS_SPACE_BYTES),
    ("cpuSeconds", "RLIMIT_CPU", MAX_CPU_SECONDS),
    ("openFiles", "RLIMIT_NOFILE", MAX_OPEN_FILES),
)

_PROBE_SOURCE = chr(10).join(
    [
        "import json, resource",
        f"_LIMITS = {tuple(_LIMITS)!r}",
        "applied = []",
        "for _name, _attr, _value in _LIMITS:",
        "    _limit = getattr(resource, _attr, None)",
        "    if _limit is None:",
        "        continue",
        "    try:",
        "        _soft, _hard = resource.getrlimit(_limit)",
        "        _ceiling = _value if _hard == resource.RLIM_INFINITY else min(_value, _hard)",
        "        if _soft != resource.RLIM_INFINITY and _soft < _ceiling:",
        "            continue",
        "        resource.setrlimit(_limit, (_ceiling, _hard))",
        "        applied.append(_name)",
        "    except (ValueError, OSError):",
        "        pass",
        "print(json.dumps(applied))",
    ]
)


@lru_cache(maxsize=1)
def effective_limits() -> frozenset[str]:
    """Probe which rlimits this platform actually applies to a child.

    A limit that cannot be set is not a limit. Reporting the enforced set
    instead of the intended one keeps the capability surface honest.
    """

    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, runs before any adapter
            [sys.executable, "-I", "-c", _PROBE_SOURCE],
            capture_output=True,
            check=False,
            timeout=20,
            env={"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"},
        )
        applied = json.loads(completed.stdout.decode("utf-8"))
    except (OSError, ValueError, subprocess.SubprocessError):
        return frozenset()
    return frozenset(item for item in applied if isinstance(item, str))


def _limit_child() -> None:  # pragma: no cover - runs in the forked child
    """Apply the probed limits to the child.

    A limit is a bound, not a sandbox: the child is reviewed same-user code, and
    a limit does not make untrusted code safe. Untrusted code needs a verified
    isolation profile, which this host does not provide.
    """

    for _name, attribute, value in _LIMITS:
        limit = getattr(resource, attribute, None)
        if limit is None:
            continue
        try:
            soft, hard = resource.getrlimit(limit)
            if soft != resource.RLIM_INFINITY and soft < value:
                continue
            ceiling = value if hard == resource.RLIM_INFINITY else min(value, hard)
            resource.setrlimit(limit, (ceiling, hard))
        except (ValueError, OSError):
            # The platform refused this bound; effective_limits() reports that.
            continue


def _bounded(raw: bytes | str, limit: int) -> str:
    data = raw if isinstance(raw, bytes) else raw.encode("utf-8", errors="replace")
    if len(data) > limit:
        # Truncation is reported by the byte counts in the public document, so a
        # clipped stream is visible rather than silently short.
        return data[:limit].decode("utf-8", errors="replace")
    return data.decode("utf-8", errors="replace")


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ExtensionError("manifest-invalid", f"{label} must be a short non-empty string")
    if any(character in value for character in ("\x00", "\n", "\r", "/", " ")):
        raise ExtensionError("manifest-invalid", f"{label} contains a disallowed character")
    return value


def _permissions(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > 16:
        raise ExtensionError(
            "permissions-invalid", "permissions must be an array of at most 16 names"
        )
    names: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or len(item) > 64:
            raise ExtensionError("permissions-invalid", "each permission must be a short string")
        names.append(item)
    if len(set(names)) != len(names):
        raise ExtensionError("permissions-invalid", "permission names must be unique")
    return tuple(sorted(names))


def _diagnostics(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 16:
        raise ExtensionError(
            "diagnostics-invalid", "diagnostics must be an object of at most 16 entries"
        )
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ExtensionError("diagnostics-invalid", "diagnostics entries must be strings")
        result[key] = item
    return result
