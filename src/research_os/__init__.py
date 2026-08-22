"""LLM Research OS — M0 kernel reference implementation.

This package provides the minimal trusted-kernel primitives proven in milestone
M0: the ``ResearchSpec`` and CloudEvents-compatible ``ResearchEvent`` protocols,
a validator with semantic (not textual) revision diffing, a versioned JSON Schema
exporter, an append-only SQLite fact source, and a ``SimulatedRuntime`` that runs
a full vertical loop without any GPU.
"""

from __future__ import annotations

API_VERSION = "researchos.dev/v0alpha1"
"""Versioned apiVersion string carried by every spec document."""

SCHEMA_VERSION = "v0alpha1"
"""Versioned schema tag carried by every event."""

__all__ = ["API_VERSION", "SCHEMA_VERSION"]
