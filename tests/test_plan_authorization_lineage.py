from __future__ import annotations

import json
import sqlite3
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from llm_research_os.blocks.registry import build_registry
from llm_research_os.execution import (
    PLAN_AUTHORIZATION_LINEAGE_API_VERSION,
    PLAN_AUTHORIZATION_LINEAGE_QUERY_SCHEMA_ID,
    PlanAuthorizationLineageError,
    PlanAuthorizationLineageQueryDocument,
    PlanAuthorizationPolicy,
    PlanAuthorizationResult,
    PlanAuthorizationStatus,
    TrustedKernel,
    authorize_plan,
    load_plan_authorization_lineage_query,
    load_plan_authorization_request,
    query_plan_authorization_lineage,
    record_plan_authorization_event,
    validate_plan_authorization_event_request_document,
    validate_plan_authorization_lineage_query_document,
    validate_plan_authorization_lineage_report_document,
)
from llm_research_os.execution.authorization_lineage import (
    forbid_null_optional_digest,
)
from llm_research_os.execution.authorization_lineage_query_schema import (
    build_schema,
    canonical_schema,
)
from llm_research_os.execution.authorization_lineage_report_schema import (
    build_schema as build_report_schema,
)
from llm_research_os.execution.authorization_lineage_report_schema import (
    canonical_schema as canonical_report_schema,
)
from llm_research_os.execution.models import DryRunReport
from llm_research_os.spec.io import SpecLoadError, load_document, load_spec
from llm_research_os.storage import EventIntegrityError, EventStore

ROOT = Path(__file__).parents[1]
SPEC = ROOT / "examples" / "valid" / "minimal.yaml"
AUTHORIZATION_REQUEST = ROOT / "examples" / "plan-authorization-requests" / "valid" / "minimal.json"
EVENT_REQUEST = ROOT / "examples" / "plan-authorization-events" / "valid" / "minimal.json"
QUERY = ROOT / "examples" / "plan-authorization-lineage" / "valid" / "minimal.json"
PLAN_IDENTITY_QUERY = (
    ROOT / "examples" / "plan-authorization-lineage" / "valid" / "plan-identity.json"
)
INVALID_QUERIES = ROOT / "examples" / "plan-authorization-lineage" / "invalid"
QUERY_SCHEMA = ROOT / "schemas" / "plan-authorization-lineage-query" / "v0alpha1.schema.json"
REPORT_SCHEMA = ROOT / "schemas" / "plan-authorization-lineage-report" / "v0alpha1.schema.json"
PROTOCOL = ROOT / "docs" / "protocols" / "plan-authorization-lineage-v0alpha1.md"
UNRELATED_EVENT = ROOT / "examples" / "events" / "valid" / "minimal.json"
ZERO_DIGEST = "sha256:" + "0" * 64


def _authorization() -> tuple[DryRunReport, PlanAuthorizationPolicy, PlanAuthorizationResult]:
    report = TrustedKernel(build_registry()).dry_run(load_spec(SPEC))
    request = load_plan_authorization_request(AUTHORIZATION_REQUEST)
    policy = request.policy()
    return report, policy, authorize_plan(report, policy)


def _event_request_for(
    report: DryRunReport,
    result: PlanAuthorizationResult,
    *,
    event_id: str = "evt.authorization.test",
    event_time: str = "2026-09-02T05:00:00Z",
) -> Any:
    document = load_document(EVENT_REQUEST)
    document["projectId"] = str(report.project.id)
    document["experimentRevision"] = report.project.revision
    document["workflowId"] = str(report.workflow_id)
    document["event"] = {"id": event_id, "time": event_time}
    document["binding"] = {
        "specDigest": result.spec_digest,
        "registryDigest": result.registry_digest,
        "planDigest": result.plan_digest,
        "decisionDigest": result.decision_digest,
    }
    return validate_plan_authorization_event_request_document(document)


