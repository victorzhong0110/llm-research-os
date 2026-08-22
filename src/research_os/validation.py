"""Deterministic validation and *semantic* (not textual) revision diffing.

M0 checkpoint: "express a research question, validate an experiment definition,
explain errors, and compare what two revisions actually changed."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml
from pydantic import ValidationError

from research_os.models.research_spec import ResearchSpec


@dataclass(frozen=True)
class ValidationIssue:
    """A single human-readable validation error located by field path."""

    location: str
    message: str

    def __str__(self) -> str:
        return f"{self.location}: {self.message}"


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating a candidate spec document."""

    valid: bool
    spec: ResearchSpec | None = None
    issues: tuple[ValidationIssue, ...] = ()


def validate_document(document: dict[str, Any]) -> ValidationResult:
    """Validate a parsed mapping against ``ResearchSpec`` and explain errors."""
    try:
        spec = ResearchSpec.model_validate(document)
    except ValidationError as exc:
        issues = tuple(
            ValidationIssue(
                location=".".join(str(p) for p in error["loc"]) or "<root>",
                message=error["msg"],
            )
            for error in exc.errors()
        )
        return ValidationResult(valid=False, issues=issues)
    return ValidationResult(valid=True, spec=spec)


def load_yaml(text: str) -> dict[str, Any]:
    """Parse a YAML/JSON document into a mapping, rejecting non-mappings."""
    parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        raise ValueError("spec document must be a mapping at the top level")
    return parsed


@dataclass
class SemanticDiff:
    """Structured difference between two spec revisions."""

    added: dict[str, Any] = field(default_factory=dict)
    removed: dict[str, Any] = field(default_factory=dict)
    changed: dict[str, tuple[Any, Any]] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested mappings/sequences into dotted leaf paths."""
    flat: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, sub in value.items():
            flat.update(_flatten(sub, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        for index, sub in enumerate(value):
            flat.update(_flatten(sub, f"{prefix}[{index}]"))
    else:
        flat[prefix] = value
    return flat


def semantic_diff(old: ResearchSpec, new: ResearchSpec) -> SemanticDiff:
    """Compare two specs by meaning (flattened field paths), not raw text."""
    old_flat = _flatten(old.model_dump(mode="json"))
    new_flat = _flatten(new.model_dump(mode="json"))

    diff = SemanticDiff()
    for path, value in new_flat.items():
        if path not in old_flat:
            diff.added[path] = value
        elif old_flat[path] != value:
            diff.changed[path] = (old_flat[path], value)
    for path, value in old_flat.items():
        if path not in new_flat:
            diff.removed[path] = value
    return diff
