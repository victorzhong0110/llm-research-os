import json
import sys

request = json.load(sys.stdin)
if request.get("kind") != "PythonBrickRequest":
    raise SystemExit(2)
inputs = request.get("inputs")
if type(inputs) is not dict:
    raise SystemExit(2)
raw_step = inputs.get("step", 0)
if type(raw_step) is not int or isinstance(raw_step, bool) or raw_step < 0:
    raise SystemExit(2)
step = raw_step + 1
json.dump(
    {
        "apiVersion": "researchos.dev/v0alpha1",
        "kind": "PythonBrickReport",
        "status": "ok",
        "outputs": {
            "step": step,
            "checkpoint": {"step": step, "status": "inspectable"},
        },
    },
    sys.stdout,
    separators=(",", ":"),
)
