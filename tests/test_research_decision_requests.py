from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from llm_research_os.research.models import DecisionRecordedPayload, ProposalSubmittedPayload
from llm_research_os.research.requests import (
    DecisionRecordRequestDocument,
    DissentRecordRequestDocument,
    ProposalSubmitRequestDocument,
    load_decision_record_request,
    load_dissent_record_request,
    load_proposal_submit_request,
)
from llm_research_os.research.schema import (
    build_decision_record_request_schema,
    build_dissent_record_request_schema,
    build_proposal_submit_request_schema,
    build_research_ledger_schema,
    decision_record_request_schema_matches,
    dissent_record_request_schema_matches,
    proposal_submit_request_schema_matches,
    schema_matches,
)
from llm_research_os.spec.io import load_document

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples" / "research-decisions"
LEDGER_SCHEMA = ROOT / "schemas" / "research-ledger" / "v0alpha1.schema.json"
PROPOSAL_SCHEMA = ROOT / "schemas" / "proposal-submit-request" / "v0alpha1.schema.json"
DISSENT_SCHEMA = ROOT / "schemas" / "dissent-record-request" / "v0alpha1.schema.json"
DECISION_SCHEMA = ROOT / "schemas" / "decision-record-request" / "v0alpha1.schema.json"


def _validator(path: Path) -> Draft202012Validator:
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def test_committed_research_decision_schemas_are_current() -> None:
    assert schema_matches(LEDGER_SCHEMA)
    assert proposal_submit_request_schema_matches(PROPOSAL_SCHEMA)
    assert dissent_record_request_schema_matches(DISSENT_SCHEMA)
    assert decision_record_request_schema_matches(DECISION_SCHEMA)
    for path in (LEDGER_SCHEMA, PROPOSAL_SCHEMA, DISSENT_SCHEMA, DECISION_SCHEMA):
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_ledger_schema_keeps_questions_empty() -> None:
    schema = build_research_ledger_schema()
    questions = schema["properties"]["questions"]
    assert questions["maxItems"] == 0
    assert questions["minItems"] == 0


def test_optional_metric_rejects_json_null() -> None:
    schema = build_proposal_submit_request_schema()
    metric = schema["$defs"]["ProposalPrediction"]["properties"]["metric"]
    assert metric.get("type") == "string"
    assert "anyOf" not in metric


@pytest.mark.parametrize(
    ("path", "model"),
    (
        (EXAMPLES / "valid" / "proposal-submit.json", ProposalSubmitRequestDocument),
        (EXAMPLES / "valid" / "dissent-record.json", DissentRecordRequestDocument),
        (EXAMPLES / "valid" / "decision-record.json", DecisionRecordRequestDocument),
    ),
    ids=("proposal", "dissent", "decision"),
)
def test_valid_research_decision_examples(path: Path, model: type[object]) -> None:
    document = load_document(path)
    schema_path = {
        "ProposalSubmitRequest": PROPOSAL_SCHEMA,
        "DissentRecordRequest": DISSENT_SCHEMA,
        "DecisionRecordRequest": DECISION_SCHEMA,
    }[document["kind"]]
    _validator(schema_path).validate(document)
    model.model_validate(document)  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "path",
    sorted((EXAMPLES / "invalid").glob("*.json")),
    ids=lambda p: p.name,
)
def test_invalid_research_decision_examples(path: Path) -> None:
    document = load_document(path)
    loaders = {
        "ProposalSubmitRequest": (
            load_proposal_submit_request,
            build_proposal_submit_request_schema,
            ProposalSubmitRequestDocument,
        ),
        "DissentRecordRequest": (
            load_dissent_record_request,
            build_dissent_record_request_schema,
            DissentRecordRequestDocument,
        ),
        "DecisionRecordRequest": (
            load_decision_record_request,
            build_decision_record_request_schema,
            DecisionRecordRequestDocument,
        ),
    }
    _load, build, model = loaders[document["kind"]]
    assert list(Draft202012Validator(build()).iter_errors(document))
    with pytest.raises(ValidationError):
        model.model_validate(document)
    with pytest.raises(Exception, match="research request failed validation"):
        _load(path)


def test_empty_rationale_is_rejected() -> None:
    document = load_document(EXAMPLES / "invalid" / "decision-empty-rationale.json")
    with pytest.raises(ValidationError):
        DecisionRecordRequestDocument.model_validate(document)
    with pytest.raises(ValidationError):
        DecisionRecordedPayload.model_validate(
            {
                "decisionId": "decision.empty",
                "targetKind": "proposal",
                "targetId": "proposal.revise-eval",
                "outcome": "accept",
                "rationale": "",
                "overriddenDissentIds": [],
                "evidenceRefs": [],
            }
        )


def test_proposal_payload_requires_at_least_one_prediction() -> None:
    with pytest.raises(ValidationError):
        ProposalSubmittedPayload.model_validate(
            {
                "proposalId": "proposal.empty",
                "baseRevision": 1,
                "specDiffDigest": "jcs-sha256:" + "11" * 32,
                "proposedSpecDigest": "jcs-sha256:" + "22" * 32,
                "rationale": "Missing predictions.",
                "predictions": [],
                "falsificationConditions": ["No predictions."],
                "riskAssessment": {"data": "", "method": "", "safety": "", "cost": ""},
                "evidenceRefs": [],
            }
        )
