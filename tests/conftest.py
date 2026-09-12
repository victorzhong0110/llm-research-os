"""CI breadcrumbs. Default pytest behaviour is unchanged without the env flag."""

from __future__ import annotations

import os
from pathlib import Path

_CURRENT = Path("pytest-current.txt")


def pytest_runtest_logstart(nodeid: str, location: tuple[str, int, str]) -> None:
    if os.environ.get("RESEARCHOS_PYTEST_FAULTLOG") != "1":
        return
    _CURRENT.write_text(nodeid, encoding="utf-8")
    print(f"BEGIN {nodeid}", flush=True)