def _query_for(
    report: DryRunReport,
    result: PlanAuthorizationResult,
    *,
    include_decision: bool = True,
) -> PlanAuthorizationLineageQueryDocument:
    document = load_document(QUERY if include_decision else PLAN_IDENTITY_QUERY)
    document["projectId"] = str(report.project.id)
    document["experimentRevision"] = report.project.revision
    document["workflowId"] = str(report.workflow_id)
    binding = {
        "specDigest": result.spec_digest,
        "registryDigest": result.registry_digest,
        "planDigest": result.plan_digest,
    }
    if include_decision:
        binding["decisionDigest"] = result.decision_digest
    document["binding"] = binding
    return validate_plan_authorization_lineage_query_document(document)


def _record_unrelated_event(store: EventStore) -> None:
    document = json.loads(UNRELATED_EVENT.read_text(encoding="utf-8"))
    document.pop("sequence", None)
    document.pop("sequencetype", None)
    document.pop("streamversion", None)
    store.append(document)


def test_query_schema_is_closed_strict_versioned_and_current() -> None:
    schema = build_schema()
    assert schema["$id"] == PLAN_AUTHORIZATION_LINEAGE_QUERY_SCHEMA_ID
    assert schema["properties"]["apiVersion"]["const"] == PLAN_AUTHORIZATION_LINEAGE_API_VERSION
    assert schema["properties"]["kind"]["const"] == "PlanAuthorizationLineageQuery"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "apiVersion",
        "kind",
        "projectId",
        "experimentRevision",
        "workflowId",
        "binding",
    }
    assert "decisionDigest" not in schema["$defs"]["PlanAuthorizationLineageBinding"]["required"]
    digest = schema["$defs"]["PlanAuthorizationLineageBinding"]["properties"]["decisionDigest"]
    assert digest["type"] == "string"
    assert "anyOf" not in digest
    assert QUERY_SCHEMA.read_text(encoding="utf-8") == canonical_schema()
    Draft202012Validator.check_schema(schema)


def test_forbid_null_optional_digest_fails_closed_on_unexpected_shape() -> None:
    with pytest.raises(ValueError, match="missing"):
        forbid_null_optional_digest({}, "PlanAuthorizationLineageBinding", "decisionDigest")
    with pytest.raises(ValueError, match="anyOf"):
        forbid_null_optional_digest(
            {
                "$defs": {
                    "PlanAuthorizationLineageBinding": {
                        "properties": {"decisionDigest": {"type": "string"}},
                    }
                }
            },
            "PlanAuthorizationLineageBinding",
            "decisionDigest",
        )
    with pytest.raises(ValueError, match="string alternative"):
        forbid_null_optional_digest(
            {
                "$defs": {
                    "PlanAuthorizationLineageBinding": {
                        "properties": {"decisionDigest": {"anyOf": [{"type": "null"}]}},
                    }
                }
            },
            "PlanAuthorizationLineageBinding",
            "decisionDigest",
        )
    schema = {
        "$defs": {
            "PlanAuthorizationLineageBinding": {
                "properties": {
                    "decisionDigest": {
                        "anyOf": [{"type": "string", "pattern": "x"}, {"type": "null"}],
                    }
                }
            }
        }
    }
    forbid_null_optional_digest(schema, "PlanAuthorizationLineageBinding", "decisionDigest")
    assert schema["$defs"]["PlanAuthorizationLineageBinding"]["properties"]["decisionDigest"] == {
        "type": "string",
        "pattern": "x",
    }


def test_report_schema_is_closed_strict_versioned_and_current() -> None:
    schema = build_report_schema()
    assert schema["properties"]["kind"]["const"] == "PlanAuthorizationLineageReport"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["authority"]["const"] == "audit-only"
    assert schema["properties"]["runtimeConsumption"]["const"] == "not-consumed"
    assert schema["properties"]["execution"]["const"] == "not-executed"
    digest = schema["$defs"]["PlanAuthorizationLineageBinding"]["properties"]["decisionDigest"]
    assert digest["type"] == "string"
    assert "anyOf" not in digest
    assert REPORT_SCHEMA.read_text(encoding="utf-8") == canonical_report_schema()
    Draft202012Validator.check_schema(schema)


