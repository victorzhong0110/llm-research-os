#!/usr/bin/env python3
"""Deterministic ms-swift stand-in for macos-mps-process tests. Not a training backend."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def _arg(flag: str) -> str | None:
    if flag not in sys.argv:
        return None
    index = sys.argv.index(flag)
    if index + 1 >= len(sys.argv):
        return None
    return sys.argv[index + 1]


def _write_checkpoint(root: Path, step: int, adapter: bytes, optimizer: bytes) -> None:
    path = root / f"checkpoint-{step}"
    path.mkdir(parents=True, exist_ok=True)
    (path / "adapter_model.safetensors").write_bytes(adapter)
    (path / "adapter_config.json").write_text('{"r": 8}\n', encoding="utf-8")
    (path / "optimizer.pt").write_bytes(optimizer)
    (path / "scheduler.pt").write_bytes(b"scheduler-" + str(step).encode("ascii"))
    (path / "rng_state.pth").write_bytes(b"rng-" + str(step).encode("ascii"))
    (path / "trainer_state.json").write_text(
        json.dumps(
            {
                "global_step": step,
                "log_history": [
                    {"step": item, "loss": 2.0 / item} for item in range(max(1, step - 9), step + 1)
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] != "sft":
        sys.stderr.write("stub swift expected sft\n")
        return 2
    sleep_for = int(os.environ.get("RESEARCHOS_MPS_STUB_SLEEP") or "0")
    if sleep_for > 0:
        time.sleep(sleep_for)
    output = Path(_arg("--output_dir") or "output")
    output.mkdir(parents=True, exist_ok=True)
    max_steps = int(_arg("--max_steps") or "20")
    save_steps = int(_arg("--save_steps") or "10")
    resume = _arg("--resume_from_checkpoint")
    adapters = _arg("--adapters")
    start = 0
    optimizer = b"optimizer-new"
    if resume is not None:
        state = json.loads((Path(resume) / "trainer_state.json").read_text(encoding="utf-8"))
        start = int(state["global_step"])
        optimizer = (Path(resume) / "optimizer.pt").read_bytes()
    elif adapters is not None:
        start = 0
        optimizer = b"optimizer-adapter-only"
    current = start
    while current < max_steps:
        current += 1
        if current % save_steps == 0 or current == max_steps:
            _write_checkpoint(
                output,
                current,
                adapter=b"adapter-" + str(current).encode("ascii"),
                optimizer=optimizer + b"-" + str(current).encode("ascii"),
            )
    (output / "train.log").write_text("stub swift sft complete\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
