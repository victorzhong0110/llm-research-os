"""Safe loading and canonical serialization for ResearchSpec documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from llm_research_os.spec.models import ResearchSpec


class SpecLoadError(ValueError):
    """Raised when a document cannot be decoded into a mapping."""


def load_document(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
        data = json.loads(text) if source.suffix.lower() == ".json" else yaml.safe_load(text)
    except (OSError, UnicodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise SpecLoadError(f"could not load {source}: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecLoadError(f"{source} must contain one object at the document root")
    return data


def load_spec(path: str | Path) -> ResearchSpec:
    return ResearchSpec.model_validate(load_document(path))


def canonical_document(spec: ResearchSpec) -> str:
    return (
        json.dumps(
            spec.model_dump(mode="json", by_alias=True, exclude_none=True),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
