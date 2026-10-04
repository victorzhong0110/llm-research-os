"""Enable, disable, uninstall and diagnose extensions (R14).

The registry owns what is enabled. Disabling and uninstalling touch only what
this surface created, and an extension that was never enabled cannot be
"disabled" into a silent success.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from llm_research_os.extensions.manifest import (
    EXTENSION_API_VERSION,
    EXTENSION_CONTRACT_VERSION,
    KNOWN_PERMISSIONS,
    NEVER_GRANTED,
    AdapterResult,
    ExtensionError,
    ExtensionManifest,
    effective_limits,
    load_manifest,
    run_adapter,
)

MAX_ENABLED_EXTENSIONS = 32

TrustLevel = Literal["inert", "reviewed-same-user", "untrusted"]


class RegistryError(ExtensionError):
    """One registry fault with a closed code."""


@dataclass(frozen=True, slots=True)
class InstalledExtension:
    """One enabled extension and the trust level it was admitted at."""

    manifest: ExtensionManifest
    trust: TrustLevel
    origin: Path
    enabled: bool = True

    def public_document(self) -> dict[str, Any]:
        return {
            **self.manifest.public_document(),
            "kind": "InstalledExtension",
            "apiVersion": EXTENSION_API_VERSION,
            "contractVersion": EXTENSION_CONTRACT_VERSION,
            "trust": self.trust,
            "enabled": self.enabled,
            "originName": self.origin.name,
        }


class ExtensionRegistry:
    """A bounded, explicit set of enabled extensions.

    The registry grants nothing on load. A manifest's permissions are a request;
    supported permission names are checked at parse time; no capability handles
    are granted by installation.
    """

    def __init__(self, *, maximum: int = MAX_ENABLED_EXTENSIONS) -> None:
        if type(maximum) is not int or maximum < 1 or maximum > MAX_ENABLED_EXTENSIONS:
            raise RegistryError("maximum-invalid", "the extension limit is out of range")
        self._maximum = maximum
        self._installed: dict[tuple[str, str], InstalledExtension] = {}
        self._disabled: set[tuple[str, str]] = set()

    def install(self, path: Path, *, trust: TrustLevel = "inert") -> InstalledExtension:
        """Load one manifest inertly and record it as enabled.

        A manifest is never imported or evaluated here. An entry module is only
        ever run later, explicitly, through `run_adapter`.
        """

        if trust not in {"inert", "reviewed-same-user"}:
            # Untrusted code requires a verified isolation profile this host
            # does not implement. Saying so is better than a false sandbox.
            raise RegistryError(
                "trust-unsupported",
                "this host has no verified isolation profile for untrusted code",
            )
        if len(self._installed) >= self._maximum:
            raise RegistryError(
                "registry-full", f"the extension limit of {self._maximum} is reached"
            )
        manifest = load_manifest(path)
        if manifest.key in self._installed:
            raise RegistryError("extension-duplicate", "this extension is already installed")
        self._disabled.discard(manifest.key)
        installed = InstalledExtension(manifest=manifest, trust=trust, origin=Path(path).resolve())
        self._installed[manifest.key] = installed
        return installed

    def resolve(self, extension_id: str, version: str) -> InstalledExtension:
        key = (extension_id, version)
        installed = self._installed.get(key)
        if installed is None:
            raise RegistryError("extension-unknown", "this extension is not installed")
        if not installed.enabled:
            raise RegistryError("extension-disabled", "this extension is disabled")
        return installed

    def run(
        self, extension_id: str, version: str, request: dict[str, Any], *, timeout: float = 10.0
    ) -> AdapterResult:
        """Dispatch only a currently enabled, explicitly reviewed registration."""
        installed = self.resolve(extension_id, version)
        if installed.trust != "reviewed-same-user":
            raise RegistryError("trust-unsupported", "inert declarations cannot dispatch code")
        return run_adapter(installed.manifest, request, timeout=timeout)

    def disable(self, extension_id: str, version: str) -> InstalledExtension:
        key = (extension_id, version)
        installed = self._installed.get(key)
        if installed is None:
            raise RegistryError("extension-unknown", "this extension is not installed")
        disabled = InstalledExtension(
            manifest=installed.manifest,
            trust=installed.trust,
            origin=installed.origin,
            enabled=False,
        )
        self._installed[key] = disabled
        self._disabled.add(key)
        return disabled

    def enable(self, extension_id: str, version: str) -> InstalledExtension:
        key = (extension_id, version)
        installed = self._installed.get(key)
        if installed is None:
            raise RegistryError("extension-unknown", "this extension is not installed")
        self._disabled.discard(key)
        enabled = InstalledExtension(
            manifest=installed.manifest, trust=installed.trust, origin=installed.origin
        )
        self._installed[key] = enabled
        return enabled

    def uninstall(self, extension_id: str, version: str) -> None:
        """Remove one extension from the registry.

        Only the registry entry is removed. The manifest file is the operator's
        file, and this surface does not delete files it did not create.
        """

        key = (extension_id, version)
        if self._installed.pop(key, None) is None:
            raise RegistryError("extension-unknown", "this extension is not installed")
        self._disabled.discard(key)

    def installed(self) -> tuple[InstalledExtension, ...]:
        return tuple(self._installed[key] for key in sorted(self._installed))

    def digest(self) -> str:
        """Identity of the enabled set, so a plan can bind to it."""

        from llm_research_os.canonical import content_digest

        return content_digest(
            [
                {
                    "id": item.manifest.extension_id,
                    "version": item.manifest.version,
                    "manifestDigest": item.manifest.digest,
                    "enabled": item.enabled,
                    "trust": item.trust,
                }
                for item in self.installed()
            ]
        )

    def capability_surface(self) -> dict[str, Any]:
        """What this host can and cannot grant, for an operator to read."""

        return {
            "apiVersion": EXTENSION_API_VERSION,
            "kind": "ExtensionCapabilitySurface",
            "contractVersion": EXTENSION_CONTRACT_VERSION,
            "grantablePermissions": sorted(KNOWN_PERMISSIONS),
            "neverGrantedPermissions": sorted(NEVER_GRANTED),
            "maximumEnabled": self._maximum,
            "enabledCount": sum(item.enabled for item in self._installed.values()),
            "installedCount": len(self._installed),
            "maximumInstalled": self._maximum,
            "effectiveResourceLimits": sorted(effective_limits()),
            "isolationProfile": "none; reviewed same-user code runs under resource limits only",
            "note": (
                "Resource limits bound a reviewed adapter; they are not a sandbox and "
                "do not make untrusted code safe. effectiveResourceLimits is the set this "
                "platform actually applies, which is smaller than the set requested."
            ),
        }
