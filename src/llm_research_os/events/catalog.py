"""Discover published core payload contracts without closing the event envelope.

Domain consumers remain responsible for actor identity, references and transitions.
Unknown extension events stay readable, but this catalog gives them no authority.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

from pydantic import BaseModel


def core_payload_models() -> MappingProxyType[str, type[BaseModel]]:
    # Lazy imports avoid a cycle through domain modules that use the envelope.
    from llm_research_os.budget.models import PAYLOAD_MODELS as budget
    from llm_research_os.evidence.models import PAYLOAD_MODELS as evidence
    from llm_research_os.providers.models import PAYLOAD_MODELS as providers
    from llm_research_os.research.models import PAYLOAD_MODELS as research
    from llm_research_os.runs.models import PAYLOAD_MODELS as runs
    from llm_research_os.workers.models import PAYLOAD_MODELS as workers

    merged: dict[str, type[BaseModel]] = {}
    for domain in (budget, evidence, providers, research, runs, workers):
        for name, model in domain.items():
            if name in merged:
                raise ValueError("duplicate core event payload registration")
            merged[name] = model
    return MappingProxyType(merged)


def payload_catalog() -> dict[str, Any]:
    return {
        "catalogVersion": "v0alpha1",
        "scope": "core domain payloads; envelope and consumer rules remain separate",
        "payloads": {
            name: {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                **model.model_json_schema(by_alias=True, mode="validation"),
            }
            for name, model in sorted(core_payload_models().items())
        },
    }
