"""Preparation receipt and doctor diagnosis for reviewed native execution.

A receipt cites verified digests and the Worker grant id. It is not a launch
credential. ``launchAllowed`` stays false, and no field records a host path.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from llm_research_os.execution.native_reviewed_documents import (
    ByteDigest,
    JcsDigest,
    NativeReviewedDocumentModel,
    ReviewedEntrypoint,
    ReviewedIdentifier,
    ReviewedInputDigest,
    ReviewedPlatform,
    ReviewedPythonVersion,
    ReviewedSequence,
    _require_json_bool,
    _require_json_int,
)

NATIVE_REVIEWED_PREPARATION_RECEIPT_SCHEMA_ID = (
    "https://researchos.dev/schemas/native-reviewed-preparation-receipt/v0alpha1.schema.json"
)
NATIVE_REVIEWED_PREPARATION_DIAGNOSIS_SCHEMA_ID = (
    "https://researchos.dev/schemas/native-reviewed-preparation-diagnosis/v0alpha1.schema.json"
)

MAX_PREPARATION_FILES = 64

PreparationReasonCode = Literal[
    "launch-not-implemented",
    "prefix-unverified",
    "decision-not-authorization",
    "foreign-project",
    "stale-revision",
    "foreign-workflow",
    "foreign-task",
    "foreign-run",
    "foreign-attempt",
    "foreign-worker",
    "authorization-event-mismatch",
    "authorization-sequence-mismatch",
    "authorization-actor-mismatch",
    "authorization-actor-not-human",
    "authorization-not-authorized",
    "authorization-capability-mismatch",
    "spec-digest-mismatch",
    "registry-digest-mismatch",
    "plan-digest-mismatch",
    "decision-digest-mismatch",
    "review-digest-mismatch",
    "config-digest-mismatch",
    "code-digest-mismatch",
    "entrypoint-mismatch",
    "media-type-mismatch",
    "input-digest-mismatch",
    "interpreter-digest-mismatch",
    "dependency-lock-mismatch",
    "inventory-digest-mismatch",
    "environment-identity-mismatch",
    "missing-resource-ceiling",
    "required-network-unenforced",
    "required-filesystem-unenforced",
    "required-memory-unenforced",
    "required-process-unenforced",
    "grant-capability-mismatch",
    "grant-hmac-invalid",
    "grant-expired",
    "grant-revoked",
    "grant-nonce-replay",
    "grant-resumed-claim",
    "grant-already-consumed",
    "grant-binding-mismatch",
    "grant-media-mismatch",
    "prepared",
    "preparation-ready",
    "preparation-incomplete",
    "preparation-damaged",
    "environment-mismatch",
    "code-substituted",
    "config-substituted",
    "input-substituted",
    "environment-substituted",
    "review-substituted",
    "binding-invalidated",
    "request-invalid",
    "artifact-missing",
    "artifact-integrity",
    "source-path-rejected",
]

DiagnosisOutcome = Literal[
    "ready",
    "incomplete",
    "damaged",
    "mismatched",
    "invalidated",
    "refused",
]

_INVALIDATED = frozenset(
    {
        "code-substituted",
        "config-substituted",
        "input-substituted",
        "environment-substituted",
        "review-substituted",
        "binding-invalidated",
    }
)


class PreparationSideEffects(NativeReviewedDocumentModel):
    """Literal zeros. Preparation does not import, spawn, consume, or install."""

    entrypoints_imported: Literal[0] = Field(alias="entrypointsImported")
    processes_spawned: Literal[0] = Field(alias="processesSpawned")
    lifecycle_facts_appended: Literal[0] = Field(alias="lifecycleFactsAppended")
    grants_consumed: Literal[0] = Field(alias="grantsConsumed")
    packages_installed: Literal[0] = Field(alias="packagesInstalled")

    @field_validator(
        "entrypoints_imported",
        "processes_spawned",
        "lifecycle_facts_appended",
        "grants_consumed",
        "packages_installed",
        mode="before",
    )
    @classmethod
    def counts_are_json_ints(cls, value: object) -> object:
        return _require_json_int(value)


class PreparedFileRecord(NativeReviewedDocumentModel):
    """One materialized object addressed by a workspace-relative path."""

    role: Literal[
        "bundle",
        "code",
        "input",
        "config",
        "interpreter",
        "dependency-lock",
        "inventory",
        "review",
    ]
    relative_path: str = Field(alias="relativePath", min_length=8, max_length=300)
    digest: str = Field(pattern=r"^(?:sha256|jcs-sha256):[0-9a-f]{64}$")
    name: ReviewedIdentifier | None = None

    @field_validator("relative_path", mode="before")
    @classmethod
    def path_stays_inside_material(cls, value: object) -> object:
        if type(value) is not str:
            raise ValueError("relativePath must be a string")
        if value.startswith(("/", "\\")) or "\\" in value or ".." in value.split("/"):
            raise ValueError("relativePath must stay inside the preparation workspace")
        return value

    @field_validator("name", mode="before")
    @classmethod
    def name_cannot_be_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("name cannot be null")
        return value

    @model_validator(mode="after")
    def role_matches_path(self) -> Self:
        path = self.relative_path
        if self.role == "input":
            if self.name is None or path != f"material/inputs/{self.name}":
                raise ValueError("input record does not match its name")
        elif self.name is not None:
            raise ValueError("only input records carry a name")
        expected = {
            "bundle": "material/bundle",
            "config": "material/config.json",
            "interpreter": "material/environment/interpreter",
            "dependency-lock": "material/environment/dependency-lock",
            "inventory": "material/environment/inventory",
            "review": "material/environment/review",
        }
        if self.role in expected and path != expected[self.role]:
            raise ValueError("material path does not match its role")
        if self.role == "code" and not path.startswith("material/code/"):
            raise ValueError("code path must stay under material/code")
        if self.role == "config" and not self.digest.startswith("jcs-sha256:"):
            raise ValueError("config identity must be a JCS digest")
        if self.role == "review" and not self.digest.startswith("jcs-sha256:"):
            raise ValueError("review identity must be a JCS digest")
        if self.role not in {"config", "review"} and not self.digest.startswith("sha256:"):
            raise ValueError("byte identity must be a sha256 digest")
        return self


class PreparationCheck(NativeReviewedDocumentModel):
    """One doctor comparison. Status is match, missing, or mismatch."""

    role: Literal[
        "bundle",
        "code",
        "input",
        "config",
        "interpreter",
        "dependency-lock",
        "inventory",
        "review",
        "receipt",
    ]
    status: Literal["match", "missing", "mismatch"]
    name: ReviewedIdentifier | None = None

    @field_validator("name", mode="before")
    @classmethod
    def name_cannot_be_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("name cannot be null")
        return value


class NativeReviewedPreparationReceipt(NativeReviewedDocumentModel):
    """Digest binding of prepared bytes to one grant and plan. Not launch authority."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["NativeReviewedPreparationReceipt"]
    profile: Literal["native-reviewed-python/v0alpha1"]
    evidence_class: Literal["preparation"] = Field(alias="evidenceClass")
    request_digest: JcsDigest = Field(alias="requestDigest")
    plan_digest: JcsDigest = Field(alias="planDigest")
    decision_digest: JcsDigest = Field(alias="decisionDigest")
    config_digest: JcsDigest = Field(alias="configDigest")
    grant_id: ReviewedIdentifier = Field(alias="grantId")
    project_id: ReviewedIdentifier = Field(alias="projectId")
    revision_id: ReviewedIdentifier = Field(alias="revisionId")
    run_id: ReviewedIdentifier = Field(alias="runId")
    attempt_id: ReviewedIdentifier = Field(alias="attemptId")
    task_id: ReviewedIdentifier = Field(alias="taskId")
    worker_id: ReviewedIdentifier = Field(alias="workerId")
    authorization_event_id: ReviewedIdentifier = Field(alias="authorizationEventId")
    authorization_sequence: ReviewedSequence = Field(alias="authorizationSequence")
    platform: ReviewedPlatform
    bundle_digest: ByteDigest = Field(alias="bundleDigest")
    media_type: Literal["researchos.native-reviewed-python-bundle/v0alpha1"] = Field(
        alias="mediaType"
    )
    entrypoint: ReviewedEntrypoint
    input_digests: tuple[ReviewedInputDigest, ...] = Field(alias="inputDigests", max_length=32)
    interpreter_digest: ByteDigest = Field(alias="interpreterDigest")
    python_version: ReviewedPythonVersion = Field(alias="pythonVersion")
    abi: Literal["cp312", "cp313", "cp314"]
    dependency_lock_digest: ByteDigest = Field(alias="dependencyLockDigest")
    inventory_digest: ByteDigest = Field(alias="inventoryDigest")
    interpreter_identity: Literal["byte-digest"] = Field(alias="interpreterIdentity")
    files: tuple[PreparedFileRecord, ...] = Field(min_length=1, max_length=MAX_PREPARATION_FILES)
    outcome: Literal["prepared"]
    reason_code: Literal["prepared"] = Field(alias="reasonCode")
    launch_allowed: Literal[False] = Field(alias="launchAllowed")
    side_effects: PreparationSideEffects = Field(alias="sideEffects")

    @field_validator("launch_allowed", mode="before")
    @classmethod
    def launch_is_json_bool(cls, value: object) -> object:
        return _require_json_bool(value)

    @field_validator("input_digests", "files", mode="before")
    @classmethod
    def freeze_collections(cls, value: object) -> object:
        if type(value) is not list:
            raise ValueError("preparation collections must be arrays")
        return tuple(value)

    @model_validator(mode="after")
    def files_match_binding(self) -> Self:
        if len(self.files) != len({item.relative_path for item in self.files}):
            raise ValueError("material paths must be unique")
        roles = [item.role for item in self.files]
        for role in ("bundle", "config", "interpreter", "dependency-lock", "inventory", "review"):
            if roles.count(role) != 1:
                raise ValueError("preparation is missing a required material role")
        by_role = {item.role: item for item in self.files if item.role != "code"}
        if by_role["bundle"].digest != self.bundle_digest:
            raise ValueError("bundle file digest does not match the receipt")
        if by_role["config"].digest != self.config_digest:
            raise ValueError("config file digest does not match the receipt")
        if by_role["interpreter"].digest != self.interpreter_digest:
            raise ValueError("interpreter file digest does not match the receipt")
        if by_role["dependency-lock"].digest != self.dependency_lock_digest:
            raise ValueError("lock file digest does not match the receipt")
        if by_role["inventory"].digest != self.inventory_digest:
            raise ValueError("inventory file digest does not match the receipt")
        if not by_role["review"].digest.startswith("jcs-sha256:"):
            raise ValueError("review file digest is not a citation")
        code_paths = [item.relative_path for item in self.files if item.role == "code"]
        if not code_paths:
            raise ValueError("preparation is missing reviewed code")
        return self


