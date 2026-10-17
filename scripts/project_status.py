"""Render bilingual README status from one reviewed evidence index."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = "<!-- generated-status:start -->"
END = "<!-- generated-status:end -->"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = json.loads((ROOT / "docs/status.json").read_text(encoding="utf-8"))
    mismatch = False
    for filename, column in (("README.md", 1), ("README.zh-CN.md", 2)):
        path = ROOT / filename
        old = path.read_text(encoding="utf-8")
        chinese = column == 2
        table = [
            START,
            "",
            "| 范围 | 状态 |" if chinese else "| Scope | Status |",
            "| --- | --- |",
        ]
        table.extend(f"| {row[0]} | {row[column]} |" for row in data["rows"])
        evidence = (
            "[当前 M3 证据与缺口](docs/evidence/m3/acceptance-matrix.md) · "
            "[历史 M1/M2 范围](docs/adr/0062-m1-m2-acceptance-and-m3-boundary.md)。"
            if chinese
            else "[Current M3 evidence and gaps](docs/evidence/m3/acceptance-matrix.md) · "
            "[Historical M1/M2 scope](docs/adr/0062-m1-m2-acceptance-and-m3-boundary.md)."
        )
        baseline = (
            f"实现快照: `{data['baseline'][:7]}`; "
            f"历史已验收证据: `{data['acceptedEvidence'][:7]}`。"
            if chinese
            else f"Implementation snapshot: `{data['baseline'][:7]}`; "
            f"historical accepted evidence: `{data['acceptedEvidence'][:7]}`."
        )
        table += ["", evidence, baseline, "", END]
        before, rest = old.split(START, 1)
        _, after = rest.split(END, 1)
        new = before + "\n".join(table) + after
        mismatch |= new != old
        if not args.check:
            path.write_text(new, encoding="utf-8")
    return int(args.check and mismatch)


if __name__ == "__main__":
    raise SystemExit(main())
