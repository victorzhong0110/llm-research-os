#!/usr/bin/env python3
"""Run each tests/test_*.py under a hard process-group timeout.

One combined pytest on GitHub sat through the job cap with no logs.
Killing a single file leaves a named HUNG line.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"
MARKER = "not oci_live and not slow"
FILE_TIMEOUT_SECONDS = 90


def _run_file(path: Path) -> str:
    uv = shutil.which("uv")
    if uv is None:
        return "fail:uv-missing"
    proc = subprocess.Popen(  # noqa: S603
        [
            uv,
            "run",
            "pytest",
            str(path),
            "-q",
            "--tb=line",
            "-m",
            MARKER,
        ],
        cwd=ROOT,
        start_new_session=True,
    )
    try:
        code = proc.wait(timeout=FILE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)
        return "hung"
    if code == 0:
        return "ok"
    return f"fail:{code}"


def main() -> int:
    files = sorted(TESTS.glob("test_*.py"))
    hung: list[str] = []
    failed: list[str] = []
    for path in files:
        print(f"FILE {path.relative_to(ROOT)}", flush=True)
        status = _run_file(path)
        print(f"{status.upper()} {path.relative_to(ROOT)}", flush=True)
        if status == "hung":
            hung.append(str(path.relative_to(ROOT)))
        elif status != "ok":
            failed.append(f"{path.relative_to(ROOT)} {status}")
    if hung or failed:
        print("hung:", hung, flush=True)
        print("failed:", failed, flush=True)
        return 1
    print(f"ok {len(files)} files", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
