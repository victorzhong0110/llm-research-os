"""R14: extension mechanism and permission boundary.

The boundary being proven: a manifest is data, a declared permission is a
request, an adapter runs under bounds, and none of it grants authority. A crash
or a hang must not damage the control plane, and an extension that asks for
something this host never grants must be refused rather than narrowed.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from llm_research_os.extensions import (
    KNOWN_PERMISSIONS,
    NEVER_GRANTED,
    ExtensionError,
    ExtensionRegistry,
    RegistryError,
    load_manifest,
    parse_manifest,
    run_adapter,
)

MANIFEST_API = "researchos.dev/extension/v0alpha1"


def _manifest(
    *,
    extension_id: str = "ext.readout",
    version: str = "1.0.0",
    contract: str = "v0alpha1",
    permissions: tuple[str, ...] = (),
    entry_module: str | None = None,
    diagnostics: dict[str, str] | None = None,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "apiVersion": MANIFEST_API,
        "kind": "Extension",
        "id": extension_id,
        "version": version,
        "contractVersion": contract,
        "permissions": list(permissions),
        "diagnostics": diagnostics or {},
    }
    if entry_module is not None:
        document["entryModule"] = entry_module
    return document


def _write(tmp_path: Path, document: dict[str, Any], name: str = "ext.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


# --- Loading a manifest is inert ---------------------------------------------


def test_manifest_load_executes_nothing(tmp_path: Path) -> None:
    """A manifest is data. Loading it must not import, evaluate or execute it.

    The entry module writes a marker file if it is ever run. Loading the
    manifest must not create it.
    """

    marker = tmp_path / "EXECUTED"
    entry = f"open({str(marker)!r}, 'w').write('ran'); print('ran')"
    path = _write(tmp_path, _manifest(entry_module=entry))
    manifest = load_manifest(path)
    assert manifest.entry_module == entry
    assert not marker.exists(), "loading a manifest must not run its entry module"


def test_manifest_is_refused_without_being_executed(tmp_path: Path) -> None:
    marker = tmp_path / "EXECUTED"
    entry = f"open({str(marker)!r}, 'w').write('ran')"
    # A never-granted permission: refused, and still nothing is run.
    path = _write(tmp_path, _manifest(permissions=("execution.launch",), entry_module=entry))
    with pytest.raises(ExtensionError) as caught:
        load_manifest(path)
    assert caught.value.code == "permission-never-granted"
    assert not marker.exists()


def test_unknown_permission_is_refused_not_narrowed() -> None:
    with pytest.raises(ExtensionError) as caught:
        parse_manifest(_manifest(permissions=("some.unknown.permission",)))
    assert caught.value.code == "permission-unknown"


def test_every_never_granted_permission_is_refused() -> None:
    for name in sorted(NEVER_GRANTED):
        with pytest.raises(ExtensionError) as caught:
            parse_manifest(_manifest(permissions=(name,)))
        assert caught.value.code in {"permission-never-granted", "permission-unknown"}, name


def test_grantable_permissions_survive_and_are_reported() -> None:
    grantable = tuple(sorted(KNOWN_PERMISSIONS))
    manifest = parse_manifest(_manifest(permissions=grantable))
    assert manifest.granted_permissions() == ()
    document = manifest.public_document()
    assert document["compatiblePermissions"] == list(grantable)
    assert document["grantedPermissions"] == []
    assert document["refusedPermissions"] == []


def test_incompatible_contract_is_refused() -> None:
    with pytest.raises(ExtensionError) as caught:
        parse_manifest(_manifest(contract="v0beta1"))
    assert caught.value.code == "contract-incompatible"


def test_unknown_api_or_kind_is_refused() -> None:
    with pytest.raises(ExtensionError, match="apiVersion"):
        parse_manifest({**_manifest(), "apiVersion": "researchos.dev/extension/v9"})
    with pytest.raises(ExtensionError, match="kind"):
        parse_manifest({**_manifest(), "kind": "Plugin"})


def test_symlinked_manifest_is_refused(tmp_path: Path) -> None:
    """O_NOFOLLOW: a manifest reached through a symlink is not this surface's input."""

    real = _write(tmp_path, _manifest(), name="real.json")
    link = tmp_path / "link.json"
    link.symlink_to(real)
    with pytest.raises(ExtensionError) as caught:
        load_manifest(link)
    assert caught.value.code == "manifest-unreadable"


