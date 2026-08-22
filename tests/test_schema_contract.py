from __future__ import annotations

from pathlib import Path

import pytest

from research_os import SCHEMA_VERSION
from research_os.schema import research_spec_schema_json

COMMITTED = (
    Path(__file__).resolve().parent.parent / "schemas" / SCHEMA_VERSION / "research-spec.json"
)


def test_committed_schema_matches_generated() -> None:
    if not COMMITTED.exists():
        pytest.fail(
            f"missing committed schema at {COMMITTED}; regenerate with `uv run research-os schema`"
        )
    expected = research_spec_schema_json() + "\n"
    actual = COMMITTED.read_text(encoding="utf-8")
    assert actual == expected, (
        "committed JSON Schema is stale; regenerate with "
        "`uv run research-os schema > schemas/v0alpha1/research-spec.json`"
    )
