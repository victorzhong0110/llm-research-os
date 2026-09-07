import json
import sys

request = json.load(sys.stdin)
if request.get("kind") != "PythonBrickRequest":
    raise SystemExit(2)
json.dump(
    {
        "apiVersion": "researchos.dev/v0alpha1",
        "kind": "PythonBrickReport",
        "status": "ok",
        "outputs": {"echo": "oci-loop"},
    },
    sys.stdout,
    separators=(",", ":"),
)