def test_oversized_manifest_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "big.json"
    padding = "x" * 300_000
    path.write_text(json.dumps({**_manifest(), "padding": padding}), encoding="utf-8")
    with pytest.raises(ExtensionError) as caught:
        load_manifest(path)
    assert caught.value.code == "manifest-too-large"


def test_malformed_manifest_json_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ExtensionError) as caught:
        load_manifest(path)
    assert caught.value.code == "manifest-invalid"


def test_manifest_digest_is_stable_and_content_derived() -> None:
    first = parse_manifest(_manifest())
    second = parse_manifest(_manifest())
    changed = parse_manifest(_manifest(permissions=("events.read",)))
    assert first.digest == second.digest
    assert first.digest != changed.digest


# --- The adapter runs under bounds --------------------------------------------


def test_adapter_receives_the_request_and_answers() -> None:
    entry = "import json,sys; r=json.load(sys.stdin); print(r['echo'])"
    manifest = parse_manifest(_manifest(entry_module=entry))
    result = run_adapter(manifest, {"echo": "hello-adapter"})
    assert result.outcome == "ok"
    assert result.exit_code == 0
    assert "hello-adapter" in result.stdout


def test_adapter_crash_is_contained() -> None:
    entry = "raise SystemExit(3)"
    manifest = parse_manifest(_manifest(entry_module=entry))
    result = run_adapter(manifest, {})
    assert result.outcome == "error"
    assert result.exit_code == 3
    assert result.timed_out is False


def test_adapter_hang_is_bounded() -> None:
    entry = "import time; time.sleep(30)"
    manifest = parse_manifest(_manifest(entry_module=entry))
    result = run_adapter(manifest, {}, timeout=0.5)
    assert result.outcome == "timeout"
    assert result.timed_out is True


def test_adapter_output_is_bounded_and_reported() -> None:
    entry = "print('y' * 400000)"
    manifest = parse_manifest(_manifest(entry_module=entry))
    result = run_adapter(manifest, {})
    assert result.outcome == "error"
    document = result.public_document()
    assert document["outputLimitExceeded"] is True
    # Clipping is visible in the byte count, so a truncated stream is not silent.
    assert document["stdoutBytes"] <= 262_144
    assert document["stdout"] != "y" * 400000


def test_adapter_message_size_is_bounded() -> None:
    manifest = parse_manifest(_manifest(entry_module="print('ok')"))
    with pytest.raises(ExtensionError) as caught:
        run_adapter(manifest, {"payload": "z" * 100_000})
    assert caught.value.code == "message-too-large"


def test_adapter_receives_no_control_plane_or_credential_environment() -> None:
    """The child must not inherit a control store, a grant or an HMAC key."""

    entry = "import os,json; print(json.dumps(sorted(os.environ)))"
    manifest = parse_manifest(_manifest(entry_module=entry))
    os.environ["RESEARCHOS_TEST_SECRET"] = "must-not-leak"
    try:
        result = run_adapter(manifest, {})
    finally:
        del os.environ["RESEARCHOS_TEST_SECRET"]
    assert result.outcome == "ok"
    names = json.loads(result.stdout.strip())
    # The operator's environment does not cross the boundary. An exact set is
    # not asserted because a platform may inject its own variables; what matters
    # is that nothing of the caller's is inherited and the child's own identity
    # is present.
    assert "RESEARCHOS_TEST_SECRET" not in names
    for leaked in ("HOME", "USER", "SSH_AUTH_SOCK", "GITHUB_TOKEN", "OPENAI_API_KEY"):
        assert leaked not in names, leaked
    assert {
        "PATH",
        "LANG",
        "PYTHONHASHSEED",
        "PYTHONDONTWRITEBYTECODE",
        "RESEARCHOS_EXTENSION_ID",
        "RESEARCHOS_EXTENSION_VERSION",
        "RESEARCHOS_EXTENSION_CONTRACT",
    } <= set(names)


