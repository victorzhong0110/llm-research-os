"""Thin shared operations over existing research, run, and execution controls.

CLI and Python callers use :meth:`ApplicationService.execute`. The service does
not mint launch authority, import task entrypoints, or rewrite EventStore
schema v2 rows.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from llm_research_os.application.errors import ApplicationError
from llm_research_os.application.models import (
    APPLICATION_API_VERSION,
    ApplicationCommand,
    ApplicationReceipt,
    PlanDryRunOperation,
    ResearchDecisionOperation,
    RunShowOperation,
    RunSimulateOperation,
    SpecDiffOperation,
    SpecValidateOperation,
)
from llm_research_os.application.receipts import ReceiptLog
from llm_research_os.application.workspace import Workspace, load_workspace
from llm_research_os.artifacts.errors import ArtifactNotFoundError, ArtifactStoreError
from llm_research_os.artifacts.store import DIGEST_PATTERN, LocalArtifactStore
from llm_research_os.blocks.io import ManifestLoadError
from llm_research_os.blocks.registry import MANIFEST_SUFFIXES, RegistryError, build_registry
from llm_research_os.canonical import content_digest
from llm_research_os.execution.errors import SimulationError
from llm_research_os.execution.kernel import TrustedKernel
from llm_research_os.execution.planner import PlanningInputError
from llm_research_os.execution.request import load_simulation_request
from llm_research_os.execution.simulated import SimulatedRuntime
from llm_research_os.projections.replay import replay_events
from llm_research_os.research.control import ResearchControl
from llm_research_os.research.errors import (
    ResearchControlError,
    ResearchLedgerError,
    ResearchRequestError,
)
from llm_research_os.research.models import research_ledger_document
from llm_research_os.research.requests import load_decision_record_request
from llm_research_os.runs.control import RunControl
from llm_research_os.runs.errors import RunControlError
from llm_research_os.runs.models import run_snapshot_document
from llm_research_os.spec.diff import semantic_diff
from llm_research_os.spec.io import SpecLoadError, load_spec
from llm_research_os.storage import EventStore
from llm_research_os.storage.errors import (
    DuplicateEventError,
    EventSequenceConflictError,
    EventStoreError,
)
from llm_research_os.storage.schema import SCHEMA_VERSION

_MAX_DIGEST_BYTES = 1_048_576


class ApplicationService:
    """One workspace's command façade. Construct a new instance per process."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace
        self._receipts = ReceiptLog(workspace.receipt_db)

    @classmethod
    def open(cls, root: Path) -> ApplicationService:
        return cls(load_workspace(root))

    @property
    def workspace(self) -> Workspace:
        return self._workspace

    def execute(self, command: ApplicationCommand) -> dict[str, Any]:
        """Run ``command`` or return the prior receipt for the same content."""

        digest = self._request_digest(command)
        prior = self._receipts.lookup(command.command_id)
        if prior is not None:
            if prior.request_digest != digest:
                raise ApplicationError(
                    "receipt-conflict",
                    "command identity was already committed with different content",
                )
            return _replay_document(prior.document)
        self._require_expected_head(command)
        outcome = self._perform(command)
        observed = self._head()
        receipt = ApplicationReceipt.model_validate(
            {
                "apiVersion": APPLICATION_API_VERSION,
                "kind": "ApplicationReceipt",
                "commandId": command.command_id,
                "actorId": command.actor_id,
                "submittedAt": command.submitted_at,
                "operation": command.operation.kind,
                "requestDigest": digest,
                "expectedHead": command.expected_head,
                "expectedRevision": command.expected_revision,
                "observedHead": observed,
                "disposition": "committed",
                "factEventIds": list(outcome.fact_event_ids),
                "artifactDigests": list(outcome.artifact_digests),
                "resultDigest": content_digest(outcome.result),
                "result": outcome.result,
            }
        )
        document = receipt.document()
        self._receipts.append(command.command_id, digest, document)
        return document

    def _perform(self, command: ApplicationCommand) -> _Outcome:
        kind = command.operation.kind
        if kind == "workspace.show":
            described = self._workspace.describe()
            return _Outcome(
                result={
                    **described,
                    "supportedEventSchemaVersion": SCHEMA_VERSION,
                }
            )
        if kind == "spec.validate":
            return self._validate(command)
        if kind == "spec.diff":
            return self._diff(command)
        if kind == "plan.dry-run":
            return self._dry_run(command)
        if kind == "revision.list":
            return self._revisions()
        if kind == "research.ledger":
            return self._ledger()
        if kind == "research.decision":
            return self._decision(command)
        if kind == "run.show":
            return self._run_show(command)
        if kind == "run.simulate":
            return self._simulate(command)
        raise ApplicationError("operation-unsupported", "operation is not implemented")

    def _validate(self, command: ApplicationCommand) -> _Outcome:
        operation = command.operation
        if not isinstance(operation, SpecValidateOperation):
            raise ApplicationError("operation-unsupported", "operation kind does not match")
        spec = _load_spec(Path(operation.document))
        _require_project(str(spec.metadata.id), self._workspace.project_id)
        _require_revision(spec.metadata.revision, command.expected_revision)
        return _Outcome(
            result={
                "valid": True,
                "projectId": str(spec.metadata.id),
                "revision": spec.metadata.revision,
            }
        )

    def _diff(self, command: ApplicationCommand) -> _Outcome:
        operation = command.operation
        if not isinstance(operation, SpecDiffOperation):
            raise ApplicationError("operation-unsupported", "operation kind does not match")
        old = _load_spec(Path(operation.old))
        new = _load_spec(Path(operation.new))
        _require_project(str(old.metadata.id), self._workspace.project_id)
        _require_project(str(new.metadata.id), self._workspace.project_id)
        _require_revision(new.metadata.revision, command.expected_revision)
        try:
            changes = semantic_diff(old, new)
        except (TypeError, ValueError) as exc:
            raise ApplicationError("spec-invalid", "spec diff failed validation") from exc
        return _Outcome(
            result={
                "projectId": str(old.metadata.id),
                "fromRevision": old.metadata.revision,
                "toRevision": new.metadata.revision,
                "changes": [change.as_dict() for change in changes],
            }
        )

    def _dry_run(self, command: ApplicationCommand) -> _Outcome:
        operation = command.operation
        if not isinstance(operation, PlanDryRunOperation):
            raise ApplicationError("operation-unsupported", "operation kind does not match")
        spec = _load_spec(Path(operation.document))
        _require_project(str(spec.metadata.id), self._workspace.project_id)
        _require_revision(spec.metadata.revision, command.expected_revision)
        try:
            registry = build_registry(tuple(Path(item) for item in operation.registry))
            report = TrustedKernel(registry).dry_run(spec, workflow_id=operation.workflow_id)
        except (
            ManifestLoadError,
            OSError,
            PlanningInputError,
            RegistryError,
            ValidationError,
        ) as exc:
            raise ApplicationError("dry-run-refused", "dry-run did not produce a report") from exc
        return _Outcome(result=report.model_dump(mode="json", by_alias=True, exclude_none=True))

    def _revisions(self) -> _Outcome:
        with self._open_store(create=False) as store:
            rows = [
                {
                    "revision": row.revision,
                    "specDigest": row.spec_digest,
                    "firstSeenSequence": row.first_seen_sequence,
                }
                for row in store.list_spec_revisions()
                if row.project_id == self._workspace.project_id
            ]
        return _Outcome(result={"projectId": self._workspace.project_id, "revisions": rows})

    def _ledger(self) -> _Outcome:
        try:
            with self._open_store(create=False) as store:
                head = ResearchControl(store, project_id=self._workspace.project_id).rebuild()
                document = research_ledger_document(head.snapshot)
        except ResearchLedgerError as exc:
            raise ApplicationError(exc.code, str(exc)) from exc
        return _Outcome(result=document)

    def _decision(self, command: ApplicationCommand) -> _Outcome:
        operation = command.operation
        if not isinstance(operation, ResearchDecisionOperation):
            raise ApplicationError("operation-unsupported", "operation kind does not match")
        try:
            request = load_decision_record_request(Path(operation.request))
        except ResearchRequestError as exc:
            raise ApplicationError(exc.code, "decision request failed validation") from exc
        if request.project_id != self._workspace.project_id:
            raise ApplicationError(
                "project-mismatch",
                "decision project does not match the workspace",
            )
        _require_revision(request.experiment_revision, command.expected_revision)
        artifacts = self._bound_artifacts(request.evidence_refs)
        try:
            with self._open_store(create=True) as store:
                try:
                    appended = ResearchControl(
                        store,
                        project_id=self._workspace.project_id,
                    ).append(request.event_draft())
                    fact_id = appended.stored.event.id
                    sequence = appended.stored.sequence
                    event_type = appended.stored.event.type
                except DuplicateEventError:
                    existing = store.get_event(request.event.id)
                    if (
                        existing is None
                        or existing.event.data.project_id != self._workspace.project_id
                    ):
                        raise ApplicationError(
                            "duplicate-event",
                            "event identity is already committed",
                        ) from None
                    fact_id = existing.event.id
                    sequence = existing.sequence
                    event_type = existing.event.type
        except (ResearchControlError, ResearchLedgerError) as exc:
            raise ApplicationError(exc.code, str(exc)) from exc
        except EventSequenceConflictError as exc:
            raise ApplicationError(
                "stale-head",
                "expectedHead does not match the EventStore head",
            ) from exc
        except EventStoreError as exc:
            raise ApplicationError("event-store", "event store operation failed") from exc
        return _Outcome(
            result={
                "eventId": fact_id,
                "sequence": sequence,
                "type": event_type,
                "projectId": self._workspace.project_id,
            },
            fact_event_ids=(fact_id,),
            artifact_digests=artifacts,
        )

    def _run_show(self, command: ApplicationCommand) -> _Outcome:
        operation = command.operation
        if not isinstance(operation, RunShowOperation):
            raise ApplicationError("operation-unsupported", "operation kind does not match")
        try:
            with self._open_store(create=False) as store:
                head = RunControl(
                    store,
                    project_id=self._workspace.project_id,
                    run_id=operation.run_id,
                ).rebuild()
        except RunControlError as exc:
            raise ApplicationError("run-refused", "run query failed") from exc
        if head.snapshot is None or head.snapshot.project_id != self._workspace.project_id:
            raise ApplicationError("run-not-found", "run is not in this project")
        return _Outcome(result=run_snapshot_document(head.snapshot))

    def _simulate(self, command: ApplicationCommand) -> _Outcome:
        operation = command.operation
        if not isinstance(operation, RunSimulateOperation):
            raise ApplicationError("operation-unsupported", "operation kind does not match")
        spec = _load_spec(Path(operation.spec))
        _require_project(str(spec.metadata.id), self._workspace.project_id)
        _require_revision(spec.metadata.revision, command.expected_revision)
        try:
            request = load_simulation_request(Path(operation.request))
        except (OSError, ValidationError, ValueError) as exc:
            raise ApplicationError(
                "simulation-request-invalid",
                "simulation request failed validation",
            ) from exc
        try:
            with self._open_store(create=True) as store:
                runtime = SimulatedRuntime(
                    store,
                    build_registry(tuple(Path(item) for item in operation.registry)),
                    project_id=self._workspace.project_id,
                    run_id=request.run_id,
                )
                result = runtime.run(spec, request.runtime_request())
                appended = tuple(stored.event.id for stored in result.stored)
                fact_ids = appended or _run_fact_ids(
                    store,
                    project_id=self._workspace.project_id,
                    run_id=request.run_id,
                )
                snapshot = result.snapshot
        except (
            EventStoreError,
            ManifestLoadError,
            OSError,
            RegistryError,
            RunControlError,
            SimulationError,
            ValidationError,
        ) as exc:
            raise ApplicationError("simulation-refused", "simulation was refused") from exc
        if snapshot.project_id != self._workspace.project_id or snapshot.run_id != request.run_id:
            raise ApplicationError(
                "project-mismatch",
                "simulation run does not match the workspace",
            )
        return _Outcome(
            result={
                "projectId": snapshot.project_id,
                "runId": snapshot.run_id,
                "status": snapshot.status.value,
                "simulationDisposition": result.disposition.value,
                "appendedEvents": len(appended),
                "lastSequence": snapshot.last_sequence,
            },
            fact_event_ids=fact_ids,
        )

    def _bound_artifacts(self, evidence_refs: tuple[str, ...]) -> tuple[str, ...]:
        digests = tuple(ref for ref in evidence_refs if DIGEST_PATTERN.fullmatch(ref))
        if not digests:
            return ()
        store = LocalArtifactStore(self._workspace.cas_root)
        verified: list[str] = []
        for digest in digests:
            try:
                record = store.verify(digest)
            except ArtifactNotFoundError as exc:
                raise ApplicationError(
                    "artifact-missing",
                    "evidence digest is not in the workspace CAS",
                ) from exc
            except ArtifactStoreError as exc:
                raise ApplicationError("artifact-invalid", "artifact verification failed") from exc
            verified.append(record.digest)
        return tuple(verified)

    def _require_expected_head(self, command: ApplicationCommand) -> None:
        if command.expected_head is None:
            return
        actual = self._head()
        if actual != command.expected_head:
            raise ApplicationError(
                "stale-head",
                f"expectedHead {command.expected_head} does not match EventStore head {actual}",
            )

    def _head(self) -> int:
        if not self._workspace.control_db.exists():
            return 0
        with self._open_store(create=False) as store:
            return store.last_sequence()

    def _open_store(self, *, create: bool) -> EventStore:
        if not self._workspace.control_db.exists():
            if not create:
                raise ApplicationError("store-missing", "workspace EventStore does not exist")
            return EventStore(self._workspace.control_db)
        try:
            return EventStore(self._workspace.control_db, require_existing=True)
        except EventStoreError as exc:
            raise ApplicationError("event-store", "event store operation failed") from exc

    def _request_digest(self, command: ApplicationCommand) -> str:
        body = {
            "actorId": command.actor_id,
            "expectedHead": command.expected_head,
            "expectedRevision": command.expected_revision,
            "operation": _operation_content(command),
            "submittedAt": command.submitted_at,
        }
        return content_digest(body)


