from pathlib import Path

from llm_research_os.cli import main

EXAMPLES = Path(__file__).parents[1] / "examples"
SCHEMA = Path(__file__).parents[1] / "schemas" / "research-spec" / "v0alpha1.schema.json"


def test_validate_command(capsys: object) -> None:
    result = main(["validate", str(EXAMPLES / "valid" / "minimal.yaml")])
    assert result == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert '"valid": true' in output.out


def test_invalid_command(capsys: object) -> None:
    result = main(["validate", str(EXAMPLES / "invalid" / "implicit-cycle.yaml")])
    assert result == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert '"valid": false' in output.err


def test_schema_check_command() -> None:
    assert main(["schema", "--check", str(SCHEMA)]) == 0
