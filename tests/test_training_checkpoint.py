from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_research_os.artifacts.errors import ArtifactStoreError
from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.cli import main
from llm_research_os.training.checkpoint import (
    collect_output_artifacts,
    inspect_snapshot,
    list_tree_files,
    load_gpu_data_checkpoint_binding,
    require_binding_matches_plan,
    tree_digest,
)
from llm_research_os.training.errors import TrainingBackendError, TrainingBackendRequestError
from llm_research_os.training.gpu_bind import (
    ADAPTER_ONLY_LOADS,
    FULL_CHECKPOINT_LOADS,
    apply_resume_overlay,
    bind_ms_swift_gpu_command,
    command_digest,
)
from llm_research_os.training.requests import load_training_backend_plan

ROOT = Path(__file__).parents[1]
PLAN = ROOT / "examples" / "training-backend" / "valid" / "ms-swift-sft.json"
SHEET_BINDING = ROOT / "examples" / "m2-gpu-checkpoint" / "data-binding.json"
CPU_BINDING = ROOT / "examples" / "training-backend" / "valid" / "gpu-data-checkpoint-cpu.json"
INVALID_BINDING = (
    ROOT / "examples" / "training-backend" / "invalid" / "gpu-data-checkpoint-extra-field.json"
)
CPU_SNAPSHOT = ROOT / "examples" / "training-backend" / "cpu-snapshot"
CHECKPOINT = CPU_SNAPSHOT / "output" / "run" / "checkpoint-1"


def test_sheet_binding_is_pending_live_and_matches_plan() -> None:
    plan = load_training_backend_plan(PLAN)
    binding = load_gpu_data_checkpoint_binding(SHEET_BINDING)
    require_binding_matches_plan(binding, plan)
    receipt = inspect_snapshot(binding, model_dir=None, data_dir=None)
    assert receipt.fetched is False
    assert receipt.gpu == "not-run"
    assert receipt.model.status == "missing"
    assert receipt.dataset.status == "pending-live"
    assert receipt.prefetch_argv[:2] == ("modelscope", "download")
    assert "--revision" in receipt.prefetch_argv


def test_cpu_fixture_snapshot_matches_committed_digests() -> None:
    binding = load_gpu_data_checkpoint_binding(CPU_BINDING)
    receipt = inspect_snapshot(
        binding,
        model_dir=CPU_SNAPSHOT / "model",
        data_dir=CPU_SNAPSHOT / "data",
    )
    assert receipt.model.status == "present"
    assert receipt.dataset.status == "present"
    assert receipt.fetched is False
    assert receipt.gpu == "not-run"


def test_snapshot_records_digest_when_binding_omits_content_digest(tmp_path: Path) -> None:
    binding = load_gpu_data_checkpoint_binding(SHEET_BINDING)
    receipt = inspect_snapshot(
        binding,
        model_dir=CPU_SNAPSHOT / "model",
        data_dir=CPU_SNAPSHOT / "data",
    )
    assert receipt.model.status == "recorded"
    assert receipt.dataset.status == "recorded"
    assert receipt.model.digest == tree_digest(list_tree_files(CPU_SNAPSHOT / "model"))


def test_snapshot_mismatch_and_symlink_fail_closed(tmp_path: Path) -> None:
    binding = load_gpu_data_checkpoint_binding(CPU_BINDING)
    model = tmp_path / "model"
    model.mkdir()
    (model / "REVISION").write_text("wrong\n", encoding="utf-8")
    receipt = inspect_snapshot(binding, model_dir=model, data_dir=CPU_SNAPSHOT / "data")
    assert receipt.model.status == "mismatch"
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / "file").symlink_to(CPU_SNAPSHOT / "model" / "REVISION")
    with pytest.raises(TrainingBackendError) as captured:
        list_tree_files(linked)
    assert captured.value.code == "snapshot-symlink-forbidden"


def test_overlay_none_rejects_checkpoint_and_binding_must_match_plan() -> None:
    plan = load_training_backend_plan(PLAN)
    with pytest.raises(TrainingBackendError) as captured:
        bind_ms_swift_gpu_command(
            plan,
            resume_mode="none",
            checkpoint_path="/work/output/run/checkpoint-1",
        )
    assert captured.value.code == "resume-overlay-conflict"
    binding = load_gpu_data_checkpoint_binding(SHEET_BINDING)
    require_binding_matches_plan(binding, plan)
    with pytest.raises(TrainingBackendError) as captured:
        apply_resume_overlay(bind_ms_swift_gpu_command(plan)[0], mode="adapter-only")
    assert captured.value.code == "gpu-mount-forbidden"
    with pytest.raises(TrainingBackendRequestError):
        load_gpu_data_checkpoint_binding(INVALID_BINDING)


