from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

from llm_research_os.cli import main
from llm_research_os.training.errors import TrainingBackendRequestError
from llm_research_os.training.ms_swift import PINNED_BACKEND_VERSION, plan_ms_swift
from llm_research_os.training.requests import load_training_backend_plan

ROOT = Path(__file__).parents[1]
VALID = ROOT / "examples" / "training-backend" / "valid" / "ms-swift-sft.json"
INVALID = ROOT / "examples" / "training-backend" / "invalid"
_CORE_PATHS = (
    ROOT / "src" / "llm_research_os" / "m2" / "prove.py",
    ROOT / "src" / "llm_research_os" / "m2" / "oci_prove.py",
    ROOT / "src" / "llm_research_os" / "m2" / "bench.py",
    ROOT / "src" / "llm_research_os" / "m2" / "usage.py",
    ROOT / "src" / "llm_research_os" / "workers" / "sandbox.py",
    ROOT / "src" / "llm_research_os" / "workers" / "client.py",
    ROOT / "src" / "llm_research_os" / "cli" / "m2_commands.py",
)


def test_pinned_ms_swift_plan_prints_argv_and_does_not_execute(
    capsys: object,
) -> None:
    assert main(["training", "plan", str(VALID), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["kind"] == "TrainingBackendPlanReceipt"
    assert payload["backendId"] == "ms-swift"
    assert payload["backendVersion"] == PINNED_BACKEND_VERSION
    assert payload["executed"] is False
    assert payload["gpu"] == "not-run"
    assert payload["costKnown"] is False
    assert type(payload["backendInstalled"]) is bool
    assert payload["argv"][0:2] == ["swift", "sft"]
    assert "--tuner_type" in payload["argv"]
    assert "Qwen/Qwen2.5-0.5B-Instruct" in payload["argv"]


@pytest.mark.parametrize(
    "name",
    ("wrong-version.json", "wrong-backend.json", "wrong-model.json", "extra-field.json"),
)
def test_training_plan_rejects_unpinned_documents(name: str, capsys: object) -> None:
    assert main(["training", "plan", str(INVALID / name), "--format", "json"]) == 2
    err = capsys.readouterr().err  # type: ignore[attr-defined]
    assert "valid" in err.lower() or "literal" in err.lower() or "extra" in err.lower()


def test_load_training_backend_plan_wraps_validation_error() -> None:
    with pytest.raises(TrainingBackendRequestError):
        load_training_backend_plan(INVALID / "wrong-version.json")


def test_plan_ms_swift_never_sets_executed() -> None:
    receipt = plan_ms_swift(load_training_backend_plan(VALID))
    assert receipt.executed is False
    assert receipt.gpu == "not-run"
    assert "swift" in receipt.argv


def test_wsl_cuda_plan_prints_argv_and_does_not_execute(capsys: object) -> None:
    plan = ROOT / "examples" / "training-backend" / "valid" / "wsl-cuda-sft.json"
    assert main(["training", "plan", str(plan), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["executed"] is False
    assert payload["gpu"] == "not-run"
    assert payload["argv"][0:2] == ["swift", "sft"]
    assert "/work/model" in payload["argv"]
    assert "--max_steps" in payload["argv"]
    assert payload["argv"][payload["argv"].index("--max_steps") + 1] == "20"


def test_wsl_cuda_plan_rejects_extra_fields(capsys: object) -> None:
    plan = INVALID / "wsl-cuda-extra-field.json"
    assert main(["training", "plan", str(plan), "--format", "json"]) == 2


def test_core_cpu_paths_do_not_import_training_adapter() -> None:
    for path in _CORE_PATHS:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "training" not in alias.name
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                assert "llm_research_os.training" not in node.module
                assert not node.module.startswith("training")


def test_importing_m2_prove_does_not_load_training_adapter() -> None:
    before = {name for name in sys.modules if name.startswith("llm_research_os.training")}
    import llm_research_os.m2.prove as prove
    import llm_research_os.workers.sandbox as sandbox

    after = {name for name in sys.modules if name.startswith("llm_research_os.training")}
    assert after == before
    assert prove.prove_cpu_loop is not None
    assert sandbox.execute_python_brick is not None
