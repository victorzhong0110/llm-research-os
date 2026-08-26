import os
from pathlib import Path

import pytest

from llm_research_os.spec.io import SpecLoadError, load_document


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("duplicate.json", '{"outer":{"value":1,"value":2}}'),
        ("duplicate.yaml", "outer:\n  value: 1\n  value: 2\n"),
    ],
)
def test_document_loader_rejects_duplicate_mapping_keys(
    tmp_path: Path,
    name: str,
    content: str,
) -> None:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    with pytest.raises(SpecLoadError, match="duplicate"):
        load_document(path)


def test_document_loader_rejects_yaml_aliases_before_expansion(tmp_path: Path) -> None:
    path = tmp_path / "alias.yaml"
    path.write_text(
        "base: &base [one, two, three]\nexpanded: [*base, *base, *base]\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecLoadError, match="aliases are not supported"):
        load_document(path)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="platform has no named pipes")
def test_document_loader_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    path = tmp_path / "input.yaml"
    os.mkfifo(path)
    with pytest.raises(SpecLoadError, match="not a regular file"):
        load_document(path)


def test_research_document_loader_preserves_symlink_compatibility(tmp_path: Path) -> None:
    target = tmp_path / "target.yaml"
    target.write_text("value: true\n", encoding="utf-8")
    link = tmp_path / "link.yaml"
    link.symlink_to(target)
    assert load_document(link) == {"value": True}