def test_extension_without_an_entry_module_cannot_run() -> None:
    manifest = parse_manifest(_manifest())
    with pytest.raises(ExtensionError) as caught:
        run_adapter(manifest, {})
    assert caught.value.code == "no-entry-module"


def test_invalid_timeout_is_refused() -> None:
    manifest = parse_manifest(_manifest(entry_module="print('ok')"))
    with pytest.raises(ExtensionError) as caught:
        run_adapter(manifest, {}, timeout=0)
    assert caught.value.code == "timeout-invalid"


# --- Registry lifecycle -------------------------------------------------------


def test_install_resolve_disable_and_uninstall(tmp_path: Path) -> None:
    registry = ExtensionRegistry()
    path = _write(tmp_path, _manifest(permissions=("events.read",)))
    installed = registry.install(path, trust="inert")
    assert installed.manifest.granted_permissions() == ()
    assert registry.resolve("ext.readout", "1.0.0").enabled is True

    disabled = registry.disable("ext.readout", "1.0.0")
    assert disabled.enabled is False
    with pytest.raises(RegistryError, match="disabled"):
        registry.resolve("ext.readout", "1.0.0")

    registry.enable("ext.readout", "1.0.0")
    assert registry.resolve("ext.readout", "1.0.0").enabled is True

    registry.uninstall("ext.readout", "1.0.0")
    with pytest.raises(RegistryError, match="not installed"):
        registry.resolve("ext.readout", "1.0.0")


def test_uninstall_does_not_delete_the_operator_file(tmp_path: Path) -> None:
    """This surface removes its registry entry, not a file it did not create."""

    registry = ExtensionRegistry()
    path = _write(tmp_path, _manifest())
    registry.install(path)
    registry.uninstall("ext.readout", "1.0.0")
    assert path.exists(), "uninstall must not delete the operator's manifest file"


def test_duplicate_install_is_refused(tmp_path: Path) -> None:
    registry = ExtensionRegistry()
    path = _write(tmp_path, _manifest())
    registry.install(path)
    with pytest.raises(RegistryError, match="already installed"):
        registry.install(path)


def test_untrusted_trust_level_is_refused_with_a_reason(tmp_path: Path) -> None:
    """No verified isolation profile exists, so untrusted code is not admitted."""

    registry = ExtensionRegistry()
    path = _write(tmp_path, _manifest())
    with pytest.raises(RegistryError) as caught:
        registry.install(path, trust="untrusted")
    assert caught.value.code == "trust-unsupported"


def test_registry_limit_is_enforced(tmp_path: Path) -> None:
    registry = ExtensionRegistry(maximum=2)
    for index in range(2):
        registry.install(_write(tmp_path, _manifest(extension_id=f"ext.{index}"), f"e{index}.json"))
    with pytest.raises(RegistryError) as caught:
        registry.install(_write(tmp_path, _manifest(extension_id="ext.overflow"), "over.json"))
    assert caught.value.code == "registry-full"


def test_capability_surface_states_the_boundary_honestly() -> None:
    surface = ExtensionRegistry().capability_surface()
    assert surface["isolationProfile"].startswith("none")
    assert "not a sandbox" in surface["note"]
    # The surface reports the limits this platform actually applies, which is
    # narrower than the set the host asks for. Reporting the requested set
    # would claim a bound macOS does not enforce.
    from llm_research_os.extensions.manifest import _LIMITS, effective_limits

    assert set(surface["effectiveResourceLimits"]) <= {name for name, _a, _v in _LIMITS}
    assert set(surface["effectiveResourceLimits"]) == set(effective_limits())
    assert set(surface["neverGrantedPermissions"]) == set(NEVER_GRANTED)
    assert set(surface["grantablePermissions"]) == set(KNOWN_PERMISSIONS)


