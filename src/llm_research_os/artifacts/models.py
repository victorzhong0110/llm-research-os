"""Immutable result objects returned by the local artifact store."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """A content-addressed object that was imported or verified."""

    digest: str
    size_bytes: int
    storage_key: str
