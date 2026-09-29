"""A checkpoint restores only a new, compatible, authorized execution object."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_native_reviewed_runtime import _world

from llm_research_os.canonical import content_digest
from llm_research_os.execution.native_reviewed import execution_object
from llm_research_os.execution.native_reviewed_checkpoint import (
    NativeRestoreClaim,
    NativeRestoreError,
    verify_native_restore,
)
from llm_research_os.execution.native_reviewed_runtime import (
    NativeLaunchError,
    execute_reviewed_native,
)


def test_full_state_checkpoint_requires_completed_source_and_new_lineage(tmp_path: Path) -> None:
    task = (
        b"def main():\n"
        b" return {'restoreMode': 'full-state', 'state': "
        b"{'model': 1, 'optimizer': 2, 'scheduler': 3, 'rng': 4}}\n"
    )
    world, plane, spec, registry = _world(tmp_path, task_source=task)
    world.prepare()
    result = execute_reviewed_native(
        request=world.request,
        spec=spec,
        registry=registry,
        plane=plane,
        workspace=world.workspace,
        state_dir=tmp_path / "source",
        grant_token=world.token,
    )
    artifact = plane.artifacts.verify(result.artifact_digest)
    target = world.request.model_copy(
        update={
            "run_id": "run.2",
            "attempt_id": "attempt.2",
            "inputs": (
                world.request.inputs[0].model_copy(
                    update={
                        "name": "prior",
                        "purpose": "checkpoint",
                        "digest": result.artifact_digest,
                        "size_bytes": artifact.size_bytes,
                    }
                ),
            ),
        }
    )
    target = target.model_copy(update={"config_digest": content_digest(execution_object(target))})
    with pytest.raises(NativeLaunchError, match="checkpoint restore requires"):
        execute_reviewed_native(
            request=target,
            spec=spec,
            registry=registry,
            plane=plane,
            workspace=world.workspace,
            state_dir=tmp_path / "unclaimed",
            grant_token=world.token,
        )
    claim = NativeRestoreClaim.model_validate(
        {
            "apiVersion": "researchos.dev/v0alpha1",
            "kind": "NativeRestoreClaim",
            "mode": "full-state",
            "sourceRunId": world.request.run_id,
            "sourceAttemptId": world.request.attempt_id,
            "targetRunId": target.run_id,
            "targetAttemptId": target.attempt_id,
            "checkpointInput": "prior",
            "artifactDigest": result.artifact_digest,
        }
    )
    verify_native_restore(claim=claim, source=world.request, target=target, plane=plane)
    with pytest.raises(NativeRestoreError, match="mode differs"):
        verify_native_restore(
            claim=claim.model_copy(update={"mode": "adapter-only"}),
            source=world.request,
            target=target,
            plane=plane,
        )
    with pytest.raises(NativeRestoreError, match="lineage"):
        verify_native_restore(
            claim=claim,
            source=world.request,
            target=target.model_copy(update={"attempt_id": world.request.attempt_id}),
            plane=plane,
        )
    bad = target.model_copy(
        update={"inputs": (target.inputs[0].model_copy(update={"digest": "sha256:" + "0" * 64}),)}
    )
    with pytest.raises(NativeRestoreError, match="digest differs"):
        verify_native_restore(claim=claim, source=world.request, target=bad, plane=plane)