def test_registry_digest_binds_the_enabled_set(tmp_path: Path) -> None:
    registry = ExtensionRegistry()
    before = registry.digest()
    registry.install(_write(tmp_path, _manifest()))
    after = registry.digest()
    assert before != after, "enabling an extension must change the set identity"
    registry.disable("ext.readout", "1.0.0")
    assert registry.digest() != after


def test_a_crashing_extension_does_not_disturb_the_registry(tmp_path: Path) -> None:
    """The boundary the plan names: a crash cannot corrupt the control plane."""

    registry = ExtensionRegistry()
    good = _write(tmp_path, _manifest(extension_id="ext.good"), "good.json")
    bad = _write(
        tmp_path,
        _manifest(extension_id="ext.bad", entry_module="raise SystemExit(9)"),
        "bad.json",
    )
    registry.install(good)
    registry.install(bad)
    result = run_adapter(registry.resolve("ext.bad", "1.0.0").manifest, {})
    assert result.outcome == "error"
    # The registry is intact and the healthy extension still resolves.
    assert registry.resolve("ext.good", "1.0.0").enabled is True
    assert len(registry.installed()) == 2
    assert sys.executable  # the parent process is still the same interpreter


def test_manifest_snapshots_do_not_alias_input_or_public_views() -> None:
    original = _manifest(permissions=("events.read",), diagnostics={"status": "reviewed"})
    manifest = parse_manifest(original)
    digest = manifest.digest
    original["permissions"].append("control.write")
    original["diagnostics"]["status"] = "changed"
    view = manifest.raw
    view["permissions"].append("execution.launch")
    manifest.diagnostics["status"] = "also changed"
    assert manifest.digest == digest
    assert manifest.permissions == ("events.read",)
    assert manifest.diagnostics == {"status": "reviewed"}


def test_fifo_manifest_is_refused_without_open_blocking(tmp_path: Path) -> None:
    import time

    path = tmp_path / "manifest.fifo"
    os.mkfifo(path)
    start = time.monotonic()
    with pytest.raises(ExtensionError, match="regular file"):
        load_manifest(path)
    assert time.monotonic() - start < 1


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_nonfinite_manifest_and_message_are_refused(value: float) -> None:
    with pytest.raises(ExtensionError, match="finite JSON"):
        parse_manifest({**_manifest(), "unknown": value})
    manifest = parse_manifest(_manifest(entry_module="print('ok')"))
    with pytest.raises(ExtensionError, match="finite bounded JSON"):
        run_adapter(manifest, {"value": value})


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), True, -1, 11])
def test_nonfinite_or_invalid_timeout_is_refused(timeout: float) -> None:
    with pytest.raises(ExtensionError) as caught:
        run_adapter(parse_manifest(_manifest(entry_module="print('ok')")), {}, timeout=timeout)
    assert caught.value.code == "timeout-invalid"


def test_unknown_trust_and_boolean_maximum_are_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, _manifest())
    with pytest.raises(RegistryError, match="no verified isolation"):
        ExtensionRegistry().install(path, trust="anything")  # type: ignore[arg-type]
    with pytest.raises(RegistryError, match="out of range"):
        ExtensionRegistry(maximum=True)


def test_registry_counts_and_digest_bind_trust(tmp_path: Path) -> None:
    path = _write(tmp_path, _manifest())
    inert, reviewed = ExtensionRegistry(), ExtensionRegistry()
    inert.install(path)
    reviewed.install(path, trust="reviewed-same-user")
    assert inert.digest() != reviewed.digest()
    inert.disable("ext.readout", "1.0.0")
    assert inert.capability_surface()["enabledCount"] == 0
    assert inert.capability_surface()["installedCount"] == 1


