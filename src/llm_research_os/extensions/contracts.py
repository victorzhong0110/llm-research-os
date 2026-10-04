"""Published inert declaration, invocation and registry document contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

API = Literal["researchos.dev/extension/v0alpha1"]
Version = Literal["v0alpha1"]
Identifier = Annotated[str, Field(min_length=1, max_length=128)]
Text = Annotated[str, Field(max_length=262144)]
Permission = Literal[
    "artifacts.read", "events.read", "evidence.read", "ledger.read", "metrics.read"
]
Limit = Literal["addressSpace", "cpuSeconds", "openFiles"]


class Document(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", allow_inf_nan=False)


class ExtensionDeclaration(Document):
    api_version: API = Field(alias="apiVersion")
    kind: Literal["Extension"]
    extension_id: Identifier = Field(alias="id")
    version: Identifier
    contract_version: Version = Field(alias="contractVersion")
    permissions: list[Permission] = Field(default_factory=list, max_length=16)
    entry_module: Text | None = Field(default=None, alias="entryModule")
    diagnostics: dict[Identifier, Annotated[str, Field(max_length=200)]] = Field(
        default_factory=dict, max_length=16
    )


class ManifestView(Document):
    api_version: API = Field(alias="apiVersion")
    kind: Literal["ExtensionManifest"]
    contract_version: Version = Field(alias="contractVersion")
    extension_id: Identifier = Field(alias="id")
    version: Identifier
    extension_contract_version: Version = Field(alias="extensionContractVersion")
    manifest_digest: Annotated[str, Field(pattern=r"^jcs-sha256:[0-9a-f]{64}$")] = Field(
        alias="manifestDigest"
    )
    requested_permissions: list[Permission] = Field(alias="requestedPermissions", max_length=16)
    compatible_permissions: list[Permission] = Field(alias="compatiblePermissions", max_length=16)
    granted_permissions: list[Permission] = Field(alias="grantedPermissions", max_length=0)
    refused_permissions: list[Permission] = Field(alias="refusedPermissions", max_length=0)
    entry_module: Text | None = Field(alias="entryModule")
    has_entry_module: bool = Field(alias="hasEntryModule")
    diagnostics: dict[Identifier, Annotated[str, Field(max_length=200)]] = Field(max_length=16)


class InstalledView(ManifestView):
    kind: Literal["InstalledExtension"]  # type: ignore[assignment]
    trust: Literal["inert", "reviewed-same-user"]
    enabled: bool
    origin_name: Annotated[str, Field(min_length=1, max_length=4096)] = Field(alias="originName")


class AdapterResultDocument(Document):
    api_version: API = Field(alias="apiVersion")
    kind: Literal["AdapterResult"]
    contract_version: Version = Field(alias="contractVersion")
    outcome: Literal["error", "ok", "timeout"]
    exit_code: int | None = Field(alias="exitCode")
    duration_seconds: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]{3}$")] = Field(
        alias="durationSeconds"
    )
    timed_out: bool = Field(alias="timedOut")
    output_limit_exceeded: bool = Field(alias="outputLimitExceeded")
    effective_resource_limits: list[Limit] = Field(alias="effectiveResourceLimits", max_length=3)
    stdout_bytes: int = Field(alias="stdoutBytes", ge=0, le=262144)
    stderr_bytes: int = Field(alias="stderrBytes", ge=0, le=65536)
    stdout: Annotated[str, Field(max_length=262144)]
    stderr: Annotated[str, Field(max_length=65536)]


class CapabilitySurfaceDocument(Document):
    api_version: API = Field(alias="apiVersion")
    kind: Literal["ExtensionCapabilitySurface"]
    contract_version: Version = Field(alias="contractVersion")
    grantable_permissions: list[Permission] = Field(alias="grantablePermissions", max_length=16)
    never_granted_permissions: list[Identifier] = Field(
        alias="neverGrantedPermissions", max_length=16
    )
    maximum_enabled: int = Field(alias="maximumEnabled", ge=1, le=32)
    maximum_installed: int = Field(alias="maximumInstalled", ge=1, le=32)
    enabled_count: int = Field(alias="enabledCount", ge=0, le=32)
    installed_count: int = Field(alias="installedCount", ge=0, le=32)
    effective_resource_limits: list[Limit] = Field(alias="effectiveResourceLimits", max_length=3)
    isolation_profile: Text = Field(alias="isolationProfile")
    note: Text
