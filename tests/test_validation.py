from __future__ import annotations

from pathlib import Path

import pytest

from research_os.validation import load_yaml, semantic_diff, validate_document


def test_valid_example_passes(examples_dir: Path) -> None:
    text = (examples_dir / "valid" / "small-model-lr.yaml").read_text()
    result = validate_document(load_yaml(text))
    assert result.valid
    assert result.spec is not None
    assert result.spec.metadata.id == "small-model-lr"
    assert result.spec.hypotheses[0].id == "lr-stability"


@pytest.mark.parametrize(
    "filename",
    [
        "01-wrong-api-version.yaml",
        "02-wrong-kind.yaml",
        "03-bad-id.yaml",
        "04-revision-zero.yaml",
        "05-duplicate-hypothesis-id.yaml",
        "06-unknown-field.yaml",
    ],
)
def test_invalid_examples_fail_with_issues(examples_dir: Path, filename: str) -> None:
    text = (examples_dir / "invalid" / filename).read_text()
    result = validate_document(load_yaml(text))
    assert not result.valid
    assert result.issues
    # Every issue must have a location and a message so users can act on it.
    for issue in result.issues:
        assert issue.location
        assert issue.message


def test_non_mapping_document_rejected() -> None:
    with pytest.raises(ValueError, match="mapping"):
        load_yaml("- just\n- a\n- list\n")


def test_semantic_diff_detects_meaningful_changes(examples_dir: Path) -> None:
    old = validate_document(
        load_yaml((examples_dir / "valid" / "small-model-lr.yaml").read_text())
    ).spec
    new = validate_document(
        load_yaml((examples_dir / "valid" / "small-model-lr.rev2.yaml").read_text())
    ).spec
    assert old is not None and new is not None

    diff = semantic_diff(old, new)
    assert not diff.empty
    assert "metadata.revision" in diff.changed
    assert diff.changed["metadata.revision"] == (1, 2)
    # A second hypothesis was added in revision 2.
    assert any(path.startswith("hypotheses[1]") for path in diff.added)


def test_semantic_diff_empty_for_identical_specs(examples_dir: Path) -> None:
    spec = validate_document(
        load_yaml((examples_dir / "valid" / "small-model-lr.yaml").read_text())
    ).spec
    assert spec is not None
    assert semantic_diff(spec, spec).empty
