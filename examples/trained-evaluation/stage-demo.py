"""Stage a source-checkout engineering fixture; launch only on explicit intent."""

import argparse
import json
from pathlib import Path

from trained_demo import stage_trained_demo

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("root", type=Path)
parser.add_argument(
    "--authorize-reviewed-cpu-demo",
    action="store_true",
    required=True,
    help="Stage a synthetic one-use grant for the pinned public CPU task.",
)
args = parser.parse_args()
if args.root.exists():
    parser.error("use a new directory; this demo never resets an existing workspace")
workspace, fixture = stage_trained_demo(args.root)
print(
    json.dumps(
        {
            "workspace": str(workspace.root),
            **fixture,
            "label": "synthetic-actors-real-public-cpu-training",
            "runsStarted": 0,
        },
        indent=2,
    )
)
