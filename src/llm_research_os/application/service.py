"""Thin shared operations over existing research, run, and execution controls.

CLI and Python callers use :meth:`ApplicationService.execute`. The service does
not mint launch authority, import task entrypoints, or rewrite EventStore
schema v2 rows.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from llm_research_os.application.errors import ApplicationError
from llm_research_os.application.models import (
    APPLICATION_API_VERSION,
    ApplicationCommand,
    ApplicationOperation,
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
from llm_research_os.blocks.builtins import builtin_manifests
from llm_research_os.blocks.io import ManifestLoadError
from llm_research_os.blocks.models import BlockManifest
from llm_research_os.blocks.registry import (
    MANIFEST_SUFFIXES,
    MAX_REGISTRY_BYTES,
    MAX_REGISTRY_DIRECTORY_ENTRIES,
    MAX_REGISTRY_MANIFESTS,
    BlockRegistry,
    RegistryError,
)
from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.execution.errors import SimulationError
from llm_research_os.execution.kernel import TrustedKernel
from llm_research_os.execution.planner import PlanningInputError
from llm_research_os.execution.request import (
    SimulationRequestDocument,
    validate_simulation_request_document,
)
from llm_research_os.execution.simulated import SimulatedRuntime
from llm_research_os.projections.replay import replay_events
from llm_research_os.research.control import ResearchControl
from llm_research_os.research.errors import (
    ResearchControlError,
    ResearchLedgerError,
    ResearchRequestError,
)
from llm_research_os.research.models import research_ledger_document
from llm_research_os.research.requests import (
    DecisionRecordRequestDocument,
    validate_decision_record_request,
)
from llm_research_os.runs.control import RunControl
from llm_research_os.runs.errors import RunControlError
from llm_research_os.runs.models import run_snapshot_document
from llm_research_os.spec.diff import semantic_diff
from llm_research_os.spec.io import SpecLoadError, decode_document_text
from llm_research_os.spec.models import ResearchSpec
from llm_research_os.storage import EventStore
from llm_research_os.storage.errors import (
    DuplicateEventError,
    EventSequenceConflictError,
    EventStoreError,
)
from llm_research_os.storage.models import StoredEvent
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

        frozen = _freeze_operation(command.operation)
        digest = self._request_digest(command, frozen)
        prior = self._receipts.lookup(command.command_id)
        if prior is not None:
            if prior.request_digest != digest:
                raise ApplicationError(
                    "receipt-conflict",
                    "command identity was already committed with different content",
                )
            return _replay_document(prior.document)
        if not self._identical_decision_already_committed(command, frozen):
            self._require_expected_head(command)
        outcome = self._perform(command, frozen)
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

    def _perform(self, command: ApplicationCommand, frozen: _FrozenOperation) -> _Outcome:
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
            return self._validate(command, frozen)
        if kind == "spec.diff":
            return self._diff(command, frozen)
        if kind == "plan.dry-run":
            return self._dry_run(command, frozen)
        if kind == "revision.list":
            return self._revisions()
        if kind == "research.ledger":
            return self._ledger()
        if kind == "research.decision":
            return self._decision(command, frozen)
        if kind == "run.show":
            return self._run_show(command)
        if kind == "run.simulate":
            return self._simulate(command, frozen)
        raise ApplicationError("operation-unsupported", "operation is not implemented")

    def _validate(self, command: ApplicationCommand, frozen: _FrozenOperation) -> _Outcome:
        operation = command.operation
        if not isinstance(operation, SpecValidateOperation) or frozen.spec is None:
            raise ApplicationError("operation-unsupported", "operation kind does not match")
        spec = _spec_from_snapshot(frozen.spec)
        _require_project(str(spec.metadata.id), self._workspace.project_id)
        _require_revision(spec.metadata.revision, command.expected_revision)
        return _Outcome(
            result={
                "valid": True,
                "projectId": str(spec.metadata.id),
                "revision": spec.metadata.revision,
            }
        )

    def _diff(self, command: ApplicationCommand, frozen: _FrozenOperation) -> _Outcome:
        operation = command.operation
        if (
            not isinstance(operation, SpecDiffOperation)
            or frozen.old_spec is None
            or frozen.new_spec is None
        ):
            raise ApplicationError("operation-unsupported", "operation kind does not match")
        old = _spec_from_snapshot(frozen.old_spec)
        new = _spec_from_snapshot(frozen.new_spec)
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

    def _dry_run(self, command: ApplicationCommand, frozen: _FrozenOperation) -> _Outcome:
        operation = command.operation
        if not isinstance(operation, PlanDryRunOperation) or frozen.spec is None:
            raise ApplicationError("operation-unsupported", "operation kind does not match")
        spec = _spec_from_snapshot(frozen.spec)
        _require_project(str(spec.metadata.id), self._workspace.project_id)
        _require_revision(spec.metadata.revision, command.expected_revision)
        try:
            registry = _registry_from_snapshots(frozen.registry_manifests)
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

    def _decision(self, command: ApplicationCommand, frozen: _FrozenOperation) -> _Outcome:
        operation = command.operation
        if not isinstance(operation, ResearchDecisionOperation) or frozen.decision is None:
            raise ApplicationError("operation-unsupported", "operation kind does not match")
        try:
            request = _decision_from_snapshot(frozen.decision)
        except ResearchRequestError as exc:
            raise ApplicationError(exc.code, "decision request failed validation") from exc
        except SpecLoadError as exc:
            raise ApplicationError(
                "research-request", "decision request failed validation"
            ) from exc
        if request.project_id != self._workspace.project_id:
            raise ApplicationError(
                "project-mismatch",
                "decision project does not match the workspace",
            )
        _require_revision(request.experiment_revision, command.expected_revision)
        expected_head = command.expected_head
        if expected_head is None:
            raise ApplicationError(
                "stale-head",
                "expectedHead does not match the EventStore head",
            )
        artifacts = self._bound_artifacts(request.evidence_refs)
        draft = request.event_draft()
        try:
            with self._open_store(create=True) as store:
                try:
                    fact_id, sequence, event_type = _append_or_recover_decision(
                        store,
                        project_id=self._workspace.project_id,
                        draft=draft,
                        event_id=request.event.id,
                        expected_head=expected_head,
                    )
                except DuplicateEventError:
                    fact_id, sequence, event_type = _recover_identical_fact(
                        store,
                        draft=draft,
                        event_id=request.event.id,
                    )
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

    def _simulate(self, command: ApplicationCommand, frozen: _FrozenOperation) -> _Outcome:
        operation = command.operation
        if (
            not isinstance(operation, RunSimulateOperation)
            or frozen.spec is None
            or frozen.simulation_request is None
        ):
            raise ApplicationError("operation-unsupported", "operation kind does not match")
        spec = _spec_from_snapshot(frozen.spec)
        _require_project(str(spec.metadata.id), self._workspace.project_id)
        _require_revision(spec.metadata.revision, command.expected_revision)
        try:
            request = _simulation_from_snapshot(frozen.simulation_request)
        except (OSError, ValidationError, ValueError) as exc:
            raise ApplicationError(
                "simulation-request-invalid",
                "simulation request failed validation",
            ) from exc
        expected_head = command.expected_head
        if expected_head is None:
            raise ApplicationError(
                "stale-head",
                "expectedHead does not match the EventStore head",
            )
        try:
            with self._open_store(create=True) as store:
                runtime = SimulatedRuntime(
                    store,
                    _registry_from_snapshots(frozen.registry_manifests),
                    project_id=self._workspace.project_id,
                    run_id=request.run_id,
                )
                result = runtime.run(
                    spec,
                    request.runtime_request(),
                    expected_last_sequence=expected_head,
                )
                appended = tuple(stored.event.id for stored in result.stored)
                fact_ids = appended or _run_fact_ids(
                    store,
                    project_id=self._workspace.project_id,
                    run_id=request.run_id,
                )
                snapshot = result.snapshot
        except EventSequenceConflictError as exc:
            raise ApplicationError(
                "stale-head",
                "expectedHead does not match the EventStore head",
            ) from exc
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

    def _identical_decision_already_committed(
        self,
        command: ApplicationCommand,
        frozen: _FrozenOperation,
    ) -> bool:
        """True when this decision fact is already stored, so a stale head can recover it."""

        operation = command.operation
        if not isinstance(operation, ResearchDecisionOperation) or frozen.decision is None:
            return False
        if not self._workspace.control_db.exists():
            return False
        try:
            request = _decision_from_snapshot(frozen.decision)
        except (ResearchRequestError, SpecLoadError):
            return False
        draft = request.event_draft()
        try:
            with self._open_store(create=False) as store:
                existing = store.get_event(request.event.id)
        except ApplicationError:
            return False
        return existing is not None and _same_committed_fact(draft, existing)

    def _request_digest(self, command: ApplicationCommand, frozen: _FrozenOperation) -> str:
        body = {
            "actorId": command.actor_id,
            "expectedHead": command.expected_head,
            "expectedRevision": command.expected_revision,
            "operation": _operation_content(command, frozen),
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


def _operation_content(command: ApplicationCommand, frozen: _FrozenOperation) -> dict[str, Any]:
    operation = command.operation
    kind = operation.kind
    if isinstance(operation, SpecValidateOperation):
        if frozen.spec is None:
            raise ApplicationError("operation-unsupported", "operation kind does not match")
        return {"kind": kind, "specDigest": frozen.spec.digest()}
    if isinstance(operation, SpecDiffOperation):
        if frozen.old_spec is None or frozen.new_spec is None:
            raise ApplicationError("operation-unsupported", "operation kind does not match")
        return {
            "kind": kind,
            "newDigest": frozen.new_spec.digest(),
            "oldDigest": frozen.old_spec.digest(),
        }
    if isinstance(operation, PlanDryRunOperation):
        if frozen.spec is None:
            raise ApplicationError("operation-unsupported", "operation kind does not match")
        return {
            "kind": kind,
            "registryDigests": list(frozen.registry_digests),
            "specDigest": frozen.spec.digest(),
            "workflowId": operation.workflow_id,
        }
    if isinstance(operation, ResearchDecisionOperation):
        if frozen.decision is None:
            raise ApplicationError("operation-unsupported", "operation kind does not match")
        return {"kind": kind, "requestDigest": frozen.decision.digest()}
    if isinstance(operation, RunShowOperation):
        return {"kind": kind, "runId": operation.run_id}
    if isinstance(operation, RunSimulateOperation):
        if frozen.spec is None or frozen.simulation_request is None:
            raise ApplicationError("operation-unsupported", "operation kind does not match")
        return {
            "kind": kind,
            "registryDigests": list(frozen.registry_digests),
            "requestDigest": frozen.simulation_request.digest(),
            "specDigest": frozen.spec.digest(),
        }
    return {"kind": kind}


def _append_or_recover_decision(
    store: EventStore,
    *,
    project_id: str,
    draft: dict[str, Any],
    event_id: str,
    expected_head: int,
) -> tuple[str, int, str]:
    existing = store.get_event(event_id)
    if existing is not None:
        return _require_identical_fact(draft, existing)
    appended = ResearchControl(store, project_id=project_id).append(
        draft,
        expected_last_sequence=expected_head,
    )
    stored = appended.stored
    return stored.event.id, stored.sequence, stored.event.type


def _recover_identical_fact(
    store: EventStore,
    *,
    draft: dict[str, Any],
    event_id: str,
) -> tuple[str, int, str]:
    existing = store.get_event(event_id)
    if existing is None:
        raise ApplicationError(
            "duplicate-event",
            "event identity is already committed",
        )
    return _require_identical_fact(draft, existing)


def _require_identical_fact(draft: dict[str, Any], existing: StoredEvent) -> tuple[str, int, str]:
    if not _same_committed_fact(draft, existing):
        raise ApplicationError(
            "duplicate-event",
            "event identity is already committed",
        )
    return existing.event.id, existing.sequence, existing.event.type


def _same_committed_fact(draft: dict[str, Any], existing: StoredEvent) -> bool:
    """True only when type and caller-supplied event content are the same fact."""

    recorded = existing.event.model_dump(mode="json", by_alias=True, exclude_none=True)
    for field in ("sequence", "sequencetype", "streamversion"):
        recorded.pop(field, None)
    if recorded.get("type") != draft.get("type"):
        return False
    return canonical_json(recorded) == canonical_json(draft)


def _reject_symlink(path: Path) -> None:
    if path.is_symlink():
        raise ApplicationError("symlink-rejected", "command input must not be a symbolic link")


def _freeze_operation(operation: ApplicationOperation) -> _FrozenOperation:
    try:
        if isinstance(operation, SpecValidateOperation):
            return _FrozenOperation(spec=_read_snapshot(Path(operation.document)))
        if isinstance(operation, SpecDiffOperation):
            return _FrozenOperation(
                old_spec=_read_snapshot(Path(operation.old)),
                new_spec=_read_snapshot(Path(operation.new)),
            )
        if isinstance(operation, PlanDryRunOperation):
            digests, manifests = _freeze_registry(operation.registry)
            return _FrozenOperation(
                spec=_read_snapshot(Path(operation.document)),
                registry_digests=digests,
                registry_manifests=manifests,
            )
        if isinstance(operation, ResearchDecisionOperation):
            return _FrozenOperation(decision=_read_snapshot(Path(operation.request)))
        if isinstance(operation, RunSimulateOperation):
            digests, manifests = _freeze_registry(operation.registry)
            return _FrozenOperation(
                spec=_read_snapshot(Path(operation.spec)),
                simulation_request=_read_snapshot(Path(operation.request)),
                registry_digests=digests,
                registry_manifests=manifests,
            )
    except RegistryError as exc:
        if isinstance(operation, PlanDryRunOperation):
            raise ApplicationError("dry-run-refused", "dry-run did not produce a report") from exc
        raise ApplicationError("simulation-refused", "simulation was refused") from exc
    return _FrozenOperation()


def _freeze_registry(paths: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[_Snapshot, ...]]:
    digests: list[str] = []
    manifests: list[_Snapshot] = []
    total_bytes = 0

    def take(path: Path) -> _Snapshot:
        nonlocal total_bytes
        if len(manifests) >= MAX_REGISTRY_MANIFESTS:
            raise RegistryError(f"registry exceeds the {MAX_REGISTRY_MANIFESTS}-manifest M0 limit")
        snapshot = _read_snapshot(path)
        total_bytes += len(snapshot.payload)
        if total_bytes > MAX_REGISTRY_BYTES:
            raise RegistryError(f"registry exceeds the {MAX_REGISTRY_BYTES}-byte M0 limit")
        manifests.append(snapshot)
        return snapshot

    for raw in paths:
        path = Path(raw)
        _reject_symlink(path)
        if path.is_dir():
            children: list[Path] = []
            try:
                entries = path.iterdir()
            except OSError as exc:
                raise ApplicationError("input-missing", "registry path does not exist") from exc
            for entry_count, child in enumerate(entries, start=1):
                if entry_count > MAX_REGISTRY_DIRECTORY_ENTRIES:
                    raise RegistryError(
                        "registry directory exceeds the "
                        f"{MAX_REGISTRY_DIRECTORY_ENTRIES}-entry M0 scan limit"
                    )
                if child.is_symlink():
                    raise ApplicationError(
                        "symlink-rejected",
                        "command input must not be a symbolic link",
                    )
                if child.is_file() and child.suffix.lower() in MANIFEST_SUFFIXES:
                    children.append(child)
            digested: list[dict[str, str]] = []
            for child in sorted(children, key=lambda item: item.name):
                snapshot = take(child)
                digested.append({"digest": snapshot.digest(), "name": child.name})
            digests.append(content_digest(digested))
        elif path.is_file():
            if path.suffix.lower() not in MANIFEST_SUFFIXES:
                raise RegistryError(f"unsupported manifest extension: {path}")
            digests.append(take(path).digest())
        else:
            raise ApplicationError("input-missing", "registry path does not exist")
    return tuple(digests), tuple(manifests)


def _read_snapshot(path: Path) -> _Snapshot:
    """Read one regular file once. Digest and execution share these bytes."""

    _reject_symlink(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ApplicationError("input-missing", "command input could not be read") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ApplicationError("input-missing", "command input could not be read")
        if metadata.st_size > _MAX_DIGEST_BYTES:
            raise ApplicationError("input-too-large", "command input exceeds the digest bound")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(65_536, _MAX_DIGEST_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > _MAX_DIGEST_BYTES:
                raise ApplicationError(
                    "input-too-large",
                    "command input exceeds the digest bound",
                )
        payload = b"".join(chunks)
    finally:
        os.close(descriptor)
    return _Snapshot(payload=payload, suffix=path.suffix.lower())


def _decode_snapshot(snapshot: _Snapshot, *, source: str) -> dict[str, Any]:
    try:
        text = snapshot.payload.decode("utf-8")
    except UnicodeError as exc:
        raise SpecLoadError(f"could not load {source}: {exc}") from exc
    return decode_document_text(text, suffix=snapshot.suffix, source=source)


def _spec_from_snapshot(snapshot: _Snapshot) -> ResearchSpec:
    try:
        return ResearchSpec.model_validate(_decode_snapshot(snapshot, source="spec"))
    except (OSError, SpecLoadError, ValidationError, ValueError) as exc:
        raise ApplicationError("spec-invalid", "spec document failed validation") from exc


def _decision_from_snapshot(snapshot: _Snapshot) -> DecisionRecordRequestDocument:
    return validate_decision_record_request(_decode_snapshot(snapshot, source="decision request"))


def _simulation_from_snapshot(snapshot: _Snapshot) -> SimulationRequestDocument:
    return validate_simulation_request_document(
        _decode_snapshot(snapshot, source="simulation request")
    )


def _registry_from_snapshots(manifests: tuple[_Snapshot, ...]) -> BlockRegistry:
    registry = BlockRegistry()
    for manifest in builtin_manifests():
        registry.register(manifest, source="builtin")
    for snapshot in manifests:
        try:
            document = _decode_snapshot(snapshot, source="registry manifest")
        except SpecLoadError as exc:
            raise ManifestLoadError(str(exc)) from exc
        registry.register(BlockManifest.model_validate(document), source="explicit")
    registry.seal()
    return registry


@dataclass(frozen=True, slots=True)
class _Snapshot:
    payload: bytes
    suffix: str

    def digest(self) -> str:
        return f"sha256:{hashlib.sha256(self.payload).hexdigest()}"


@dataclass(frozen=True, slots=True)
class _FrozenOperation:
    spec: _Snapshot | None = None
    old_spec: _Snapshot | None = None
    new_spec: _Snapshot | None = None
    decision: _Snapshot | None = None
    simulation_request: _Snapshot | None = None
    registry_digests: tuple[str, ...] = ()
    registry_manifests: tuple[_Snapshot, ...] = ()


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
