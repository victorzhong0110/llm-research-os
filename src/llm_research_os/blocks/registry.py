"""Deterministic, data-only BlockManifest registry for M0 planning."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

from llm_research_os.blocks.builtins import builtin_manifests
from llm_research_os.blocks.io import load_manifest
from llm_research_os.blocks.models import BlockManifest
from llm_research_os.canonical import canonical_json, content_digest

MANIFEST_SUFFIXES = {".json", ".yaml", ".yml"}
MAX_REGISTRY_MANIFESTS = 1024
MAX_REGISTRY_BYTES = 67_108_864
MAX_REGISTRY_DIRECTORY_ENTRIES = 4096
MAX_CONFIG_BYTES = 262_144
MAX_CONFIG_DEPTH = 32
MAX_CONFIG_NODES = 16_384


class RegistryError(ValueError):
    """Base class for deterministic registry failures."""


class DuplicateBlockError(RegistryError):
    """Raised when an id/version pair appears more than once."""


class UnknownBlockError(RegistryError):
    """Raised when a pinned block cannot be resolved."""


class BlockConfigError(RegistryError):
    """Raised when task configuration violates the resolved manifest."""


@dataclass(frozen=True, slots=True)
class RegisteredBlock:
    manifest: BlockManifest
    digest: str
    source: str

    @property
    def key(self) -> tuple[str, str]:
        return (str(self.manifest.metadata.id), str(self.manifest.metadata.version))

    def public_summary(self) -> dict[str, object]:
        return {
            "id": self.manifest.metadata.id,
            "version": self.manifest.metadata.version,
            "runtimeType": self.manifest.runtime.type.value,
            "manifestDigest": self.digest,
            "capabilities": sorted(self.manifest.capabilities),
            "permissions": sorted(self.manifest.permissions),
        }

    def public_detail(self) -> dict[str, object]:
        return {
            **self.public_summary(),
            "manifest": self.manifest.model_dump(mode="json", by_alias=True, exclude_none=True),
        }


class BlockRegistry:
    """An in-memory registry that never imports or executes block entrypoints."""

    def __init__(self) -> None:
        self._blocks: dict[tuple[str, str], RegisteredBlock] = {}
        self._sealed = False

    def register(self, manifest: BlockManifest, *, source: str = "memory") -> RegisteredBlock:
        if self._sealed:
            raise RegistryError("registry is sealed")
        input_payload = manifest.model_dump(mode="json", by_alias=True, exclude_none=True)
        snapshot = BlockManifest.model_validate(input_payload)
        snapshot_payload = snapshot.model_dump(mode="json", by_alias=True, exclude_none=True)
        registered = RegisteredBlock(snapshot, content_digest(snapshot_payload), source)
        if registered.key in self._blocks:
            block_id, version = registered.key
            raise DuplicateBlockError(f"duplicate block manifest: {block_id}@{version}")
        self._blocks[registered.key] = registered
        return self._copy(registered)

    def seal(self) -> None:
        self._sealed = True

    @property
    def sealed(self) -> bool:
        return self._sealed

    def resolve(self, block_id: str, version: str) -> RegisteredBlock:
        try:
            return self._copy(self._blocks[(block_id, version)])
        except KeyError as exc:
            raise UnknownBlockError(f"unknown block manifest: {block_id}@{version}") from exc

    def validate_config(self, block: RegisteredBlock, config: dict[str, object]) -> None:
        try:
            registered = self._blocks[block.key]
        except KeyError as exc:
            block_id, version = block.key
            raise UnknownBlockError(f"unknown block manifest: {block_id}@{version}") from exc
        _validate_config_limits(config)
        validator = Draft202012Validator(registered.manifest.config_schema)
        errors = sorted(
            validator.iter_errors(config),
            key=lambda error: (
                tuple(str(part) for part in error.absolute_path),
                tuple(str(part) for part in error.absolute_schema_path),
                str(error.validator),
            ),
        )
        if not errors:
            return
        error = errors[0]
        block_id, version = block.key
        raise BlockConfigError(
            f"config for {block_id}@{version} violates JSON Schema rule {error.validator!r}"
        )

    def blocks(self) -> tuple[RegisteredBlock, ...]:
        return tuple(self._copy(self._blocks[key]) for key in sorted(self._blocks))

    def digest(self) -> str:
        return content_digest(
            [
                {
                    "id": block.key[0],
                    "version": block.key[1],
                    "manifestDigest": block.digest,
                }
                for block in self.blocks()
            ]
        )

    @staticmethod
    def _copy(block: RegisteredBlock) -> RegisteredBlock:
        return RegisteredBlock(block.manifest.model_copy(deep=True), block.digest, block.source)


def build_registry(paths: Iterable[Path] = ()) -> BlockRegistry:
    registry = BlockRegistry()
    for manifest in builtin_manifests():
        registry.register(manifest, source="builtin")
    for path in _manifest_paths(paths):
        registry.register(load_manifest(path), source="explicit")
    registry.seal()
    return registry


def _manifest_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    manifests: list[Path] = []
    total_bytes = 0

    def append_manifest(path: Path) -> None:
        nonlocal total_bytes
        if len(manifests) >= MAX_REGISTRY_MANIFESTS:
            raise RegistryError(f"registry exceeds the {MAX_REGISTRY_MANIFESTS}-manifest M0 limit")
        try:
            total_bytes += path.stat().st_size
        except OSError as exc:
            raise RegistryError(f"could not inspect registry manifest: {path}") from exc
        if total_bytes > MAX_REGISTRY_BYTES:
            raise RegistryError(f"registry exceeds the {MAX_REGISTRY_BYTES}-byte M0 limit")
        manifests.append(path)

    for source in paths:
        if source.is_symlink():
            raise RegistryError(f"registry path must not be a symbolic link: {source}")
        if source.is_dir():
            children: list[Path] = []
            for entry_count, child in enumerate(source.iterdir(), start=1):
                if entry_count > MAX_REGISTRY_DIRECTORY_ENTRIES:
                    raise RegistryError(
                        "registry directory exceeds the "
                        f"{MAX_REGISTRY_DIRECTORY_ENTRIES}-entry M0 scan limit: {source}"
                    )
                if child.is_symlink():
                    raise RegistryError(f"registry entry must not be a symbolic link: {child}")
                if child.is_file() and child.suffix.lower() in MANIFEST_SUFFIXES:
                    children.append(child)
            for child in sorted(children, key=lambda item: item.name):
                append_manifest(child)
        elif source.is_file():
            if source.suffix.lower() not in MANIFEST_SUFFIXES:
                raise RegistryError(f"unsupported manifest extension: {source}")
            append_manifest(source)
        else:
            raise RegistryError(f"registry path does not exist: {source}")
    return tuple(manifests)


def _validate_config_limits(config: dict[str, object]) -> None:
    size = len(canonical_json(config).encode("utf-8"))
    if size > MAX_CONFIG_BYTES:
        raise BlockConfigError(f"config exceeds the {MAX_CONFIG_BYTES}-byte M0 limit")

    seen = 0
    stack: list[tuple[object, int]] = [(config, 0)]
    while stack:
        value, depth = stack.pop()
        seen += 1
        if seen > MAX_CONFIG_NODES:
            raise BlockConfigError(f"config exceeds the {MAX_CONFIG_NODES}-node M0 limit")
        if depth > MAX_CONFIG_DEPTH:
            raise BlockConfigError(f"config exceeds the M0 nesting limit of {MAX_CONFIG_DEPTH}")
        if isinstance(value, dict):
            stack.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            stack.extend((child, depth + 1) for child in value)
