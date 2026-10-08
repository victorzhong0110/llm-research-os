"""Closed v0alpha1 backup, restore, and diagnostic documents.

These are durable on-disk and operator-facing contracts: a backup image is
self-describing so it can be verified and restored without the workspace it
came from, and a diagnostic report is meant to be pasted into an issue after
redaction. Neither carries a host path, a credential, or a Worker identity.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from llm_research_os.events.models import (
    EventDocumentModel,
    EventIdentifier,
    Rfc3339Timestamp,
)

# ``RESTORE_RELAUNCH_POLICY`` states, in the contract itself, that restoring
# copies facts and never grants execution authority. See
# docs/protocols/backup-restore-v0alpha1.md, "The no-relaunch rule".

RECOVERY_API_VERSION = "researchos.dev/recovery/v0alpha1"
BACKUP_MANIFEST_SCHEMA_ID = "https://researchos.dev/schemas/backup-manifest/v0alpha1.schema.json"
BACKUP_REPORT_SCHEMA_ID = "https://researchos.dev/schemas/backup-report/v0alpha1.schema.json"
RESTORE_REPORT_SCHEMA_ID = "https://researchos.dev/schemas/restore-report/v0alpha1.schema.json"
DIAGNOSTIC_REPORT_SCHEMA_ID = (
    "https://researchos.dev/schemas/workspace-diagnostic/v0alpha1.schema.json"
)

MANIFEST_NAME = "backup-manifest.json"
EVENTS_SNAPSHOT_NAME = "events.sqlite3"
OBJECT_ROOT_NAME = "cas"
OPERATIONS_SNAPSHOT_NAME = "operations.json"
BACKUP_MANIFEST_V2_SCHEMA_ID = "https://researchos.dev/schemas/backup-manifest/v0alpha2.schema.json"

RESTORE_RELAUNCH_POLICY: Literal["not-relaunched"] = "not-relaunched"

# An image is untrusted input, so the object list is bounded before it becomes
# a loop of filesystem reads.
MAX_BACKUP_OBJECTS = 100_000

CheckStatus = Literal["ok", "warning", "failed", "skipped"]


# The persisted recovery documents inherit the strict alias-only external
# document config from ``EventDocumentModel``; they add no relaxed field.
_RecoveryModel = EventDocumentModel


class BackupObject(_RecoveryModel):
    """One immutable content-addressed object copied into the image."""

    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    size_bytes: int = Field(alias="sizeBytes", ge=0)
    storage_key: str = Field(alias="storageKey", min_length=1, max_length=512)


class BackupManifest(_RecoveryModel):
    """Self-describing backup image header. Restore trusts only what it re-verifies."""

    api_version: str = Field(default=RECOVERY_API_VERSION, alias="apiVersion")
    kind: Literal["BackupManifest"] = "BackupManifest"
    project_id: EventIdentifier = Field(alias="projectId")
    created_at: Rfc3339Timestamp = Field(alias="createdAt")
    high_water: int = Field(alias="highWater", ge=0)
    event_count: int = Field(alias="eventCount", ge=0)
    last_event_digest: str | None = Field(default=None, alias="lastEventDigest")
    schema_version: int = Field(alias="schemaVersion", ge=1)
    schema_digest: str = Field(alias="schemaDigest", min_length=1)
    snapshot_digest: str = Field(alias="snapshotDigest", pattern=r"^sha256:[0-9a-f]{64}$")
    snapshot_bytes: int = Field(alias="snapshotBytes", ge=1)
    objects: list[BackupObject] = Field(max_length=MAX_BACKUP_OBJECTS)
    total_object_bytes: int = Field(alias="totalObjectBytes", ge=0)
    relaunch_policy: Literal["not-relaunched"] = Field(
        default=RESTORE_RELAUNCH_POLICY, alias="relaunchPolicy"
    )

    @field_validator("last_event_digest")
    @classmethod
    def _check_digest(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("sha256:", "jcs-sha256:")):
            raise ValueError("lastEventDigest must be a content digest")
        return value

    def object_count(self) -> int:
        return len(self.objects)


class BackupManifestV2(BackupManifest):
    """Receipt-aware image; the original v0alpha1 event-prefix contract is unchanged."""

    api_version: Literal["researchos.dev/recovery/v0alpha2"] = Field(
        default="researchos.dev/recovery/v0alpha2", alias="apiVersion"
    )
    operations_snapshot_digest: str = Field(
        alias="operationsSnapshotDigest", pattern=r"^sha256:[0-9a-f]{64}$"
    )
    operations_snapshot_bytes: int = Field(alias="operationsSnapshotBytes", ge=1, le=67_108_864)
    operations_receipt_count: int = Field(alias="operationsReceiptCount", ge=0, le=100_000)
    operations_intent_count: int = Field(alias="operationsIntentCount", ge=0, le=100_000)


class BackupReport(_RecoveryModel):
    """Outcome of creating or verifying one backup image."""

    api_version: str = Field(default=RECOVERY_API_VERSION, alias="apiVersion")
    kind: Literal["BackupReport"] = "BackupReport"
    project_id: EventIdentifier = Field(alias="projectId")
    verified: bool
    high_water: int = Field(alias="highWater", ge=0)
    event_count: int = Field(alias="eventCount", ge=0)
    object_count: int = Field(alias="objectCount", ge=0)
    total_object_bytes: int = Field(alias="totalObjectBytes", ge=0)
    snapshot_bytes: int = Field(alias="snapshotBytes", ge=1)


class ReconciledRun(_RecoveryModel):
    """One Run that needs operator action after a restore.

    A restore cannot observe a process that belonged to the previous machine, so
    a Run left non-terminal is reported as ``unknown`` and left that way
    (ADR-0054). Listing it is not relaunching it.
    """

    run_id: EventIdentifier = Field(alias="runId")
    last_state: str = Field(alias="lastState", min_length=1)
    observation: Literal["unknown"] = "unknown"
    next_action: Literal["reconcile-manually"] = Field(
        default="reconcile-manually", alias="nextAction"
    )


class RestoreReport(_RecoveryModel):
    """Outcome of restoring one verified image into a new workspace directory."""

    api_version: str = Field(default=RECOVERY_API_VERSION, alias="apiVersion")
    kind: Literal["RestoreReport"] = "RestoreReport"
    project_id: EventIdentifier = Field(alias="projectId")
    restored_high_water: int = Field(alias="restoredHighWater", ge=0)
    restored_event_count: int = Field(alias="restoredEventCount", ge=0)
    restored_object_count: int = Field(alias="restoredObjectCount", ge=0)
    ledger_matches: bool = Field(alias="ledgerMatches")
    relaunch_policy: Literal["not-relaunched"] = Field(
        default=RESTORE_RELAUNCH_POLICY, alias="relaunchPolicy"
    )
    reconciled_runs: list[ReconciledRun] = Field(alias="reconciledRuns")
    appended_events: Literal[0] = Field(default=0, alias="appendedEvents")


class DiagnosticCheck(_RecoveryModel):
    """One named result. ``detail`` carries counts and identifiers, never a host path."""

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9.-]*$")
    status: CheckStatus
    detail: dict[str, object] = Field(default_factory=dict)


class DiagnosticReport(_RecoveryModel):
    """Redacted workspace diagnostics, safe to share before it is inspected."""

    api_version: str = Field(default=RECOVERY_API_VERSION, alias="apiVersion")
    kind: Literal["WorkspaceDiagnostic"] = "WorkspaceDiagnostic"
    project_id: EventIdentifier | None = Field(default=None, alias="projectId")
    healthy: bool
    generated_at: Rfc3339Timestamp = Field(alias="generatedAt")
    python_version: str = Field(alias="pythonVersion", min_length=1, max_length=32)
    schema_version: int = Field(alias="schemaVersion", ge=1)
    checks: list[DiagnosticCheck]

    def worst_status(self) -> CheckStatus:
        order: tuple[CheckStatus, ...] = ("failed", "warning", "skipped")
        for status in order:
            if any(check.status == status for check in self.checks):
                return status
        return "ok"

    def describe(self) -> dict[str, object]:
        """Render the report for a CLI or a redacted support bundle."""

        return self.model_dump(mode="json", by_alias=True, exclude_none=True)
