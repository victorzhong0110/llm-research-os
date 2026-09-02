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
from llm_research_os.events.models import ResearchEvent
from llm_research_os.execution import (
    PLAN_AUTHORIZATION_EVALUATED_TYPE,
    PLAN_AUTHORIZATION_EVENT_API_VERSION,
    PLAN_AUTHORIZATION_EVENT_REQUEST_SCHEMA_ID,
    PlanAuthorizationEventRequestDocument,
    PlanAuthorizationPolicy,
    PlanAuthorizationRecordError,
    PlanAuthorizationResult,
    PlanAuthorizationStatus,
    TrustedKernel,
    authorize_plan,
    load_plan_authorization_event_request,
    load_plan_authorization_request,
    record_plan_authorization_event,
    validate_plan_authorization_evaluated_event,
    validate_plan_authorization_event_request_document,
)
from llm_research_os.execution.authorization_event_request_schema import (
    build_schema,
    canonical_schema,
)
from llm_research_os.execution.models import DryRunReport
from llm_research_os.spec.io import SpecLoadError, load_document, load_spec
from llm_research_os.storage import (
    EventIntegrityError,
    EventSequenceConflictError,
    EventStore,
)

ROOT = Path(__file__).parents[1]
SPEC = ROOT / "examples" / "valid" / "minimal.yaml"
AUTHORIZATION_REQUEST = ROOT / "examples" / "plan-authorization-requests" / "valid" / "minimal.json"
EVENT_REQUEST = ROOT / "examples" / "plan-authorization-events" / "valid" / "minimal.json"
INVALID_REQUESTS = ROOT / "examples" / "plan-authorization-events" / "invalid"
REQUEST_SCHEMA = ROOT / "schemas" / "plan-authorization-event-request" / "v0alpha1.schema.json"
PROTOCOL = ROOT / "docs" / "protocols" / "plan-authorization-event-v0alpha1.md"
ZERO_DIGEST = "sha256:" + "0" * 64


def _authorization() -> tuple[DryRunReport, PlanAuthorizationPolicy, PlanAuthorizationResult]:
    report = TrustedKernel(build_registry()).dry_run(load_spec(SPEC))
    request = load_plan_authorization_request(AUTHORIZATION_REQUEST)
    policy = request.policy()
    return report, policy, authorize_plan(report, policy)


def _request_for(
    report: DryRunReport,
    result: PlanAuthorizationResult,
    *,
    event_id: str = "evt.authorization.test",
    event_time: str = "2026-09-02T05:00:00Z",
) -> PlanAuthorizationEventRequestDocument:
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


def test_request_schema_is_closed_strict_versioned_and_current() -> None:
    schema = build_schema()
    assert schema["$id"] == PLAN_AUTHORIZATION_EVENT_REQUEST_SCHEMA_ID
    assert schema["properties"]["apiVersion"]["const"] == PLAN_AUTHORIZATION_EVENT_API_VERSION
    assert schema["properties"]["kind"]["const"] == "PlanAuthorizationEventRequest"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "apiVersion",
        "kind",
        "projectId",
        "experimentRevision",
        "workflowId",
        "binding",
        "source",
        "subject",
        "streamid",
        "actor",
        "event",
        "evidenceRefs",
    }
    assert schema["properties"]["evidenceRefs"]["uniqueItems"] is True
    assert REQUEST_SCHEMA.read_text(encoding="utf-8") == canonical_schema()
    Draft202012Validator.check_schema(schema)


def test_valid_request_round_trips_without_aliasing_input() -> None:
    document = load_document(EVENT_REQUEST)
    request = validate_plan_authorization_event_request_document(document)
    assert request.model_dump(mode="json", by_alias=True) == document
    assert request.evidence_refs == ()
    document["binding"]["decisionDigest"] = ZERO_DIGEST
    document["actor"]["id"] = "changed"
    assert request.binding.decision_digest != ZERO_DIGEST
    assert request.actor.id == "researcher.alice"
    with pytest.raises((FrozenInstanceError, ValidationError)):
        request.project_id = "changed"  # type: ignore[misc]


