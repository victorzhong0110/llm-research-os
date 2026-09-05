"""Kernel-facing ModelProvider surface (chapter 18 ``8-MC``, ADR-0017)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from llm_research_os.providers.capabilities import CapabilityReport, ModelCapability

MOCK_PROVIDER_ID = "mock.deterministic"
MOCK_MODEL_ID = "mock.deterministic.v1"


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    provider_id: str
    model_id: str
    local: bool
    cost_known: bool
    data_leaves_machine: bool
    context_tokens: int
    max_output_tokens: int
    endpoint: str | None = None

    def document(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "providerId": self.provider_id,
            "modelId": self.model_id,
            "local": self.local,
            "costKnown": self.cost_known,
            "dataLeavesMachine": self.data_leaves_machine,
            "contextTokens": self.context_tokens,
            "maxOutputTokens": self.max_output_tokens,
        }
        if self.endpoint is not None:
            payload["endpoint"] = self.endpoint
        return payload


@dataclass(frozen=True, slots=True)
class GenerateRequest:
    fixture_id: str
    requested: frozenset[ModelCapability]


@dataclass(frozen=True, slots=True)
class GenerateResult:
    prompt_digest: str
    output_digest: str
    capabilities: CapabilityReport
    output_payload: dict[str, object] | None = None


class ModelProvider(ABC):
    """Owned generate boundary. Adapters MUST NOT leak vendor response objects."""

    @abstractmethod
    def identity(self) -> ModelIdentity:
        """Return provider and model identity for this adapter instance."""

    @abstractmethod
    def capabilities(self) -> CapabilityReport:
        """Return declared, measured, and allowed capability sets."""

    @abstractmethod
    def generate(self, request: GenerateRequest) -> GenerateResult:
        """Return digests for one fixture-backed generation.

        Implementations MUST fail closed when ``request.requested`` is not a
        subset of ``allowed``. They MUST NOT silently simulate a missing
        capability.
        """
