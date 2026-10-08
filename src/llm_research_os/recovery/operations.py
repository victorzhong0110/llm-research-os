"""Bounded, inert operation-state snapshots for receipt-aware recovery."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Literal, Self
from urllib.parse import quote

from pydantic import Field, model_validator

from llm_research_os.application.models import ApplicationModel, ApplicationReceipt
from llm_research_os.application.receipts import ReceiptLog
from llm_research_os.application.workspace import Workspace
from llm_research_os.canonical import SEMANTIC_DIGEST_PATTERN, canonical_json, content_digest
from llm_research_os.evaluation.trained_contracts import (
    ResearchReport,
    TrainedComparison,
    TrainingProvenance,
)
from llm_research_os.events.models import EventIdentifier
from llm_research_os.recovery.errors import BackupIntegrityError, RecoveryError
from llm_research_os.storage.store import EventStore

OPERATIONS_SCHEMA_ID = "https://researchos.dev/schemas/operations-backup/v0alpha1.schema.json"
MAX_OPERATION_BYTES = 64 << 20
MAX_OPERATION_ROWS = 100_000
MAX_RECEIPT_BYTES = 4 << 20


class EffectIntent(ApplicationModel):
    """A prior dispatch reservation, never a permission or relaunch request."""

    scope: str = Field(min_length=1, max_length=4096)
    content_digest: str = Field(alias="contentDigest", pattern=SEMANTIC_DIGEST_PATTERN)


class OperationState(ApplicationModel):
    """Inert receipts and dispatch reservations bound to one workspace."""

    api_version: Literal["researchos.dev/operations-backup/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["OperationState"]
    project_id: EventIdentifier = Field(alias="projectId")
    receipts: list[ApplicationReceipt] = Field(max_length=MAX_OPERATION_ROWS)
    intents: list[EffectIntent] = Field(max_length=MAX_OPERATION_ROWS)

    @model_validator(mode="after")
    def identities_are_unique(self) -> Self:
        if len({r.command_id for r in self.receipts}) != len(self.receipts):
            raise ValueError("duplicate operation receipt identity")
        if len({i.scope for i in self.intents}) != len(self.intents):
            raise ValueError("duplicate dispatch reservation identity")
        return self


def capture_operation_state(workspace: Workspace) -> OperationState | None:
    """Read both tables in one SQLite transaction before capturing the event prefix."""

    if not workspace.receipt_db.exists():
        return None
    uri = f"file:{quote(workspace.receipt_db.absolute().as_posix(), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=30.0)
    receipts = []
    intents = []
    total_bytes = 0
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        rows = connection.execute(
            """SELECT command_id, request_digest, length(CAST(receipt_json AS BLOB)),
            CASE WHEN length(CAST(receipt_json AS BLOB)) <= 4194304 THEN receipt_json END
            FROM operation_receipts ORDER BY rowid LIMIT 100001"""
        )
        for command_id, request_digest, size, payload in rows:
            total_bytes += size
            if size > MAX_RECEIPT_BYTES or total_bytes > MAX_OPERATION_BYTES:
                raise RecoveryError("backup-operations-too-large", "operation state exceeds bounds")
            if len(receipts) >= MAX_OPERATION_ROWS:
                raise RecoveryError("backup-operations-too-large", "too many operation receipts")
            receipt = ApplicationReceipt.model_validate_json(payload)
            if receipt.command_id != command_id or receipt.request_digest != request_digest:
                raise ValueError("operation receipt identity differs from its database row")
            receipts.append(receipt.document())
        rows = connection.execute(
            """SELECT CASE WHEN length(CAST(scope AS BLOB)) <= 16384 THEN scope END,
            CASE WHEN length(content_digest) <= 128 THEN content_digest END
            FROM operation_effect_intents
            ORDER BY rowid LIMIT 100001"""
        )
        for scope, digest in rows:
            if len(intents) >= MAX_OPERATION_ROWS:
                raise RecoveryError("backup-operations-too-large", "too many dispatch reservations")
            intents.append({"scope": scope, "contentDigest": digest})
        return OperationState.model_validate(
            {
                "apiVersion": "researchos.dev/operations-backup/v0alpha1",
                "kind": "OperationState",
                "projectId": workspace.project_id,
                "receipts": receipts,
                "intents": intents,
            }
        )
    except (sqlite3.Error, ValueError, TypeError) as exc:
        raise BackupIntegrityError(
            "backup-operations-invalid", "operation state failed validation"
        ) from exc
    finally:
        connection.close()


def operation_references(
    state: OperationState, store: EventStore, *, project_id: str, high_water: int
) -> tuple[str, ...]:
    """Re-derive object roots from validated receipts, including embedded report lineage."""

    if state.project_id != project_id:
        raise BackupIntegrityError("backup-operations-project", "operation state belongs elsewhere")
    digests: set[str] = set()
    try:
        for receipt in state.receipts:
            if receipt.observed_head > high_water or receipt.disposition != "committed":
                raise ValueError("operation receipt is outside the captured prefix")
            if content_digest(receipt.result) != receipt.result_digest:
                raise ValueError("operation receipt result digest differs")
            for event_id in receipt.fact_event_ids:
                event = store.get_event(event_id)
                if event is None or event.event.data.project_id not in (None, project_id):
                    raise ValueError("operation receipt cites an absent or foreign fact")
            digests.update(d for d in receipt.artifact_digests if d.startswith("sha256:"))
            result = receipt.result
            comparisons = []
            if receipt.operation in ("conclusion.publish", "conclusion.inspect"):
                report = ResearchReport.model_validate(result["report"])
                if (
                    report.project_id != project_id
                    or report.comparison_digest
                    != content_digest(report.comparison.model_dump(mode="json", by_alias=True))
                ):
                    raise ValueError("report identity or project differs")
                if receipt.operation == "conclusion.publish" and report.actor_id != receipt.actor_id:
                    raise ValueError("report actor differs from its recorded receipt")
                if _byte_digest(report.model_dump(mode="json", by_alias=True)) != result["reportArtifact"]:
                    raise ValueError("report object differs from its recorded content")
                digests.add(result["reportArtifact"])
                comparisons.append(report.comparison)
            elif receipt.operation == "evaluation.report":
                comparison = TrainedComparison.model_validate(result["comparison"])
                if content_digest(result["comparison"]) != result["comparisonDigest"]:
                    raise ValueError("comparison digest differs")
                if _byte_digest(result["comparison"]) != result["comparisonArtifact"]:
                    raise ValueError("comparison object differs from its recorded content")
                digests.add(result["comparisonArtifact"])
                comparisons.append(comparison)
            elif receipt.operation == "evaluation.collect":
                digests.update((result["baselineArtifact"], result["candidateArtifact"]))
                provenance = TrainingProvenance.model_validate(result["provenance"])
                if provenance.project_id != project_id:
                    raise ValueError("training result belongs to another project")
                digests.update((provenance.request_artifact, provenance.output_artifact))
            for comparison in comparisons:
                digests.update((comparison.baseline_artifact, comparison.candidate_artifact))
                for provenance in (comparison.baseline, comparison.candidate):
                    if provenance.project_id != project_id:
                        raise ValueError("training provenance belongs to another project")
                    digests.update((provenance.request_artifact, provenance.output_artifact))
        if len(digests) > MAX_OPERATION_ROWS:
            raise ValueError("too many receipt-backed objects")
        # Result fields are dictionaries. Validate every derived object id before
        # it is handed to the CAS path derivation, including embedded lineage.
        from llm_research_os.artifacts.store import storage_key_for

        for digest in digests:
            storage_key_for(digest)
        return tuple(sorted(digests))
    except (ValueError, TypeError, KeyError) as exc:
        raise BackupIntegrityError(
            "backup-operations-invalid", "operation receipts do not match the verified prefix"
        ) from exc


def restore_operation_state(state: OperationState, workspace: Workspace) -> None:
    """Rebuild the local append-only log through its API; execute no command."""

    log = ReceiptLog(workspace.receipt_db)
    for intent in state.intents:
        log.reserve_effect(intent.scope, intent.content_digest)
    for receipt in state.receipts:
        log.append(receipt.command_id, receipt.request_digest, receipt.document())


def _byte_digest(document: dict[str, object]) -> str:
    return f"sha256:{hashlib.sha256(canonical_json(document).encode()).hexdigest()}"
