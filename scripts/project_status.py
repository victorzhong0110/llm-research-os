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
        table = [START, "", "| Scope | Status |", "| --- | --- |"]
        table.extend(f"| {row[0]} | {row[column]} |" for row in data["rows"])
        table += [
            "",
            "[Evidence and limits](docs/evidence/m2-wsl2-cuda-live/m2-closure-matrix.md).",
            f"Integrated baseline: `{data['baseline'][:7]}`; "
            f"accepted evidence: `{data['acceptedEvidence'][:7]}`.",
            "",
            END,
        ]
        before, rest = old.split(START, 1)
        _, after = rest.split(END, 1)
        new = before + "\n".join(table) + after
        mismatch |= new != old
        if not args.check:
            path.write_text(new, encoding="utf-8")
    return int(args.check and mismatch)


if __name__ == "__main__":
    raise SystemExit(main())
