"""Application-layer operation façade for R02.

Each operation is a thin wrapper over an existing control. The application
service does not introduce new state machines, new events, or new
authority stores. The result documents reuse the schemas produced by
``research/``, ``runs/``, ``execution/`` and ``report/`` so external
consumers see identical contracts.

R02 ships:

- ``validate`` — load and validate a ResearchSpec YAML/JSON document.
- ``diff`` — semantic diff between two spec documents.
- ``dry_run`` — planner output (DAG, resources, capabilities); no execution.
- ``ledger_read`` — research-ledger fold for the workspace's project id.
- ``run_query`` — RunSnapshot read for one ``run_id``.

The application operations never append facts. Read operations do not
require an expected EventStore head and never produce a ``researchos``
event id; only the existing command handlers (M1-4 issuance, R02 receipt
log) record durability.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from llm_research_os.blocks.io import ManifestLoadError
from llm_research_os.blocks.registry import RegistryError, build_registry
from llm_research_os.execution import TrustedKernel
from llm_research_os.execution.models import DryRunReport
from llm_research_os.execution.planner import PlanningInputError
from llm_research_os.projections.replay import replay_events
from llm_research_os.report.fold import build_run_report
from llm_research_os.report.render import render_markdown
from llm_research_os.research.errors import ResearchLedgerError
from llm_research_os.research.ledger import build_research_ledger
from llm_research_os.research.models import research_ledger_document
from llm_research_os.runs.models import run_snapshot_document
from llm_research_os.runs.reducer import RunStateProjection
from llm_research_os.spec.diff import SemanticChange, semantic_diff
from llm_research_os.spec.io import SpecLoadError, load_spec
from llm_research_os.storage import EventStore


@dataclass(frozen=True, slots=True)
class OperationStatus:
    """Common outcome envelope for all operations."""

    name: str
    ok: bool
    reason_code: str | None = None
    detail: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def to_document(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "reasonCode": self.reason_code,
            "detail": dict(self.detail),
        }


def _ok(name: str, **detail: Any) -> OperationStatus:
    return OperationStatus(name=name, ok=True, detail=MappingProxyType(detail))


def _refused(name: str, reason: str, **detail: Any) -> OperationStatus:
    return OperationStatus(
        name=name,
        ok=False,
        reason_code=reason,
        detail=MappingProxyType(detail),
    )


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    status: OperationStatus
    document: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class DiffOutcome:
    status: OperationStatus
    document: dict[str, Any] | list[SemanticChange] | None = None


@dataclass(frozen=True, slots=True)
class DryRunOutcome:
    status: OperationStatus
    report_document: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ReadOutcome:
    status: OperationStatus
    documents: tuple[dict[str, Any], ...] = ()
    summary: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class ApplicationOperations:
    """Stateless façade over the existing research / runs / execution controls."""

    project_id: str

    def validate(self, document: Path) -> ValidationOutcome:
        try:
            spec = load_spec(document)
        except (SpecLoadError, ValueError) as exc:
            return ValidationOutcome(status=_refused("validate", "spec-invalid", error=str(exc)))
        if spec.metadata.id != self.project_id:
            return ValidationOutcome(
                status=_refused(
                    "validate",
                    "project-mismatch",
                    projectId=spec.metadata.id,
                    workspaceProjectId=self.project_id,
                )
            )
        return ValidationOutcome(
            status=_ok(
                "validate",
                projectId=spec.metadata.id,
                revision=spec.metadata.revision,
            ),
            document={
                "projectId": spec.metadata.id,
                "revision": spec.metadata.revision,
                "valid": True,
            },
        )

    def diff(self, old: Path, new: Path) -> DiffOutcome:
        try:
            old_spec = load_spec(old)
        except (SpecLoadError, ValueError) as exc:
            return DiffOutcome(
                status=_refused("diff", "old-spec-invalid", side="old", error=str(exc))
            )
        try:
            new_spec = load_spec(new)
        except (SpecLoadError, ValueError) as exc:
            return DiffOutcome(
                status=_refused("diff", "new-spec-invalid", side="new", error=str(exc))
            )
        if old_spec.metadata.id != self.project_id or new_spec.metadata.id != self.project_id:
            return DiffOutcome(
                status=_refused(
                    "diff",
                    "project-mismatch",
                    workspaceProjectId=self.project_id,
                    oldProjectId=old_spec.metadata.id,
                    newProjectId=new_spec.metadata.id,
                )
            )
        try:
            diff_document = semantic_diff(old_spec, new_spec)
        except (ValueError, TypeError) as exc:
            return DiffOutcome(status=_refused("diff", "diff-error", error=str(exc)))
        return DiffOutcome(
            status=_ok(
                "diff",
                oldProjectId=old_spec.metadata.id,
                newProjectId=new_spec.metadata.id,
            ),
            document=diff_document,
        )

    def dry_run(
        self,
        spec: Path,
        workflow: str | None,
        registry: Path | None,
    ) -> DryRunOutcome:
        try:
            parsed = load_spec(spec)
        except (SpecLoadError, ValueError) as exc:
            return DryRunOutcome(status=_refused("dry-run", "spec-invalid", error=str(exc)))
        if parsed.metadata.id != self.project_id:
            return DryRunOutcome(
                status=_refused(
                    "dry-run",
                    "project-mismatch",
                    workspaceProjectId=self.project_id,
                    specProjectId=parsed.metadata.id,
                )
            )
        if registry is None:
            return DryRunOutcome(
                status=_refused(
                    "dry-run",
                    "registry-required",
                    hint="R02 dry_run requires --registry; supply an existing manifest.",
                )
            )
        try:
            block_registry = build_registry([registry])
        except (ManifestLoadError, RegistryError, ValueError, OSError) as exc:
            return DryRunOutcome(
                status=_refused(
                    "dry-run",
                    "registry-invalid",
                    hint="check that --registry points at a valid manifest",
                    error=str(exc),
                )
            )
        try:
            report: DryRunReport = TrustedKernel(block_registry).dry_run(
                parsed, workflow_id=workflow
            )
        except (PlanningInputError, ValueError) as exc:
            return DryRunOutcome(status=_refused("dry-run", "planning-error", error=str(exc)))
        report_document = report.model_dump(mode="json", by_alias=True, exclude_none=True)
        nodes = (report_document.get("graph") or {}).get("nodes") or []
        tasks = report_document.get("tasks") or []
        return DryRunOutcome(
            status=_ok(
                "dry-run",
                workflowId=workflow,
                nodes=len(nodes),
                tasks=len(tasks),
            ),
            report_document=report_document,
        )

    def ledger_read(self, store: EventStore) -> ReadOutcome:
        high_water = store.freeze_high_water()
        events: list[Any] = []
        for stored in replay_events(
            store,
            after_sequence=0,
            freeze_high_water=True,
        ):
            events.append(stored.event)
        try:
            ledger = build_research_ledger(
                tuple(events),
                project_id=self.project_id,
                last_sequence=high_water,
            )
        except ResearchLedgerError as exc:
            return ReadOutcome(
                status=_refused(
                    "ledger-read",
                    "ledger-error",
                    projectId=self.project_id,
                    error=str(exc),
                )
            )
        document = research_ledger_document(ledger)
        decisions = list(ledger.decisions)
        return ReadOutcome(
            status=_ok(
                "ledger-read",
                projectId=self.project_id,
                lastSequence=high_water,
                decisions=len(decisions),
            ),
            documents=(document,),
            summary={"proposals": len(ledger.proposals), "decisions": len(decisions)},
        )

    def run_query(self, store: EventStore, run_id: str) -> ReadOutcome:
        projection = RunStateProjection(project_id=self.project_id, run_id=run_id)
        snapshot = None  # RunStateProjection.initial_state() returns None on entry.
        try:
            for stored in replay_events(
                store,
                after_sequence=0,
                freeze_high_water=True,
            ):
                try:
                    snapshot = projection.apply(snapshot, stored.event)
                except (ValueError, KeyError, AttributeError):
                    # Skip events that don't match this (projectId, runId) pair
                    continue
        except (ValueError, KeyError) as exc:
            return ReadOutcome(
                status=_refused(
                    "run-query",
                    "run-not-found",
                    runId=run_id,
                    error=str(exc),
                )
            )
        if snapshot is None:
            return ReadOutcome(status=_refused("run-query", "run-not-found", runId=run_id))
        if snapshot.project_id != self.project_id:
            return ReadOutcome(
                status=_refused(
                    "run-query",
                    "project-mismatch",
                    runId=run_id,
                    runProjectId=snapshot.project_id,
                    workspaceProjectId=self.project_id,
                )
            )
        report = build_run_report(store, run_id)
        markdown = render_markdown(report)
        document = {
            "runId": run_id,
            "projectId": snapshot.project_id,
            "snapshot": run_snapshot_document(snapshot),
            "reportMarkdownDigest": _markdown_digest(markdown),
        }
        return ReadOutcome(
            status=_ok(
                "run-query",
                runId=run_id,
                projectId=snapshot.project_id,
                attempts=len(snapshot.attempts),
            ),
            documents=(document,),
            summary={"attempts": len(snapshot.attempts)},
        )


def _markdown_digest(markdown: str) -> str:
    return f"sha256:{hashlib.sha256(markdown.encode('utf-8')).hexdigest()}"


__all__ = [
    "ApplicationOperations",
    "DiffOutcome",
    "DryRunOutcome",
    "OperationStatus",
    "ReadOutcome",
    "ValidationOutcome",
]