class _Outcome:
    def __init__(
        self,
        *,
        result: dict[str, Any],
        fact_event_ids: tuple[str, ...] = (),
        artifact_digests: tuple[str, ...] = (),
    ) -> None:
        self.result = result
        self.fact_event_ids = fact_event_ids
        self.artifact_digests = artifact_digests


def _replay_document(document: dict[str, object]) -> dict[str, Any]:
    replayed = dict(document)
    replayed["disposition"] = "replayed"
    try:
        receipt = ApplicationReceipt.model_validate(replayed)
    except ValidationError as exc:
        raise ApplicationError("receipt-corrupt", "stored receipt failed validation") from exc
    return receipt.document(disposition="replayed")


def _operation_content(command: ApplicationCommand) -> dict[str, Any]:
    operation = command.operation
    kind = operation.kind
    if isinstance(operation, SpecValidateOperation):
        return {"kind": kind, "specDigest": _file_digest(Path(operation.document))}
    if isinstance(operation, SpecDiffOperation):
        return {
            "kind": kind,
            "newDigest": _file_digest(Path(operation.new)),
            "oldDigest": _file_digest(Path(operation.old)),
        }
    if isinstance(operation, PlanDryRunOperation):
        return {
            "kind": kind,
            "registryDigests": _registry_digests(operation.registry),
            "specDigest": _file_digest(Path(operation.document)),
            "workflowId": operation.workflow_id,
        }
    if isinstance(operation, ResearchDecisionOperation):
        return {"kind": kind, "requestDigest": _file_digest(Path(operation.request))}
    if isinstance(operation, RunShowOperation):
        return {"kind": kind, "runId": operation.run_id}
    if isinstance(operation, RunSimulateOperation):
        return {
            "kind": kind,
            "registryDigests": _registry_digests(operation.registry),
            "requestDigest": _file_digest(Path(operation.request)),
            "specDigest": _file_digest(Path(operation.spec)),
        }
    return {"kind": kind}


