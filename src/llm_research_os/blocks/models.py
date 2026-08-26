"""Pydantic authoring models for BlockManifest v0alpha1."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import Field, model_validator

from llm_research_os.spec.models import (
    Identifier,
    JsonObject,
    NonEmptyText,
    SemanticVersion,
    StrictModel,
)
from llm_research_os.spec.schema import SCHEMA_DIALECT

MAX_CONFIG_SCHEMA_DEPTH = 32
MAX_CONFIG_SCHEMA_NODES = 4096
SUPPORTED_CONFIG_SCHEMA_KEYWORDS = frozenset(
    {
        "$comment",
        "$schema",
        "additionalProperties",
        "const",
        "default",
        "deprecated",
        "description",
        "enum",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "items",
        "maxItems",
        "maxLength",
        "maxProperties",
        "maximum",
        "minItems",
        "minLength",
        "minProperties",
        "minimum",
        "multipleOf",
        "properties",
        "readOnly",
        "required",
        "title",
        "type",
        "writeOnly",
    }
)


class RuntimeType(StrEnum):
    SIMULATED = "simulated"
    PYTHON = "python"
    CONTAINER = "container"
    REMOTE_SERVICE = "remote-service"
    COMPOSITE = "composite"


class BlockMetadata(StrictModel):
    id: Identifier
    version: SemanticVersion
    title: NonEmptyText | None = None
    description: NonEmptyText | None = None


class BlockRuntime(StrictModel):
    type: RuntimeType
    entrypoint: NonEmptyText | None = None
    config: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def executable_runtimes_declare_entrypoints(self) -> Self:
        executable = {
            RuntimeType.PYTHON,
            RuntimeType.CONTAINER,
            RuntimeType.REMOTE_SERVICE,
        }
        if self.type in executable and self.entrypoint is None:
            raise ValueError(f"runtime type {self.type!r} requires an entrypoint")
        if self.type in {RuntimeType.SIMULATED, RuntimeType.COMPOSITE} and self.entrypoint:
            raise ValueError(f"runtime type {self.type!r} must not declare an entrypoint")
        return self


class BlockPort(StrictModel):
    id: Identifier
    value_type: NonEmptyText = Field(default="researchos.any", alias="valueType")
    required: bool = False
    description: NonEmptyText | None = None


def _default_config_schema() -> dict[str, object]:
    return {"type": "object", "additionalProperties": False}


class BlockManifest(StrictModel):
    """Language-neutral declaration of one versioned workflow block."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["Block"]
    metadata: BlockMetadata
    runtime: BlockRuntime
    inputs: list[BlockPort] = Field(default_factory=list)
    outputs: list[BlockPort] = Field(default_factory=list)
    config_schema: JsonObject = Field(default_factory=_default_config_schema, alias="configSchema")
    resources: JsonObject = Field(default_factory=dict)
    capabilities: list[Identifier] = Field(default_factory=list)
    permissions: list[Identifier] = Field(default_factory=list)
    telemetry: list[Identifier] = Field(default_factory=list)
    reproducibility: JsonObject = Field(default_factory=dict)
    extensions: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_manifest_contract(self) -> Self:
        self._require_unique(self.inputs, "input port ids")
        self._require_unique(self.outputs, "output port ids")
        for values, label in (
            (self.capabilities, "capabilities"),
            (self.permissions, "permissions"),
            (self.telemetry, "telemetry"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} entries must be unique")
        _validate_config_schema(self.config_schema)
        return self

    @staticmethod
    def _require_unique(ports: list[BlockPort], label: str) -> None:
        ids = [port.id for port in ports]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{label} must be unique")


def _validate_config_schema(schema: JsonObject) -> None:
    if schema.get("$schema", SCHEMA_DIALECT) != SCHEMA_DIALECT:
        raise ValueError(f"configSchema must use {SCHEMA_DIALECT}")
    if schema.get("type") != "object":
        raise ValueError("configSchema must describe an object")

    seen = 0
    stack: list[tuple[object, int]] = [(schema, 0)]
    while stack:
        value, depth = stack.pop()
        seen += 1
        if seen > MAX_CONFIG_SCHEMA_NODES:
            raise ValueError("configSchema exceeds the M0 node limit")
        if depth > MAX_CONFIG_SCHEMA_DEPTH:
            raise ValueError("configSchema exceeds the M0 nesting limit")
        if isinstance(value, dict):
            if "$ref" in value or "$dynamicRef" in value:
                raise ValueError("configSchema references are not supported in M0")
            stack.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            stack.extend((child, depth + 1) for child in value)

    _validate_supported_keywords(schema)

    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError(f"configSchema is not valid Draft 2020-12: {exc.message}") from exc


def _validate_supported_keywords(schema: dict[str, object]) -> None:
    """Reject expensive or remote-capable JSON Schema features in the M0 subset."""

    stack = [schema]
    while stack:
        current = stack.pop()
        unsupported = sorted(set(current).difference(SUPPORTED_CONFIG_SCHEMA_KEYWORDS))
        if unsupported:
            rendered = ", ".join(repr(item) for item in unsupported)
            raise ValueError(f"configSchema uses unsupported M0 keyword(s): {rendered}")

        properties = current.get("properties")
        if isinstance(properties, dict):
            stack.extend(value for value in properties.values() if isinstance(value, dict))
        additional = current.get("additionalProperties")
        if isinstance(additional, dict):
            stack.append(additional)
        items = current.get("items")
        if isinstance(items, dict):
            stack.append(items)


BlockManifest.model_rebuild()