def test_valid_query_round_trips_without_aliasing_input() -> None:
    document = load_document(QUERY)
    query = validate_plan_authorization_lineage_query_document(document)
    assert query.model_dump(mode="json", by_alias=True, exclude_none=True) == document
    document["binding"]["decisionDigest"] = ZERO_DIGEST
    assert query.binding.decision_digest != ZERO_DIGEST
    with pytest.raises((FrozenInstanceError, ValidationError)):
        query.project_id = "changed"  # type: ignore[misc]


def test_plan_identity_query_omits_decision_digest() -> None:
    query = load_plan_authorization_lineage_query(PLAN_IDENTITY_QUERY)
    assert query.binding.decision_digest is None
    dumped = query.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert "decisionDigest" not in dumped["binding"]


def test_protocol_normative_queries_match_committed_examples() -> None:
    protocol = PROTOCOL.read_text(encoding="utf-8")
    for path in (QUERY, PLAN_IDENTITY_QUERY):
        rendered = json.dumps(load_document(path), ensure_ascii=False, indent=2)
        assert rendered in protocol


@pytest.mark.parametrize(
    "name",
    ("coerced-revision.json", "unknown-field.json", "null-decision-digest.json"),
)
def test_committed_invalid_examples_fail_schema_and_reference_validation(name: str) -> None:
    document = load_document(INVALID_QUERIES / name)
    assert list(Draft202012Validator(build_schema()).iter_errors(document))
    with pytest.raises(ValidationError):
        validate_plan_authorization_lineage_query_document(document)


def test_query_loader_rejects_symlinks_duplicates_and_yaml_aliases(tmp_path: Path) -> None:
    link = tmp_path / "query.json"
    link.symlink_to(QUERY)
    with pytest.raises(SpecLoadError, match="symbolic link"):
        load_plan_authorization_lineage_query(link)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"kind":"PlanAuthorizationLineageQuery","kind":"changed"}',
        encoding="utf-8",
    )
    with pytest.raises(SpecLoadError, match="duplicate JSON object key"):
        load_plan_authorization_lineage_query(duplicate)

    alias = tmp_path / "alias.yaml"
    alias.write_text("refs: &refs\n  - evidence.1\ncopy: *refs\n", encoding="utf-8")
    with pytest.raises(SpecLoadError, match="aliases are not supported"):
        load_plan_authorization_lineage_query(alias)


def test_recorded_authorized_fact_is_located_by_four_digest_query(tmp_path: Path) -> None:
    report, policy, authorization = _authorization()
    query = _query_for(report, authorization)
    with EventStore(tmp_path / "events.db") as store:
        recorded = record_plan_authorization_event(
            store,
            report,
            policy,
            _event_request_for(report, authorization),
        )
        reconstructed = query_plan_authorization_lineage(store, query)

    assert reconstructed.match_count == 1
    assert reconstructed.high_water_sequence == 1
    match = reconstructed.matches[0]
    assert match.event_id == recorded.stored.event.id
    assert match.sequence == 1
    assert match.status is PlanAuthorizationStatus.AUTHORIZED
    assert match.authorized is True
    assert match.binding.decision_digest == authorization.decision_digest
    assert match.approval_authentication == "not-authenticated"
    assert match.authority == "audit-only"
    assert match.execution == "not-executed"
    assert reconstructed.runtime_consumption == "not-consumed"
    assert reconstructed.persistence == "read-only"
    assert reconstructed.side_effects.persistent_writes == 0
    validate_plan_authorization_lineage_report_document(
        reconstructed.model_dump(mode="json", by_alias=True, exclude_none=True)
    )
    Draft202012Validator(build_report_schema()).validate(
        reconstructed.model_dump(mode="json", by_alias=True, exclude_none=True)
    )


