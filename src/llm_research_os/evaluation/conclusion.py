"""Human research conclusions (R13).

A conclusion is a human's recorded judgement about evidence, not something the
system infers from a score. The system refuses to attach a conclusion to a
comparison that cannot support one, and it never supplies the conclusion text.
A negative or inconclusive result is a legitimate recorded outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from llm_research_os.canonical import content_digest
from llm_research_os.evaluation.compare import Comparison

CONCLUSION_API_VERSION: Final = "researchos.dev/conclusion/v0alpha1"
CONCLUSION_CONTRACT_VERSION: Final = "v0alpha1"
MAX_RATIONALE_CHARACTERS: Final = 4000
MAX_EVIDENCE_REFS: Final = 32

# A conclusion is one of exactly three judgements. There is deliberately no
# "partial" or "probably" member: a human picks one and writes why.
ConclusionVerdict = Literal["insufficient-evidence", "supported", "unsupported"]


class ConclusionError(ValueError):
    """One conclusion fault with a closed code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class Conclusion:
    """One human conclusion bound to the evidence it was drawn from."""

    conclusion_id: str
    project_id: str
    experiment_revision: int
    verdict: ConclusionVerdict
    rationale: str
    comparison_detail_digest: str
    evidence_refs: tuple[str, ...]
    actor_id: str
    contract_version: str = CONCLUSION_CONTRACT_VERSION

    def document(self) -> dict[str, object]:
        return {
            "apiVersion": CONCLUSION_API_VERSION,
            "kind": "ResearchConclusion",
            "contractVersion": self.contract_version,
            "conclusionId": self.conclusion_id,
            "projectId": self.project_id,
            "experimentRevision": self.experiment_revision,
            "verdict": self.verdict,
            "rationale": self.rationale,
            "comparisonDetailDigest": self.comparison_detail_digest,
            "evidenceRefs": list(self.evidence_refs),
            "actorId": self.actor_id,
        }


def record(
    comparison: Comparison,
    *,
    conclusion_id: str,
    project_id: str,
    experiment_revision: int,
    verdict: ConclusionVerdict,
    rationale: str,
    evidence_refs: tuple[str, ...],
    actor_id: str,
) -> Conclusion:
    """Record a human conclusion, refusing what the evidence cannot carry.

    ``supported`` and ``unsupported`` both require a comparison that can support
    a conclusion. ``insufficient-evidence`` is always allowed: saying the
    evidence is insufficient is itself a finding, and a valid one.
    """

    if verdict not in {"insufficient-evidence", "supported", "unsupported"}:
        raise ConclusionError("conclusion-verdict-invalid", "unknown human verdict")
    if not project_id.strip() or any(not ref.strip() for ref in evidence_refs):
        raise ConclusionError(
            "conclusion-reference-invalid", "project and evidence references must be nonempty"
        )
    if not conclusion_id.strip():
        raise ConclusionError("conclusion-id-invalid", "a conclusion needs an identifier")
    if not rationale.strip():
        raise ConclusionError("conclusion-rationale-empty", "a conclusion needs a rationale")
    if len(rationale) > MAX_RATIONALE_CHARACTERS:
        raise ConclusionError(
            "conclusion-rationale-too-long",
            f"a conclusion rationale is capped at {MAX_RATIONALE_CHARACTERS} characters",
        )
    if not actor_id.strip():
        raise ConclusionError("conclusion-actor-missing", "a conclusion needs a human actor")
    if len(evidence_refs) > MAX_EVIDENCE_REFS:
        raise ConclusionError(
            "conclusion-evidence-too-many",
            f"a conclusion cites at most {MAX_EVIDENCE_REFS} references",
        )
    if len(set(evidence_refs)) != len(evidence_refs):
        raise ConclusionError(
            "conclusion-evidence-duplicate", "conclusion evidence references must be unique"
        )
    if experiment_revision < 1:
        raise ConclusionError(
            "conclusion-revision-invalid", "a conclusion needs a positive experiment revision"
        )

    if verdict != "insufficient-evidence" and not comparison.supports_a_conclusion:
        reason = comparison.refusal or (
            "the comparison has too few required metrics to support a conclusion"
            if comparison.missing_metrics
            else "a single improved metric is not a conclusion"
        )
        raise ConclusionError("conclusion-unsupported", reason)

    return Conclusion(
        conclusion_id=conclusion_id,
        project_id=project_id,
        experiment_revision=experiment_revision,
        verdict=verdict,
        rationale=rationale,
        comparison_detail_digest=content_digest(comparison.document()),
        evidence_refs=evidence_refs,
        actor_id=actor_id,
    )
