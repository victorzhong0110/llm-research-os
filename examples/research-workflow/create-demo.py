"""Stage a synthetic offline browser research demo; generate no call or Run."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from llm_research_os.application.research import spec_identity
from llm_research_os.application.workspace import init_workspace
from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.spec.diff import semantic_diff
from llm_research_os.spec.models import ResearchSpec
from llm_research_os.storage import EventStore

root = Path(sys.argv[1])
workspace = init_workspace(
    root,
    project_id="research-demo",
    control_db=Path("control/events.sqlite"),
    cas_root=Path("cas"),
    worker_root=Path("worker"),
)
with EventStore(workspace.control_db):
    pass
base_document = {
    "apiVersion": "researchos.dev/v0alpha1",
    "kind": "ResearchProject",
    "metadata": {"id": "research-demo", "revision": 1, "title": "Synthetic offline research demo"},
    "questions": [{"id": "rq.demo", "question": "Does the held-out metric change?"}],
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
base = ResearchSpec.model_validate(base_document)
candidate_document = {
    **base_document,
    "metadata": {
        **base_document["metadata"],
        "revision": 2,
        "title": "Synthetic candidate; no measured improvement",
    },
}
candidate = ResearchSpec.model_validate(candidate_document)
artifacts = LocalArtifactStore(workspace.cas_root)
base_id = artifacts.put_bytes(
    canonical_json(base.model_dump(mode="json", by_alias=True, exclude_none=True)).encode()
).digest
candidate_id = artifacts.put_bytes(
    canonical_json(candidate.model_dump(mode="json", by_alias=True, exclude_none=True)).encode()
).digest
time = "2026-10-07T00:00:00Z"
actor = {"id": "mock.deterministic", "kind": "ai", "modelId": "mock.deterministic.v1"}
proposal = {
    "apiVersion": "researchos.dev/v0alpha1",
    "kind": "ProposalSubmitRequest",
    "projectId": workspace.project_id,
    "experimentRevision": 1,
    "source": "researchos://demo/synthetic",
    "subject": "proposal.demo",
    "streamid": "stream.research",
    "actor": actor,
    "event": {"id": "evt.proposal.demo", "time": time},
    "proposalId": "proposal.demo",
    "proposedSpecDigest": spec_identity(candidate),
    "specDiffDigest": content_digest(
        {
            "baseSpecDigest": spec_identity(base),
            "candidateSpecDigest": spec_identity(candidate),
            "changes": [change.as_dict() for change in semantic_diff(base, candidate)],
        }
    ),
    "rationale": "Synthetic offline demonstration; no evidence of research improvement.",
    "predictions": [
        {
            "id": "prediction.demo",
            "statement": "A future held-out result changes.",
            "expectedDirection": "decrease",
        }
    ],
    "falsificationConditions": ["A future held-out result does not change."],
    "riskAssessment": {
        "data": "No real dataset used.",
        "method": "Demonstration only.",
        "safety": "",
        "cost": "No paid provider.",
    },
    "evidenceRefs": [],
}
fixture = {
    "apiVersion": "researchos.dev/v0alpha1",
    "kind": "ModelFixture",
    "id": "research-demo",
    "prompt": {"task": "Synthetic proposal demonstration; no tools or execution."},
    "output": proposal,
}
request = {
    "apiVersion": "researchos.dev/v0alpha1",
    "kind": "ModelGenerateRequest",
    "projectId": workspace.project_id,
    "experimentRevision": 1,
    "source": "researchos://models/mock",
    "subject": "call.demo",
    "streamid": "stream.models",
    "actor": actor,
    "callId": "call.demo",
    "fixtureId": fixture["id"],
    "providerId": "mock.deterministic",
    "requestedCapabilities": ["generate"],
    "events": {
        "ai.call.started": {"id": "evt.call.demo.started", "time": time},
        "ai.call.completed": {"id": "evt.call.demo.completed", "time": time},
    },
    "evidenceRefs": [],
}
profile = {
    "apiVersion": "researchos.dev/application/v0alpha1",
    "kind": "ResearchModelProfile",
    "request": "request.json",
    "fixture": "fixture.json",
    "baseArtifact": base_id,
    "candidateArtifact": candidate_id,
}
(root / "model-profiles").mkdir()
(root / "evidence-inbox").mkdir()
(root / "evidence-inbox/demo.md").write_text(
    "Synthetic demonstration evidence. Text cannot grant tools or launch runs.\n"
)
for name, document in [
    ("fixture.json", fixture),
    ("request.json", request),
    ("model-profiles/mock.json", profile),
]:
    (root / name).write_text(json.dumps(document, indent=2) + "\n")
print(
    json.dumps(
        {
            "workspace": str(root.resolve()),
            "profileId": "mock",
            "synthetic": True,
            "modelCalls": 0,
            "runs": 0,
            "baseArtifact": base_id,
            "candidateArtifact": candidate_id,
        }
    )
)
