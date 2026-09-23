"""Strict request and report documents for reviewed native execution.

R03 freezes ``native-reviewed-python/v0alpha1``. These models reject unknown
fields and never authorize a process. ``launchAllowed`` is constantly false.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

from llm_research_os.spec.models import StrictModel

NATIVE_REVIEWED_API_VERSION: Literal["researchos.dev/v0alpha1"] = "researchos.dev/v0alpha1"
NATIVE_REVIEWED_PROFILE: Literal["native-reviewed-python/v0alpha1"] = (
    "native-reviewed-python/v0alpha1"
)
NATIVE_REVIEWED_MEDIA_TYPE: Literal["researchos.native-reviewed-python-bundle/v0alpha1"] = (
    "researchos.native-reviewed-python-bundle/v0alpha1"
)
EXECUTE_NATIVE_CAPABILITY = "execute.native"
NATIVE_REVIEWED_REQUEST_SCHEMA_ID = (
    "https://researchos.dev/schemas/native-reviewed-execution-request/v0alpha1.schema.json"
)
NATIVE_REVIEWED_REPORT_SCHEMA_ID = (
    "https://researchos.dev/schemas/native-reviewed-execution-report/v0alpha1.schema.json"
)

MAX_REVIEWED_REQUEST_BYTES = 65_536
MAX_REVIEWED_INPUTS = 32
MAX_REVIEWED_WALL_TIME_SECONDS = 86_400
MAX_REVIEWED_STREAM_BYTES = 16_777_216
MAX_REVIEWED_ARTIFACT_BYTES = 1_073_741_824
MAX_REVIEWED_INPUT_BYTES = 1_073_741_824
MAX_REVIEWED_PROCESS_COUNT = 256
MAX_REVIEWED_MEMORY_BYTES = 17_179_869_184
MAX_REVIEWED_ENTRYPOINT_LENGTH = 256

SUPPORTED_REVIEWED_PLATFORMS: frozenset[tuple[str, str]] = frozenset(
    {
        ("linux", "x86_64"),
        ("linux", "aarch64"),
        ("darwin", "x86_64"),
        ("darwin", "arm64"),
    }
)
_ABI_BY_MINOR = {"12": "cp312", "13": "cp313", "14": "cp314"}
_PYTHON_VERSION = re.compile(r"^3\.(12|13|14)\.[0-9]{1,4}$")
_ENTRYPOINT = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
    r":[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$"
)

ByteDigest = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=False, pattern=r"^sha256:[0-9a-f]{64}$"),
]
JcsDigest = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=False, pattern=r"^jcs-sha256:[0-9a-f]{64}$"),
]
ReviewedIdentifier = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=False,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
ReviewedSequence = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=False,
        pattern=r"^[1-9][0-9]{0,17}$",
    ),
]
ReviewedEntrypoint = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=False,
        min_length=3,
        max_length=MAX_REVIEWED_ENTRYPOINT_LENGTH,
        pattern=_ENTRYPOINT.pattern,
    ),
]
ReviewedPythonVersion = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=False,
        pattern=_PYTHON_VERSION.pattern,
    ),
]


class NativeReviewedDocumentModel(StrictModel):
    """Frozen alias-only external model without coercion or repair."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        populate_by_name=False,
        str_strip_whitespace=False,
        strict=True,
        validate_by_alias=True,
        validate_by_name=False,
    )


def _require_json_bool(value: object) -> object:
    if type(value) is not bool:
        raise ValueError("value must be a JSON boolean")
    return value


def _require_json_int(value: object) -> object:
    if type(value) is not int:
        raise ValueError("value must be a JSON integer")
    return value


class LinuxReviewedPlatform(NativeReviewedDocumentModel):
    """Linux pairs named the way ``uname`` reports them."""

    os: Literal["linux"]
    architecture: Literal["x86_64", "aarch64"]


class DarwinReviewedPlatform(NativeReviewedDocumentModel):
    """macOS pairs named the way ``uname`` reports them."""

    os: Literal["darwin"]
    architecture: Literal["x86_64", "arm64"]


ReviewedPlatform = Annotated[
    LinuxReviewedPlatform | DarwinReviewedPlatform,
    Field(discriminator="os"),
]


class ReviewedCodeReview(NativeReviewedDocumentModel):
    citation_digest: JcsDigest = Field(alias="citationDigest")
    bundle_digest: ByteDigest = Field(alias="bundleDigest")


