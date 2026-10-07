"""Frozen operator materials and evidence-linked research drafts, without authority."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field

from llm_research_os.application.errors import ApplicationError
from llm_research_os.application.models import ApplicationModel, CommandPath
from llm_research_os.application.native import confined
from llm_research_os.application.workspace import Workspace
from llm_research_os.artifacts import ArtifactStoreError
from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.budget.control import BudgetControl
from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.evidence.control import EvidenceControl
from llm_research_os.execution.native_reviewed_preparation import load_bounded_file
from llm_research_os.providers.compat_requests import OpenAICompatGenerateRequestDocument
from llm_research_os.providers.models import ModelFixtureDocument
from llm_research_os.providers.requests import ModelGenerateRequestDocument
from llm_research_os.research.requests import ProposalSubmitRequestDocument
from llm_research_os.spec.diff import semantic_diff
from llm_research_os.spec.io import decode_document_text
from llm_research_os.spec.models import ResearchSpec
from llm_research_os.storage import EventStore

ArtifactId = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
MAX_RESEARCH_BYTES = 1_048_576


class ResearchModelProfile(ApplicationModel):
    api_version: Literal["researchos.dev/application/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["ResearchModelProfile"]
    request: CommandPath
    fixture: CommandPath
    base_artifact: ArtifactId = Field(alias="baseArtifact")
    candidate_artifact: ArtifactId = Field(alias="candidateArtifact")


@dataclass(frozen=True, slots=True)
class ModelContext:
    profile: ResearchModelProfile
    request: ModelGenerateRequestDocument | OpenAICompatGenerateRequestDocument
    fixture: ModelFixtureDocument
    base: ResearchSpec
    candidate: ResearchSpec
    digest: str


def read_artifact(workspace: Workspace, digest: str) -> dict[str, Any]:
    try:
        with LocalArtifactStore(workspace.cas_root).open(digest) as stream:
            payload = stream.read(MAX_RESEARCH_BYTES + 1)
        if (
            len(payload) > MAX_RESEARCH_BYTES
            or "sha256:" + hashlib.sha256(payload).hexdigest() != digest
        ):
            raise ValueError("artifact size or digest")
        document = decode_document_text(payload.decode("utf-8"), suffix=".json")
        if type(document) is not dict:
            raise ValueError("artifact is not an object")
        return document
    except (OSError, ValueError, ArtifactStoreError) as exc:
        raise ApplicationError(
            "research-artifact-invalid", "research artifact is unreadable"
        ) from exc


def spec_artifact(workspace: Workspace, digest: str) -> ResearchSpec:
    return ResearchSpec.model_validate(read_artifact(workspace, digest))


def spec_identity(spec: ResearchSpec) -> str:
    return content_digest(spec.model_dump(mode="json", by_alias=True, exclude_none=True))


def freeze_model(workspace: Workspace, profile_id: str) -> ModelContext:
    def document(path: Path) -> dict[str, Any]:
        payload = load_bounded_file(confined(workspace.root, path), limit=MAX_RESEARCH_BYTES)
        return decode_document_text(payload.decode("utf-8"), suffix=path.suffix)

    try:
        profile = ResearchModelProfile.model_validate(
            document(Path("model-profiles") / f"{profile_id}.json")
        )
        raw = document(Path(profile.request))
        request = (
            ModelGenerateRequestDocument.model_validate(raw)
            if raw.get("kind") == "ModelGenerateRequest"
            else OpenAICompatGenerateRequestDocument.model_validate(raw)
        )
        fixture = ModelFixtureDocument.model_validate(document(Path(profile.fixture)))
        if request.project_id != workspace.project_id or request.fixture_id != fixture.id:
            raise ValueError("profile identity mismatch")
        base = spec_artifact(workspace, profile.base_artifact)
        candidate = spec_artifact(workspace, profile.candidate_artifact)
        if (
            base.metadata.revision != request.experiment_revision
            or str(base.metadata.id) != workspace.project_id
        ):
            raise ValueError("base project or revision mismatch")
        if str(candidate.metadata.id) != workspace.project_id:
            raise ValueError("candidate project mismatch")
        semantic_diff(base, candidate)
        digest = content_digest(
            {
                "profile": profile.model_dump(mode="json", by_alias=True),
                "request": request.model_dump(mode="json", by_alias=True),
                "fixture": fixture.model_dump(mode="json", by_alias=True),
                "base": spec_identity(base),
                "candidate": spec_identity(candidate),
            }
        )
        return ModelContext(profile, request, fixture, base, candidate, digest)
    except (OSError, ValueError) as exc:
        raise ApplicationError(
            "model-profile-invalid", "installed model profile failed validation"
        ) from exc


def require_base(workspace: Workspace, base: ResearchSpec, revision: int | None) -> None:
    if str(base.metadata.id) != workspace.project_id or base.metadata.revision != revision:
        raise ApplicationError("stale-revision", "base project or expectedRevision differs")
    with EventStore(workspace.control_db, require_existing=True) as store:
        rows = [
            row for row in store.list_spec_revisions() if row.project_id == workspace.project_id
        ]
        if rows:
            latest = max(rows, key=lambda row: row.revision)
            if latest.revision != revision or latest.spec_digest != spec_identity(base):
                raise ApplicationError(
                    "stale-revision", "base does not match the latest recorded specification"
                )
        elif revision != 1:
            raise ApplicationError(
                "stale-revision", "an unrecorded project may only draft from its initial revision"
            )


def require_citations(workspace: Workspace, references: tuple[str, ...]) -> list[dict[str, Any]]:
    with EventStore(workspace.control_db, require_existing=True) as store:
        recorded = (
            EvidenceControl(store, project_id=workspace.project_id).rebuild().fold.evidence_ids
        )
        if any(reference not in recorded for reference in references):
            raise ApplicationError(
                "citation-unresolved", "citations must resolve to imported evidence in this project"
            )
        # Preserve versioned source facts and distinguish reading from training rights.
        from llm_research_os.projections.replay import replay_events

        wanted = set(references)
        rows = []
        for stored in replay_events(store):
            event = stored.event
            if event.type == "evidence.imported" and event.data.project_id == workspace.project_id:
                payload = dict(event.data.payload)
                if payload.get("evidenceId") in wanted:
                    rows.append({"eventId": event.id, **payload})
        return rows


def proposal_preview(
    workspace: Workspace,
    proposal: ProposalSubmitRequestDocument,
    base: ResearchSpec,
    candidate: ResearchSpec,
    revision: int | None,
    *,
    historical_committed: bool = False,
) -> dict[str, Any]:
    if historical_committed:
        if str(base.metadata.id) != workspace.project_id or base.metadata.revision != revision:
            raise ApplicationError("stale-revision", "historical base identity differs")
    else:
        require_base(workspace, base, revision)
    if proposal.project_id != workspace.project_id or proposal.experiment_revision != revision:
        raise ApplicationError("stale-revision", "proposal base project or revision differs")
    changes = [change.as_dict() for change in semantic_diff(base, candidate)]
    derived = content_digest(
        {
            "baseSpecDigest": spec_identity(base),
            "candidateSpecDigest": spec_identity(candidate),
            "changes": changes,
        }
    )
    if (
        proposal.proposed_spec_digest != spec_identity(candidate)
        or proposal.spec_diff_digest != derived
    ):
        raise ApplicationError(
            "proposal-diff-mismatch",
            "proposal must bind the recomputed candidate and semantic diff",
        )
    citations = require_citations(workspace, proposal.evidence_refs)
    return {
        "valid": True,
        "historicalCommittedFact": historical_committed,
        "draft": proposal.model_dump(mode="json", by_alias=True),
        "baseRevision": base.metadata.revision,
        "candidateRevision": candidate.metadata.revision,
        "baseSpecDigest": spec_identity(base),
        "candidateSpecDigest": spec_identity(candidate),
        "specDiffDigest": derived,
        "changes": changes,
        "citations": citations,
        "resourceNeeds": [
            item.model_dump(mode="json", by_alias=True) for item in candidate.resources
        ],
        "runQueued": False,
        "grantedPermissions": [],
        "launchAllowed": False,
    }


def store_draft(
    workspace: Workspace, preview: dict[str, Any], base_artifact: str, candidate_artifact: str
) -> str:
    document = {
        "apiVersion": "researchos.dev/application/v0alpha1",
        "kind": "ValidatedResearchDraft",
        "baseArtifact": base_artifact,
        "candidateArtifact": candidate_artifact,
        **preview,
    }
    return (
        LocalArtifactStore(workspace.cas_root).put_bytes(canonical_json(document).encode()).digest
    )


def budget_view(workspace: Workspace) -> dict[str, Any]:
    with EventStore(workspace.control_db, require_existing=True) as store:
        head = BudgetControl(store, project_id=workspace.project_id).rebuild()
    fold = head.fold
    return {
        "projectId": workspace.project_id,
        "lastSequence": head.last_sequence,
        "approvedCap": str(fold.approved_cap) if fold.approved_cap is not None else None,
        "consumed": str(fold.consumed),
        "outstanding": str(fold.outstanding),
        "remaining": str(fold.approved_cap - fold.consumed - fold.outstanding)
        if fold.approved_cap is not None
        else None,
        "openReservations": [
            {"budgetId": item.budget_id, "callId": item.call_id, "amount": str(item.amount)}
            for item in fold.open
        ],
        "accounting": "project budget facts; actual provider invoice cost is unknown",
        "actualProviderCost": None,
        "launchAllowed": False,
    }
