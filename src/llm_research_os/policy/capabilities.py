"""Closed kernel capability registry (ADR-0038 E6). Unknown names fail closed."""

from __future__ import annotations

from enum import StrEnum


class KernelCapability(StrEnum):
    SIMULATE = "simulate"
    READ_LOCAL_EVIDENCE = "read.local_evidence"
    READ_EXTERNAL_API = "read.external_api"
    WRITE_EXPERIMENT_DRAFT = "write.experiment_draft"


KERNEL_CAPABILITIES: frozenset[KernelCapability] = frozenset(KernelCapability)


def coerce_kernel_capability(value: object) -> object:
    if type(value) is str:
        try:
            return KernelCapability(value)
        except ValueError:
            return value
    return value


def require_known_kernel_capabilities(values: tuple[object, ...]) -> tuple[KernelCapability, ...]:
    unknown = [item for item in values if not isinstance(item, KernelCapability)]
    if unknown:
        raise ValueError("unknown kernel capability")
    names = tuple(item for item in values if isinstance(item, KernelCapability))
    if len(names) != len(set(names)):
        raise ValueError("grantedKernelCapabilities entries must be unique")
    return names
