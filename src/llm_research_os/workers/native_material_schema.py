"""Generated JSON Schema for native material indexing v0alpha1."""

from __future__ import annotations

from pathlib import Path

from llm_research_os.execution.native_reviewed_schema import _build, _canonical, _matches, _write
from llm_research_os.workers.native_material_documents import NativeMaterialIndex


def canonical_schema() -> str:
    return _canonical(
        _build(
            NativeMaterialIndex,
            "https://researchos.dev/schemas/native-material-index/v0alpha1.schema.json",
        )
    )


def schema_matches(path: str | Path) -> bool:
    return _matches(canonical_schema(), path)


def write_schema(path: str | Path) -> None:
    _write(canonical_schema(), path)
