"""Exercise the installed wheel outside the checkout, without training extras."""

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import llm_research_os

parser = argparse.ArgumentParser()
parser.add_argument("corpus", type=Path)
args = parser.parse_args()
package = Path(llm_research_os.__file__).resolve()
if "site-packages" not in package.parts:
    raise SystemExit("smoke must import an installed wheel, not the source checkout")
if importlib.util.find_spec("torch") is not None or importlib.util.find_spec("swift") is not None:
    raise SystemExit("smoke environment must not contain training extras")
receipts = {}
with tempfile.TemporaryDirectory(prefix="researchos-wheel-") as directory:
    root = Path(directory)
    shutil.copytree(args.corpus, root / "corpus")
    for decision in ("accept", "reject"):
        result = subprocess.run(  # noqa: S603 - fixed CLI, isolated interpreter, no shell
            [
                sys.executable,
                "-I",
                "-m",
                "llm_research_os",
                "m1",
                "prove",
                str(root / "corpus"),
                str(root / f"{decision}.db"),
                "--decision",
                decision,
                "--format",
                "json",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        receipt = json.loads(result.stdout)
        accepted = decision == "accept"
        if receipt["queued"] is not accepted:
            raise SystemExit("checkpoint decision/queue mismatch")
        if accepted and (
            "run.completed" not in receipt["eventTypes"]
            or receipt["answeredQuestionCount"] != 1
            or receipt["overriddenDissentCount"] != 1
            or receipt["rationaleCharacters"] <= 0
        ):
            raise SystemExit("accepted checkpoint lacks research or execution evidence")
        if not accepted and (receipt["runId"] is not None or "run.queued" in receipt["eventTypes"]):
            raise SystemExit("rejected checkpoint unexpectedly queued execution")
        receipts[decision] = receipt
print(json.dumps({"installedWheel": True, "trainingExtras": False, "receipts": receipts}, indent=2))
