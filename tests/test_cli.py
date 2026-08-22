from __future__ import annotations

from pathlib import Path

import pytest

from research_os.cli import main

VALID = "examples/valid/small-model-lr.yaml"
REV2 = "examples/valid/small-model-lr.rev2.yaml"
INVALID = "examples/invalid/03-bad-id.yaml"


def test_validate_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", VALID]) == 0
    assert "OK" in capsys.readouterr().out


def test_validate_invalid_reports_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", INVALID]) == 1
    assert "INVALID" in capsys.readouterr().err


def test_diff_reports_changes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["diff", VALID, REV2]) == 0
    out = capsys.readouterr().out
    assert "metadata.revision" in out


def test_schema_prints_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["schema"]) == 0
    assert '"ResearchSpec"' in capsys.readouterr().out


def test_run_then_events_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = str(tmp_path / "loop.db")
    assert main(["run", VALID, "--db", db, "--steps", "2"]) == 0
    run_out = capsys.readouterr().out
    assert "status=completed" in run_out

    assert main(["events", "--db", db]) == 0
    events_out = capsys.readouterr().out
    assert "run.completed" in events_out
