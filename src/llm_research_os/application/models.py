"""Closed v0alpha1 command and receipt documents for shared application services."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import ConfigDict, Field, ValidationError, field_validator, model_validator

from llm_research_os.application.errors import ApplicationError
from llm_research_os.canonical import SEMANTIC_DIGEST_PATTERN
from llm_research_os.events.models import (
    CLOUD_EVENTS_INTEGER_MAX,
    EventDocumentModel,
    EventIdentifier,
    Rfc3339Timestamp,
)
from llm_research_os.spec.io import load_document

APPLICATION_API_VERSION = "researchos.dev/application/v0alpha1"
APPLICATION_COMMAND_SCHEMA_ID = (
    "https://researchos.dev/schemas/application-command/v0alpha1.schema.json"
)
APPLICATION_RECEIPT_SCHEMA_ID = (
    "https://researchos.dev/schemas/application-receipt/v0alpha1.schema.json"
)

# `evaluation.run` writes a CAS detail artifact but appends no event, so it is
# revision-bound without being head-bound. Only an operation that appends a fact
# needs the CAS token.
_MUTATING = frozenset(
    {
        "authorization.revoke",
        "conclusion.record",
        "proposal.submit",
        "research.decision",
        "run.cancel",
        "run.simulate",
        "native.start",
        "native.restore",
        "backup.restore",
    }
)
_REVISION_BOUND = frozenset(
    {
        "spec.validate",
        "spec.diff",
        "plan.dry-run",
        "research.decision",
        "run.simulate",
        "plan.preflight",
        "proposal.validate",
        "proposal.submit",
        "evaluation.run",
        "conclusion.record",
        "native.start",
        "native.restore",
    }
)
_HEAD_BOUND = frozenset(
    {
        "research.ledger",
        "research.decision",
        "revision.list",
        "run.show",
        "run.simulate",
        "run.cancel",
        "proposal.submit",
        "proposal.validate",
    }
)
_PATH_PATTERN = r"^[^\x00-\x1F\x7F]+$"
CommandPath = Annotated[str, Field(min_length=1, max_length=4096, pattern=_PATH_PATTERN)]


class ApplicationModel(EventDocumentModel):
    """Frozen application documents: aliases only, strict, no trimming."""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=False,
        validate_by_name=False,
        validate_by_alias=True,
        str_strip_whitespace=False,
        strict=True,
        extra="forbid",
        validate_assignment=True,
        allow_inf_nan=False,
    )


def _require_path_array(value: object) -> object:
    if type(value) is list:
        return tuple(value)
    if type(value) is tuple:
        return value
    raise ValueError("registry must be a JSON array")


class SpecValidateOperation(ApplicationModel):
    kind: Literal["spec.validate"]
    document: CommandPath


class SpecDiffOperation(ApplicationModel):
    kind: Literal["spec.diff"]
    old: CommandPath
    new: CommandPath


class PlanDryRunOperation(ApplicationModel):
    kind: Literal["plan.dry-run"]
    document: CommandPath
    workflow_id: EventIdentifier | None = Field(default=None, alias="workflowId")
    registry: tuple[CommandPath, ...] = Field(default_factory=tuple)

    @field_validator("registry", mode="before")
    @classmethod
    def registry_is_array(cls, value: object) -> object:
        return _require_path_array(value)


class ResearchLedgerOperation(ApplicationModel):
    kind: Literal["research.ledger"]


class ResearchDecisionOperation(ApplicationModel):
    kind: Literal["research.decision"]
    request: CommandPath


class RevisionListOperation(ApplicationModel):
    kind: Literal["revision.list"]


class RunShowOperation(ApplicationModel):
    kind: Literal["run.show"]
    run_id: EventIdentifier = Field(alias="runId")


class RunSimulateOperation(ApplicationModel):
    kind: Literal["run.simulate"]
    spec: CommandPath
    request: CommandPath
    registry: tuple[CommandPath, ...] = Field(default_factory=tuple)

    @field_validator("registry", mode="before")
    @classmethod
    def registry_is_array(cls, value: object) -> object:
        return _require_path_array(value)


class WorkspaceShowOperation(ApplicationModel):
    kind: Literal["workspace.show"]


class NativeOperation(ApplicationModel):
    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"kind": {"enum": ["native.start", "native.restore"]}}},
                    "then": {
                        "required": ["materialDigest"],
                        "properties": {"materialDigest": {"type": "string"}},
                    },
                }
            ]
        }
    )

    kind: Literal["native.start", "native.restore", "native.observe", "native.inspect"]
    profile_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")] = Field(
        alias="profileId"
    )
    material_digest: Annotated[str, Field(pattern=SEMANTIC_DIGEST_PATTERN)] | None = Field(
        default=None, alias="materialDigest"
    )

    @model_validator(mode="after")
    def launches_bind_inspected_material(self) -> Self:
        if self.kind in {"native.start", "native.restore"} and self.material_digest is None:
            raise ValueError("launch requires inspected materialDigest")
        return self


class BackupOperation(ApplicationModel):
    kind: Literal["backup.verify", "backup.restore"]
    image_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")] = Field(
        alias="imageId"
    )
    destination_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")] | None = (
        Field(default=None, alias="destinationId")
    )

    @model_validator(mode="after")
    def destination_matches_operation(self) -> Self:
        if (self.kind == "backup.restore") != (self.destination_id is not None):
            raise ValueError("only restore requires destinationId")
        return self


class PlanPreflightOperation(ApplicationModel):
    """Show what a plan would require, without authorizing anything.

    The browser must be able to display exact plan identity, target,
    permissions, supported/enforced limits and resource or budget requirements
    *before* a human authorizes it. This operation therefore reads only: it
    mints no grant, records no fact, and never reports a launch as allowed.
    """

    kind: Literal["plan.preflight"]
    document: CommandPath
    workflow_id: EventIdentifier | None = Field(default=None, alias="workflowId")
    registry: tuple[CommandPath, ...] = Field(default_factory=tuple)

    @field_validator("registry", mode="before")
    @classmethod
    def registry_is_array(cls, value: object) -> object:
        return _require_path_array(value)


class RunCancelOperation(ApplicationModel):
    """Request cancellation of a Run or one active Attempt.

    A request is not an outcome. The receipt reports that the request was
    committed; the observed stop, if any, arrives as a later fact.
    """

    kind: Literal["run.cancel"]
    request: CommandPath


class ProposalValidateOperation(ApplicationModel):
    """Validate one proposal document and resolve its citations. Appends nothing.

    Generated or hand-written proposal text becomes a draft only after it has
    passed this check, so an unresolved citation is refused before a proposal can
    exist, rather than being discovered later.
    """

    kind: Literal["proposal.validate"]
    request: CommandPath


class ProposalSubmitOperation(ApplicationModel):
    """Append one proposal bound to a base revision and a server-derived diff.

    The document supplies its own ``experimentRevision``; a proposal whose
    revision is not the current head is refused, so a stale proposal cannot
    overwrite a newer revision.
    """

    kind: Literal["proposal.submit"]
    request: CommandPath


class EvaluationRunOperation(ApplicationModel):
    """Compute one real evaluation over the fixed held-out set.

    Reads the committed dataset and the registered predictors, writes a detail
    artifact, and appends no per-sample events. A caller may add their own
    predictor later by registering it; this slice evaluates the baseline and the
    threshold candidate only, and says so.
    """

    kind: Literal["evaluation.run"]
    mode: Literal["candidate", "majority", "threshold"]
    threshold: float | None = None
    seed: int | None = None


class EvaluationCompareOperation(ApplicationModel):
    """Compare a baseline and a candidate result, refusing incompatible setups."""

    kind: Literal["evaluation.compare"]
    baseline: CommandPath
    candidate: CommandPath


class ConclusionRecordOperation(ApplicationModel):
    """Record a human conclusion. The system never supplies the judgement."""

    kind: Literal["conclusion.record"]
    baseline: CommandPath
    candidate: CommandPath
    verdict: Literal["insufficient-evidence", "supported", "unsupported"]
    rationale: str
    conclusion_id: str = Field(alias="conclusionId")


class AuthorizationRevokeOperation(ApplicationModel):
    """Revoke an unused Worker grant. Revocation never launches or completes work."""

    kind: Literal["authorization.revoke"]
    grant_id: EventIdentifier = Field(alias="grantId")
    event_id: EventIdentifier = Field(alias="eventId")
    reason_code: EventIdentifier = Field(default="human.revoke", alias="reasonCode")


ApplicationOperation = Annotated[
    SpecValidateOperation
    | SpecDiffOperation
    | PlanDryRunOperation
    | ResearchLedgerOperation
    | ResearchDecisionOperation
    | RevisionListOperation
    | RunShowOperation
    | RunSimulateOperation
    | WorkspaceShowOperation
    | ConclusionRecordOperation
    | EvaluationCompareOperation
    | EvaluationRunOperation
    | PlanPreflightOperation
    | ProposalSubmitOperation
    | ProposalValidateOperation
    | RunCancelOperation
    | AuthorizationRevokeOperation
    | NativeOperation
    | BackupOperation,
    Field(discriminator="kind"),
]


class ApplicationCommand(ApplicationModel):
    """One identity-bound command. Callers supply identity, time, and expected head."""

    api_version: Literal["researchos.dev/application/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["ApplicationCommand"]
    command_id: EventIdentifier = Field(alias="commandId")
    actor_id: EventIdentifier = Field(alias="actorId")
    submitted_at: Rfc3339Timestamp = Field(alias="submittedAt")
    expected_head: int | None = Field(
        default=None,
        alias="expectedHead",
        ge=0,
        le=CLOUD_EVENTS_INTEGER_MAX,
    )
    expected_revision: int | None = Field(
        default=None,
        alias="expectedRevision",
        ge=1,
        le=CLOUD_EVENTS_INTEGER_MAX,
    )
    operation: ApplicationOperation

    @model_validator(mode="after")
    def bound_operations_name_their_expectations(self) -> Self:
        kind = self.operation.kind
        if kind in _HEAD_BOUND and self.expected_head is None:
            raise ValueError("expectedHead is required for this operation")
        if kind in _REVISION_BOUND and self.expected_revision is None:
            raise ValueError("expectedRevision is required for this operation")
        if kind in _MUTATING and self.expected_head is None:
            raise ValueError("expectedHead is required for a mutating operation")
        return self


class ApplicationReceipt(ApplicationModel):
    """Durable result of one command, linked to facts and artifact digests."""

    api_version: Literal["researchos.dev/application/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["ApplicationReceipt"]
    command_id: EventIdentifier = Field(alias="commandId")
    actor_id: EventIdentifier = Field(alias="actorId")
    submitted_at: Rfc3339Timestamp = Field(alias="submittedAt")
    operation: Literal[
        "spec.validate",
        "spec.diff",
        "plan.dry-run",
        "research.ledger",
        "research.decision",
        "revision.list",
        "run.show",
        "run.simulate",
        "workspace.show",
        "authorization.revoke",
        "conclusion.record",
        "evaluation.compare",
        "evaluation.run",
        "plan.preflight",
        "proposal.submit",
        "proposal.validate",
        "run.cancel",
        "native.start",
        "native.restore",
        "native.observe",
        "native.inspect",
        "backup.verify",
        "backup.restore",
    ]
    request_digest: Annotated[str, Field(pattern=SEMANTIC_DIGEST_PATTERN)] = Field(
        alias="requestDigest"
    )
    expected_head: int | None = Field(
        alias="expectedHead",
        ge=0,
        le=CLOUD_EVENTS_INTEGER_MAX,
    )
    expected_revision: int | None = Field(
        alias="expectedRevision",
        ge=1,
        le=CLOUD_EVENTS_INTEGER_MAX,
    )
    observed_head: int = Field(alias="observedHead", ge=0, le=CLOUD_EVENTS_INTEGER_MAX)
    disposition: Literal["committed", "replayed"]
    fact_event_ids: tuple[EventIdentifier, ...] = Field(alias="factEventIds")
    artifact_digests: tuple[Annotated[str, Field(pattern=SEMANTIC_DIGEST_PATTERN)], ...] = Field(
        alias="artifactDigests"
    )
    result_digest: Annotated[str, Field(pattern=SEMANTIC_DIGEST_PATTERN)] = Field(
        alias="resultDigest"
    )
    result: dict[str, Any]

    @field_validator("fact_event_ids", "artifact_digests", mode="before")
    @classmethod
    def identifier_lists_are_arrays(cls, value: object) -> object:
        if type(value) is list:
            return tuple(value)
        if type(value) is tuple:
            return value
        raise ValueError("receipt list fields must be JSON arrays")

    @model_validator(mode="after")
    def links_are_unique(self) -> Self:
        if len(self.fact_event_ids) != len(set(self.fact_event_ids)):
            raise ValueError("factEventIds entries must be unique")
        if len(self.artifact_digests) != len(set(self.artifact_digests)):
            raise ValueError("artifactDigests entries must be unique")
        return self

    def document(
        self, *, disposition: Literal["committed", "replayed"] | None = None
    ) -> dict[str, Any]:
        payload = self.model_dump(mode="json", by_alias=True)
        if disposition is not None:
            payload["disposition"] = disposition
        return payload


def load_application_command(path: str | Path) -> ApplicationCommand:
    """Load one command document. Symbolic links and invalid documents are refused."""

    try:
        document = load_document(path, reject_symlinks=True)
        return ApplicationCommand.model_validate(document)
    except (OSError, ValidationError, ValueError) as exc:
        raise ApplicationError(
            "command-invalid",
            "application command failed validation",
        ) from exc
