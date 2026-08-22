from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from llm_research_os.spec.io import load_document, load_spec
from llm_research_os.spec.models import ResearchSpec

EXAMPLES = Path(__file__).parents[1] / "examples"


def test_unknown_fields_are_rejected() -> None:
    document = load_document(EXAMPLES / "valid" / "minimal.yaml")
    document["surprise"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ResearchSpec.model_validate(document)


def test_loop_with_accelerator_reference_requires_caps() -> None:
    document = load_document(EXAMPLES / "valid" / "bounded-loop.yaml")
    loop = document["workflows"][0]["graph"]["nodes"][0]
    loop["mayIncurCost"] = False
    del loop["maxCost"]
    del loop["maxWallTimeSeconds"]
    with pytest.raises(ValidationError, match="uses paid/accelerated capability"):
        ResearchSpec.model_validate(document)


def test_hypothesis_question_references_are_checked() -> None:
    document = load_document(EXAMPLES / "valid" / "minimal.yaml")
    document["hypotheses"] = [
        {
            "id": "hypothesis.missing-question",
            "statement": "A statement",
            "questionRefs": ["rq.missing"],
        }
    ]
    with pytest.raises(ValidationError, match="references unknown questions"):
        ResearchSpec.model_validate(document)


def test_model_dump_uses_external_aliases() -> None:
    spec = load_spec(EXAMPLES / "valid" / "bounded-loop.yaml")
    dumped = spec.model_dump(mode="json", by_alias=True)
    loop = dumped["workflows"][0]["graph"]["nodes"][0]
    assert dumped["apiVersion"] == "researchos.dev/v0alpha1"
    assert loop["maxIterations"] == 3
    assert "max_iterations" not in loop


def test_assignment_validation_preserves_invariants() -> None:
    spec = load_spec(EXAMPLES / "valid" / "minimal.yaml")
    metadata = deepcopy(spec.metadata)
    with pytest.raises(ValidationError):
        metadata.revision = 0


def test_extension_values_must_be_json_compatible() -> None:
    document = load_document(EXAMPLES / "valid" / "minimal.yaml")
    document["extensions"] = {"unsafe": object()}
    with pytest.raises(ValidationError, match="JSON-compatible"):
        ResearchSpec.model_validate(document)


def test_constitutional_policy_values_cannot_be_disabled() -> None:
    document = load_document(EXAMPLES / "valid" / "minimal.yaml")
    document["policies"]["preserveAiDissent"] = False
    with pytest.raises(ValidationError):
        ResearchSpec.model_validate(document)
