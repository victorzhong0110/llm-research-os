"""Rebuild a static Run report from EventStore. The log remains the fact source."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import TypeAdapter, ValidationError

from llm_research_os.budget.control import BudgetFold, apply_budget_fold
from llm_research_os.budget.errors import BudgetError
from llm_research_os.budget.models import BUDGET_EVENT_TYPES
from llm_research_os.budget.money import format_money
from llm_research_os.events.models import EventIdentifier
from llm_research_os.execution.errors import SimulationError
from llm_research_os.execution.synthetic import (
    TYPE_EVALUATION_METRIC,
    TYPE_TRAINING_STEP,
    EvaluationMetricPayload,
    TrainingStepPayload,
    parse_evaluation_metric_payload,
    parse_training_step_payload,
)
from llm_research_os.projections.replay import replay_events
from llm_research_os.report.errors import ReportError
from llm_research_os.research.errors import ResearchLedgerError, ResearchPayloadError
from llm_research_os.research.ledger import LedgerFold, ResearchLedgerProjection
from llm_research_os.research.models import ResearchLedger
from llm_research_os.runs.errors import RunStateError, RunTransitionError
from llm_research_os.runs.models import RunSnapshot
from llm_research_os.runs.reducer import RunStateProjection
from llm_research_os.storage.models import StoredEvent
from llm_research_os.storage.store import EventStore

_IDENTIFIER = TypeAdapter(EventIdentifier)


@dataclass(frozen=True, slots=True)
class TrainingStepRecord:
    stored: StoredEvent
    payload: TrainingStepPayload


@dataclass(frozen=True, slots=True)
class EvaluationMetricRecord:
    stored: StoredEvent
    payload: EvaluationMetricPayload


@dataclass(frozen=True, slots=True)
class RunReport:
    """In-memory projection used to render HTML or Markdown. Not an external document."""

    run_id: str
    project_id: str
    snapshot: RunSnapshot | None
    ledger: ResearchLedger
    training: tuple[TrainingStepRecord, ...]
    evaluation: tuple[EvaluationMetricRecord, ...]
    budget_events: tuple[StoredEvent, ...]
    budget: BudgetFold
    lineage: tuple[StoredEvent, ...]
    last_sequence: int


def build_run_report(store: EventStore, run_id: str, *, project_id: str | None = None) -> RunReport:
    """Replay the verified prefix and fold one Run into a static report."""

    bound_run = _require_identifier("run_id", run_id)
    bound_project = None if project_id is None else _require_identifier("project_id", project_id)
    high_water = store.freeze_high_water()
    prefix = list(
        replay_events(
            store,
            freeze_high_water=False,
            until_sequence=high_water,
        )
    )
    matching: list[StoredEvent] = []
    projects: set[str] = set()
    for stored in prefix:
        if stored.event.data.run_id != bound_run:
            continue
        matching.append(stored)
        projects.add(stored.event.data.project_id)
    if not matching:
        raise ReportError("run not found", code="run-not-found")
    if len(projects) != 1:
        raise ReportError("run is bound to more than one project", code="run-project-mismatch")
    observed_project = next(iter(projects))
    if bound_project is not None and bound_project != observed_project:
        raise ReportError("run project does not match", code="run-project-mismatch")
    snapshot = _fold_snapshot(matching, observed_project, bound_run)
    try:
        ledger, budget, budget_events = _fold_project_prefix(
            prefix,
            project_id=observed_project,
            last_sequence=high_water,
        )
    except (BudgetError, ResearchLedgerError, ResearchPayloadError) as exc:
        raise ReportError(str(exc), code=getattr(exc, "code", "report-fold")) from None
    training: list[TrainingStepRecord] = []
    evaluation: list[EvaluationMetricRecord] = []
    try:
        for stored in matching:
            event = stored.event
            if event.type == TYPE_TRAINING_STEP:
                training.append(
                    TrainingStepRecord(stored=stored, payload=parse_training_step_payload(event))
                )
            elif event.type == TYPE_EVALUATION_METRIC:
                evaluation.append(
                    EvaluationMetricRecord(
                        stored=stored,
                        payload=parse_evaluation_metric_payload(event),
                    )
                )
    except SimulationError as exc:
        raise ReportError(str(exc), code=exc.code) from None
    return RunReport(
        run_id=bound_run,
        project_id=observed_project,
        snapshot=snapshot,
        ledger=ledger,
        training=tuple(training),
        evaluation=tuple(evaluation),
        budget_events=tuple(budget_events),
        budget=budget,
        lineage=tuple(matching),
        last_sequence=high_water,
    )


def _fold_project_prefix(
    prefix: list[StoredEvent],
    *,
    project_id: str,
    last_sequence: int,
) -> tuple[ResearchLedger, BudgetFold, list[StoredEvent]]:
    projection = ResearchLedgerProjection(project_id=project_id)
    ledger_fold: LedgerFold | None = None
    budget = BudgetFold()
    budget_events: list[StoredEvent] = []
    for stored in prefix:
        ledger_fold = projection.apply(ledger_fold, stored.event)
        budget = apply_budget_fold(budget, stored.event, project_id=project_id)
        if stored.event.data.project_id == project_id and stored.event.type in BUDGET_EVENT_TYPES:
            budget_events.append(stored)
    if ledger_fold is None:
        ledger_fold = LedgerFold()
    return projection.snapshot(ledger_fold, last_sequence), budget, budget_events


def _fold_snapshot(
    matching: list[StoredEvent],
    project_id: str,
    run_id: str,
) -> RunSnapshot | None:
    projection = RunStateProjection(project_id=project_id, run_id=run_id)
    snapshot: RunSnapshot | None = None
    try:
        for stored in matching:
            snapshot = projection.apply(snapshot, stored.event)
    except (RunStateError, RunTransitionError) as exc:
        raise ReportError("run projection failed", code="run-projection") from exc
    return snapshot


def _require_identifier(name: str, value: str) -> str:
    try:
        return _IDENTIFIER.validate_python(value, strict=True)
    except ValidationError:
        raise ReportError(f"{name} is not a valid identifier", code="invalid-identifier") from None


def format_consumed(fold: BudgetFold) -> str:
    return format_money(fold.consumed)
