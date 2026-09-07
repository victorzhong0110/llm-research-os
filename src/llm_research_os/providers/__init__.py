"""Minimal ModelProvider, deterministic mock, and ``ai.call.*`` recording."""

from llm_research_os.providers.capabilities import CapabilityReport, ModelCapability
from llm_research_os.providers.compat import CompatHttpProvider
from llm_research_os.providers.compat_requests import (
    COMPAT_PROVIDER_ID,
    OpenAICompatGenerateRequestDocument,
    load_compat_generate_request,
)
from llm_research_os.providers.control import ModelCallControl, ModelCallResult
from llm_research_os.providers.errors import (
    ModelCallError,
    ModelCapabilityError,
    ModelFixtureError,
    ModelPayloadError,
    ModelProviderError,
    ModelRequestError,
)
from llm_research_os.providers.mock import DeterministicMockProvider
from llm_research_os.providers.models import ModelFixtureDocument, parse_ai_call_payload
from llm_research_os.providers.provider import (
    MOCK_MODEL_ID,
    MOCK_PROVIDER_ID,
    GenerateRequest,
    GenerateResult,
    ModelIdentity,
    ModelProvider,
)
from llm_research_os.providers.requests import (
    ModelGenerateRequestDocument,
    load_model_fixture,
    load_model_generate_request,
)

__all__ = [
    "COMPAT_PROVIDER_ID",
    "MOCK_MODEL_ID",
    "MOCK_PROVIDER_ID",
    "CapabilityReport",
    "CompatHttpProvider",
    "DeterministicMockProvider",
    "GenerateRequest",
    "GenerateResult",
    "ModelCallControl",
    "ModelCallError",
    "ModelCallResult",
    "ModelCapability",
    "ModelCapabilityError",
    "ModelFixtureDocument",
    "ModelFixtureError",
    "ModelGenerateRequestDocument",
    "ModelIdentity",
    "ModelPayloadError",
    "ModelProvider",
    "ModelProviderError",
    "ModelRequestError",
    "OpenAICompatGenerateRequestDocument",
    "load_compat_generate_request",
    "load_model_fixture",
    "load_model_generate_request",
    "parse_ai_call_payload",
]
