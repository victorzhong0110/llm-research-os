"""Deterministic fixture-backed ModelProvider. No network, process, or GPU."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from llm_research_os.canonical import content_digest
from llm_research_os.providers.capabilities import CapabilityReport, ModelCapability
from llm_research_os.providers.errors import ModelCapabilityError, ModelFixtureError
from llm_research_os.providers.models import ModelFixtureDocument
from llm_research_os.providers.provider import (
    MOCK_MODEL_ID,
    MOCK_PROVIDER_ID,
    GenerateRequest,
    GenerateResult,
    ModelIdentity,
    ModelProvider,
)

_MOCK_CAPABILITIES = frozenset(
    {ModelCapability.GENERATE, ModelCapability.JSON_SCHEMA, ModelCapability.SEED}
)
_MOCK_IDENTITY = ModelIdentity(
    provider_id=MOCK_PROVIDER_ID,
    model_id=MOCK_MODEL_ID,
    local=True,
    cost_known=True,
    data_leaves_machine=False,
    context_tokens=8192,
    max_output_tokens=1024,
)
_MOCK_REPORT = CapabilityReport(
    declared=_MOCK_CAPABILITIES,
    measured=_MOCK_CAPABILITIES,
    allowed=_MOCK_CAPABILITIES,
)


class DeterministicMockProvider(ModelProvider):
    """Return canned prompt/output digests from fixtures. Never opens a network connection."""

    def __init__(self, fixtures: Mapping[str, ModelFixtureDocument]) -> None:
        if not isinstance(fixtures, Mapping):
            raise ModelFixtureError("fixtures must be a mapping", code="invalid-fixtures")
        catalog: dict[str, ModelFixtureDocument] = {}
        for fixture_id, fixture in fixtures.items():
            if type(fixture_id) is not str:
                raise ModelFixtureError("fixture id must be a string", code="invalid-fixture-id")
            if not isinstance(fixture, ModelFixtureDocument):
                raise ModelFixtureError("fixture document is invalid", code="invalid-fixture")
            if fixture.id != fixture_id:
                raise ModelFixtureError(
                    "fixture mapping key does not match fixture id",
                    code="fixture-id-mismatch",
                )
            catalog[fixture_id] = fixture
        self._fixtures = MappingProxyType(catalog)

    def identity(self) -> ModelIdentity:
        return _MOCK_IDENTITY

    def capabilities(self) -> CapabilityReport:
        return _MOCK_REPORT

    def generate(self, request: GenerateRequest) -> GenerateResult:
        if not request.requested <= _MOCK_REPORT.allowed:
            raise ModelCapabilityError(
                "requested capability is not allowed",
                code="capability-not-allowed",
            )
        if not request.requested:
            raise ModelCapabilityError(
                "requested capability set is empty",
                code="capability-empty",
            )
        fixture = self._fixtures.get(request.fixture_id)
        if fixture is None:
            raise ModelFixtureError("fixture is not registered", code="fixture-not-found")
        return GenerateResult(
            prompt_digest=content_digest(fixture.prompt),
            output_digest=content_digest(fixture.output),
            capabilities=_MOCK_REPORT,
        )