def test_protocol_normative_request_matches_committed_example() -> None:
    rendered = json.dumps(load_document(EVENT_REQUEST), ensure_ascii=False, indent=2)
    assert rendered in PROTOCOL.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ("coerced-revision.json", "unknown-field.json"))
def test_committed_invalid_examples_fail_schema_and_reference_validation(name: str) -> None:
    document = load_document(INVALID_REQUESTS / name)
    assert list(Draft202012Validator(build_schema()).iter_errors(document))
    with pytest.raises(ValidationError):
        validate_plan_authorization_event_request_document(document)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.__setitem__("unknown", True),
        lambda value: value.__setitem__("experimentRevision", True),
        lambda value: value.__setitem__("evidenceRefs", ()),
        lambda value: value.__setitem__("evidenceRefs", ["evidence.1", "evidence.1"]),
        lambda value: value["binding"].__setitem__("decisionDigest", "invalid"),
        lambda value: value["actor"].__setitem__("id", 1),
        lambda value: value["event"].__setitem__("time", "2026-09-02"),
    ),
)
def test_request_rejects_unknown_coerced_duplicate_or_malformed_input(mutate: Any) -> None:
    document = load_document(EVENT_REQUEST)
    mutate(document)
    assert list(Draft202012Validator(build_schema()).iter_errors(document))
    with pytest.raises(ValidationError):
        validate_plan_authorization_event_request_document(document)


def test_request_loader_rejects_symlinks_duplicates_and_yaml_aliases(tmp_path: Path) -> None:
    link = tmp_path / "request.json"
    link.symlink_to(EVENT_REQUEST)
    with pytest.raises(SpecLoadError, match="symbolic link"):
        load_plan_authorization_event_request(link)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"kind":"PlanAuthorizationEventRequest","kind":"changed"}',
        encoding="utf-8",
    )
    with pytest.raises(SpecLoadError, match="duplicate JSON object key"):
        load_plan_authorization_event_request(duplicate)

    alias = tmp_path / "alias.yaml"
    alias.write_text("refs: &refs\n  - evidence.1\ncopy: *refs\n", encoding="utf-8")
    with pytest.raises(SpecLoadError, match="aliases are not supported"):
        load_plan_authorization_event_request(alias)


def test_direct_python_api_revalidates_forged_request_before_write(tmp_path: Path) -> None:
    report, policy, authorization = _authorization()
    request = _request_for(report, authorization)
    forged = request.model_copy(update={"evidence_refs": ("private-evidence", "private-evidence")})

    with EventStore(tmp_path / "events.db") as store:
        with pytest.raises(PlanAuthorizationRecordError, match="request is invalid") as error:
            record_plan_authorization_event(store, report, policy, forged)
        assert "private-evidence" not in str(error.value)
        assert store.verify_integrity() == 0


def test_authorized_decision_is_recorded_as_one_audit_only_event(tmp_path: Path) -> None:
    report, policy, authorization = _authorization()
    request = _request_for(report, authorization)
    database = tmp_path / "events.db"
    with EventStore(database) as store:
        recorded = record_plan_authorization_event(store, report, policy, request)
        assert store.verify_integrity() == 1
        replayed = store.get_event(recorded.stored.event.id)

    assert replayed == recorded.stored
    event = recorded.stored.event
    payload = validate_plan_authorization_evaluated_event(event)
    assert recorded.authorization.status is PlanAuthorizationStatus.AUTHORIZED
    assert event.type == PLAN_AUTHORIZATION_EVALUATED_TYPE
    assert event.sequence == "1"
    assert event.streamversion == 0
    assert event.data.project_id == "example-minimal"
    assert event.data.experiment_revision == 1
    assert event.data.run_id is None
    assert event.data.attempt_id is None
    assert event.data.block_id is None
    assert payload.status is PlanAuthorizationStatus.AUTHORIZED
    assert payload.authorized is True
    assert payload.binding.decision_digest == authorization.decision_digest
    assert payload.approval_authentication == "not-authenticated"
    assert payload.authority == "audit-only"
    assert payload.execution == "not-executed"


