"""The final gate must reject rounded-up coverage and invalid evidence."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "check_coverage.py"


@pytest.mark.parametrize(("covered", "expected"), [(8477, 1), (8500, 0), (10000, 0)])
def test_unrounded_gate_exit(tmp_path: Path, covered: int, expected: int) -> None:
    summary = {
        "num_statements": 10000,
        "covered_lines": covered,
        "num_branches": 0,
        "covered_branches": 0,
    }
    report = tmp_path / "coverage.json"
    report.write_text(
        json.dumps(
            {
                "meta": {"branch_coverage": True},
                "totals": summary,
                "files": {"source.py": {"summary": summary}},
            }
        )
    )
    result = subprocess.run([sys.executable, str(SCRIPT), str(report)], capture_output=True)
    assert result.returncode == expected


def test_missing_evidence_fails(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "missing")], capture_output=True
    )
    assert result.returncode == 2
