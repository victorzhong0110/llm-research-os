"""Reviewed CPU Python brick fixture.

R04 materializes these bytes and must not import or call this module.
"""

from __future__ import annotations

import os
from pathlib import Path


def main() -> int:
    """Entrypoint reserved for a later execution package."""

    marker = os.environ.get("R04_BRICK_RAN_MARKER")
    if marker:
        Path(marker).write_text("ran", encoding="utf-8")
    raise RuntimeError("reviewed entrypoint execution is not available")
