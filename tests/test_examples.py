from pathlib import Path

import pytest
from pydantic import ValidationError

from llm_research_os.spec.io import SpecLoadError, load_spec

EXAMPLES = Path(__file__).parents[1] / "examples"


@pytest.mark.parametrize("path", sorted((EXAMPLES / "valid").glob("*.yaml")), ids=lambda p: p.name)
def test_valid_examples(path: Path) -> None:
    spec = load_spec(path)
    assert spec.api_version == "researchos.dev/v0alpha1"


@pytest.mark.parametrize(
    "path", sorted((EXAMPLES / "invalid").glob("*.yaml")), ids=lambda p: p.name
)
def test_invalid_examples(path: Path) -> None:
    with pytest.raises((ValidationError, SpecLoadError)):
        load_spec(path)
