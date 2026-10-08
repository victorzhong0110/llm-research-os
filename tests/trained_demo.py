"""Source-checkout engineering demo; synthetic actors, real reviewed CPU model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from test_application_native import setup_native

from llm_research_os.application.research import spec_identity
from llm_research_os.application.workspace import Workspace
from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.evaluation import iris
from llm_research_os.spec.diff import semantic_diff
from llm_research_os.spec.models import ResearchSpec


def stage_trained_demo(directory: Path) -> tuple[Workspace, dict[str, Any]]:
    workspace, _world, _profile = setup_native(
        directory, task_source=Path(iris.__file__).read_bytes(), stdout_bytes=65536, revision=2
    )
    candidate = ResearchSpec.model_validate_json((workspace.root / "spec.json").read_bytes())
    base = ResearchSpec.model_validate(
        {
            "apiVersion": "researchos.dev/v0alpha1",
            "kind": "ResearchProject",
            "metadata": {
                "id": workspace.project_id,
                "revision": 1,
                "title": "Engineering demo before CPU task",
            },
            "questions": [
                {"id": "rq.demo", "question": "Can a fixed public training result be recomputed?"}
            ],
            "hypotheses": [],
            "evidence": [],
            "datasets": [],
            "models": [],
            "workflows": [],
            "evaluations": [],
            "resources": [],
            "policies": {
                "paidActionsRequireApproval": True,
                "destructiveActionsRequireApproval": True,
                "preserveAiDissent": True,
                "unknownEvidenceMayTrain": False,
            },
        }
    )
    artifacts = LocalArtifactStore(workspace.cas_root)
    base_id, candidate_id = [
        artifacts.put_bytes(
            canonical_json(spec.model_dump(mode="json", by_alias=True, exclude_none=True)).encode()
        ).digest
        for spec in (base, candidate)
    ]
    actor = {"id": "mock.deterministic", "kind": "ai", "modelId": "mock.deterministic.v1"}
    proposal = {
        "apiVersion": "researchos.dev/v0alpha1",
        "kind": "ProposalSubmitRequest",
        "projectId": workspace.project_id,
        "experimentRevision": 1,
        "source": "researchos://demo/synthetic",
        "subject": "proposal.cpu",
        "streamid": "stream.research",
        "actor": actor,
        "event": {"id": "evt.proposal.cpu", "time": "2026-10-08T00:00:00Z"},
        "proposalId": "proposal.cpu",
        "proposedSpecDigest": spec_identity(candidate),
        "specDiffDigest": content_digest(
            {
                "baseSpecDigest": spec_identity(base),
                "candidateSpecDigest": spec_identity(candidate),
                "changes": [change.as_dict() for change in semantic_diff(base, candidate)],
            }
        ),
        "rationale": "Synthetic proposed CPU benchmark; no research improvement claim.",
        "predictions": [
            {
                "id": "prediction.cpu",
                "statement": "Stored predictions reproduce aggregate metrics.",
                "expectedDirection": "increase",
            }
        ],
        "falsificationConditions": [
            "A stored prediction, model parameter or setup cannot be reproduced."
        ],
        "riskAssessment": {
            "data": "Public UCI Iris, CC BY 4.0; development benchmark.",
            "method": "One deterministic split; no significance or independent confirmation.",
            "safety": "Reviewed same-user CPU task; not hostile-code isolation.",
            "cost": "No paid provider.",
        },
        "evidenceRefs": [],
    }
    fixture = {
        "apiVersion": "researchos.dev/v0alpha1",
        "kind": "ModelFixture",
        "id": "trained-demo",
        "prompt": {"task": "Synthetic CPU workflow proposal; no execution authority."},
        "output": proposal,
    }
    request = {
        "apiVersion": "researchos.dev/v0alpha1",
        "kind": "ModelGenerateRequest",
        "projectId": workspace.project_id,
        "experimentRevision": 1,
        "source": "researchos://models/mock",
        "subject": "call.cpu",
        "streamid": "stream.models",
        "actor": actor,
        "callId": "call.cpu",
        "fixtureId": fixture["id"],
        "providerId": "mock.deterministic",
        "requestedCapabilities": ["generate"],
        "events": {
            "ai.call.started": {"id": "evt.call.cpu.started", "time": "2026-10-08T00:00:00Z"},
            "ai.call.completed": {"id": "evt.call.cpu.completed", "time": "2026-10-08T00:00:01Z"},
        },
        "evidenceRefs": [],
    }
    (workspace.root / "trained-request.json").write_text(json.dumps(request))
    (workspace.root / "trained-model-fixture.json").write_text(json.dumps(fixture))
    (workspace.root / "model-profiles").mkdir()
    (workspace.root / "model-profiles/mock.json").write_text(
        json.dumps(
            {
                "apiVersion": "researchos.dev/application/v0alpha1",
                "kind": "ResearchModelProfile",
                "request": "trained-request.json",
                "fixture": "trained-model-fixture.json",
                "baseArtifact": base_id,
                "candidateArtifact": candidate_id,
            }
        )
    )
    return workspace, {
        "profile": "mock",
        "nativeProfile": "cpu",
        "proposalId": proposal["proposalId"],
        "revision": 2,
        "baseArtifact": base_id,
        "candidateArtifact": candidate_id,
    }
