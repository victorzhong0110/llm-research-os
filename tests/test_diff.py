from copy import deepcopy
from pathlib import Path

import pytest

from llm_research_os.spec.diff import ChangeImpact, ChangeKind, semantic_diff
from llm_research_os.spec.io import load_document
from llm_research_os.spec.models import ResearchSpec

EXAMPLES = Path(__file__).parents[1] / "examples"


def _revision_pair() -> tuple[ResearchSpec, ResearchSpec]:
    first_data = load_document(EXAMPLES / "valid" / "minimal.yaml")
    second_data = deepcopy(first_data)
    second_data["metadata"]["revision"] = 2
    second_data["hypotheses"] = [
        {
            "id": "hypothesis.loss",
            "statement": "The intervention reduces validation loss.",
            "questionRefs": ["rq.loss"],
        }
    ]
    return ResearchSpec.model_validate(first_data), ResearchSpec.model_validate(second_data)


def test_semantic_diff_is_id_aware() -> None:
    first, second = _revision_pair()
    changes = semantic_diff(first, second)
    added = [change for change in changes if change.kind is ChangeKind.ADDED]
    assert len(added) == 1
    assert added[0].path == "/hypotheses[id=hypothesis.loss]"
    assert added[0].impact is ChangeImpact.RESEARCH


def test_revision_must_increase() -> None:
    first, second = _revision_pair()
    with pytest.raises(ValueError, match="greater than"):
        semantic_diff(second, first)


def test_reordering_id_lists_is_not_a_change() -> None:
    first_data = load_document(EXAMPLES / "valid" / "minimal.yaml")
    first_data["questions"].append({"id": "rq.second", "question": "Does ordering matter?"})
    second_data = deepcopy(first_data)
    second_data["metadata"]["revision"] = 2
    second_data["questions"].reverse()
    first = ResearchSpec.model_validate(first_data)
    second = ResearchSpec.model_validate(second_data)
    paths = {change.path for change in semantic_diff(first, second)}
    assert paths == {"/metadata/revision"}
