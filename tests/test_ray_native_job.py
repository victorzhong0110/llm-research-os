"""Ray protocol fixtures preserve one submit; they are not real CPU acceptance."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_native_remote_executor import _setup
from test_native_worker_cli import _credential
from test_ray_probe import backend as backend

from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.workers import ray_native_job
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.native_state import private_state_lock
from llm_research_os.workers.ray_native_job import RayNativeJob, main, run_driver
from llm_research_os.workers.ray_probe import RayProbeError


@pytest.fixture
def job(tmp_path, backend):  # type: ignore[no-untyped-def]
    world, plane, server, client, kwargs = _setup(tmp_path)
    credential = _credential(client, kwargs)
    adapter, state, jobs, calls, controls = backend
    task = RayNativeJob(
        adapter,
        world.request,
        credential,
        kwargs["artifacts"].root,
        kwargs["workspace"],
        kwargs["staging_root"],
        kwargs["state_root"],
        state,
    )
    yield task, jobs, calls, controls, world, client
    server.stop()
    plane.store.close()


def test_one_fixed_job_and_unknown_history_never_resubmit(job):  # type: ignore[no-untyped-def]
    task, jobs, calls, _, _, client = job
    result = task.submit_once()
    vendor = jobs[result.submission_id]
    assert vendor["entrypoint_num_cpus"] == 1 and vendor["entrypoint_num_gpus"] == 0
    assert (
        vendor["runtime_env"] == {}
        and "-I -m llm_research_os.workers.ray_native_job" in vendor["entrypoint"]
    )
    intent = next(task.ray_state_root.glob("*.intent"))
    assert client.session not in intent.read_text() and client.grant_token not in intent.read_text()
    assert task.backend.token not in vendor["entrypoint"] + str(vendor["metadata"])
    assert replace(task).submit_once() == result
    jobs[result.submission_id]["status"] = "SUCCEEDED"
    assert task.observe().backend_status == "SUCCEEDED"  # no logs or Run success inferred
    jobs.clear()
    assert task.submit_once().backend_status == "UNKNOWN"
    assert calls.count(("POST", "/api/jobs/")) == 1
    assert not any(path.endswith("/logs") for _, path in calls)


@pytest.mark.parametrize("fault", ["lose", "refuse"])
def test_lost_or_refused_post_retains_one_intent(job, fault):  # type: ignore[no-untyped-def]
    task, _, calls, controls, _, _ = job
    controls[fault] = True
    assert task.submit_once().backend_status == "UNKNOWN"
    controls[fault] = False
    task.submit_once()
    assert calls.count(("POST", "/api/jobs/")) == 1


@pytest.mark.parametrize("fault", ["version", "collision", "busy", "public"])
def test_initial_refusal_precedes_submit(job, fault):  # type: ignore[no-untyped-def]
    task, jobs, calls, controls, _, _ = job
    lock = None
    if fault == "version":
        controls["version"] = "0"
    elif fault == "collision":
        jobs[task._binding()["submissionId"]] = {}
    elif fault == "public":
        task.ray_state_root.chmod(0o755)
    else:
        lock = private_state_lock(task.ray_state_root, task._binding()["submissionId"])
        lock.__enter__()
    try:
        with pytest.raises((RayProbeError, WorkerError)):
            task.submit_once()
        assert calls.count(("POST", "/api/jobs/")) == 0
        assert not list(task.ray_state_root.glob("*.intent"))
    finally:
        if lock is not None:
            lock.__exit__(None, None, None)


@pytest.mark.parametrize(
    "field",
    [
        "entrypoint",
        "metadata",
        "runtime_env",
        "entrypoint_num_cpus",
        "entrypoint_num_gpus",
        "submission_id",
        "status",
    ],
)
def test_changed_vendor_observation_refuses_without_new_submission(job, field):  # type: ignore[no-untyped-def]
    task, jobs, calls, _, _, _ = job
    result = task.submit_once()
    jobs[result.submission_id][field] = None
    with pytest.raises(RayProbeError, match="binding differs"):
        task.observe()
    assert calls.count(("POST", "/api/jobs/")) == 1


@pytest.mark.parametrize("fault", ["changed", "mode", "link", "hardlink", "large"])
def test_private_intent_corruption_refuses(job, fault):  # type: ignore[no-untyped-def]
    task, _, calls, _, _, _ = job
    task.submit_once()
    intent = next(task.ray_state_root.glob("*.intent"))
    if fault == "changed":
        intent.write_text("{}")
    elif fault == "mode":
        intent.chmod(0o644)
    elif fault == "link":
        saved = intent.with_suffix(".saved")
        intent.rename(saved)
        intent.symlink_to(saved)
    elif fault == "hardlink":
        intent.with_suffix(".linked").hardlink_to(intent)
    else:
        intent.write_bytes(b"x" * 65537)
    with pytest.raises((WorkerError, RayProbeError)):
        task.submit_once()
    assert calls.count(("POST", "/api/jobs/")) == 1


def test_recovery_uses_original_request_without_ray_or_launch(job, monkeypatch):  # type: ignore[no-untyped-def]
    task, _, calls, _, world, _ = job
    with pytest.raises(WorkerError, match="unavailable"):
        task.reconcile()
    task.submit_once()
    before = list(calls)
    seen = []
    result = SimpleNamespace(disposition="unknown")

    def reconcile(client, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(kwargs)
        return result

    monkeypatch.setattr(ray_native_job, "reconcile_remote_native", reconcile)
    monkeypatch.setattr(
        ray_native_job, "execute_remote_native", lambda *a, **k: pytest.fail("recovery launched")
    )
    assert task.reconcile() is result
    assert seen[0]["request"] == world.request and calls == before


def test_driver_checks_binding_and_passes_exact_expected_request(job, monkeypatch):  # type: ignore[no-untyped-def]
    task, _, _, _, world, _ = job
    task.submit_once()
    path = next(task.ray_state_root.glob("*.intent"))
    binding = task._binding()
    seen = []
    result = SimpleNamespace(disposition="completed", receipt=object())

    def execute(client, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(kwargs)
        return result

    monkeypatch.setattr(ray_native_job, "execute_remote_native", execute)
    assert run_driver(path, content_digest(binding)) is result
    assert seen[0]["expected_request"] == world.request
    assert main([str(path), content_digest(binding)]) == 0
    with pytest.raises(RayProbeError, match="binding differs"):
        run_driver(path, "sha256:" + "0" * 64)
    binding["uid"] += 1
    path.write_text(canonical_json(binding))
    with pytest.raises(RayProbeError, match="context differs"):
        run_driver(path, content_digest(binding))
    assert len(seen) == 2


@pytest.mark.parametrize(
    "fault", ["overlap", "newline", "parent", "worker", "extra", "paths", "version"]
)
def test_invalid_local_or_driver_context_never_launches(job, monkeypatch, fault):  # type: ignore[no-untyped-def]
    task, _, _, _, _, _ = job
    monkeypatch.setattr(
        ray_native_job,
        "execute_remote_native",
        lambda *a, **k: pytest.fail("invalid context launched"),
    )
    if fault in {"overlap", "newline", "parent", "worker"}:
        if fault == "overlap":
            task = replace(task, state_root=task.artifacts_root)
        elif fault == "newline":
            task = replace(task, workspace=Path(str(task.workspace) + "\n"))
        elif fault == "parent":
            task = replace(task, workspace=task.workspace / ".." / "workspace")
        else:
            task = replace(
                task, request=task.request.model_copy(update={"worker_id": "worker.foreign"})
            )
        with pytest.raises(RayProbeError):
            task.submit_once()
        return
    task.submit_once()
    binding = task._binding()
    binding[{"extra": "unapproved", "paths": "state", "version": "rayVersion"}[fault]] = None
    path = next(task.ray_state_root.glob("*.intent"))
    path.write_text(canonical_json(binding))
    with pytest.raises(RayProbeError):
        run_driver(path, content_digest(binding))


def test_driver_errors_and_nonterminal_results_are_sanitized(monkeypatch, capsys):  # type: ignore[no-untyped-def]
    assert main([]) == 1
    monkeypatch.setattr(
        ray_native_job,
        "run_driver",
        lambda *a: SimpleNamespace(disposition="unknown", receipt=None),
    )
    assert main(["path", "digest"]) == 1

    def fail(*a):  # type: ignore[no-untyped-def]
        raise ValueError("secret fixture bytes")

    monkeypatch.setattr(ray_native_job, "run_driver", fail)
    assert main(["path", "digest"]) == 1
    output = capsys.readouterr()
    assert not output.out and "secret" not in output.err


def test_expected_native_request_refuses_before_preparation_poll_or_child(job, monkeypatch):  # type: ignore[no-untyped-def]
    from llm_research_os.artifacts.store import LocalArtifactStore
    from llm_research_os.workers import native_executor
    from llm_research_os.workers.client import WorkerClient

    task, _, _, _, _, client = job
    monkeypatch.setattr(WorkerClient, "poll", lambda *a: pytest.fail("changed request polled"))
    monkeypatch.setattr(
        native_executor,
        "prepare_remote_native",
        lambda *a, **k: pytest.fail("changed request prepared"),
    )
    with pytest.raises(WorkerError, match="request changed") as exc:
        native_executor.execute_remote_native(
            client,
            artifacts=LocalArtifactStore(task.artifacts_root),
            workspace=task.workspace,
            staging_root=task.staging_root,
            state_root=task.state_root,
            expected_request=task.request.model_copy(update={"workflow_id": "workflow.foreign"}),
        )
    assert exc.value.code == "native-execution-binding"
    assert not list(task.state_root.glob("*.intent"))


def test_pinned_public_job_details_omits_resource_fields_but_binding_retains_them(job):  # type: ignore[no-untyped-def]
    task, jobs, calls, _, _, _ = job
    result = task.submit_once()
    vendor = jobs[result.submission_id]
    vendor.pop("entrypoint_num_cpus")
    vendor.pop("entrypoint_num_gpus")
    assert task.observe() == result
    assert task._binding()["resources"] == {"entrypoint_num_cpus": 1, "entrypoint_num_gpus": 0}
    assert calls.count(("POST", "/api/jobs/")) == 1
