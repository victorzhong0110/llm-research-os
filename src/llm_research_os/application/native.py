"""Operator-configured native launches; browser callers never select secret paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import ConfigDict, Field, model_validator

from llm_research_os.application.errors import ApplicationError
from llm_research_os.application.models import ApplicationModel, CommandPath
from llm_research_os.application.workspace import Workspace
from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.blocks.registry import BlockRegistry, build_registry
from llm_research_os.canonical import content_digest
from llm_research_os.execution.native_reviewed import parse_native_reviewed_request, request_digest
from llm_research_os.execution.native_reviewed_checkpoint import NativeRestoreClaim
from llm_research_os.execution.native_reviewed_documents import NativeReviewedExecutionRequest
from llm_research_os.execution.native_reviewed_preparation import load_bounded_file
from llm_research_os.execution.native_reviewed_recovery import reconcile_reviewed_native
from llm_research_os.execution.native_reviewed_runtime import execute_reviewed_native
from llm_research_os.spec.io import decode_document_text
from llm_research_os.spec.models import ResearchSpec
from llm_research_os.storage import EventStore
from llm_research_os.storage.errors import EventStoreError
from llm_research_os.workers.plane import WorkerPlane


class NativeLaunchProfile(ApplicationModel):
    """Installed by the operator, never accepted as browser-supplied JSON."""

    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {"required": [name], "properties": {name: {"type": "string"}}},
                    "then": {"required": [other], "properties": {other: {"type": "string"}}},
                }
                for name, other in (
                    ("restoreClaim", "sourceRequest"),
                    ("sourceRequest", "restoreClaim"),
                )
            ]
        }
    )

    api_version: Literal["researchos.dev/application/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["NativeLaunchProfile"]
    request: CommandPath
    spec: CommandPath
    registry: list[CommandPath] = Field(min_length=1, max_length=32)
    prepared_root: CommandPath = Field(alias="preparedRoot")
    state_root: CommandPath = Field(alias="stateRoot")
    grant_token_file: CommandPath = Field(alias="grantTokenFile")
    hmac_key_file: CommandPath = Field(alias="hmacKeyFile")
    restore_claim: CommandPath | None = Field(default=None, alias="restoreClaim")
    source_request: CommandPath | None = Field(default=None, alias="sourceRequest")

    @model_validator(mode="after")
    def restore_requires_both_documents(self) -> Self:
        if (self.restore_claim is None) != (self.source_request is None):
            raise ValueError("restore requires both sourceRequest and restoreClaim")
        return self


def confined(root: Path, path: Path, *, exists: bool = True) -> Path:
    """Check every ancestor; existing inputs cannot traverse symbolic links."""
    root = root.resolve()
    if not path.is_absolute():
        path = root / path
    try:
        relative = path.relative_to(root)
        if ".." in relative.parts:
            raise ValueError("parent traversal")
        current = root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ValueError("symlink")
        path.resolve(strict=exists).relative_to(root)
    except (ValueError, OSError):
        raise ApplicationError(
            "input-refused", "configured material must stay inside its root"
        ) from None
    return path


@dataclass(frozen=True)
class NativeContext:
    profile: NativeLaunchProfile
    request: NativeReviewedExecutionRequest
    spec: ResearchSpec
    registry: BlockRegistry
    prepared: Path
    state: Path
    token: str
    key: bytes
    claim: NativeRestoreClaim | None
    source: NativeReviewedExecutionRequest | None
    digest: str


def freeze_native(workspace: Workspace, profile_id: str) -> NativeContext:
    try:
        profile_path = confined(workspace.root, Path("native-profiles") / f"{profile_id}.json")
        profile = NativeLaunchProfile.model_validate_json(
            load_bounded_file(profile_path, limit=65536)
        )

        def read(name: str, limit: int = 1_048_576) -> bytes:
            return load_bounded_file(confined(workspace.root, Path(name)), limit=limit)

        request = parse_native_reviewed_request(read(profile.request))
        spec_path = confined(workspace.root, Path(profile.spec))
        spec = ResearchSpec.model_validate(
            decode_document_text(read(profile.spec).decode("utf-8"), suffix=spec_path.suffix)
        )
        # Registry contents are frozen in memory before dispatch, just as the
        # request/spec are. The runtime checks their exact authorization digests.
        paths = [confined(workspace.root, Path(name)) for name in profile.registry]
        registry = build_registry(paths)
        token = read(profile.grant_token_file, 4096).decode("ascii").rstrip("\r\n")
        key = read(profile.hmac_key_file, 32)
        if len(key) != 32:
            raise ValueError("key length")
        prepared = confined(workspace.worker_root, Path(profile.prepared_root))
        state = confined(workspace.worker_root, Path(profile.state_root), exists=False)
        claim = (
            NativeRestoreClaim.model_validate_json(read(profile.restore_claim))
            if profile.restore_claim
            else None
        )
        source = (
            parse_native_reviewed_request(read(profile.source_request))
            if profile.source_request
            else None
        )
        if (
            request.project_id != workspace.project_id
            or str(spec.metadata.id) != workspace.project_id
        ):
            raise ValueError("project differs")
        if int(request.revision_id) != spec.metadata.revision:
            raise ValueError("revision differs")
        digest = content_digest(
            {
                "profile": profile.model_dump(mode="json", by_alias=True),
                "request": request_digest(request),
                "spec": content_digest(
                    spec.model_dump(mode="json", by_alias=True, exclude_none=True)
                ),
                "registry": registry.digest(),
                "claim": claim.model_dump(mode="json", by_alias=True) if claim else None,
                "source": request_digest(source) if source else None,
            }
        )
        return NativeContext(
            profile, request, spec, registry, prepared, state, token, key, claim, source, digest
        )
    except (OSError, ValueError) as exc:
        raise ApplicationError(
            "native-profile-invalid", "the installed native profile was refused"
        ) from exc


def dispatch_native(
    workspace: Workspace, context: NativeContext, *, observe: bool
) -> dict[str, Any]:
    """Use existing reviewed launch/restore or conservative reconciliation gates."""
    request = context.request
    try:
        with EventStore(workspace.control_db, require_existing=True) as store:
            plane = WorkerPlane(
                store=store,
                artifacts=LocalArtifactStore(workspace.cas_root),
                hmac_key=context.key,
                project_id=workspace.project_id,
                source=f"https://researchos.dev/projects/{workspace.project_id}",
                experiment_revision=int(request.revision_id),
            )
            if observe:
                result = reconcile_reviewed_native(
                    request=request, plane=plane, state_dir=context.state, grant_token=context.token
                )
                return {
                    "runId": request.run_id,
                    "attemptId": request.attempt_id,
                    "observation": result.disposition,
                    "leaseId": result.lease_id,
                    "launchAllowed": False,
                }
            completed = execute_reviewed_native(
                request=request,
                spec=context.spec,
                registry=context.registry,
                plane=plane,
                workspace=context.prepared,
                state_dir=context.state,
                grant_token=context.token,
                restore_claim=context.claim,
                source_request=context.source,
            )
            return {
                "runId": request.run_id,
                "attemptId": request.attempt_id,
                "observation": "completed",
                "leaseId": completed.lease_id,
                "artifactDigest": completed.artifact_digest,
                "resultDigest": completed.result_digest,
                "launchAllowed": False,
            }
    except (OSError, ValueError, EventStoreError) as exc:
        raise ApplicationError(
            "native-outcome-uncertain",
            "native dispatch was refused or remains uncertain; observe this Run",
        ) from exc