class NativeReviewedPreparationDiagnosis(NativeReviewedDocumentModel):
    """Doctor report. Ready still does not authorize user code."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["NativeReviewedPreparationDiagnosis"]
    profile: Literal["native-reviewed-python/v0alpha1"]
    evidence_class: Literal["preparation-diagnosis"] = Field(alias="evidenceClass")
    request_digest: JcsDigest | None = Field(default=None, alias="requestDigest")
    receipt_digest: JcsDigest | None = Field(default=None, alias="receiptDigest")
    expected_receipt_digest: JcsDigest | None = Field(default=None, alias="expectedReceiptDigest")
    grant_id: ReviewedIdentifier | None = Field(default=None, alias="grantId")
    outcome: DiagnosisOutcome
    reason_code: PreparationReasonCode = Field(alias="reasonCode")
    launch_allowed: Literal[False] = Field(alias="launchAllowed")
    interpreter_identity: Literal["byte-digest"] = Field(alias="interpreterIdentity")
    checks: tuple[PreparationCheck, ...] = Field(max_length=MAX_PREPARATION_FILES)
    side_effects: PreparationSideEffects = Field(alias="sideEffects")

    @field_validator("launch_allowed", mode="before")
    @classmethod
    def launch_is_json_bool(cls, value: object) -> object:
        return _require_json_bool(value)

    @field_validator(
        "request_digest",
        "receipt_digest",
        "expected_receipt_digest",
        "grant_id",
        mode="before",
    )
    @classmethod
    def optional_fields_cannot_be_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("optional diagnosis field cannot be null")
        return value

    @field_validator("checks", mode="before")
    @classmethod
    def freeze_checks(cls, value: object) -> object:
        if type(value) is not list:
            raise ValueError("checks must be a JSON array")
        return tuple(value)

    @model_validator(mode="after")
    def outcome_matches_reason(self) -> Self:
        expected = _outcome_for_reason(self.reason_code)
        if self.outcome != expected:
            raise ValueError("diagnosis outcome does not match reasonCode")
        if self.outcome == "ready" and (
            self.request_digest is None
            or self.receipt_digest is None
            or self.expected_receipt_digest is None
            or self.receipt_digest != self.expected_receipt_digest
        ):
            raise ValueError("ready diagnosis requires matching receipt digests")
        return self


def _outcome_for_reason(reason: str) -> DiagnosisOutcome:
    if reason == "preparation-ready":
        return "ready"
    if reason == "preparation-incomplete":
        return "incomplete"
    if reason == "preparation-damaged":
        return "damaged"
    if reason == "environment-mismatch":
        return "mismatched"
    if reason in _INVALIDATED:
        return "invalidated"
    return "refused"


def diagnosis_outcome(reason: PreparationReasonCode) -> DiagnosisOutcome:
    """Return the only outcome allowed for this reason code."""

    return _outcome_for_reason(reason)
