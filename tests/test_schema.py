from __future__ import annotations

import json

from research_os import API_VERSION
from research_os.schema import research_spec_schema, research_spec_schema_json


def test_schema_has_stable_identity() -> None:
    schema = research_spec_schema()
    assert schema["$id"].endswith("research-spec.json")
    assert schema["x-apiVersion"] == API_VERSION
    assert schema["title"] == "ResearchSpec"


def test_schema_json_is_deterministic() -> None:
    first = research_spec_schema_json()
    second = research_spec_schema_json()
    assert first == second
    # Valid, parseable JSON.
    parsed = json.loads(first)
    assert "properties" in parsed
    assert "metadata" in parsed["properties"]