def test_plan_identity_query_returns_every_evaluation_of_the_same_plan(
    tmp_path: Path,
) -> None:
    report, authorized_policy, authorized = _authorization()
    denied_document = load_document(AUTHORIZATION_REQUEST)
    denied_document["grantedCapabilities"] = []
    denied_path = tmp_path / "denied.json"
    denied_path.write_text(json.dumps(denied_document), encoding="utf-8")
    denied_policy = load_plan_authorization_request(denied_path).policy()
    denied = authorize_plan(report, denied_policy)
    query = _query_for(report, authorized, include_decision=False)

    with EventStore(tmp_path / "events.db") as store:
        record_plan_authorization_event(
            store,
            report,
            authorized_policy,
            _event_request_for(report, authorized, event_id="evt.authorization.authorized"),
        )
        record_plan_authorization_event(
            store,
            report,
            denied_policy,
            _event_request_for(report, denied, event_id="evt.authorization.denied"),
        )
        reconstructed = query_plan_authorization_lineage(store, query)

    assert reconstructed.match_count == 2
    assert [match.status for match in reconstructed.matches] == [
        PlanAuthorizationStatus.AUTHORIZED,
        PlanAuthorizationStatus.DENIED,
    ]
    assert reconstructed.matches[0].sequence < reconstructed.matches[1].sequence


def test_decision_digest_filter_excludes_other_evaluations_of_the_same_plan(
    tmp_path: Path,
) -> None:
    report, authorized_policy, authorized = _authorization()
    denied_document = load_document(AUTHORIZATION_REQUEST)
    denied_document["grantedCapabilities"] = []
    denied_path = tmp_path / "denied.json"
    denied_path.write_text(json.dumps(denied_document), encoding="utf-8")
    denied_policy = load_plan_authorization_request(denied_path).policy()
    denied = authorize_plan(report, denied_policy)
    query = _query_for(report, authorized, include_decision=True)

    with EventStore(tmp_path / "events.db") as store:
        record_plan_authorization_event(
            store,
            report,
            authorized_policy,
            _event_request_for(report, authorized, event_id="evt.authorization.authorized"),
        )
        record_plan_authorization_event(
            store,
            report,
            denied_policy,
            _event_request_for(report, denied, event_id="evt.authorization.denied"),
        )
        reconstructed = query_plan_authorization_lineage(store, query)

    assert reconstructed.match_count == 1
    assert reconstructed.matches[0].status is PlanAuthorizationStatus.AUTHORIZED


def test_legacy_digest_tag_does_not_match_recomputed_jcs_digest(tmp_path: Path) -> None:
    report, policy, authorization = _authorization()
    query = _query_for(report, authorization)
    legacy = query.model_copy(
        update={
            "binding": query.binding.model_copy(
                update={
                    "decision_digest": authorization.decision_digest.replace(
                        "jcs-sha256:",
                        "sha256:",
                    )
                }
            )
        }
    )
    with EventStore(tmp_path / "events.db") as store:
        record_plan_authorization_event(
            store,
            report,
            policy,
            _event_request_for(report, authorization),
        )
        reconstructed = query_plan_authorization_lineage(store, legacy)

    assert reconstructed.match_count == 0
    assert reconstructed.high_water_sequence == 1


def test_unrelated_lifecycle_events_are_skipped(tmp_path: Path) -> None:
    report, policy, authorization = _authorization()
    query = _query_for(report, authorization)
    with EventStore(tmp_path / "events.db") as store:
        _record_unrelated_event(store)
        recorded = record_plan_authorization_event(
            store,
            report,
            policy,
            _event_request_for(report, authorization),
        )
        reconstructed = query_plan_authorization_lineage(store, query)

    assert reconstructed.high_water_sequence == 2
    assert reconstructed.match_count == 1
    assert reconstructed.matches[0].event_id == recorded.stored.event.id
    assert reconstructed.matches[0].sequence == 2


