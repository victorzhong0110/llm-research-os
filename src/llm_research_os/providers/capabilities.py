"""Closed capability names and the declared / measured / allowed triple."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

ModelCapabilityName = Literal[
    "generate",
    "stream",
    "json-schema",
    "tools",
    "image",
    "embedding",
    "logprobs",
    "seed",
]


class ModelCapability(StrEnum):
    GENERATE = "generate"
    STREAM = "stream"
    JSON_SCHEMA = "json-schema"
    TOOLS = "tools"
    IMAGE = "image"
    EMBEDDING = "embedding"
    LOGPROBS = "logprobs"
    SEED = "seed"


KNOWN_CAPABILITIES: frozenset[ModelCapability] = frozenset(ModelCapability)


def coerce_capability(value: object) -> object:
    if type(value) is str:
        try:
            return ModelCapability(value)
        except ValueError:
            return value
    return value


def sorted_capability_names(values: frozenset[ModelCapability]) -> list[str]:
    return sorted(item.value for item in values)


@dataclass(frozen=True, slots=True)
class CapabilityReport:
    """Three capability sets recorded on every call (ADR-0017)."""

    declared: frozenset[ModelCapability]
    measured: frozenset[ModelCapability]
    allowed: frozenset[ModelCapability]

    def __post_init__(self) -> None:
        if not self.measured <= self.declared:
            raise ValueError("measured capabilities must be a subset of declared")
        if not self.allowed <= self.declared:
            raise ValueError("allowed capabilities must be a subset of declared")

    def document(self) -> dict[str, list[str]]:
        return {
            "declaredCapabilities": sorted_capability_names(self.declared),
            "measuredCapabilities": sorted_capability_names(self.measured),
            "allowedCapabilities": sorted_capability_names(self.allowed),
        }
