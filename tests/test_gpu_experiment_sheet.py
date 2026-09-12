from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from llm_research_os.training.ms_swift import plan_ms_swift
from llm_research_os.training.requests import load_training_backend_plan

ROOT = Path(__file__).parents[1]
VALID = ROOT / "examples" / "training-backend" / "valid" / "ms-swift-sft.json"
DOCKERFILE = ROOT / "examples" / "m2-gpu-image" / "Dockerfile"
VERIFY = ROOT / "examples" / "m2-gpu-image" / "verify.sh"
SHEET = ROOT / "docs" / "guides" / "m2-gpu-experiment.md"

# Flag names from ms-swift v4.5.2 Command-line-parameters.md (tag v4.5.2).
_SWIFT_452_FLAGS = frozenset(
    {
        "--model",
        "--tuner_type",
        "--dataset",
        "--torch_dtype",
        "--max_steps",
        "--per_device_train_batch_size",
        "--gradient_accumulation_steps",
        "--learning_rate",
        "--lora_rank",
        "--lora_alpha",
        "--output_dir",
        "--save_steps",
        "--logging_steps",
        "--max_length",
    }
)


def test_planned_argv_matches_ms_swift_452_flag_names() -> None:
    receipt = plan_ms_swift(load_training_backend_plan(VALID))
    assert receipt.argv[0:2] == ("swift", "sft")
    assert receipt.executed is False
    assert receipt.gpu == "not-run"
    flags = [item for item in receipt.argv if item.startswith("--")]
    assert "--tuner_type" in flags
    assert "--sft_type" not in flags
    assert "--train_type" not in flags
    unknown = [flag for flag in flags if flag not in _SWIFT_452_FLAGS]
    assert unknown == []


def test_cuda_image_method_pins_ms_swift_and_forbids_gpus() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    verify = VERIFY.read_text(encoding="utf-8")
    assert "ms-swift==4.5.2" in dockerfile
    assert "nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04" in dockerfile
    assert " --gpus" not in verify
    assert "--gpus=" not in verify
    assert "swift sft --help" in verify
    assert "RESEARCHOS_GPU_IMAGE_BUILD" in verify
    assert "gpu" in verify and "not-run" in verify


def test_verify_script_skips_cuda_pull_by_default() -> None:
    env = os.environ.copy()
    env["RESEARCHOS_GPU_IMAGE_BUILD"] = "0"
    completed = subprocess.run(
        ["sh", str(VERIFY)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["gpu"] == "not-run"
    assert payload["executed"] is False
    assert payload["status"] in ("skipped-no-runtime", "skipped-no-build")


def test_gpu_sheet_names_cap_stop_and_not_run() -> None:
    sheet = SHEET.read_text(encoding="utf-8")
    assert "AutoDL RTX 4090" in sheet
    assert "45 minutes" in sheet
    assert "¥20.00" in sheet
    assert "¥1000" in sheet
    assert "关机" in sheet
    assert "付费数据盘" in sheet
    assert "--resume_from_checkpoint" in sheet
    assert "gpu: not-run" in sheet or "`gpu: not-run`" in sheet
    assert "authorization to spend" in sheet
    assert "RESEARCHOS_GPU_IMAGE_BUILD" in sheet
