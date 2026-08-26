"""Versioned machine-readable reports for inert BlockManifest CLI operations."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Self

from pydantic import ConfigDict, Field, TypeAdapter, model_validator

from llm_research_os.blocks.models import BlockManifest, RuntimeType
from llm_research_os.canonical import ContentDigest, canonical_json, content_digest
from llm_research_os.spec.models import Identifier, SemanticVersion, StrictModel


class FrozenBlockReportModel(StrictModel):
    """Base class for immutable block command reports."""

    model_config = ConfigDict(frozen=True)


class BlockRegistryEntry(FrozenBlockReportModel):
    id: Identifier
    version: SemanticVersion
    runtime_type: RuntimeType = Field(alias="runtimeType")
    manifest_digest: ContentDigest = Field(alias="manifestDigest")
    capabilities: tuple[Identifier, ...] = Field(default_factory=tuple)
    permissions: tuple[Identifier, ...] = Field(default_factory=tuple)
    manifest_snapshot: str | None = Field(default=None, exclude=True, repr=False)

    @model_validator(mode="before")
    @classmethod
    def store_immutable_manifest_snapshot(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if "manifest_snapshot" in data or "manifestSnapshot" in data:
            raise ValueError("manifest snapshot is an internal field")
        manifest = data.pop("manifest", None)
        if manifest is not None:
            validated = BlockManifest.model_validate(manifest)
            payload = validated.model_dump(mode="json", by_alias=True, exclude_none=True)
            data["manifest_snapshot"] = canonical_json(payload)
        return data

    @property
    def manifest(self) -> BlockManifest | None:
        if self.manifest_snapshot is None:
            return None
        return BlockManifest.model_validate(json.loads(self.manifest_snapshot))

    def public_payload(self) -> dict[str, object]:
        payload = self.model_dump(mode="json", by_alias=True, exclude_none=True)
        if self.manifest_snapshot is not None:
            payload["manifest"] = json.loads(self.manifest_snapshot)
        return payload

    @model_validator(mode="after")
    def embedded_manifest_matches_summary(self) -> Self:
        if self.manifest is None:
            return self
        payload = self.manifest.model_dump(mode="json", by_alias=True, exclude_none=True)
        expected = (
            self.manifest.metadata.id,
            self.manifest.metadata.version,
            self.manifest.runtime.type,
            content_digest(payload),
            tuple(sorted(self.manifest.capabilities)),
            tuple(sorted(self.manifest.permissions)),
        )
        actual = (
            self.id,
            self.version,
            self.runtime_type,
            self.manifest_digest,
            self.capabilities,
            self.permissions,
        )
        if actual != expected:
            raise ValueError("registry entry summary does not match its embedded manifest")
        return self


class BlockRegistryReport(FrozenBlockReportModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["BlockRegistryReport"]
    operation: Literal["list", "show"]
    registry_digest: ContentDigest = Field(alias="registryDigest")
    blocks: tuple[BlockRegistryEntry, ...]

    def public_payload(self) -> dict[str, object]:
        payload = self.model_dump(mode="json", by_alias=True, exclude_none=True)
        payload["blocks"] = [block.public_payload() for block in self.blocks]
        return payload

    @model_validator(mode="after")
    def operation_matches_entries(self) -> Self:
        if self.operation == "list" and any(block.manifest is not None for block in self.blocks):
            raise ValueError("list reports must not embed full manifests")
        if self.operation == "show" and (len(self.blocks) != 1 or self.blocks[0].manifest is None):
            raise ValueError("show reports require exactly one full manifest")
        if self.operation == "list":
            digest_payload = [
                {
                    "id": block.id,
                    "version": block.version,
                    "manifestDigest": block.manifest_digest,
                }
                for block in self.blocks
            ]
            if self.registry_digest != content_digest(digest_payload):
                raise ValueError("list report registry digest does not match its entries")
        return self


class BlockManifestValidationReport(FrozenBlockReportModel):
    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["BlockManifestValidationReport"]
    valid: Literal[True]
    id: Identifier
    version: SemanticVersion
    manifest_digest: ContentDigest = Field(alias="manifestDigest")


BlockCommandReport = Annotated[
    BlockRegistryReport | BlockManifestValidationReport,
    Field(discriminator="kind"),
]
BLOCK_COMMAND_REPORT_ADAPTER: TypeAdapter[BlockCommandReport] = TypeAdapter(BlockCommandReport)
