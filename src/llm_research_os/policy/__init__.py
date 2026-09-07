"""Trusted-kernel policy primitives used by M1 adapters."""

from llm_research_os.policy.capabilities import (
    KERNEL_CAPABILITIES,
    KernelCapability,
    require_known_kernel_capabilities,
)

__all__ = [
    "KERNEL_CAPABILITIES",
    "KernelCapability",
    "require_known_kernel_capabilities",
]
