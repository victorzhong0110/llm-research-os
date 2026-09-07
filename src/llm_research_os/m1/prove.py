"""One-command M1 research chain. Issue #38 stays open until a human closes it."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from llm_research_os.blocks.registry import BlockRegistry, build_registry
from llm_research_os.canonical import content_digest
from llm_research_os.execution import (
    SimulatedRuntime,
    TrustedKernel,
    authorize_plan,
    record_plan_authorization_event,
    validate_plan_authorization_event_request_document,
    validate_simulation_request_document,
)
from llm_research_os.execution.authorization_documents import load_plan_authorization_request
from llm_research_os.execution.models import DryRunReport, DryRunStatus
from llm_research_os.execution.request import SimulationRequestDocument
from llm_research_os.execution.simulated import SimulationDisposition
from llm_research_os.internal.jsonclone import snapshot_json_document
from llm_research_os.m1.errors import M1CheckpointError
from llm_research_os.projections.replay import replay_events
from llm_research_os.providers.control import ModelCallControl
from llm_research_os.providers.mock import DeterministicMockProvider
from llm_research_os.providers.requests import load_model_fixture, validate_model_generate_request
from llm_research_os.report import build_run_report, render_markdown
from llm_research_os.research.control import ResearchControl
from llm_research_os.research.models import DecisionOutcome, ResearchLedger
from llm_research_os.research.requests import (
    load_decision_record_request,
    load_dissent_record_request,
    load_question_answer_request,
    load_question_ask_request,
    validate_proposal_submit_request,
)
from llm_research_os.runs.models import TYPE_RUN_QUEUED
from llm_research_os.spec.io import load_document, load_spec
from llm_research_os.spec.models import ResearchSpec
from llm_research_os.storage import EventStore
from llm_research_os.storage.models import StoredEvent

CheckpointDecision = Literal["accept", "reject"]

_SPEC = "spec.yaml"
_FIXTURE = "fixture.json"
_GENERATE = "generate.json"
_DISSENT = "dissent.json"
_QUESTION_ASK = "question-ask.json"
_QUESTION_ANSWER = "question-answer.json"
_DECISION_ACCEPT = "decision-accept.json"
_DECISION_REJECT = "decision-reject.json"
_AUTHORIZATION_REQUEST = "authorization-request.json"
_AUTHORIZATION_EVENT = "authorization-event.json"
_SIMULATION = "simulation.json"


@dataclass(frozen=True, slots=True)
class M1CheckpointResult:
    decision: CheckpointDecision
    project_id: str
    run_id: str | None
    spec_digest: str
    proposed_spec_digest: str
    spec_diff_digest: str
    output_digest: str
    event_types: tuple[str, ...]
    event_ids: tuple[str, ...]
    queued: bool
    decision_count: int
    answered_question_count: int
    rationale_characters: int
    overridden_dissent_count: int
    report_markdown: str | None


def initial_spec_diff_digest(*, spec_digest: str, base_revision: int) -> str:
    """Digest for a proposal that binds the authorized spec without a later revision."""

    return content_digest(
        {
            "kind": "initial-spec",
            "specDigest": spec_digest,
            "baseRevision": base_revision,
        }
    )


def prove_checkpoint(
    corpus: Path,
    database: Path,
    *,
    decision: CheckpointDecision = "accept",
    registry_paths: list[Path] | None = None,
) -> M1CheckpointResult:
    """Record one offline research chain and reopen the store to replay it."""

    spec_path = _corpus_file(corpus, _SPEC)
    fixture_path = _corpus_file(corpus, _FIXTURE)
    generate_path = _corpus_file(corpus, _GENERATE)
    spec = load_spec(spec_path)
    if len(spec.workflows) != 1:
        raise M1CheckpointError(
            "checkpoint spec must contain exactly one workflow",
            code="plan-not-ready",
        )
    workflow_id = spec.workflows[0].id
    registry = build_registry(list(registry_paths or []))
    dry_run = TrustedKernel(registry).dry_run(spec, workflow_id=workflow_id)
    if dry_run.status is not DryRunStatus.READY or dry_run.digests.plan is None:
        raise M1CheckpointError(
            "checkpoint spec did not produce a ready plan",
            code="plan-not-ready",
        )
    fixture = load_model_fixture(fixture_path)
    proposal = validate_proposal_submit_request(fixture.output)
    if proposal.project_id != spec.metadata.id:
        raise M1CheckpointError(
            "proposal projectId does not match the checkpoint spec",
            code="proposal-project-mismatch",
        )
    if proposal.experiment_revision != spec.metadata.revision:
        raise M1CheckpointError(
            "proposal experimentRevision does not match the checkpoint spec",
            code="proposal-project-mismatch",
        )
    if proposal.proposed_spec_digest != dry_run.digests.spec:
        raise M1CheckpointError(
            "fixture proposal is not bound to the live spec digest",
            code="proposal-spec-mismatch",
        )
    expected_diff = initial_spec_diff_digest(
        spec_digest=dry_run.digests.spec,
        base_revision=spec.metadata.revision,
    )
    if proposal.spec_diff_digest != expected_diff:
        raise M1CheckpointError(
            "fixture proposal specDiffDigest is not the live initial-spec digest",
            code="proposal-diff-mismatch",
        )
    generate_document = load_document(generate_path, reject_symlinks=True)
    if type(generate_document) is not dict:
        raise M1CheckpointError(
            "checkpoint generate request must be ModelGenerateRequest",
            code="provider-not-mock",
        )
    if generate_document.get("kind") != "ModelGenerateRequest":
        raise M1CheckpointError(
            "checkpoint generate request must be ModelGenerateRequest",
            code="provider-not-mock",
        )
    generate = validate_model_generate_request(generate_document)
    if generate.fixture_id != fixture.id:
        raise M1CheckpointError(
            "generate request fixtureId does not match the fixture",
            code="fixture-mismatch",
        )
    if generate.project_id != spec.metadata.id:
        raise M1CheckpointError(
            "generate request projectId does not match the checkpoint spec",
            code="proposal-project-mismatch",
        )
    dissent = load_dissent_record_request(_corpus_file(corpus, _DISSENT))
    question = load_question_ask_request(_corpus_file(corpus, _QUESTION_ASK))
    answer = load_question_answer_request(_corpus_file(corpus, _QUESTION_ANSWER))
    decision_name = _DECISION_ACCEPT if decision == "accept" else _DECISION_REJECT
    recorded_decision = load_decision_record_request(_corpus_file(corpus, decision_name))
    if recorded_decision.outcome is not DecisionOutcome(decision):
        raise M1CheckpointError(
            "decision document outcome does not match --decision",
            code="decision-outcome-mismatch",
        )
    project_id = spec.metadata.id
    provider = DeterministicMockProvider({fixture.id: fixture})
    with EventStore(database) as store:
        if store.last_sequence() != 0:
            raise M1CheckpointError(
                "checkpoint database must be empty",
                code="store-not-empty",
            )
        call = ModelCallControl(store, project_id=project_id).record_generate(
            generate,
            fixture,
            provider,
        )
        output_digest = call.completed.event.data.payload.get("outputDigest")
        if type(output_digest) is not str or output_digest != content_digest(fixture.output):
            raise M1CheckpointError(
                "recorded output digest does not match the fixture proposal",
                code="digest-mismatch",
            )
        research = ResearchControl(store, project_id=project_id)
        research.append(proposal.event_draft())
        research.append(dissent.event_draft())
        research.append(question.event_draft())
        research.append(answer.event_draft())
        research.append(recorded_decision.event_draft())
        run_id: str | None = None
        report_markdown: str | None = None
        if decision == "accept":
            run_id, report_markdown = _authorize_and_simulate(
                store,
                corpus=corpus,
                spec=spec,
                dry_run=dry_run,
                workflow_id=workflow_id,
                project_id=project_id,
                registry=registry,
            )
        elif _has_queued_run(store):
            raise M1CheckpointError(
                "reject path queued a Run",
                code="reject-queued",
            )
        types, ids = _recorded_identity(store)
        ledger = research.rebuild().snapshot
    with EventStore(database, require_existing=True) as store:
        replayed_types, replayed_ids = _recorded_identity(store)
        if replayed_types != types or replayed_ids != ids:
            raise M1CheckpointError(
                "reopened store did not replay the same events",
                code="replay-mismatch",
            )
        replayed = ResearchControl(store, project_id=project_id).rebuild().snapshot
        _require_same_ledger(ledger, replayed)
        if decision == "accept":
            if run_id is None:
                raise M1CheckpointError(
                    "accept path did not record a Run",
                    code="accept-not-queued",
                )
            replayed_report = render_markdown(
                build_run_report(store, run_id, project_id=project_id)
            )
            if replayed_report != report_markdown:
                raise M1CheckpointError(
                    "reopened store did not replay the same report",
                    code="replay-mismatch",
                )
        elif _has_queued_run(store):
            raise M1CheckpointError(
                "reject path queued a Run",
                code="reject-queued",
            )
    return M1CheckpointResult(
        decision=decision,
        project_id=project_id,
        run_id=run_id,
        spec_digest=dry_run.digests.spec,
        proposed_spec_digest=proposal.proposed_spec_digest,
        spec_diff_digest=proposal.spec_diff_digest,
        output_digest=output_digest,
        event_types=types,
        event_ids=ids,
        queued=run_id is not None,
        decision_count=ledger.decision_count,
        answered_question_count=ledger.answered_question_count,
        rationale_characters=ledger.rationale_characters,
        overridden_dissent_count=ledger.overridden_dissent_count,
        report_markdown=report_markdown,
    )


def _authorize_and_simulate(
    store: EventStore,
    *,
    corpus: Path,
    spec: ResearchSpec,
    dry_run: DryRunReport,
    workflow_id: str,
    project_id: str,
    registry: BlockRegistry,
) -> tuple[str, str]:
    authorization_request = load_plan_authorization_request(
        _corpus_file(corpus, _AUTHORIZATION_REQUEST)
    )
    if (
        authorization_request.spec_digest != dry_run.digests.spec
        or authorization_request.registry_digest != dry_run.digests.registry
        or authorization_request.plan_digest != dry_run.digests.plan
    ):
        raise M1CheckpointError(
            "authorization request is not bound to the live plan",
            code="authorization-binding-mismatch",
        )
    policy = authorization_request.policy()
    result = authorize_plan(dry_run, policy)
    if result.authorized is not True:
        raise M1CheckpointError(
            "checkpoint authorization was not granted",
            code="authorization-denied",
        )
    event_document = snapshot_json_document(
        load_document(_corpus_file(corpus, _AUTHORIZATION_EVENT), reject_symlinks=True)
    )
    if type(event_document) is not dict:
        raise M1CheckpointError(
            "authorization event request must be a JSON object",
            code="authorization-binding-mismatch",
        )
    event_document["binding"] = {
        "specDigest": result.spec_digest,
        "registryDigest": result.registry_digest,
        "planDigest": result.plan_digest,
        "decisionDigest": result.decision_digest,
    }
    event_request = validate_plan_authorization_event_request_document(event_document)
    if event_request.workflow_id != workflow_id or event_request.project_id != project_id:
        raise M1CheckpointError(
            "authorization event request does not match the checkpoint spec",
            code="authorization-binding-mismatch",
        )
    recorded = record_plan_authorization_event(store, dry_run, policy, event_request)
    simulation = _simulation_bound_to(corpus, recorded.stored)
    if simulation.workflow_id != workflow_id:
        raise M1CheckpointError(
            "simulation workflowId does not match the checkpoint spec",
            code="authorization-binding-mismatch",
        )
    runtime_result = SimulatedRuntime(
        store,
        registry,
        project_id=project_id,
        run_id=simulation.run_id,
    ).run(spec, simulation.runtime_request())
    if runtime_result.disposition is not SimulationDisposition.COMPLETED:
        raise M1CheckpointError(
            "simulated run did not complete",
            code="simulation-not-completed",
        )
    report = build_run_report(store, simulation.run_id, project_id=project_id)
    return simulation.run_id, render_markdown(report)


def _simulation_bound_to(corpus: Path, stored: StoredEvent) -> SimulationRequestDocument:
    document = snapshot_json_document(
        load_document(_corpus_file(corpus, _SIMULATION), reject_symlinks=True)
    )
    if type(document) is not dict:
        raise M1CheckpointError(
            "simulation request must be a JSON object",
            code="authorization-binding-mismatch",
        )
    document["authorization"] = {
        "eventId": stored.event.id,
        "sequence": stored.event.sequence,
    }
    return validate_simulation_request_document(document)


def _corpus_file(corpus: Path, name: str) -> Path:
    path = corpus / name
    if path.is_symlink() or not path.is_file():
        raise M1CheckpointError(
            "checkpoint corpus is missing a required file",
            code="missing-corpus-file",
        )
    return path


def _has_queued_run(store: EventStore) -> bool:
    return any(item.event.type == TYPE_RUN_QUEUED for item in _stored(store))


def _recorded_identity(store: EventStore) -> tuple[tuple[str, ...], tuple[str, ...]]:
    stored = tuple(_stored(store))
    return (
        tuple(item.event.type for item in stored),
        tuple(item.event.id for item in stored),
    )


def _stored(store: EventStore) -> tuple[StoredEvent, ...]:
    return tuple(replay_events(store, freeze_high_water=False))


def _require_same_ledger(first: ResearchLedger, second: ResearchLedger) -> None:
    if first.model_dump(mode="json", by_alias=True) != second.model_dump(
        mode="json", by_alias=True
    ):
        raise M1CheckpointError(
            "reopened store did not replay the same research ledger",
            code="replay-mismatch",
        )
