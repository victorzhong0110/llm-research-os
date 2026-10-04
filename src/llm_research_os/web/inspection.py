"""Bounded inspection of verified facts and project-linked immutable objects."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from llm_research_os.execution.models import ExecutionPlan
from llm_research_os.secrets.redaction import redact_object
from llm_research_os.spec.models import ResearchSpec

_DIGEST = re.compile(r"^(?:jcs-sha256|sha256):[0-9a-f]{64}$")


def safe_document(value: Any) -> Any:
    """Hide secret keys and absolute paths, retaining bounded research facts."""
    return _hide_paths(redact_object(value))


def _hide_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _hide_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_hide_paths(item) for item in value]
    if isinstance(value, str) and (value.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", value)):
        return "[host path redacted]"
    return value


def references(value: Any) -> list[dict[str, str]]:
    """Extract typed digest/event references; never turn arbitrary text into URLs."""
    result: dict[tuple[str, str], dict[str, str]] = {}
    stack = [("reference", value)]
    while stack and len(result) < 100:
        key, item = stack.pop()
        if isinstance(item, dict):
            stack.extend(item.items())
        elif isinstance(item, list):
            stack.extend((key, child) for child in item)
        elif isinstance(item, str):
            kind = (
                "artifact"
                if _DIGEST.fullmatch(item)
                else ("event" if key.lower().endswith("eventid") or key == "evidenceRefs" else "")
            )
            if not kind and key.endswith("Sequence") and item.isascii() and item.isdigit():
                kind = "event"
            if kind == "event" and not key.endswith("Sequence"):
                item = "id:" + item
            if kind:
                result[(kind, item)] = {"kind": kind, "target": item, "label": key}
        elif isinstance(item, int) and not isinstance(item, bool) and key.endswith("Sequence"):
            result[("event", str(item))] = {"kind": "event", "target": str(item), "label": key}
    return list(result.values())


def graph_document(text: str) -> dict[str, Any]:
    """Validate stored spec/plan contracts before presenting graph topology."""
    try:
        spec = ResearchSpec.model_validate_json(text)
    except ValidationError:
        spec = None
    if spec is not None:
        graphs = []
        for workflow in spec.workflows[:20]:
            graph = workflow.graph
            graphs.append(
                {
                    "id": workflow.id,
                    "nodes": [{"id": n.id, "kind": n.kind} for n in graph.nodes[:200]],
                    "edges": [{"source": e.source, "target": e.target} for e in graph.edges[:400]],
                    "unsupported": any(n.kind == "loop" for n in graph.nodes)
                    or len(graph.nodes) > 200
                    or len(graph.edges) > 400,
                }
            )
        return {"source": "ResearchSpec", "graphs": graphs}
    try:
        plan = ExecutionPlan.model_validate_json(text)
    except ValidationError:
        return {"source": "unsupported", "graphs": []}
    nodes = [n for stage in plan.graph.stages for n in stage.nodes]
    return {
        "source": "ExecutionPlan",
        "graphs": [
            {
                "id": plan.workflow_id,
                "nodes": [{"id": "/".join(n.node_path), "kind": n.kind} for n in nodes[:200]],
                "edges": [
                    {"source": "/".join(e.source_path), "target": "/".join(e.target_path)}
                    for e in plan.graph.edges[:400]
                ],
                "unsupported": any(n.kind == "loop" for n in nodes)
                or len(nodes) > 200
                or len(plan.graph.edges) > 400,
            }
        ],
    }


def inspected_text(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        return {"text": text, "links": [], "graph": {"source": "unsupported", "graphs": []}}
    return {
        "content": safe_document(value),
        "links": references(safe_document(value)),
        "graph": graph_document(text),
    }
