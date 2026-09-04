"""Deterministic JSON Schema generation for research decision contracts."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from llm_research_os.research.models import RESEARCH_LEDGER_SCHEMA_ID, ResearchLedger
from llm_research_os.research.requests import (
    DECISION_RECORD_REQUEST_SCHEMA_ID,
    DISSENT_RECORD_REQUEST_SCHEMA_ID,
    PROPOSAL_SUBMIT_REQUEST_SCHEMA_ID,
    DecisionRecordRequestDocument,
    DissentRecordRequestDocument,
    ProposalSubmitRequestDocument,
)
from llm_research_os.spec.schema import SCHEMA_DIALECT

SCHEMA_ID = RESEARCH_LEDGER_SCHEMA_ID


def _build(
    model: type[Any],
    schema_id: str,
    patch: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    generated = model.model_json_schema(
        by_alias=True,
        mode="validation",
        ref_template="#/$defs/{model}",
    )
    schema = {"$schema": SCHEMA_DIALECT, "$id": schema_id, **generated}
    if patch is not None:
        patch(schema)
    return schema


def _canonical(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write(schema: dict[str, Any], path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(_canonical(schema), encoding="utf-8")


def _matches(schema: dict[str, Any], path: str | Path) -> bool:
    candidate = Path(path)
    try:
        return candidate.read_text(encoding="utf-8") == _canonical(schema)
    except OSError:
        return False


def _forbid_null_optional(schema: dict[str, Any], definition: str, field: str) -> None:
    location = f"$defs.{definition}.properties.{field}"
    definitions = schema.get("$defs")
    if type(definitions) is not dict:
        raise ValueError(f"schema is missing $defs while forbidding null on {location}")
    binding = definitions.get(definition)
    if type(binding) is not dict:
        raise ValueError(f"schema is missing {location} definition")
    properties = binding.get("properties")
    if type(properties) is not dict:
        raise ValueError(f"schema is missing {location} properties")
    value = properties.get(field)
    if type(value) is not dict:
        raise ValueError(f"schema is missing {location}")
    alternatives = value.get("anyOf")
    if type(alternatives) is not list:
        raise ValueError(f"schema {location} is not an anyOf union")
    typed = next(
        (
            item
            for item in alternatives
            if type(item) is dict and item.get("type") in {"string", "integer"}
        ),
        None,
    )
    if typed is None:
        raise ValueError(f"schema {location} anyOf has no string or integer alternative")
    properties[field] = typed


def _patch_ledger(schema: dict[str, Any]) -> None:
    questions = schema.get("properties", {}).get("questions")
    if type(questions) is not dict:
        raise ValueError("research ledger schema is missing questions")
    questions["maxItems"] = 0
    questions["minItems"] = 0
    _forbid_null_optional(schema, "ProposalLedgerEntry", "acceptedByDecisionId")
    _forbid_null_optional(schema, "ProposalLedgerEntry", "supersededByProposalId")


def _patch_proposal_request(schema: dict[str, Any]) -> None:
    _forbid_null_optional(schema, "ProposalPrediction", "metric")
    _forbid_null_optional(schema, "ProposalRequestActor", "modelId")


def _patch_dissent_request(schema: dict[str, Any]) -> None:
    _forbid_null_optional(schema, "ProposalRequestActor", "modelId")


def build_research_ledger_schema() -> dict[str, Any]:
    return _build(ResearchLedger, RESEARCH_LEDGER_SCHEMA_ID, _patch_ledger)


def build_proposal_submit_request_schema() -> dict[str, Any]:
    return _build(
        ProposalSubmitRequestDocument,
        PROPOSAL_SUBMIT_REQUEST_SCHEMA_ID,
        _patch_proposal_request,
    )


def build_dissent_record_request_schema() -> dict[str, Any]:
    return _build(
        DissentRecordRequestDocument,
        DISSENT_RECORD_REQUEST_SCHEMA_ID,
        _patch_dissent_request,
    )


def build_decision_record_request_schema() -> dict[str, Any]:
    return _build(DecisionRecordRequestDocument, DECISION_RECORD_REQUEST_SCHEMA_ID)


def canonical_schema() -> str:
    return _canonical(build_research_ledger_schema())


def write_schema(path: str | Path) -> None:
    _write(build_research_ledger_schema(), path)


def schema_matches(path: str | Path) -> bool:
    return _matches(build_research_ledger_schema(), path)


def canonical_proposal_submit_request_schema() -> str:
    return _canonical(build_proposal_submit_request_schema())


def write_proposal_submit_request_schema(path: str | Path) -> None:
    _write(build_proposal_submit_request_schema(), path)


def proposal_submit_request_schema_matches(path: str | Path) -> bool:
    return _matches(build_proposal_submit_request_schema(), path)


def canonical_dissent_record_request_schema() -> str:
    return _canonical(build_dissent_record_request_schema())


def write_dissent_record_request_schema(path: str | Path) -> None:
    _write(build_dissent_record_request_schema(), path)


def dissent_record_request_schema_matches(path: str | Path) -> bool:
    return _matches(build_dissent_record_request_schema(), path)


def canonical_decision_record_request_schema() -> str:
    return _canonical(build_decision_record_request_schema())


def write_decision_record_request_schema(path: str | Path) -> None:
    _write(build_decision_record_request_schema(), path)


def decision_record_request_schema_matches(path: str | Path) -> bool:
    return _matches(build_decision_record_request_schema(), path)
