"""Inert T0 manifests bundled with the M0 control plane."""

from __future__ import annotations

from llm_research_os.blocks.models import BlockManifest


def builtin_manifests() -> tuple[BlockManifest, ...]:
    """Return fresh immutable-by-convention manifest objects for registry construction."""

    return (
        BlockManifest.model_validate(
            {
                "apiVersion": "researchos.dev/v0alpha1",
                "kind": "Block",
                "metadata": {
                    "id": "simulated.experiment",
                    "version": "0.1.0",
                    "title": "Deterministic simulated experiment",
                    "description": "An inert M0 block declaration; dry-run never executes it.",
                },
                "runtime": {"type": "simulated"},
                "inputs": [],
                "outputs": [
                    {
                        "id": "result",
                        "valueType": "researchos.simulated-result/v0alpha1",
                    }
                ],
                "configSchema": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object",
                    "properties": {
                        "outcome": {
                            "type": "string",
                            "enum": ["success", "failure", "unknown"],
                        },
                        "seed": {"type": "integer", "minimum": 0},
                    },
                    "additionalProperties": False,
                },
                "capabilities": ["simulate"],
                "permissions": [],
                "telemetry": ["metric", "log"],
                "reproducibility": {"deterministicWhenSeeded": True},
            }
        ),
    )