def test_endless_output_is_stopped_while_reading() -> None:
    import time

    entry = "import os\nwhile True: os.write(1, b'x' * 8192)"
    start = time.monotonic()
    result = run_adapter(parse_manifest(_manifest(entry_module=entry)), {}, timeout=5)
    assert result.outcome == "error" and result.output_limited and not result.timed_out
    assert len(result.stdout.encode()) <= 262144
    assert time.monotonic() - start < 3


def test_non_utf8_stderr_is_bounded_and_explicit() -> None:
    entry = "import os; os.write(2, b'\\xff' * 100000)"
    result = run_adapter(parse_manifest(_manifest(entry_module=entry)), {})
    assert result.output_limited and result.outcome == "error"
    assert result.public_document()["stderrBytes"] <= 65536


def test_descendant_holding_pipes_is_killed_with_owned_group(tmp_path: Path) -> None:
    import time

    marker = tmp_path / "descendant-survived"
    descendant = f"import time; time.sleep(0.8); open({str(marker)!r}, 'w').write('bad')"
    entry = (
        f"import subprocess,sys; subprocess.Popen([sys.executable, '-c', {descendant!r}]); "
        "print('parent', flush=True)"
    )
    result = run_adapter(parse_manifest(_manifest(entry_module=entry)), {}, timeout=0.2)
    assert result.timed_out and result.outcome == "timeout"
    time.sleep(0.9)
    assert not marker.exists()


def test_adapter_limits_are_measured_in_invoked_child() -> None:
    result = run_adapter(parse_manifest(_manifest(entry_module="print('ok')")), {})
    assert result.outcome == "ok"
    assert "cpuSeconds" in result.effective_resource_limits
    assert "openFiles" in result.effective_resource_limits


def test_spawn_error_is_structured() -> None:
    with pytest.raises(ExtensionError, match="could not be started") as caught:
        run_adapter(
            parse_manifest(_manifest(entry_module="print('ok')")), {}, python="/nonexistent-python"
        )
    assert caught.value.code == "adapter-unavailable"


def test_deep_manifest_is_refused_with_closed_error() -> None:
    value: Any = None
    for _ in range(70):
        value = [value]
    with pytest.raises(ExtensionError, match="bounded finite JSON"):
        parse_manifest({**_manifest(), "extra": value})


def test_registry_dispatch_requires_review_and_respects_disable(tmp_path: Path) -> None:
    path = _write(tmp_path, _manifest(entry_module="print('reviewed')"))
    registry = ExtensionRegistry()
    registry.install(path)
    with pytest.raises(RegistryError, match="inert declarations"):
        registry.run("ext.readout", "1.0.0", {})
    registry.uninstall("ext.readout", "1.0.0")
    registry.install(path, trust="reviewed-same-user")
    assert registry.run("ext.readout", "1.0.0", {}).outcome == "ok"
    registry.disable("ext.readout", "1.0.0")
    with pytest.raises(RegistryError, match="disabled"):
        registry.run("ext.readout", "1.0.0", {})


def test_all_extension_documents_match_registered_schema(tmp_path: Path) -> None:
    from jsonschema import Draft202012Validator

    from llm_research_os.extensions.schema import build_schema

    raw = _manifest(entry_module="print('schema')", permissions=("events.read",))
    manifest = parse_manifest(raw)
    registry = ExtensionRegistry()
    installed = registry.install(_write(tmp_path, raw), trust="reviewed-same-user")
    result = registry.run("ext.readout", "1.0.0", {})
    validator = Draft202012Validator(build_schema())
    for document in (
        raw,
        manifest.public_document(),
        installed.public_document(),
        result.public_document(),
        registry.capability_surface(),
    ):
        validator.validate(document)