def test_full_checkpoint_overlay_is_not_adapter_only() -> None:
    plan = load_training_backend_plan(PLAN)
    base, base_digest = bind_ms_swift_gpu_command(plan)
    full, full_digest = bind_ms_swift_gpu_command(
        plan,
        resume_mode="full-checkpoint",
        checkpoint_path="/work/output/run/checkpoint-1",
    )
    adapter, adapter_digest = bind_ms_swift_gpu_command(
        plan,
        resume_mode="adapter-only",
        checkpoint_path="/work/output/run/checkpoint-1",
    )
    assert full_digest != base_digest
    assert adapter_digest != full_digest
    assert "--resume_from_checkpoint" in full
    assert "--adapters" not in full
    assert "--adapters" in adapter
    assert "--resume_from_checkpoint" not in adapter
    assert FULL_CHECKPOINT_LOADS == (
        "weights",
        "optimizer",
        "scheduler",
        "rng",
        "global_step",
    )
    assert ADAPTER_ONLY_LOADS == ("adapter_weights",)
    assert command_digest(base) == base_digest
    with pytest.raises(TrainingBackendError) as captured:
        apply_resume_overlay(base, mode="full-checkpoint", checkpoint_path="/tmp/checkpoint-1")
    assert captured.value.code == "gpu-mount-forbidden"
    with pytest.raises(TrainingBackendError) as captured:
        apply_resume_overlay(
            (*base, "--resume_from_checkpoint", "/work/output/x"),
            mode="adapter-only",
            checkpoint_path="/work/output/run/checkpoint-1",
        )
    assert captured.value.code == "resume-overlay-conflict"
    with pytest.raises(TrainingBackendError) as captured:
        apply_resume_overlay(
            (*base, "--resume_only_model"),
            mode="full-checkpoint",
            checkpoint_path="/work/output/run/checkpoint-1",
        )
    assert captured.value.code == "gpu-mount-forbidden"


def test_collect_puts_checkpoint_files_and_resumes_after_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    complete = collect_output_artifacts(CHECKPOINT, artifacts)
    assert complete.status == "complete"
    assert complete.executed is False
    assert complete.gpu == "not-run"
    paths = {item.path for item in complete.files}
    assert "trainer_state.json" in paths
    assert "adapter_config.json" in paths
    assert "optimizer.pt" in paths
    for item in complete.files:
        artifacts.verify(item.digest)

    calls = {"n": 0}
    original = LocalArtifactStore.put

    def fail_second(self: LocalArtifactStore, source: str | Path) -> object:
        calls["n"] += 1
        if calls["n"] == 2:
            raise ArtifactStoreError("injected interrupt")
        return original(self, source)

    monkeypatch.setattr(LocalArtifactStore, "put", fail_second)
    interrupted_root = tmp_path / "partial"
    interrupted_root.mkdir()
    partial_store = LocalArtifactStore(interrupted_root)
    partial = collect_output_artifacts(CHECKPOINT, partial_store)
    assert partial.status == "incomplete"
    assert len(partial.files) == 1
    monkeypatch.undo()
    resumed = collect_output_artifacts(
        CHECKPOINT,
        partial_store,
        prior={item.path: item.digest for item in partial.files},
    )
    assert resumed.status == "complete"
    assert len(resumed.files) == 3


def test_collect_rejects_changed_file_on_resume(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    artifacts = LocalArtifactStore(artifacts_root)
    with pytest.raises(TrainingBackendError) as captured:
        collect_output_artifacts(
            CHECKPOINT,
            artifacts,
            prior={"trainer_state.json": "sha256:" + ("0" * 64)},
        )
    assert captured.value.code == "artifact-integrity-mismatch"


def test_training_overlay_snapshot_and_collect_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(
            [
                "training",
                "overlay",
                str(PLAN),
                "--resume",
                "full-checkpoint",
                "--checkpoint",
                "/work/output/run/checkpoint-1",
                "--format",
                "json",
            ]
        )
        == 0
    )
    overlay = json.loads(capsys.readouterr().out)
    assert overlay["kind"] == "GpuResumeOverlayReceipt"
    assert overlay["executed"] is False
    assert overlay["gpu"] == "not-run"
    assert overlay["loads"] == list(FULL_CHECKPOINT_LOADS)
    assert "--resume_from_checkpoint" in overlay["commandArgv"]

    assert (
        main(
            [
                "training",
                "snapshot",
                str(CPU_BINDING),
                "--plan",
                str(PLAN),
                "--model-dir",
                str(CPU_SNAPSHOT / "model"),
                "--data-dir",
                str(CPU_SNAPSHOT / "data"),
                "--format",
                "json",
            ]
        )
        == 0
    )
    snapshot = json.loads(capsys.readouterr().out)
    assert snapshot["fetched"] is False
    assert snapshot["model"]["status"] == "present"

    artifacts = tmp_path / "artifacts"
    assert (
        main(
            [
                "training",
                "collect",
                str(CHECKPOINT),
                "--artifacts",
                str(artifacts),
                "--format",
                "json",
            ]
        )
        == 0
    )
    collected = json.loads(capsys.readouterr().out)
    assert collected["status"] == "complete"
    assert collected["executed"] is False
    assert collected["gpu"] == "not-run"

    assert (
        main(
            [
                "training",
                "overlay",
                str(PLAN),
                "--resume",
                "adapter-only",
                "--checkpoint",
                "/work/output/run/checkpoint-1",
            ]
        )
        == 0
    )
    text = capsys.readouterr().out
    assert "training overlay: recorded" in text
    assert "gpu: not-run" in text

    assert main(["training", "snapshot", str(SHEET_BINDING)]) == 0
    snap_text = capsys.readouterr().out
    assert "fetched: False" in snap_text
    assert "dataset: pending-live" in snap_text

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(collected), encoding="utf-8")
    assert (
        main(
            [
                "training",
                "collect",
                str(CHECKPOINT),
                "--artifacts",
                str(artifacts),
                "--resume-from",
                str(manifest),
            ]
        )
        == 0
    )
    collect_text = capsys.readouterr().out
    assert "training collect: recorded" in collect_text
    assert "gpu: not-run" in collect_text