def test_domain_validator_rejects_tampered_decision_payload() -> None:
    report, _policy, authorization = _authorization()
    request = _request_for(report, authorization)
    document = request.event_draft(authorization)
    document.update({"sequence": "1", "sequencetype": "Integer", "streamversion": 0})
    document["data"]["payload"]["binding"]["decisionDigest"] = ZERO_DIGEST
    event = ResearchEvent.model_validate(document)
    with pytest.raises(PlanAuthorizationRecordError, match="payload is invalid"):
        validate_plan_authorization_evaluated_event(event)


@pytest.mark.parametrize(
    "field",
    (
        "spec_digest",
        "registry_digest",
        "plan_digest",
        "decision_digest",
    ),
)
def test_every_decision_binding_mismatch_fails_before_write(
    tmp_path: Path,
    field: str,
) -> None:
    report, policy, authorization = _authorization()
    request = _request_for(report, authorization)
    binding = request.binding.model_copy(update={field: ZERO_DIGEST})
    stale = request.model_copy(update={"binding": binding})
    with EventStore(tmp_path / "events.db") as store:
        with pytest.raises(PlanAuthorizationRecordError, match="recomputed decision"):
            record_plan_authorization_event(store, report, policy, stale)
        assert store.verify_integrity() == 0


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("project_id", "other-project"),
        ("experiment_revision", 2),
        ("workflow_id", "other-workflow"),
    ),
)
def test_revision_identity_mismatch_fails_before_write(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    report, policy, authorization = _authorization()
    request = _request_for(report, authorization).model_copy(update={field: value})
    with EventStore(tmp_path / "events.db") as store:
        with pytest.raises(PlanAuthorizationRecordError, match="planned revision"):
            record_plan_authorization_event(store, report, policy, request)
        assert store.verify_integrity() == 0


def test_denied_decision_is_recorded_without_becoming_authority(tmp_path: Path) -> None:
    document = load_document(AUTHORIZATION_REQUEST)
    document["grantedCapabilities"] = []
    path = tmp_path / "denied.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    report = TrustedKernel(build_registry()).dry_run(load_spec(SPEC))
    authorization_request = load_plan_authorization_request(path)
    policy = authorization_request.policy()
    authorization = authorize_plan(report, policy)
    request = _request_for(report, authorization, event_id="evt.authorization.denied")

    with EventStore(tmp_path / "events.db") as store:
        recorded = record_plan_authorization_event(store, report, policy, request)

    payload = validate_plan_authorization_evaluated_event(recorded.stored.event)
    assert payload.status is PlanAuthorizationStatus.DENIED
    assert payload.authorized is False
    assert payload.missing_capabilities == ("simulate",)
    assert payload.authority == "audit-only"


def test_corrupt_existing_store_is_rejected_before_append(tmp_path: Path) -> None:
    report, policy, authorization = _authorization()
    first = _request_for(report, authorization, event_id="evt.authorization.first")
    second = _request_for(report, authorization, event_id="evt.authorization.second")
    database = tmp_path / "events.db"
    with EventStore(database) as store:
        record_plan_authorization_event(store, report, policy, first)

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

    with EventStore(database) as store:
        with pytest.raises(EventIntegrityError, match="digest mismatch"):
            record_plan_authorization_event(store, report, policy, second)
        assert store.last_sequence() == 1


def test_concurrent_append_causes_cas_conflict_without_retry(tmp_path: Path) -> None:
    report, policy, authorization = _authorization()
    request = _request_for(report, authorization, event_id="evt.authorization.requested")
    with EventStore(tmp_path / "events.db") as store:
        original_append = store.append
        calls = 0

        def competing_append(
            document: dict[str, Any],
            *,
            expected_last_sequence: int | None = None,
        ) -> object:
            nonlocal calls
            calls += 1
            competing = request.event_draft(authorization)
            competing["id"] = "evt.authorization.competing"
            original_append(competing)
            return original_append(
                document,
                expected_last_sequence=expected_last_sequence,
            )

        store.append = competing_append  # type: ignore[method-assign]
        with pytest.raises(EventSequenceConflictError):
            record_plan_authorization_event(store, report, policy, request)
        assert calls == 1
        assert store.verify_integrity() == 1
