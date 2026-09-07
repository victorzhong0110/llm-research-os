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
    QUESTION_ANSWER_REQUEST_SCHEMA_ID,
    QUESTION_ASK_REQUEST_SCHEMA_ID,
    DecisionRecordRequestDocument,
    DissentRecordRequestDocument,
    ProposalSubmitRequestDocument,
    QuestionAnswerRequestDocument,
    QuestionAskRequestDocument,
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
        (item for item in alternatives if type(item) is dict and item.get("type") != "null"),
        None,
    )
    if typed is None:
        raise ValueError(f"schema {location} anyOf has no non-null alternative")
    properties[field] = typed


def _forbid_null_root(schema: dict[str, Any], field: str) -> None:
    location = f"properties.{field}"
    properties = schema.get("properties")
    if type(properties) is not dict:
        raise ValueError(f"schema is missing {location} properties")
    value = properties.get(field)
    if type(value) is not dict:
        raise ValueError(f"schema is missing {location}")
    alternatives = value.get("anyOf")
    if type(alternatives) is not list:
        raise ValueError(f"schema {location} is not an anyOf union")
    typed = next(
        (item for item in alternatives if type(item) is dict and item.get("type") != "null"),
        None,
    )
    if typed is None:
        raise ValueError(f"schema {location} anyOf has no non-null alternative")
    properties[field] = typed


def _patch_ledger(schema: dict[str, Any]) -> None:
    _forbid_null_optional(schema, "ProposalLedgerEntry", "acceptedByDecisionId")
    _forbid_null_optional(schema, "ProposalLedgerEntry", "supersededByProposalId")
    _forbid_null_optional(schema, "QuestionLedgerEntry", "relatedProposalId")
    _forbid_null_optional(schema, "QuestionLedgerEntry", "answerEventId")
    _forbid_null_optional(schema, "QuestionLedgerEntry", "answerSequence")
    _forbid_null_optional(schema, "QuestionLedgerEntry", "answer")
    _forbid_null_optional(schema, "QuestionLedgerEntry", "rights")
    _patch_question_ledger_status(schema)
    _patch_answer_exclusive(schema)
    _patch_unknown_rights(schema)


def _patch_proposal_request(schema: dict[str, Any]) -> None:
    _forbid_null_optional(schema, "ProposalPrediction", "metric")
    _forbid_null_optional(schema, "ProposalRequestActor", "modelId")


def _patch_dissent_request(schema: dict[str, Any]) -> None:
    _forbid_null_optional(schema, "ProposalRequestActor", "modelId")


def _patch_question_ask_request(schema: dict[str, Any]) -> None:
    _forbid_null_optional(schema, "QuestionRequestActor", "modelId")
    _forbid_null_root(schema, "options")
    _forbid_null_root(schema, "relatedProposalId")


def _patch_question_answer_request(schema: dict[str, Any]) -> None:
    _patch_answer_exclusive(schema)
    _patch_unknown_rights(schema)


def _patch_question_ledger_status(schema: dict[str, Any]) -> None:
    definitions = schema.get("$defs")
    if type(definitions) is not dict:
        raise ValueError("schema is missing $defs while patching question status")
    binding = definitions.get("QuestionLedgerEntry")
    if type(binding) is not dict:
        raise ValueError("schema is missing QuestionLedgerEntry")
    extra = [
        {
            "if": {"properties": {"status": {"const": "open"}}, "required": ["status"]},
            "then": {
                "not": {
                    "anyOf": [
                        {"required": ["answer"]},
                        {"required": ["rights"]},
                        {"required": ["answerEventId"]},
                        {"required": ["answerSequence"]},
                    ]
                }
            },
        },
        {
            "if": {"properties": {"status": {"const": "answered"}}, "required": ["status"]},
            "then": {
                "required": ["answer", "rights", "answerEventId", "answerSequence"],
            },
        },
    ]
    existing = binding.get("allOf")
    if type(existing) is list:
        binding["allOf"] = [*existing, *extra]
    else:
        binding["allOf"] = extra


def _patch_answer_exclusive(schema: dict[str, Any]) -> None:
    definitions = schema.get("$defs")
    if type(definitions) is not dict:
        raise ValueError("schema is missing $defs while patching answer exclusivity")
    binding = definitions.get("QuestionAnswerValue")
    if type(binding) is not dict:
        raise ValueError("schema is missing QuestionAnswerValue")
    properties = binding.get("properties")
    if type(properties) is not dict:
        raise ValueError("schema QuestionAnswerValue is missing properties")
    text = properties.get("text")
    option = properties.get("option")
    if type(text) is not dict or type(option) is not dict:
        raise ValueError("schema QuestionAnswerValue is missing text or option")
    text_schema = _non_null_schema(text)
    option_schema = _non_null_schema(option)
    definitions["QuestionAnswerValue"] = {
        "oneOf": [
            {
                "additionalProperties": False,
                "properties": {"text": text_schema},
                "required": ["text"],
                "type": "object",
            },
            {
                "additionalProperties": False,
                "properties": {"option": option_schema},
                "required": ["option"],
                "type": "object",
            },
        ]
    }


def _patch_unknown_rights(schema: dict[str, Any]) -> None:
    definitions = schema.get("$defs")
    if type(definitions) is not dict:
        raise ValueError("schema is missing $defs while patching unknown rights")
    binding = definitions.get("AnswerRights")
    if type(binding) is not dict:
        raise ValueError("schema is missing AnswerRights")
    binding["not"] = {
        "properties": {
            "allowedUses": {"contains": {"enum": ["redistribution", "training"]}},
            "status": {"const": "unknown"},
        },
        "required": ["allowedUses", "status"],
    }


def _non_null_schema(value: dict[str, Any]) -> dict[str, Any]:
    alternatives = value.get("anyOf")
    if type(alternatives) is not list:
        return value
    typed = next(
        (item for item in alternatives if type(item) is dict and item.get("type") != "null"),
        None,
    )
    if typed is None:
        raise ValueError("optional field anyOf has no non-null alternative")
    return typed


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


def build_question_ask_request_schema() -> dict[str, Any]:
    return _build(
        QuestionAskRequestDocument,
        QUESTION_ASK_REQUEST_SCHEMA_ID,
        _patch_question_ask_request,
    )


def canonical_question_ask_request_schema() -> str:
    return _canonical(build_question_ask_request_schema())


def write_question_ask_request_schema(path: str | Path) -> None:
    _write(build_question_ask_request_schema(), path)


def question_ask_request_schema_matches(path: str | Path) -> bool:
    return _matches(build_question_ask_request_schema(), path)


def build_question_answer_request_schema() -> dict[str, Any]:
    return _build(
        QuestionAnswerRequestDocument,
        QUESTION_ANSWER_REQUEST_SCHEMA_ID,
        _patch_question_answer_request,
    )


def canonical_question_answer_request_schema() -> str:
    return _canonical(build_question_answer_request_schema())


def write_question_answer_request_schema(path: str | Path) -> None:
    _write(build_question_answer_request_schema(), path)


def question_answer_request_schema_matches(path: str | Path) -> bool:
    return _matches(build_question_answer_request_schema(), path)
