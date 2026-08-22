"""Export the versioned, language-neutral JSON Schema contract.

Per decision ``3-SE``, Pydantic is the M0 authoring entry point while the
versioned JSON Schema is the outward-facing contract other languages consume.
"""

from __future__ import annotations

import json
from typing import Any

from research_os import API_VERSION
from research_os.models.research_spec import ResearchSpec

SCHEMA_ID = f"https://researchos.dev/schemas/{API_VERSION}/research-spec.json"


def research_spec_schema() -> dict[str, Any]:
    """Return the JSON Schema for ``ResearchSpec`` with a stable ``$id``."""
    schema = ResearchSpec.model_json_schema()
    schema["$id"] = SCHEMA_ID
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "ResearchSpec"
    schema["x-apiVersion"] = API_VERSION
    return schema


def research_spec_schema_json(*, indent: int = 2) -> str:
    """Return the JSON Schema serialized as a deterministic JSON string."""
    return json.dumps(research_spec_schema(), indent=indent, sort_keys=True)