class ReviewedCode(NativeReviewedDocumentModel):
    bundle_digest: ByteDigest = Field(alias="bundleDigest")
    media_type: Literal["researchos.native-reviewed-python-bundle/v0alpha1"] = Field(
        alias="mediaType"
    )
    entrypoint: ReviewedEntrypoint
    review: ReviewedCodeReview

    @model_validator(mode="after")
    def review_binds_bundle(self) -> Self:
        if self.review.bundle_digest != self.bundle_digest:
            raise ValueError("review citation does not bind the code bundle")
        return self


class ReviewedInput(NativeReviewedDocumentModel):
    name: ReviewedIdentifier
    digest: ByteDigest
    purpose: Literal["dataset", "checkpoint", "config", "input"]
    size_bytes: int = Field(alias="sizeBytes", ge=0, le=MAX_REVIEWED_INPUT_BYTES)

    @field_validator("size_bytes", mode="before")
    @classmethod
    def size_is_json_int(cls, value: object) -> object:
        return _require_json_int(value)


class ReviewedProcessCeiling(NativeReviewedDocumentModel):
    ceiling: int = Field(ge=1, le=MAX_REVIEWED_PROCESS_COUNT)
    required: bool

    @field_validator("ceiling", mode="before")
    @classmethod
    def ceiling_is_json_int(cls, value: object) -> object:
        return _require_json_int(value)

    @field_validator("required", mode="before")
    @classmethod
    def required_is_json_bool(cls, value: object) -> object:
        return _require_json_bool(value)


class ReviewedMemoryCeiling(NativeReviewedDocumentModel):
    ceiling: int = Field(ge=1, le=MAX_REVIEWED_MEMORY_BYTES)
    required: bool

    @field_validator("ceiling", mode="before")
    @classmethod
    def ceiling_is_json_int(cls, value: object) -> object:
        return _require_json_int(value)

    @field_validator("required", mode="before")
    @classmethod
    def required_is_json_bool(cls, value: object) -> object:
        return _require_json_bool(value)


class ReviewedLimits(NativeReviewedDocumentModel):
    wall_time_seconds: int = Field(
        alias="wallTimeSeconds",
        ge=1,
        le=MAX_REVIEWED_WALL_TIME_SECONDS,
    )
    stdout_bytes: int = Field(alias="stdoutBytes", ge=0, le=MAX_REVIEWED_STREAM_BYTES)
    stderr_bytes: int = Field(alias="stderrBytes", ge=0, le=MAX_REVIEWED_STREAM_BYTES)
    artifact_bytes: int = Field(alias="artifactBytes", ge=0, le=MAX_REVIEWED_ARTIFACT_BYTES)
    process_count: ReviewedProcessCeiling | None = Field(default=None, alias="processCount")
    memory_bytes: ReviewedMemoryCeiling | None = Field(default=None, alias="memoryBytes")

    @field_validator(
        "wall_time_seconds",
        "stdout_bytes",
        "stderr_bytes",
        "artifact_bytes",
        mode="before",
    )
    @classmethod
    def ceilings_are_json_ints(cls, value: object) -> object:
        return _require_json_int(value)

    @field_validator("process_count", "memory_bytes", mode="before")
    @classmethod
    def optional_ceilings_are_objects(cls, value: object) -> object:
        if value is None:
            raise ValueError("optional ceiling cannot be null")
        return value


class NetworkRestriction(NativeReviewedDocumentModel):
    requested: Literal["none", "denied", "allowlist"]
    required: bool

    @field_validator("required", mode="before")
    @classmethod
    def required_is_json_bool(cls, value: object) -> object:
        return _require_json_bool(value)


class FilesystemRestriction(NativeReviewedDocumentModel):
    requested: Literal["host", "confined"]
    required: bool

    @field_validator("required", mode="before")
    @classmethod
    def required_is_json_bool(cls, value: object) -> object:
        return _require_json_bool(value)


class MemoryRestriction(NativeReviewedDocumentModel):
    requested: Literal["unbounded", "bounded"]
    required: bool

    @field_validator("required", mode="before")
    @classmethod
    def required_is_json_bool(cls, value: object) -> object:
        return _require_json_bool(value)