def test_empty_verified_store_returns_zero_matches(tmp_path: Path) -> None:
    report, _policy, authorization = _authorization()
    query = _query_for(report, authorization)
    with EventStore(tmp_path / "events.db") as store:
        reconstructed = query_plan_authorization_lineage(store, query)
        assert store.verify_integrity() == 0

    assert reconstructed.match_count == 0
    assert reconstructed.matches == ()
    assert reconstructed.high_water_sequence == 0
    assert reconstructed.runtime_consumption == "not-consumed"


def test_invalid_authorization_event_fails_closed(tmp_path: Path) -> None:
    report, _policy, authorization = _authorization()
    query = _query_for(report, authorization)
    with EventStore(tmp_path / "events.db") as store:
        store.append(
            {
                "specversion": "1.0",
                "id": "evt.authorization.corrupt",
                "source": "https://researchos.dev/projects/example-minimal",
                "type": "plan.authorization.evaluated",
                "time": "2026-09-02T05:00:00Z",
                "subject": "authorization.corrupt",
                "dataschema": (
                    "https://researchos.dev/schemas/research-event/v0alpha1.schema.json"
                ),
                "datacontenttype": "application/json",
                "streamid": "authorization.example-minimal",
                "data": {
                    "schemaVersion": "v0alpha1",
                    "actor": {"id": "researcher.alice"},
                    "projectId": "example-minimal",
                    "experimentRevision": 1,
                    "payload": {"not": "an-authorization-payload"},
                    "evidenceRefs": [],
                },
            }
        )
        with pytest.raises(PlanAuthorizationLineageError, match="authorization event is invalid"):
            query_plan_authorization_lineage(store, query)


def test_corrupt_store_fails_before_reconstruction(tmp_path: Path) -> None:
    report, policy, authorization = _authorization()
    query = _query_for(report, authorization)
    database = tmp_path / "events.db"
    with EventStore(database) as store:
        record_plan_authorization_event(
            store,
            report,
            policy,
            _event_request_for(report, authorization),
        )

    with sqlite3.connect(database, autocommit=True) as connection:
        trigger_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?",
            ("events_reject_update",),
        ).fetchone()[0]
        connection.execute("DROP TRIGGER events_reject_update")
        connection.execute(
            "UPDATE events SET event_digest = ? WHERE sequence = 1",
            (ZERO_DIGEST,),
        )
        connection.execute(trigger_sql)

    with (
        EventStore(database, create=False) as store,
        pytest.raises(EventIntegrityError, match="digest mismatch"),
    ):
        query_plan_authorization_lineage(store, query)


def test_direct_python_api_revalidates_forged_query(tmp_path: Path) -> None:
    report, policy, authorization = _authorization()
    query = _query_for(report, authorization)
    forged = query.model_copy(
        update={
            "binding": query.binding.model_copy(
                update={"spec_digest": "private-secret-digest-value"}
            )
        }
    )
    with EventStore(tmp_path / "events.db") as store:
        record_plan_authorization_event(
            store,
            report,
            policy,
            _event_request_for(report, authorization),
        )
        with pytest.raises(PlanAuthorizationLineageError, match="query is invalid") as error:
            query_plan_authorization_lineage(store, forged)
        assert "private-secret-digest-value" not in str(error.value)


def test_mismatched_project_or_digest_is_an_empty_candidate_set(tmp_path: Path) -> None:
    report, policy, authorization = _authorization()
    query = _query_for(report, authorization).model_copy(update={"project_id": "other-project"})
    with EventStore(tmp_path / "events.db") as store:
        record_plan_authorization_event(
            store,
            report,
            policy,
            _event_request_for(report, authorization),
        )
        reconstructed = query_plan_authorization_lineage(store, query)

    assert reconstructed.match_count == 0
    assert reconstructed.high_water_sequence == 1
