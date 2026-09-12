"""Enforce unrounded statement+branch coverage independently of pytest-cov."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def check(path: Path) -> int:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document["meta"]["branch_coverage"] is not True or not document["files"]:
            raise ValueError("branch coverage and nonempty source files are required")
        totals = document["totals"]
        names = ("num_statements", "covered_lines", "num_branches", "covered_branches")
        values = [totals[name] for name in names]
        if any(type(v) is not int or v < 0 for v in values):
            raise ValueError("invalid coverage counts")
        lines, covered_lines, branches, covered_branches = values
        if covered_lines > lines or covered_branches > branches or lines + branches == 0:
            raise ValueError("inconsistent coverage counts")
        for name, total in zip(names, values, strict=True):
            if sum(item["summary"][name] for item in document["files"].values()) != total:
                raise ValueError("file counts disagree with totals")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f"Invalid coverage evidence: {exc}", file=sys.stderr)
        return 2
    covered = covered_lines + covered_branches
    possible = lines + branches
    passed = covered * 100 >= possible * 85
    print(f"Coverage: {covered}/{possible} = {covered * 100 / possible:.6f}%; required >=85%")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(check(Path(sys.argv[1])))