class ReviewedRestrictions(NativeReviewedDocumentModel):
    network: NetworkRestriction
    filesystem: FilesystemRestriction
    memory: MemoryRestriction


class ReviewedEnvironment(NativeReviewedDocumentModel):
    interpreter_digest: ByteDigest = Field(alias="interpreterDigest")
    python_version: ReviewedPythonVersion = Field(alias="pythonVersion")
    abi: Literal["cp312", "cp313", "cp314"]
    dependency_lock_digest: ByteDigest = Field(alias="dependencyLockDigest")
    inventory_digest: ByteDigest = Field(alias="inventoryDigest")
    platform: ReviewedPlatform

    @model_validator(mode="after")
    def abi_matches_version(self) -> Self:
        match = _PYTHON_VERSION.fullmatch(self.python_version)
        if match is None or _ABI_BY_MINOR[match.group(1)] != self.abi:
            raise ValueError("interpreter ABI is not supported")
        return self


class NativeReviewedExecutionRequest(NativeReviewedDocumentModel):
    """Closed request for one reviewed Python task. Not a launch credential."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["NativeReviewedExecutionRequest"]
    profile: Literal["native-reviewed-python/v0alpha1"]
    platform: ReviewedPlatform
    project_id: ReviewedIdentifier = Field(alias="projectId")
    revision_id: ReviewedIdentifier = Field(alias="revisionId")
    workflow_id: ReviewedIdentifier = Field(alias="workflowId")
    task_id: ReviewedIdentifier = Field(alias="taskId")
    run_id: ReviewedIdentifier = Field(alias="runId")
    attempt_id: ReviewedIdentifier = Field(alias="attemptId")
    worker_id: ReviewedIdentifier = Field(alias="workerId")
    actor_id: ReviewedIdentifier = Field(alias="actorId")
    authorization_event_id: ReviewedIdentifier = Field(alias="authorizationEventId")
    authorization_sequence: ReviewedSequence = Field(alias="authorizationSequence")
    spec_digest: JcsDigest = Field(alias="specDigest")
    registry_digest: JcsDigest = Field(alias="registryDigest")
    plan_digest: JcsDigest = Field(alias="planDigest")
    decision_digest: JcsDigest = Field(alias="decisionDigest")
    code: ReviewedCode
    inputs: tuple[ReviewedInput, ...] = Field(
        max_length=MAX_REVIEWED_INPUTS,
        json_schema_extra={"uniqueItems": True},
    )
    config_digest: JcsDigest = Field(alias="configDigest")
    environment: ReviewedEnvironment
    limits: ReviewedLimits
    restrictions: ReviewedRestrictions

    @field_validator("inputs", mode="before")
    @classmethod
    def freeze_inputs(cls, value: object) -> object:
        if type(value) is not list:
            raise ValueError("inputs must be a JSON array")
        return tuple(value)

    @model_validator(mode="after")
    def bindings_are_closed(self) -> Self:
        names = [item.name for item in self.inputs]
        if len(names) != len(set(names)):
            raise ValueError("input names must be unique")
        if self.environment.platform != self.platform:
            raise ValueError("environment platform does not match the request platform")
        return self


class NetworkEvidence(NativeReviewedDocumentModel):
    requested: Literal["none", "denied", "allowlist"]
    enforced: Literal["not-enforced"]
    unsupported: Literal["none", "network-isolation"]


class FilesystemEvidence(NativeReviewedDocumentModel):
    requested: Literal["host", "confined"]
    enforced: Literal["not-enforced"]
    unsupported: Literal["none", "filesystem-confinement"]


class MemoryEvidence(NativeReviewedDocumentModel):
    requested: Literal["unbounded", "bounded"]
    enforced: Literal["not-enforced"]
    unsupported: Literal["none", "memory-limit"]


class RestrictionEvidence(NativeReviewedDocumentModel):
    network: NetworkEvidence
    filesystem: FilesystemEvidence
    memory: MemoryEvidence


class LimitEvidence(NativeReviewedDocumentModel):
    enforced: Literal["not-enforced"]
    evidence: Literal["declared", "missing"]
    requested: int | None = Field(default=None, ge=0)

    @field_validator("requested", mode="before")
    @classmethod
    def requested_is_json_int(cls, value: object) -> object:
        if value is None:
            raise ValueError("requested ceiling cannot be null")
        return _require_json_int(value)

    @model_validator(mode="after")
    def evidence_matches_request(self) -> Self:
        if self.evidence == "declared" and type(self.requested) is not int:
            raise ValueError("declared limit is missing its requested value")
        if self.evidence == "missing" and self.requested is not None:
            raise ValueError("missing limit cannot carry a requested value")
        return self


class LimitEvidenceSet(NativeReviewedDocumentModel):
    wall_time_seconds: LimitEvidence = Field(alias="wallTimeSeconds")
    stdout_bytes: LimitEvidence = Field(alias="stdoutBytes")
    stderr_bytes: LimitEvidence = Field(alias="stderrBytes")
    artifact_bytes: LimitEvidence = Field(alias="artifactBytes")
    process_count: LimitEvidence = Field(alias="processCount")
    memory_bytes: LimitEvidence = Field(alias="memoryBytes")


class ReviewedInputDigest(NativeReviewedDocumentModel):
    name: ReviewedIdentifier
    digest: ByteDigest


class ReviewedSideEffects(NativeReviewedDocumentModel):
    """Literal zeros. The validator has no import, spawn, or append path."""

    entrypoints_imported: Literal[0] = Field(alias="entrypointsImported")
    processes_spawned: Literal[0] = Field(alias="processesSpawned")
    lifecycle_facts_appended: Literal[0] = Field(alias="lifecycleFactsAppended")

    @field_validator(
        "entrypoints_imported",
        "processes_spawned",
        "lifecycle_facts_appended",
        mode="before",
    )
    @classmethod
    def counts_are_json_ints(cls, value: object) -> object:
        return _require_json_int(value)


ReviewedReasonCode = Literal[
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
]


class NativeReviewedExecutionReport(NativeReviewedDocumentModel):
    """Validation report. ``launchAllowed`` cannot be true in this schema."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["NativeReviewedExecutionReport"]
    profile: Literal["native-reviewed-python/v0alpha1"]
    evidence_class: Literal["contract-check"] = Field(alias="evidenceClass")
    request_digest: JcsDigest = Field(alias="requestDigest")
    project_id: ReviewedIdentifier = Field(alias="projectId")
    run_id: ReviewedIdentifier = Field(alias="runId")
    attempt_id: ReviewedIdentifier = Field(alias="attemptId")
    task_id: ReviewedIdentifier = Field(alias="taskId")
    authorization_event_id: ReviewedIdentifier = Field(alias="authorizationEventId")
    authorization_sequence: ReviewedSequence = Field(alias="authorizationSequence")
    platform: ReviewedPlatform
    accepted_for_preparation: bool = Field(alias="acceptedForPreparation")
    launch_allowed: Literal[False] = Field(alias="launchAllowed")
    outcome: Literal["accepted-for-preparation", "refused"]
    reason_code: ReviewedReasonCode = Field(alias="reasonCode")
    restrictions: RestrictionEvidence
    limits: LimitEvidenceSet
    code_digest: ByteDigest = Field(alias="codeDigest")
    input_digests: tuple[ReviewedInputDigest, ...] = Field(
        max_length=MAX_REVIEWED_INPUTS,
        alias="inputDigests",
    )
    interpreter_digest: ByteDigest = Field(alias="interpreterDigest")
    dependency_lock_digest: ByteDigest = Field(alias="dependencyLockDigest")
    inventory_digest: ByteDigest = Field(alias="inventoryDigest")
    side_effects: ReviewedSideEffects = Field(alias="sideEffects")

    @field_validator("accepted_for_preparation", "launch_allowed", mode="before")
    @classmethod
    def flags_are_json_bools(cls, value: object) -> object:
        return _require_json_bool(value)

    @field_validator("input_digests", mode="before")
    @classmethod
    def freeze_input_digests(cls, value: object) -> object:
        if type(value) is not list:
            raise ValueError("inputDigests must be a JSON array")
        return tuple(value)

    @model_validator(mode="after")
    def outcome_is_not_launch_authority(self) -> Self:
        if self.accepted_for_preparation:
            if (
                self.outcome != "accepted-for-preparation"
                or self.reason_code != "launch-not-implemented"
            ):
                raise ValueError("accepted report is not launch authority")
        elif self.outcome != "refused" or self.reason_code == "launch-not-implemented":
            raise ValueError("refusal report is inconsistent")
        return self