def _registry_digests(paths: tuple[str, ...]) -> list[str]:
    digests: list[str] = []
    for raw in paths:
        path = Path(raw)
        _reject_symlink(path)
        if path.is_dir():
            children = sorted(
                child.name
                for child in path.iterdir()
                if child.is_file()
                and not child.is_symlink()
                and child.suffix.lower() in MANIFEST_SUFFIXES
            )
            digests.append(
                content_digest(
                    [{"digest": _file_digest(path / name), "name": name} for name in children]
                )
            )
        elif path.is_file():
            digests.append(_file_digest(path))
        else:
            raise ApplicationError("input-missing", "registry path does not exist")
    return digests


def _file_digest(path: Path) -> str:
    _reject_symlink(path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ApplicationError("input-missing", "command input could not be read") from exc
    if size > _MAX_DIGEST_BYTES:
        raise ApplicationError("input-too-large", "command input exceeds the digest bound")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ApplicationError("input-missing", "command input could not be read") from exc
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _reject_symlink(path: Path) -> None:
    if path.is_symlink():
        raise ApplicationError("symlink-rejected", "command input must not be a symbolic link")


def _load_spec(path: Path) -> Any:
    try:
        return load_spec(path)
    except (OSError, SpecLoadError, ValidationError, ValueError) as exc:
        raise ApplicationError("spec-invalid", "spec document failed validation") from exc


def _require_project(document_project: str, workspace_project: str) -> None:
    if document_project != workspace_project:
        raise ApplicationError(
            "project-mismatch",
            "document project does not match the workspace",
        )


def _require_revision(actual: int, expected: int | None) -> None:
    if expected is not None and actual != expected:
        raise ApplicationError(
            "stale-revision",
            f"revision {actual} does not match expectedRevision {expected}",
        )


def _run_fact_ids(store: EventStore, *, project_id: str, run_id: str) -> tuple[str, ...]:
    identities: list[str] = []
    for stored in replay_events(store, after_sequence=0, freeze_high_water=True):
        data = stored.event.data
        if data.project_id == project_id and data.run_id == run_id:
            identities.append(stored.event.id)
    return tuple(dict.fromkeys(identities))
