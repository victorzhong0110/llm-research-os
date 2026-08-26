import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from llm_research_os.blocks.io import ManifestLoadError, load_manifest
from llm_research_os.blocks.models import BlockManifest
from llm_research_os.blocks.registry import (
    BlockConfigError,
    BlockRegistry,
    DuplicateBlockError,
    RegistryError,
    build_registry,
)
from llm_research_os.blocks.reports import BlockRegistryEntry, BlockRegistryReport
from llm_research_os.canonical import content_digest

EXAMPLES = Path(__file__).parents[1] / "examples"


def _manifest(
    block_id: str = "example.block",
    version: str = "0.1.0",
    *,
    config_schema: dict[str, object] | None = None,
) -> BlockManifest:
    return BlockManifest.model_validate(
        {
            "apiVersion": "researchos.dev/v0alpha1",
            "kind": "Block",
            "metadata": {"id": block_id, "version": version},
            "runtime": {"type": "simulated"},
            "configSchema": config_schema
            or {
                "type": "object",
                "properties": {"count": {"type": "integer"}},
                "additionalProperties": False,
            },
        }
    )


def test_builtin_registry_is_exact_sorted_and_sealed() -> None:
    registry = build_registry()
    assert registry.sealed
    blocks = registry.blocks()
    assert [(block.key, block.manifest.runtime.type.value) for block in blocks] == [
        (("simulated.experiment", "0.1.0"), "simulated")
    ]
    with pytest.raises(RegistryError, match="sealed"):
        registry.register(_manifest())


def test_duplicate_block_version_is_rejected_without_override() -> None:
    registry = BlockRegistry()
    registry.register(_manifest())
    with pytest.raises(DuplicateBlockError, match="duplicate block manifest"):
        registry.register(_manifest())


def test_registry_returns_defensive_manifest_copies() -> None:
    registry = BlockRegistry()
    registry.register(_manifest())
    registry.seal()
    first = registry.resolve("example.block", "0.1.0")
    first.manifest.metadata.title = "caller mutation"
    second = registry.resolve("example.block", "0.1.0")
    assert second.manifest.metadata.title is None
    assert first.digest == second.digest


def test_config_diagnostic_does_not_echo_value() -> None:
    registry = BlockRegistry()
    block = registry.register(_manifest())
    secret = "TOP-SECRET-SENTINEL"
    with pytest.raises(BlockConfigError) as raised:
        registry.validate_config(block, {"count": secret})
    assert secret not in str(raised.value)
    assert "'type'" in str(raised.value)


def test_registration_revalidates_a_mutated_manifest() -> None:
    manifest = _manifest()
    manifest.config_schema["$ref"] = "https://example.invalid/schema.json"
    with pytest.raises(ValidationError, match="references are not supported"):
        BlockRegistry().register(manifest)


def test_registered_digest_uses_the_normalized_private_snapshot() -> None:
    manifest = _manifest()
    manifest.capabilities.append("  model.call  ")
    registered = BlockRegistry().register(manifest)
    payload = registered.manifest.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert registered.manifest.capabilities == ["model.call"]
    assert registered.digest == content_digest(payload)


def test_config_validation_uses_the_private_verified_manifest() -> None:
    registry = BlockRegistry()
    registry.register(_manifest())
    registry.seal()
    returned = registry.resolve("example.block", "0.1.0")
    returned.manifest.config_schema.clear()
    returned.manifest.config_schema["$ref"] = "https://example.invalid/schema.json"
    with pytest.raises(BlockConfigError, match="'type'"):
        registry.validate_config(returned, {"count": "wrong"})


