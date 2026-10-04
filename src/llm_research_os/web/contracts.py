"""Authoritative response contracts for the local API.

The browser's types are generated from these models, so the wire contract has
one owner. ``scripts/generate_web_types.py`` renders the TypeScript, and
``tests/test_web_contracts.py`` fails when the committed file drifts from the
models. A view that changes shape therefore breaks the type check and the drift
test instead of silently disagreeing with the client.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from llm_research_os.canonical import SEMANTIC_DIGEST_PATTERN
from llm_research_os.web.errors import ApiErrorCode

LOCAL_API_VERSION = "researchos.dev/local-api/v0alpha1"
LOCAL_API_CONTRACT_VERSION = "v0alpha1"

# Every lifecycle state the workbench must keep visually distinct. R10 acceptance
# requires that unknown, lost, failed, cancel-requested and an observed stop are
# never styled as success, so the states are a closed set rather than free text.
RunObservationState = Literal[
    "absent",
    "cancel-requested",
    "failed",
    "lost",
    "observed-stop",
    "queued",
    "running",
    "succeeded",
    "unknown",
]

# A metric or result is real, synthetic, or absent. Synthetic values must never
# be presented as measurements.
DataOrigin = Literal["absent", "real", "synthetic"]


class Contract(BaseModel):
    """Frozen, alias-keyed, closed models matching the repository convention."""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=False,
        validate_by_alias=True,
        str_strip_whitespace=False,
        strict=True,
        extra="forbid",
        allow_inf_nan=False,
    )


class ErrorDocument(Contract):
    api_version: Literal["researchos.dev/local-api/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["LocalApiError"]
    code: ApiErrorCode
    message: str


class HealthDocument(Contract):
    api_version: Literal["researchos.dev/local-api/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["Health"]
    status: Literal["ready"]


class SessionDetails(Contract):
    csrf_token: str = Field(alias="csrfToken")
    csrf_header: str = Field(alias="csrfHeader")
    idle_timeout_seconds: int = Field(alias="idleTimeoutSeconds", ge=1)


class SessionDocument(SessionDetails):
    api_version: Literal["researchos.dev/local-api/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["BrowserSession"]


class LimitsDocument(Contract):
    max_body_bytes: int = Field(alias="maxBodyBytes", ge=1)
    max_concurrent_requests: int = Field(alias="maxConcurrentRequests", ge=1)
    max_decoded_depth: int = Field(alias="maxDecodedDepth", ge=1)
    max_decoded_nodes: int = Field(alias="maxDecodedNodes", ge=1)
    max_evidence_bytes: int = Field(alias="maxEvidenceBytes", ge=1)
    max_extracted_chars: int = Field(alias="maxExtractedChars", ge=1)
    max_pdf_pages: int = Field(alias="maxPdfPages", ge=1)
    read_timeout_seconds: float = Field(alias="readTimeoutSeconds", gt=0)


class CapabilitiesDocument(Contract):
    api_version: Literal["researchos.dev/local-api/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["Capabilities"]
    read_only: bool = Field(alias="readOnly")
    limits: LimitsDocument
    session: SessionDetails
    poll_fallback_seconds: float = Field(alias="pollFallbackSeconds", gt=0)


class WorkspaceDocument(Contract):
    api_version: Literal["researchos.dev/local-api/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["WorkspaceView"]
    project_id: str = Field(alias="projectId")
    control_db: str = Field(alias="controlDb")
    cas_root: str = Field(alias="casRoot")
    worker_root: str = Field(alias="workerRoot")
    high_water_mark: int = Field(alias="highWaterMark", ge=0)


class EventItem(Contract):
    sequence: int = Field(ge=1)
    event_id: str = Field(alias="eventId")
    type: str
    occurred_at: str = Field(alias="occurredAt")
    project_id: str = Field(alias="projectId")
    run_id: str | None = Field(default=None, alias="runId")
    attempt_id: str | None = Field(default=None, alias="attemptId")


class RevisionItem(Contract):
    revision: int = Field(ge=1)
    spec_digest: Annotated[str, Field(pattern=SEMANTIC_DIGEST_PATTERN)] = Field(alias="specDigest")
    first_seen_sequence: int = Field(alias="firstSeenSequence", ge=1)


class RunItem(Contract):
    run_id: str = Field(alias="runId")
    last_sequence: int = Field(alias="lastSequence", ge=1)
    last_event_type: str = Field(alias="lastEventType")
    attempt_id: str | None = Field(default=None, alias="attemptId")
    observation: RunObservationState = "absent"
    origin: DataOrigin = "absent"


class ArtifactDocument(Contract):
    api_version: Literal["researchos.dev/local-api/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["ArtifactView"]
    digest: Annotated[str, Field(pattern=SEMANTIC_DIGEST_PATTERN)]
    byte_length: int = Field(alias="byteLength", ge=0)
    inline: bool
    verification: Literal["verified", "not-inlined"] = "not-inlined"
    text: str | None = None

    @model_validator(mode="after")
    def inline_requires_text(self) -> Self:
        if self.inline and self.text is None:
            raise ValueError("an inlined artifact must carry its text")
        return self


class LineageLink(Contract):
    kind: Literal["event", "artifact", "revision"]
    target: str
    label: str
    via: tuple[str, ...] = Field(default=(), max_length=9)


class InspectionDocument(Contract):
    api_version: Literal["researchos.dev/local-api/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["InspectionView"]
    identity: str
    document: dict[str, Any]
    links: tuple[LineageLink, ...]
    immutable: Literal[True]


class DocumentPreviewDocument(Contract):
    api_version: Literal["researchos.dev/local-api/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["DocumentPreview"]
    document_kind: Literal["json", "pdf", "yaml"] = Field(alias="documentKind")
    byte_length: int = Field(alias="byteLength", ge=1)
    decoded: dict[str, Any]


class CommandReceipt(Contract):
    """Result of one browser-dispatched shared command.

    R11's honesty rule lives in this shape: ``disposition`` says whether the
    command was newly committed or replayed from a prior receipt, and the
    result carries ``observedStop``/``launchAllowed`` so the client can never
    render an accepted request as an observed process outcome.
    """

    # The receipt is the shared application's own document, passed through
    # unchanged. The local API envelope carries the local-api version; the body
    # keeps the identity the CLI, Python and browser all agree on.
    api_version: Literal["researchos.dev/application/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["ApplicationReceipt"]
    command_id: str = Field(alias="commandId")
    actor_id: str = Field(alias="actorId")
    submitted_at: str = Field(alias="submittedAt")
    operation: str
    request_digest: Annotated[str, Field(pattern=SEMANTIC_DIGEST_PATTERN)] = Field(
        alias="requestDigest"
    )
    expected_head: int | None = Field(default=None, alias="expectedHead", ge=0)
    expected_revision: int | None = Field(default=None, alias="expectedRevision", ge=1)
    observed_head: int = Field(alias="observedHead", ge=0)
    disposition: Literal["committed", "replayed"]
    fact_event_ids: tuple[str, ...] = Field(alias="factEventIds")
    artifact_digests: tuple[str, ...] = Field(alias="artifactDigests")
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


class _Page(Contract):
    api_version: Literal["researchos.dev/local-api/v0alpha1"] = Field(alias="apiVersion")
    next_cursor: str | None = Field(default=None, alias="nextCursor")
    high_water_mark: int = Field(alias="highWaterMark", ge=0)


class EventPageDocument(_Page):
    kind: Literal["EventPage"]
    items: tuple[EventItem, ...]


class RevisionPageDocument(_Page):
    kind: Literal["RevisionPage"]
    items: tuple[RevisionItem, ...]


class RunPageDocument(_Page):
    kind: Literal["RunPage"]
    items: tuple[RunItem, ...]


CONTRACT_MODELS: dict[str, type[Contract]] = {
    "ArtifactView": ArtifactDocument,
    "Capabilities": CapabilitiesDocument,
    "CommandReceipt": CommandReceipt,
    "DocumentPreview": DocumentPreviewDocument,
    "Error": ErrorDocument,
    "EventPage": EventPageDocument,
    "EventItem": EventItem,
    "Health": HealthDocument,
    "InspectionView": InspectionDocument,
    "LineageLink": LineageLink,
    "Limits": LimitsDocument,
    "LocalApiError": ErrorDocument,
    "RevisionItem": RevisionItem,
    "RevisionPage": RevisionPageDocument,
    "RunItem": RunItem,
    "RunPage": RunPageDocument,
    "Session": SessionDocument,
    "WorkspaceView": WorkspaceDocument,
}