def test_config_diagnostics_are_deterministic_and_redact_dynamic_keys() -> None:
    first_schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "minLength": 3,
                "enum": ["allowed"],
            }
        },
        "additionalProperties": {
            "type": "object",
            "additionalProperties": {"type": "integer"},
        },
    }
    second_schema = {
        "additionalProperties": first_schema["additionalProperties"],
        "properties": {
            "name": {
                "enum": ["allowed"],
                "minLength": 3,
                "type": "string",
            }
        },
        "type": "object",
    }
    first_registry = BlockRegistry()
    first = first_registry.register(_manifest(config_schema=first_schema))
    second_registry = BlockRegistry()
    second = second_registry.register(_manifest(config_schema=second_schema))
    assert first.digest == second.digest

    messages = []
    for registry, block in ((first_registry, first), (second_registry, second)):
        with pytest.raises(BlockConfigError) as raised:
            registry.validate_config(block, {"name": "x"})
        messages.append(str(raised.value))
    assert messages[0] == messages[1]

    secret_key = "TOP-SECRET-SENTINEL"
    with pytest.raises(BlockConfigError) as raised:
        first_registry.validate_config(first, {secret_key: {secret_key: "wrong"}})
    assert secret_key not in str(raised.value)


def test_expensive_schema_keywords_and_oversized_configs_fail_fast() -> None:
    with pytest.raises(ValidationError, match="unsupported M0 keyword"):
        _manifest(
            config_schema={
                "type": "object",
                "properties": {"value": {"type": "string", "pattern": "^(a+)+$"}},
            }
        )

    registry = BlockRegistry()
    block = registry.register(
        _manifest(config_schema={"type": "object", "additionalProperties": True})
    )
    with pytest.raises(BlockConfigError, match="byte M0 limit"):
        registry.validate_config(block, {"value": "x" * 300_000})


@pytest.mark.parametrize("name", ["external-ref.yaml", "duplicate-input.yaml"])
def test_invalid_manifest_examples_fail_semantic_validation(name: str) -> None:
    with pytest.raises(ValidationError):
        load_manifest(EXAMPLES / "invalid-manifests" / name)


def test_manifest_loader_rejects_symbolic_links(tmp_path: Path) -> None:
    target = EXAMPLES / "manifests" / "example-train.yaml"
    link = tmp_path / "linked.yaml"
    link.symlink_to(target)
    with pytest.raises(ManifestLoadError, match="symbolic link"):
        load_manifest(link)


def test_manifest_read_is_bound_to_the_checked_file_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.yaml"
    target = tmp_path / "target.yaml"
    source.write_text(
        (EXAMPLES / "manifests/example-train.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    target.write_text(
        (EXAMPLES / "manifests/example-transform.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    real_fstat = os.fstat
    raced = False

    def replace_after_open(descriptor: int) -> os.stat_result:
        nonlocal raced
        metadata = real_fstat(descriptor)
        if not raced:
            raced = True
            source.unlink()
            source.symlink_to(target)
        return metadata

    monkeypatch.setattr(os, "fstat", replace_after_open)
    loaded = load_manifest(source)
    assert loaded.metadata.id == "example.train"


def test_registry_digest_ignores_registration_order() -> None:
    first = BlockRegistry()
    first.register(_manifest("example.a"))
    first.register(_manifest("example.b"))
    first.seal()
    second = BlockRegistry()
    second.register(_manifest("example.b"))
    second.register(_manifest("example.a"))
    second.seal()
    assert first.digest() == second.digest()


def test_show_report_keeps_an_immutable_manifest_snapshot() -> None:
    registry = build_registry()
    block = registry.blocks()[0]
    report = BlockRegistryReport(
        apiVersion="researchos.dev/v0alpha1",
        kind="BlockRegistryReport",
        operation="show",
        registryDigest=registry.digest(),
        blocks=(BlockRegistryEntry.model_validate(block.public_detail()),),
    )
    before = report.public_payload()
    returned = report.blocks[0].manifest
    assert returned is not None
    returned.capabilities.append("secret.read")
    assert report.public_payload() == before


def test_registry_directory_scan_limit_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import llm_research_os.blocks.registry as registry_module

    monkeypatch.setattr(registry_module, "MAX_REGISTRY_DIRECTORY_ENTRIES", 1)
    (tmp_path / "first.txt").write_text("ignored", encoding="utf-8")
    (tmp_path / "second.txt").write_text("ignored", encoding="utf-8")
    with pytest.raises(RegistryError, match="entry M0 scan limit"):
        build_registry([tmp_path])
